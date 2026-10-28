"""Reviews-Only Public Projection Rebuild and Reconciliation Utility.

Operates strictly and exclusively on:
  - 'feedback' (authoritative review source collection)
  - 'public_destination_reviews' (derived consumer read projection)

Never reads, updates, or deletes records in 'tourism_packages',
'promotional_campaigns', 'public_tourism_packages', or 'public_promotional_campaigns'.

Default mode is strictly DRY-RUN.
Apply requires an existing reviewed manifest, its independently approved digest,
and an exclusive backup path. This release permits only the isolated demo project.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import firebase_admin
from firebase_service import get_db, init_firebase
from services.review_service import (
    ReviewConflict,
    published_review,
    review_revision,
)
from services.public_content_projection import (
    PUBLIC_REVIEW_COLLECTION,
    public_review,
)

FEEDBACK_COLLECTION = 'feedback'
PROHIBITED_PRODUCTION_PROJECT = 'travelmate2-30a8a'
ISOLATED_PROJECT = 'demo-travelmate-f3p2v'


def init_reviews_firebase(expected_project):
    """Initialize Firebase Admin safely with project assertion and emulator support."""
    env_project = os.environ.get('GOOGLE_CLOUD_PROJECT')
    if env_project and env_project != expected_project:
        raise RuntimeError(
            f"Environment GOOGLE_CLOUD_PROJECT '{env_project}' does not match "
            f"specified target project '{expected_project}'."
        )

    if firebase_admin._apps:
        app = firebase_admin.get_app()
        if app.project_id != expected_project:
            raise RuntimeError(
                f"Existing Firebase app project '{app.project_id}' does not match "
                f"expected target project '{expected_project}'."
            )
        return app

    fs_host = os.environ.get('FIRESTORE_EMULATOR_HOST')
    auth_host = os.environ.get('FIREBASE_AUTH_EMULATOR_HOST')

    # If running against emulator or test project, use AnonymousCredentials and enforce project
    if fs_host or auth_host or expected_project.startswith('demo-'):
        from google.auth.credentials import AnonymousCredentials

        class LocalCredential(firebase_admin.credentials.Base):
            def get_credential(self):
                return AnonymousCredentials()

        return firebase_admin.initialize_app(LocalCredential(), {'projectId': expected_project})

    # Otherwise fallback to standard init_firebase with expected project options
    os.environ['GOOGLE_CLOUD_PROJECT'] = expected_project
    return init_firebase()


def assert_project_safety(expected_project, is_apply=False, db=None):
    """Enforce strict project identity checks and prevent unauthorized writes."""
    if not expected_project:
        raise ValueError("Target project must be explicitly specified via --project")

    # Enforce batch constraint: Production apply is strictly prohibited
    if is_apply and expected_project != ISOLATED_PROJECT:
        raise RuntimeError(
            "Production apply is strictly prohibited; only the isolated demo project is enabled."
        )

    app = firebase_admin.get_app()
    resolved = getattr(app, 'project_id', None)
    if resolved != expected_project or os.environ.get('GOOGLE_CLOUD_PROJECT', expected_project) != expected_project:
        raise RuntimeError(
            "Firebase Admin/environment project does not match expected project."
        )

    # In emulated environment, assert emulator settings
    fs_host = os.environ.get('FIRESTORE_EMULATOR_HOST')
    if expected_project.startswith('demo-') and not fs_host:
        raise RuntimeError(
            f"Expected FIRESTORE_EMULATOR_HOST for test project '{expected_project}', "
            "but emulator environment variable is missing."
        )
    if db is not None:
        resource = f'projects/{expected_project}/databases/(default)'
        if db.project != expected_project or db._database_string != resource:
            raise RuntimeError('Firestore client project/database does not match expected project.')
        if expected_project == ISOLATED_PROJECT:
            from google.auth.credentials import AnonymousCredentials
            from urllib.parse import urlsplit
            host = urlsplit('http://' + (fs_host or ''))
            if (host.hostname not in {'127.0.0.1', 'localhost', '::1'} or not host.port
                    or host.path or host.username or host.password
                    or db._emulator_host != fs_host or db._target != fs_host
                    or not isinstance(db._credentials, AnonymousCredentials)):
                raise RuntimeError('Demo Firestore must use anonymous credentials and loopback emulator transport.')


def _encode_record(record):
    """Firestore's typed JSON retains timestamps, bytes, references and numeric types."""
    if record is None:
        return None
    from google.cloud.firestore_v1 import _helpers
    from google.cloud.firestore_v1.types import Document
    return json.loads(Document.to_json(Document(fields=_helpers.encode_dict(record))))


def _decode_record(record, db):
    if record is None:
        return None
    from google.cloud.firestore_v1 import _helpers
    from google.cloud.firestore_v1.types import Document
    return _helpers.decode_dict(Document.from_json(json.dumps(record)).fields, db)


def _fingerprint(record):
    """Deterministic hash of document content for CAS validation."""
    payload = json.dumps(_encode_record(record), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def manifest_digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _snapshot_state(snapshot, source=False):
    record = snapshot.to_dict() if snapshot.exists else None
    version = getattr(snapshot, 'update_time', None)
    state = {'exists': snapshot.exists, 'fingerprint': _fingerprint(record),
             'updateTime': version.isoformat() if version is not None else None}
    if source:
        state['contentRevision'] = review_revision(record) if record is not None else None
    return state


def write_artifact(path, data):
    """Never overwrite evidence. Windows callers must pre-restrict the parent ACL."""
    descriptor = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump(data, output, indent=2)
        output.flush()
        os.fsync(output.fileno())


def _is_projection_compliant(existing_proj, expected_proj):
    """Check if an existing projection already matches the expected published contract."""
    # Extra legacy private fields must be removed, not accepted as compliant.
    return existing_proj is not None and _fingerprint(existing_proj) == _fingerprint(expected_proj)


def plan_review_migration(db, destination_id=None):
    """Analyze all feedback source documents and public projections without mutating anything.
    
    Returns manifest and source/projection snapshots for read-only inspection.
    """
    assert_project_safety(db.project, db=db)
    # 1. Read all feedback records
    feedback_ref = db.collection(FEEDBACK_COLLECTION)
    if destination_id:
        feedback_docs = feedback_ref.where('destinationId', '==', destination_id).stream()
    else:
        feedback_docs = feedback_ref.stream()

    sources = {}
    source_states = {}
    for doc in feedback_docs:
        sources[doc.id] = doc.to_dict()
        source_states[doc.id] = _snapshot_state(doc, source=True)

    # 2. Read all public_destination_reviews records
    proj_ref = db.collection(PUBLIC_REVIEW_COLLECTION)
    if destination_id:
        proj_docs = proj_ref.where('destinationId', '==', destination_id).stream()
    else:
        proj_docs = proj_ref.stream()

    existing_projections = {}
    projection_states = {}
    for doc in proj_docs:
        existing_projections[doc.id] = doc.to_dict()
        projection_states[doc.id] = _snapshot_state(doc)

    if destination_id:
        for doc_id in sources:
            if doc_id not in projection_states:
                snap = proj_ref.document(doc_id).get()
                projection_states[doc_id] = _snapshot_state(snap)
                if snap.exists:
                    existing_projections[doc_id] = snap.to_dict()
        for doc_id in existing_projections:
            if doc_id not in source_states:
                snap = feedback_ref.document(doc_id).get()
                if snap.exists:
                    raise RuntimeError('Scoped source/projection destination mismatch; review an unscoped plan.')
                source_states[doc_id] = _snapshot_state(snap, source=True)

    # 3. Categorize sources
    total_sources = len(sources)
    approved_sources = {}
    pending_sources = {}
    rejected_hidden_sources = {}
    invalid_unknown_sources = {}

    for doc_id, data in sources.items():
        feedback_status = data.get('feedbackStatus')
        moderation_status = data.get('moderationStatus')

        # Check published review criteria (explicit visible + reviewed/approved + valid rating)
        if published_review(data):
            approved_sources[doc_id] = data
        elif feedback_status == 'visible' and moderation_status == 'pending_review':
            pending_sources[doc_id] = data
        elif moderation_status in {'rejected', 'removed', 'hidden'} or feedback_status in {'removed', 'hidden'}:
            rejected_hidden_sources[doc_id] = data
        else:
            invalid_unknown_sources[doc_id] = data

    # 4. Analyze distinct owner contributions for approved reviews
    owner_dest_contributions = {}
    for doc_id, data in approved_sources.items():
        owner_key = (data.get('travellerId') or doc_id, data.get('destinationId'))
        owner_dest_contributions.setdefault(owner_key, []).append(doc_id)

    distinct_approved_contributions = len(owner_dest_contributions)
    duplicate_owner_contributions = len(approved_sources) - distinct_approved_contributions

    # 5. Formulate projection reconciliation plan
    to_create = []
    to_update = []
    to_remove = []
    unchanged = []

    # A. Check approved sources against projections
    for doc_id, src in approved_sources.items():
        expected = public_review({**src, 'id': doc_id})
        existing = existing_projections.get(doc_id)

        if existing is None:
            to_create.append({
                'id': doc_id,
                'sourceFingerprint': _fingerprint(src),
                'expectedProjection': _encode_record(expected),
            })
        elif _is_projection_compliant(existing, expected):
            unchanged.append(doc_id)
        else:
            to_update.append({
                'id': doc_id,
                'sourceFingerprint': _fingerprint(src),
                'expectedProjection': _encode_record(expected),
                'currentProjectionFingerprint': _fingerprint(existing),
            })

    # B. Check existing projections for stale entries
    for doc_id, proj in existing_projections.items():
        src = sources.get(doc_id)
        if src is None or not published_review(src):
            to_remove.append({
                'id': doc_id,
                'currentProjectionFingerprint': _fingerprint(proj),
                'reason': 'source_missing' if not src else f'source_not_approved_{src.get("moderationStatus")}',
            })

    for item in to_create + to_update + to_remove:
        doc_id = item['id']
        # Paired reads also prevent a scoped query from treating a moved source as an orphan.
        if doc_id not in source_states:
            snap = feedback_ref.document(doc_id).get()
            source_states[doc_id] = _snapshot_state(snap, source=True)
        if doc_id not in projection_states:
            snap = proj_ref.document(doc_id).get()
            projection_states[doc_id] = _snapshot_state(snap)
            if snap.exists:
                existing_projections[doc_id] = snap.to_dict()
        item['sourceState'] = source_states[doc_id]
        item['projectionState'] = projection_states[doc_id]
        item['projectionBefore'] = _encode_record(existing_projections.get(doc_id))
        item.setdefault('expectedProjection', None)

    manifest = {
        'schemaVersion': 2,
        'projectId': db.project,
        'database': db._database_string,
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'destinationScope': destination_id or 'all',
        'counts': {
            'totalSourcesExamined': total_sources,
            'approvedSources': len(approved_sources),
            'distinctApprovedContributions': distinct_approved_contributions,
            'duplicateOwnerContributions': duplicate_owner_contributions,
            'pendingSources': len(pending_sources),
            'rejectedHiddenSources': len(rejected_hidden_sources),
            'invalidUnknownSources': len(invalid_unknown_sources),
            'existingProjections': len(existing_projections),
            'projectionsToCreate': len(to_create),
            'projectionsToUpdate': len(to_update),
            'projectionsToRemove': len(to_remove),
            'projectionsUnchanged': len(unchanged),
            'skippedConcurrentChanges': 0,
        },
        'actions': {
            'creates': to_create,
            'updates': to_update,
            'removals': to_remove,
            'unchanged': unchanged,
        }
    }

    return manifest, sources, existing_projections


def execute_migration(db, manifest, expected_project, *, reviewed_digest, backup_path):
    """Apply only reviewed IDs, with full before-images durable before the first write."""
    assert_project_safety(expected_project, is_apply=True, db=db)
    if (not reviewed_digest or manifest_digest(manifest) != reviewed_digest
            or manifest.get('schemaVersion') != 2 or manifest.get('projectId') != expected_project
            or manifest.get('database') != db._database_string):
        raise ValueError('A matching reviewed manifest and project/database are required.')
    actions = manifest['actions']
    items = actions['removals'] + actions['creates'] + actions['updates']
    ids = [item['id'] for item in items]
    if len(ids) != len(set(ids)) or any(not isinstance(key, str) or not key or '/' in key for key in ids):
        raise ValueError('Manifest contains invalid or duplicate document IDs.')
    for group, count_key in (('creates', 'projectionsToCreate'), ('updates', 'projectionsToUpdate'),
                             ('removals', 'projectionsToRemove')):
        if manifest['counts'][count_key] != len(actions[group]):
            raise ValueError('Manifest action counts do not match reviewed IDs.')
        for item in actions[group]:
            if ((item['projectionBefore'] is not None) != (group != 'creates')
                    or (item['expectedProjection'] is None) != (group == 'removals')):
                raise ValueError('Manifest action type does not match its before/after images.')
    for item in items:
        if _fingerprint(_decode_record(item['projectionBefore'], db)) != item['projectionState']['fingerprint']:
            raise ValueError('Manifest before-image integrity failure.')
    write_artifact(backup_path, {'manifestSha256': reviewed_digest, 'manifest': manifest,
                                'recovery': 'forward-reconciliation-only; never blindly restore projections'})
    from google.cloud import firestore

    counts = dict(manifest['counts'])
    applied_creates = 0
    applied_updates = 0
    applied_removals = 0
    skipped_conflicts = 0

    for item in items:
        source = db.collection(FEEDBACK_COLLECTION).document(item['id'])
        projection = db.collection(PUBLIC_REVIEW_COLLECTION).document(item['id'])

        @firestore.transactional
        def reconcile(transaction):
            source_snap = source.get(transaction=transaction)
            projection_snap = projection.get(transaction=transaction)
            if (_snapshot_state(source_snap, source=True) != item['sourceState']
                    or _snapshot_state(projection_snap) != item['projectionState']):
                raise ReviewConflict('Source or projection changed; generate and review a new manifest.')
            current = source_snap.to_dict() if source_snap.exists else None
            desired = public_review({**current, 'id': item['id']}) if current is not None and published_review(current) else None
            if _encode_record(desired) != item['expectedProjection']:
                raise ReviewConflict('Current publication contract differs from the reviewed plan.')
            if desired is None:
                transaction.delete(projection)
            else:
                transaction.set(projection, desired)

        try:
            reconcile(db.transaction())
            if item in actions['creates']:
                applied_creates += 1
            elif item in actions['removals']:
                applied_removals += 1
            else:
                applied_updates += 1
        except ReviewConflict:
            skipped_conflicts += 1

    counts['projectionsCreated'] = applied_creates
    counts['projectionsUpdated'] = applied_updates
    counts['projectionsRemoved'] = applied_removals
    counts['skippedConcurrentChanges'] = skipped_conflicts

    return counts


def format_report(manifest, mode='dry-run', applied_counts=None):
    """Format an audit report without leaking personal information or review text."""
    c = applied_counts or manifest['counts']
    lines = [
        "================================================================================",
        f"TRAVELMATE LOCAL REVIEWS PROJECTION RECONCILIATION REPORT ({mode.upper()})",
        "================================================================================",
        f"Execution Timestamp : {manifest.get('timestamp')}",
        f"Destination Scope   : {manifest.get('destinationScope')}",
        "--------------------------------------------------------------------------------",
        "AUTHORITATIVE SOURCE CLASSIFICATION (feedback):",
        f"  Total Source Documents Examined   : {c.get('totalSourcesExamined', 0)}",
        f"  Explicitly Approved Sources        : {c.get('approvedSources', 0)}",
        f"  - Distinct Approved Contributions : {c.get('distinctApprovedContributions', 0)}",
        f"  - Duplicate Owner Contributions   : {c.get('duplicateOwnerContributions', 0)}",
        f"  Pending Sources (awaiting admin)  : {c.get('pendingSources', 0)}",
        f"  Rejected or Hidden Sources        : {c.get('rejectedHiddenSources', 0)}",
        f"  Invalid or Unknown Status Sources : {c.get('invalidUnknownSources', 0)}",
        "--------------------------------------------------------------------------------",
        "PUBLIC PROJECTION RECONCILIATION (public_destination_reviews):",
        f"  Existing Public Projections       : {c.get('existingProjections', 0)}",
        f"  Projections Unchanged (compliant) : {c.get('projectionsUnchanged', 0)}",
        f"  Projections Requiring Creation    : {c.get('projectionsToCreate', 0)}",
        f"  Projections Requiring Update      : {c.get('projectionsToUpdate', 0)}",
        f"  Projections Requiring Removal     : {c.get('projectionsToRemove', 0)}",
    ]
    if mode == 'apply':
        lines.extend([
            "--------------------------------------------------------------------------------",
            "APPLIED MUTATIONS (CAS Verified):",
            f"  Projections Created               : {c.get('projectionsCreated', 0)}",
            f"  Projections Updated               : {c.get('projectionsUpdated', 0)}",
            f"  Projections Removed (stale)       : {c.get('projectionsRemoved', 0)}",
            f"  Concurrent Change Conflicts       : {c.get('skippedConcurrentChanges', 0)}",
        ])
    lines.append("================================================================================")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Reviews-only public projection reconciliation and migration utility."
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Execute mutations against Firestore projections (default: dry-run only)'
    )
    parser.add_argument(
        '--project',
        required=True,
        help='Explicit target Firebase project ID (e.g. demo-travelmate-f3p2v)'
    )
    parser.add_argument(
        '--destination-id',
        default=None,
        help='Optional: Restrict reconciliation to a single destination ID'
    )
    parser.add_argument(
        '--manifest-path',
        default=None,
        help='Dry-run output path (new file in a protected directory)'
    )
    parser.add_argument('--reviewed-manifest', help='Apply only: previously reviewed dry-run manifest')
    parser.add_argument('--manifest-sha256', help='Apply only: independently approved canonical manifest digest')
    parser.add_argument('--backup-path', help='Apply only: new protected before-image evidence file')
    args = parser.parse_args()

    # No real-project inventory or apply is enabled by this isolated verification release.
    if args.project != ISOLATED_PROJECT:
        raise RuntimeError('Only demo-travelmate-f3p2v is authorized by this release; production is denied.')
    if args.apply and (not args.reviewed_manifest or not args.manifest_sha256 or not args.backup_path
                       or args.manifest_path or args.destination_id):
        parser.error('Apply requires --reviewed-manifest, --manifest-sha256 and --backup-path; no replanning flags.')

    # Safely initialize Firebase Admin targeting the requested project
    init_reviews_firebase(args.project)
    assert_project_safety(args.project, is_apply=args.apply)

    db = get_db()
    assert_project_safety(args.project, is_apply=args.apply, db=db)

    if not args.apply:
        manifest, _, _ = plan_review_migration(db, destination_id=args.destination_id)
        if args.manifest_path:
            write_artifact(args.manifest_path, manifest)
        print(format_report(manifest, mode='dry-run'))
        print('Manifest SHA-256:', manifest_digest(manifest))
        return 0

    manifest = json.loads(Path(args.reviewed_manifest).read_text(encoding='utf-8'))
    applied_counts = execute_migration(db, manifest, args.project,
                                       reviewed_digest=args.manifest_sha256, backup_path=args.backup_path)
    print(format_report(manifest, mode='apply', applied_counts=applied_counts))
    return 2 if applied_counts['skippedConcurrentChanges'] else 0


if __name__ == '__main__':
    sys.exit(main())
