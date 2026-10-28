"""Unit and Integration Tests for Reviews-Only Public Projection Rebuild Utility.

Tests all 15 scenarios mandated in TravelMate Batch R-DEP1:
1. Empty database handling.
2. One approved legacy review projection creation.
3. Multiple approved reviews across destinations.
4. Pending reviews remain unpublished.
5. Rejected/hidden reviews remain unpublished.
6. Missing moderation status remains unpublished.
7. Existing approved projections updated with required publicationStatus and reviewKey.
8. Stale projections (missing/unapproved sources) marked and removed.
9. Duplicate historical owner contributions deduplicated logically while preserving source records.
10. Idempotent repeated execution.
11. Safe conflict handling when source changes concurrently (CAS).
12. Strict rejection of incorrect or production project identity.
13. Zero mutations during dry-run.
14. Zero cross-collection mutations (Package/Campaign data intact).
15. Accurate backup/recovery manifest generation.
"""

import copy
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rebuild_reviews_only import (
    FEEDBACK_COLLECTION,
    PUBLIC_REVIEW_COLLECTION,
    PROHIBITED_PRODUCTION_PROJECT,
    assert_project_safety,
    execute_migration,
    format_report,
    plan_review_migration,
)
from services.review_service import ReviewConflict, review_id


class FakeDocSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = copy.deepcopy(data) if data is not None else None

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class FakeFirestoreDB:
    """Deterministic in-memory Firestore fixture supporting collections, streams, docs, and CAS transactions."""

    def __init__(self):
        self.collections = {
            FEEDBACK_COLLECTION: {},
            PUBLIC_REVIEW_COLLECTION: {},
            'tourism_packages': {},
            'promotional_campaigns': {},
            'public_tourism_packages': {},
            'public_promotional_campaigns': {},
        }

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = {}
        return FakeCollectionRef(self, name)

    def transaction(self):
        return FakeTransaction(self)


class FakeCollectionRef:
    def __init__(self, db, name, filters=None):
        self.db = db
        self.name = name
        self.filters = filters or []

    def document(self, doc_id):
        return FakeDocumentRef(self.db, self.name, str(doc_id))

    def where(self, field, op, value):
        new_filters = list(self.filters)
        new_filters.append((field, op, value))
        return FakeCollectionRef(self.db, self.name, new_filters)

    def stream(self):
        docs = []
        for doc_id, data in list(self.db.collections[self.name].items()):
            match = True
            for field, op, value in self.filters:
                if op == '==' and data.get(field) != value:
                    match = False
                    break
            if match:
                docs.append(FakeDocSnapshot(doc_id, data))
        return docs


class FakeDocumentRef:
    def __init__(self, db, col_name, doc_id):
        self.db = db
        self.col_name = col_name
        self.doc_id = doc_id

    def get(self, transaction=None):
        data = self.db.collections[self.col_name].get(self.doc_id)
        return FakeDocSnapshot(self.doc_id, data)

    def set(self, data):
        self.db.collections[self.col_name][self.doc_id] = copy.deepcopy(data)

    def delete(self):
        self.db.collections[self.col_name].pop(self.doc_id, None)


class FakeTransaction:
    def __init__(self, db):
        self.db = db
        self.writes = []

    def get(self, doc_ref):
        return doc_ref.get()

    def set(self, doc_ref, data):
        self.writes.append(('set', doc_ref.col_name, doc_ref.doc_id, copy.deepcopy(data)))

    def update(self, doc_ref, data):
        self.writes.append(('update', doc_ref.col_name, doc_ref.doc_id, copy.deepcopy(data)))

    def delete(self, doc_ref):
        self.writes.append(('delete', doc_ref.col_name, doc_ref.doc_id, None))


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeFirestoreDB()
    monkeypatch.setattr('firebase_service.get_db', lambda: db)
    monkeypatch.setattr('scripts.rebuild_reviews_only.get_db', lambda: db)

    # Wrap transactional decorator for commit_feedback
    def fake_transactional(fn):
        def wrapper(transaction, *args, **kwargs):
            res = fn(transaction, *args, **kwargs)
            # Commit pending writes
            for action, col, doc_id, data in transaction.writes:
                if action == 'set':
                    db.collections[col][doc_id] = data
                elif action == 'update':
                    if doc_id in db.collections[col]:
                        db.collections[col][doc_id].update(data)
                elif action == 'delete':
                    db.collections[col].pop(doc_id, None)
            return res
        return wrapper

    from google.cloud import firestore as real_firestore
    monkeypatch.setattr(real_firestore, 'transactional', fake_transactional)
    return db


@pytest.fixture
def fake_app(monkeypatch):
    app = MagicMock()
    app.project_id = 'demo-travelmate-f3p2v'
    monkeypatch.setattr('firebase_admin.get_app', lambda: app)
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT', 'demo-travelmate-f3p2v')
    monkeypatch.setenv('FIRESTORE_EMULATOR_HOST', '127.0.0.1:18085')
    return app


# -----------------------------------------------------------------------------
# 1. Empty Database
# -----------------------------------------------------------------------------
def test_1_empty_database(fake_db):
    manifest, sources, projs = plan_review_migration(fake_db)
    assert manifest['counts']['totalSourcesExamined'] == 0
    assert manifest['counts']['approvedSources'] == 0
    assert manifest['counts']['projectionsToCreate'] == 0
    assert manifest['counts']['projectionsToUpdate'] == 0
    assert manifest['counts']['projectionsToRemove'] == 0


# -----------------------------------------------------------------------------
# 2. One Approved Legacy Review
# -----------------------------------------------------------------------------
def test_2_one_approved_legacy_review(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_1'] = {
        'id': 'rev_1',
        'destinationId': 'penang_hill',
        'travellerId': 'user_a',
        'travellerName': 'Alice',
        'rating': 5,
        'comment': 'Scenic and pleasant funicular ride.',
        'feedbackStatus': 'visible',
        'moderationStatus': 'reviewed',
        'submittedAt': '2026-01-10T10:00:00Z',
    }
    manifest, sources, projs = plan_review_migration(fake_db)
    assert manifest['counts']['totalSourcesExamined'] == 1
    assert manifest['counts']['approvedSources'] == 1
    assert manifest['counts']['projectionsToCreate'] == 1

    applied = execute_migration(fake_db, manifest, sources, projs, 'demo-travelmate-f3p2v')
    assert applied['projectionsCreated'] == 1
    created_proj = fake_db.collections[PUBLIC_REVIEW_COLLECTION].get('rev_1')
    assert created_proj is not None
    assert created_proj['publicationStatus'] == 'approved'
    assert created_proj['reviewKey'] == review_id('user_a', 'penang_hill')
    assert created_proj['rating'] == 5


# -----------------------------------------------------------------------------
# 3. Multiple Approved Reviews Across Destinations
# -----------------------------------------------------------------------------
def test_3_multiple_approved_reviews(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_1'] = {
        'id': 'rev_1', 'destinationId': 'dest_a', 'travellerId': 'user_a',
        'rating': 4, 'comment': 'Great historic streets.', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'
    }
    fake_db.collections[FEEDBACK_COLLECTION]['rev_2'] = {
        'id': 'rev_2', 'destinationId': 'dest_b', 'travellerId': 'user_b',
        'rating': 5, 'comment': 'Stunning sunrise views.', 'feedbackStatus': 'visible', 'moderationStatus': 'approved'
    }
    manifest, sources, projs = plan_review_migration(fake_db)
    assert manifest['counts']['approvedSources'] == 2
    assert manifest['counts']['projectionsToCreate'] == 2

    execute_migration(fake_db, manifest, sources, projs, 'demo-travelmate-f3p2v')
    assert len(fake_db.collections[PUBLIC_REVIEW_COLLECTION]) == 2


# -----------------------------------------------------------------------------
# 4. Pending Review Remains Unpublished
# -----------------------------------------------------------------------------
def test_4_pending_review_remains_unpublished(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_pending'] = {
        'id': 'rev_pending', 'destinationId': 'dest_a', 'travellerId': 'user_a',
        'rating': 5, 'comment': 'Pending submission.', 'feedbackStatus': 'visible', 'moderationStatus': 'pending_review'
    }
    manifest, sources, projs = plan_review_migration(fake_db)
    assert manifest['counts']['pendingSources'] == 1
    assert manifest['counts']['approvedSources'] == 0
    assert manifest['counts']['projectionsToCreate'] == 0

    applied = execute_migration(fake_db, manifest, sources, projs, 'demo-travelmate-f3p2v')
    assert applied['projectionsCreated'] == 0
    assert 'rev_pending' not in fake_db.collections[PUBLIC_REVIEW_COLLECTION]


# -----------------------------------------------------------------------------
# 5. Rejected Review Remains Unpublished
# -----------------------------------------------------------------------------
def test_5_rejected_review_remains_unpublished(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_rej'] = {
        'id': 'rev_rej', 'destinationId': 'dest_a', 'travellerId': 'user_c',
        'rating': 1, 'comment': 'Inappropriate content.', 'feedbackStatus': 'removed', 'moderationStatus': 'rejected'
    }
    manifest, sources, projs = plan_review_migration(fake_db)
    assert manifest['counts']['rejectedHiddenSources'] == 1
    assert manifest['counts']['approvedSources'] == 0
    assert manifest['counts']['projectionsToCreate'] == 0


# -----------------------------------------------------------------------------
# 6. Missing Moderation Status Remains Unpublished
# -----------------------------------------------------------------------------
def test_6_missing_moderation_status_unpublished(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_unknown'] = {
        'id': 'rev_unknown', 'destinationId': 'dest_a', 'travellerId': 'user_d',
        'rating': 4, 'comment': 'Legacy record without moderationStatus field.', 'feedbackStatus': 'visible'
    }
    manifest, sources, projs = plan_review_migration(fake_db)
    assert manifest['counts']['invalidUnknownSources'] == 1
    assert manifest['counts']['approvedSources'] == 0
    assert manifest['counts']['projectionsToCreate'] == 0


# -----------------------------------------------------------------------------
# 7. Existing Approved Projection Receives Required Marker & Key
# -----------------------------------------------------------------------------
def test_7_existing_projection_updates_marker_and_key(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_legacy'] = {
        'id': 'rev_legacy', 'destinationId': 'kek_lok_si', 'travellerId': 'user_x', 'travellerName': 'Xavier',
        'rating': 5, 'comment': 'Beautiful pagoda and temples.', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'
    }
    # Existing legacy projection lacks publicationStatus and reviewKey
    fake_db.collections[PUBLIC_REVIEW_COLLECTION]['rev_legacy'] = {
        'id': 'rev_legacy', 'destinationId': 'kek_lok_si', 'rating': 5, 'description': 'Beautiful pagoda and temples.'
    }
    manifest, sources, projs = plan_review_migration(fake_db)
    assert manifest['counts']['projectionsToCreate'] == 0
    assert manifest['counts']['projectionsToUpdate'] == 1

    execute_migration(fake_db, manifest, sources, projs, 'demo-travelmate-f3p2v')
    updated = fake_db.collections[PUBLIC_REVIEW_COLLECTION]['rev_legacy']
    assert updated['publicationStatus'] == 'approved'
    assert updated['reviewKey'] == review_id('user_x', 'kek_lok_si')


# -----------------------------------------------------------------------------
# 8. Stale Projections Removed
# -----------------------------------------------------------------------------
def test_8_stale_projections_removed(fake_db, fake_app):
    # Case A: Source was rejected by admin
    fake_db.collections[FEEDBACK_COLLECTION]['rev_now_rejected'] = {
        'id': 'rev_now_rejected', 'destinationId': 'dest_a', 'travellerId': 'user_a',
        'rating': 1, 'comment': 'Spam review', 'feedbackStatus': 'removed', 'moderationStatus': 'removed'
    }
    fake_db.collections[PUBLIC_REVIEW_COLLECTION]['rev_now_rejected'] = {
        'id': 'rev_now_rejected', 'rating': 1, 'description': 'Old projection before rejection'
    }
    # Case B: Orphan projection with no source document
    fake_db.collections[PUBLIC_REVIEW_COLLECTION]['rev_orphan'] = {
        'id': 'rev_orphan', 'rating': 4, 'description': 'Orphan projection'
    }

    manifest, sources, projs = plan_review_migration(fake_db)
    assert manifest['counts']['projectionsToRemove'] == 2

    applied = execute_migration(fake_db, manifest, sources, projs, 'demo-travelmate-f3p2v')
    assert applied['projectionsRemoved'] == 2
    assert 'rev_now_rejected' not in fake_db.collections[PUBLIC_REVIEW_COLLECTION]
    assert 'rev_orphan' not in fake_db.collections[PUBLIC_REVIEW_COLLECTION]


# -----------------------------------------------------------------------------
# 9. Duplicate Historical Owner Contributions Deduplicated Logically
# -----------------------------------------------------------------------------
def test_9_duplicate_owner_contributions_deduplication(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_old'] = {
        'id': 'rev_old', 'destinationId': 'dest_a', 'travellerId': 'user_same',
        'rating': 4, 'comment': 'First visit in 2025.', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed',
        'submittedAt': '2025-06-01T10:00:00Z'
    }
    fake_db.collections[FEEDBACK_COLLECTION]['rev_new'] = {
        'id': 'rev_new', 'destinationId': 'dest_a', 'travellerId': 'user_same',
        'rating': 5, 'comment': 'Second visit in 2026.', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed',
        'submittedAt': '2026-06-01T10:00:00Z'
    }

    manifest, sources, projs = plan_review_migration(fake_db)
    # Both sources are approved, but they represent 1 distinct owner contribution
    assert manifest['counts']['approvedSources'] == 2
    assert manifest['counts']['distinctApprovedContributions'] == 1
    assert manifest['counts']['duplicateOwnerContributions'] == 1

    execute_migration(fake_db, manifest, sources, projs, 'demo-travelmate-f3p2v')
    # Both projections exist and share identical canonical reviewKey
    p_old = fake_db.collections[PUBLIC_REVIEW_COLLECTION]['rev_old']
    p_new = fake_db.collections[PUBLIC_REVIEW_COLLECTION]['rev_new']
    assert p_old['reviewKey'] == p_new['reviewKey'] == review_id('user_same', 'dest_a')
    # Authoritative feedback collection is preserved (neither source was deleted)
    assert len(fake_db.collections[FEEDBACK_COLLECTION]) == 2


# -----------------------------------------------------------------------------
# 10. Idempotent Repeated Application
# -----------------------------------------------------------------------------
def test_10_idempotent_repeated_application(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_1'] = {
        'id': 'rev_1', 'destinationId': 'dest_a', 'travellerId': 'user_1',
        'rating': 5, 'comment': 'Scenic route.', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'
    }
    # Run 1: Apply
    manifest1, src1, prj1 = plan_review_migration(fake_db)
    execute_migration(fake_db, manifest1, src1, prj1, 'demo-travelmate-f3p2v')

    # Run 2: Re-plan immediately
    manifest2, src2, prj2 = plan_review_migration(fake_db)
    assert manifest2['counts']['projectionsToCreate'] == 0
    assert manifest2['counts']['projectionsToUpdate'] == 0
    assert manifest2['counts']['projectionsToRemove'] == 0
    assert manifest2['counts']['projectionsUnchanged'] == 1

    # Run 2: Apply
    applied2 = execute_migration(fake_db, manifest2, src2, prj2, 'demo-travelmate-f3p2v')
    assert applied2['projectionsCreated'] == 0
    assert applied2['projectionsUpdated'] == 0
    assert applied2['projectionsRemoved'] == 0


# -----------------------------------------------------------------------------
# 11. Safe Conflict Handling When Source Changes Concurrently (CAS)
# -----------------------------------------------------------------------------
def test_11_concurrent_source_edit_safe_conflict(fake_db, fake_app):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_1'] = {
        'id': 'rev_1', 'destinationId': 'dest_a', 'travellerId': 'user_1',
        'rating': 5, 'comment': 'Initial comment', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'
    }
    manifest, sources, prjs = plan_review_migration(fake_db)

    # Simulate concurrent mutation by user between plan and apply
    fake_db.collections[FEEDBACK_COLLECTION]['rev_1']['comment'] = 'User edited comment concurrently'

    # Apply should catch ReviewConflict and increment skippedConcurrentChanges
    applied = execute_migration(fake_db, manifest, sources, prjs, 'demo-travelmate-f3p2v')
    assert applied['skippedConcurrentChanges'] == 1
    # Projection was not mutated with stale snapshot
    assert 'rev_1' not in fake_db.collections[PUBLIC_REVIEW_COLLECTION]


# -----------------------------------------------------------------------------
# 12. Strict Rejection of Incorrect or Production Project Identity
# -----------------------------------------------------------------------------
def test_12_project_safety_assertions(fake_app):
    # Reject project mismatch
    with pytest.raises(RuntimeError, match="does not match expected project"):
        assert_project_safety('wrong-project-id', is_apply=False)

    # Reject missing project
    with pytest.raises(ValueError, match="Target project must be explicitly specified"):
        assert_project_safety('', is_apply=False)

    # Strictly reject production apply
    with pytest.raises(RuntimeError, match="Production apply against 'travelmate2-30a8a' is strictly prohibited"):
        assert_project_safety(PROHIBITED_PRODUCTION_PROJECT, is_apply=True)


# -----------------------------------------------------------------------------
# 13. Zero Mutations During Dry-Run
# -----------------------------------------------------------------------------
def test_13_dry_run_zero_mutations(fake_db):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_1'] = {
        'id': 'rev_1', 'destinationId': 'dest_a', 'travellerId': 'user_1',
        'rating': 5, 'comment': 'Test review', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'
    }
    manifest, sources, prjs = plan_review_migration(fake_db)
    assert manifest['counts']['projectionsToCreate'] == 1
    # Verify no writes occurred to projections during dry-run
    assert len(fake_db.collections[PUBLIC_REVIEW_COLLECTION]) == 0


# -----------------------------------------------------------------------------
# 14. Zero Cross-Collection Mutations (Package/Campaign Data Intact)
# -----------------------------------------------------------------------------
def test_14_packages_campaigns_unaffected(fake_db, fake_app):
    # Seed Package and Campaign collections with sentinel records
    fake_db.collections['tourism_packages']['pkg_1'] = {'id': 'pkg_1', 'title': 'Penang Heritage'}
    fake_db.collections['promotional_campaigns']['cmp_1'] = {'id': 'cmp_1', 'title': 'Holiday Promo'}
    fake_db.collections['public_tourism_packages']['pkg_1'] = {'id': 'pkg_1', 'title': 'Penang Heritage'}
    fake_db.collections['public_promotional_campaigns']['cmp_1'] = {'id': 'cmp_1', 'title': 'Holiday Promo'}

    snapshot_packages = copy.deepcopy(fake_db.collections['tourism_packages'])
    snapshot_campaigns = copy.deepcopy(fake_db.collections['promotional_campaigns'])
    snapshot_pub_pkgs = copy.deepcopy(fake_db.collections['public_tourism_packages'])
    snapshot_pub_cmps = copy.deepcopy(fake_db.collections['public_promotional_campaigns'])

    fake_db.collections[FEEDBACK_COLLECTION]['rev_1'] = {
        'id': 'rev_1', 'destinationId': 'dest_a', 'travellerId': 'user_1',
        'rating': 5, 'comment': 'Test review', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'
    }

    manifest, sources, prjs = plan_review_migration(fake_db)
    execute_migration(fake_db, manifest, sources, prjs, 'demo-travelmate-f3p2v')

    # Assert Package & Campaign collections are completely identical and untouched
    assert fake_db.collections['tourism_packages'] == snapshot_packages
    assert fake_db.collections['promotional_campaigns'] == snapshot_campaigns
    assert fake_db.collections['public_tourism_packages'] == snapshot_pub_pkgs
    assert fake_db.collections['public_promotional_campaigns'] == snapshot_pub_cmps


# -----------------------------------------------------------------------------
# 15. Accurate Backup/Recovery Manifest Generation
# -----------------------------------------------------------------------------
def test_15_manifest_generation(fake_db, tmp_path):
    fake_db.collections[FEEDBACK_COLLECTION]['rev_1'] = {
        'id': 'rev_1', 'destinationId': 'dest_a', 'travellerId': 'user_1',
        'rating': 5, 'comment': 'Manifest review', 'feedbackStatus': 'visible', 'moderationStatus': 'reviewed'
    }
    manifest, sources, prjs = plan_review_migration(fake_db)
    manifest_file = tmp_path / 'audit_manifest.json'
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    loaded = json.loads(manifest_file.read_text(encoding='utf-8'))
    assert loaded['counts']['approvedSources'] == 1
    assert len(loaded['actions']['creates']) == 1
    assert loaded['actions']['creates'][0]['id'] == 'rev_1'
    assert 'expectedProjection' in loaded['actions']['creates'][0]
    assert loaded['actions']['creates'][0]['expectedProjection']['publicationStatus'] == 'approved'
