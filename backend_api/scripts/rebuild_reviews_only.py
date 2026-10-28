"""Reviews-Only Public Projection Rebuild and Reconciliation Utility.

Operates strictly and exclusively on:
  - 'feedback' (authoritative review source collection)
  - 'public_destination_reviews' (derived consumer read projection)

Never reads, updates, or deletes records in 'tourism_packages',
'promotional_campaigns', 'public_tourism_packages', or 'public_promotional_campaigns'.

Default mode is strictly DRY-RUN.
Apply mode requires explicit --apply and --project <project_id>.
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
    approved_reviews,
    commit_feedback,
    published_review,
    review_id,
)
from services.public_content_projection import (
    PUBLIC_REVIEW_COLLECTION,
    public_review,
)

FEEDBACK_COLLECTION = 'feedback'
PROHIBITED_PRODUCTION_PROJECT = 'travelmate2-30a8a'


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


def assert_project_safety(expected_project, is_apply=False):
    """Enforce strict project identity checks and prevent unauthorized writes."""
    if not expected_project:
        raise ValueError("Target project must be explicitly specified via --project")

    # Enforce batch constraint: Production apply is strictly prohibited
    if is_apply and expected_project == PROHIBITED_PRODUCTION_PROJECT:
        raise RuntimeError(
            f"Production apply against '{PROHIBITED_PRODUCTION_PROJECT}' is strictly prohibited "
            "in this verification batch."
        )

    app = firebase_admin.get_app()
    resolved = getattr(app, 'project_id', None) or os.environ.get('GOOGLE_CLOUD_PROJECT')
    if resolved != expected_project:
        raise RuntimeError(
            f"Firebase Admin resolved project '{resolved}' does not match "
            f"expected project '{expected_project}'. Aborting for safety."
        )

    # In emulated environment, assert emulator settings
    fs_host = os.environ.get('FIRESTORE_EMULATOR_HOST')
    if expected_project.startswith('demo-') and not fs_host:
        raise RuntimeError(
            f"Expected FIRESTORE_EMULATOR_HOST for test project '{expected_project}', "
            "but emulator environment variable is missing."
        )


def _fingerprint(record):
    """Deterministic hash of document content for CAS validation."""
    payload = json.dumps(record or {}, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _is_projection_compliant(existing_proj, expected_proj):
    """Check if an existing projection already matches the expected published contract."""
    if not existing_proj:
        return False
    if existing_proj.get('publicationStatus') != 'approved':
        return False
    if existing_proj.get('reviewKey') != expected_proj.get('reviewKey'):
        return False
    # Check core public fields
    core_keys = ('rating', 'description', 'destinationId', 'source', 'username')
    for k in core_keys:
        if str(existing_proj.get(k) or '').strip() != str(expected_proj.get(k) or '').strip():
            return False
    return True


def plan_review_migration(db, destination_id=None):
    """Analyze all feedback source documents and public projections without mutating anything.
    
    Returns a tuple of (manifest, actions).
    """
    # 1. Read all feedback records
    feedback_ref = db.collection(FEEDBACK_COLLECTION)
    if destination_id:
        feedback_docs = feedback_ref.where('destinationId', '==', destination_id).stream()
    else:
        feedback_docs = feedback_ref.stream()

    sources = {}
    for doc in feedback_docs:
        sources[doc.id] = doc.to_dict()

    # 2. Read all public_destination_reviews records
    proj_ref = db.collection(PUBLIC_REVIEW_COLLECTION)
    if destination_id:
        proj_docs = proj_ref.where('destinationId', '==', destination_id).stream()
    else:
        proj_docs = proj_ref.stream()

    existing_projections = {}
    for doc in proj_docs:
        existing_projections[doc.id] = doc.to_dict()

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
        owner_key = (data.get('travellerId') or data.get('id'), data.get('destinationId'))
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
        expected = public_review({'id': doc_id, **src})
        existing = existing_projections.get(doc_id)

        if not existing:
            to_create.append({
                'id': doc_id,
                'sourceFingerprint': _fingerprint(src),
                'expectedProjection': expected,
            })
        elif _is_projection_compliant(existing, expected):
            unchanged.append(doc_id)
        else:
            to_update.append({
                'id': doc_id,
                'sourceFingerprint': _fingerprint(src),
                'expectedProjection': expected,
                'currentProjectionFingerprint': _fingerprint(existing),
            })

    # B. Check existing projections for stale entries
    for doc_id, proj in existing_projections.items():
        src = sources.get(doc_id)
        if not src or not published_review(src):
            to_remove.append({
                'id': doc_id,
                'currentProjectionFingerprint': _fingerprint(proj),
                'reason': 'source_missing' if not src else f'source_not_approved_{src.get("moderationStatus")}',
            })

    manifest = {
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


def execute_migration(db, manifest, sources, existing_projections, expected_project):
    """Execute the planned migration with CAS source verification and audit logging."""
    assert_project_safety(expected_project, is_apply=True)

    counts = dict(manifest['counts'])
    applied_creates = 0
    applied_updates = 0
    applied_removals = 0
    skipped_conflicts = 0

    actions = manifest['actions']

    # 1. Execute Removals (stale projections)
    for item in actions['removals']:
        doc_id = item['id']
        src = sources.get(doc_id)
        if src:
            try:
                # Use CAS commit_feedback with patch={} to delete projection
                commit_feedback(doc_id, src, patch={})
                applied_removals += 1
            except ReviewConflict:
                skipped_conflicts += 1
        else:
            # Orphaned projection with no source document
            db.collection(PUBLIC_REVIEW_COLLECTION).document(doc_id).delete()
            applied_removals += 1

    # 2. Execute Creates & Updates
    for item in (actions['creates'] + actions['updates']):
        doc_id = item['id']
        src = sources.get(doc_id)
        if not src:
            skipped_conflicts += 1
            continue
        try:
            # CAS update projection using canonical commit_feedback
            commit_feedback(doc_id, src, patch={})
            if item in actions['creates']:
                applied_creates += 1
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
        help='Optional: Output file path for audit manifest JSON'
    )
    args = parser.parse_args()

    # Safely initialize Firebase Admin targeting the requested project
    init_reviews_firebase(args.project)
    assert_project_safety(args.project, is_apply=args.apply)

    db = get_db()
    manifest, sources, existing_projections = plan_review_migration(db, destination_id=args.destination_id)

    if args.manifest_path:
        out_path = Path(args.manifest_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    if not args.apply:
        print(format_report(manifest, mode='dry-run'))
        return 0

    applied_counts = execute_migration(db, manifest, sources, existing_projections, args.project)
    print(format_report(manifest, mode='apply', applied_counts=applied_counts))
    return 0


if __name__ == '__main__':
    sys.exit(main())
