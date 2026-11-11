import os
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.plan_penang_fyp_reviews import build_plan
from scripts.plan_penang_fyp_expansion import _create_expansion, build_plan as build_expansion, plan_bytes
from services.fyp_reviews import DATASET_PATH, PROJECT, dataset_for, dataset_reviews, moderate_review
from services.review_service import ReviewConflict, review_revision
from test_local_reviews import headers, memory


@pytest.fixture
def planned_dataset(monkeypatch):
    plan = build_plan()
    documents = plan['documents']
    ref = Mock()
    ref.get.return_value = SimpleNamespace(exists=True, to_dict=lambda: documents[DATASET_PATH])
    rows = [SimpleNamespace(id=path.rsplit('/', 1)[-1], to_dict=lambda row=row: row)
            for path, row in documents.items() if path != DATASET_PATH]
    collections = {name: Mock() for name in ('reviews', 'manifests', 'expanded_reviews', 'moderation')}
    ref.collection.side_effect = collections.__getitem__
    collections['reviews'].limit.return_value.stream.return_value = rows
    collections['manifests'].document.return_value.get.return_value = SimpleNamespace(exists=False)
    collections['moderation'].limit.return_value.stream.return_value = []
    db = Mock(project=PROJECT)
    db.document.return_value = ref
    monkeypatch.delenv('FIRESTORE_EMULATOR_HOST', raising=False)
    monkeypatch.setenv('FYP_REVIEW_VIEWER_UID', 'fyp-viewer')
    monkeypatch.setattr('services.fyp_reviews.get_db', lambda: db)
    return plan, db, ref


def test_plan_is_bounded_create_only_and_screened(planned_dataset):
    plan, db, ref = planned_dataset
    assert (plan['project'], plan['database'], plan['operation']) == (PROJECT, '(default)', 'create_only')
    assert len(plan['documents']) == 37
    assert all(path == DATASET_PATH or path.startswith(DATASET_PATH + '/reviews/review_')
               for path in plan['documents'])
    assert dataset_for('other') is None
    db.document.assert_not_called()
    _, destinations = dataset_for('fyp-viewer')
    rows = dataset_reviews(ref, destinations)
    assert all(row['moderationDecision']['actor'] == 'system' and row['screening']['risk'] == 'low' for row in rows)
    ref.collection('reviews').limit.assert_called_once_with(37)


def test_expansion_is_deterministic_and_uses_actual_screening():
    assert plan_bytes() == plan_bytes()
    plan = build_expansion()
    assert plan['screeningCounts'] == {'low': 60, 'flagged': 6, 'uncertain': 2}
    assert len(plan['documents']) == 69
    assert len({row['comment'] for row in plan['documents'].values() if 'comment' in row}) == 68
    assert len({row['average'] for row in plan['initialDestinationSummaries'].values()}) > 5
    assert sum(row['approved'] for row in plan['initialDestinationSummaries'].values()) == 96
    assert all(not path.startswith(DATASET_PATH + '/reviews/') for path in plan['documents'])


def test_admin_sees_private_sources_and_legacy_decisions_without_mixing(client, memory, planned_dataset):
    _, _, ref = planned_dataset
    memory['feedback', 'real'] = {'id': 'real', 'rating': 5, 'comment': 'Beautiful and lovely'}
    url = '/api/fr13/feedback'
    private = {'source': 'fyp_penang'}
    assert client.get(url, headers=headers('fyp-viewer'), query_string=private).status_code == 403
    assert client.get(url, headers=headers('admin'), query_string={'source': 'wrong'}).status_code == 400
    assert [item['id'] for item in client.get(url, headers=headers('admin')).json['items']] == ['real']
    response = client.get(url, headers=headers('admin'), query_string=private)
    rows = response.json['items']
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert len(rows) == 36 and {row['moderationCategory'] for row in rows} == {'automatic'}
    ref.collection('moderation').document.return_value.collection.return_value.stream.return_value = []
    path = f"{url}/{rows[0]['id']}"
    history = client.get(path + '/history', headers=headers('admin'), query_string=private)
    assert history.json['items'][0]['outcome'] == 'approve'
    assert history.json['items'][0]['actor'] == 'system'
    assert client.post(path + '/review', headers=headers('admin'), query_string=private,
                       json={'decision': 'hide'}).status_code == 409
    assert client.delete(path, headers=headers('admin'), query_string=private).status_code == 400


def test_preview_project_and_missing_scope_fail_closed(planned_dataset, monkeypatch):
    _, db, _ = planned_dataset
    db.project = 'unrelated'
    assert dataset_for('fyp-viewer') is None
    db.document.assert_not_called()
    db.project = PROJECT
    monkeypatch.setenv('FIRESTORE_EMULATOR_HOST', '127.0.0.1:18085')
    assert dataset_for('fyp-viewer') is None
    db.document.assert_not_called()


def test_authorized_account_only_gets_private_ratings_and_search(client, memory, planned_dataset):
    plan, _, _ = planned_dataset
    memory['feedback', 'real'] = {
        'id': 'real', 'travellerId': 'genuine-owner', 'travellerName': 'Genuine reviewer',
        'destinationId': 'local_penang_hill', 'comment': 'Genuine review',
        'rating': 4, 'moderationStatus': 'reviewed', 'feedbackStatus': 'visible',
    }
    alias = '/api/fr3/destinations/penang_hill/ratings-reviews'
    context = {'X-TravelMate-Review-Context': 'fyp-v1'}
    viewer = {**headers('fyp-viewer'), **context}
    real = client.get(alias, headers={**headers('other'), **context})
    private = client.get(alias, headers=viewer)
    assert real.json['result']['rating'] == 4 and real.json['result']['reviews'] == 1
    assert client.get(alias, headers=headers('fyp-viewer')).json == real.json
    assert private.json['source'] == 'fyp_private'
    result = private.json['result']
    assert (result['rating'], result['reviews'], result['fypPreview']) == (3.0, 3, True)
    assert {row['rating'] for row in result['user_reviews']} == {1, 3, 5}
    assert all('travellerId' not in row and 'screening' not in row for row in result['user_reviews'])
    assert real.headers['Cache-Control'] == private.headers['Cache-Control'] == 'private, no-store'
    assert 'Authorization' in private.headers['Vary']
    assert client.get(alias, headers=context).status_code == 401
    ratings = client.get('/api/fr3/local-ratings', headers=viewer).json['items']
    assert ratings['penang_hill'] == {'rating': 3.0, 'reviews': 3, 'fypPreview': True}
    assert client.get('/api/fr3/local-ratings', headers=headers('other')).json['items']['penang_hill'] == {
        'rating': 4.0, 'reviews': 1,
    }
    destinations = plan['documents'][DATASET_PATH]['destinations']
    for identity, place in destinations.items():
        assert ratings[identity]['reviews'] == 3
        search = client.get('/api/fr3/destinations/search', headers=viewer,
                            query_string={'q': place['title'], 'location': 'Penang'})
        assert search.json['source'] == 'fyp_private'
        assert search.json['results'][0]['destinationId'] == identity
        details = client.get(f'/api/fr3/destinations/{identity}', headers=viewer)
        assert details.json['destination']['destinationId'] == identity
    assert client.get('/api/fr10/feedback', headers=headers('fyp-viewer')).json['items'] == []


@pytest.mark.skipif(not os.getenv('PENANG_TEST_EMULATOR'), reason='requires disposable Firestore emulator')
def test_firestore_expansion_and_private_moderation(client, memory, monkeypatch):
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore

    host = os.environ['PENANG_TEST_EMULATOR']
    assert host.startswith('127.0.0.1:')
    project = 'demo-travelmate-penang-expansion'
    monkeypatch.setenv('FIRESTORE_EMULATOR_HOST', host)
    db = firestore.Client(project=project, credentials=AnonymousCredentials())
    # Only this test fixture supplies an emulator client to the private service.
    monkeypatch.delenv('FIRESTORE_EMULATOR_HOST')
    monkeypatch.setattr('services.fyp_reviews.PROJECT', project)
    monkeypatch.setattr('services.fyp_reviews.get_db', lambda: db)
    monkeypatch.setenv('FYP_REVIEW_VIEWER_UID', 'fyp-viewer')
    base = build_plan()['documents']
    expansion = build_expansion()['documents']
    batch = db.batch()
    for path, row in base.items():
        batch.create(db.document(path), row)
    batch.commit()
    unexpected = db.document(f'{DATASET_PATH}/expanded_reviews/unexpected')
    unexpected.create({'synthetic': True})
    with pytest.raises(ValueError, match='occupied or partially present'):
        _create_expansion(db, base, expansion, firestore)
    assert not db.document(f'{DATASET_PATH}/manifests/v2').get().exists
    unexpected.delete()
    assert _create_expansion(db, base, expansion, firestore) == 'created'
    assert _create_expansion(db, base, expansion, firestore) == 'already_applied'
    assert len(list(db.document(DATASET_PATH).collection('expanded_reviews').stream())) == 68

    url = '/api/fr13/feedback'
    admin, source = headers('admin'), {'source': 'fyp_penang'}
    viewer = {**headers('fyp-viewer'), 'X-TravelMate-Review-Context': 'fyp-v1'}
    memory['feedback', 'genuine'] = {
        'id': 'genuine', 'travellerId': 'real', 'destinationId': 'local_penang_hill',
        'rating': 4, 'moderationStatus': 'reviewed', 'feedbackStatus': 'visible',
    }
    rows = client.get(url, headers=admin, query_string=source).json['items']
    assert Counter(row['moderationCategory'] for row in rows) == {
        'automatic': 96, 'flagged': 6, 'needs_review': 2,
    }
    assert [row['id'] for row in client.get(url, headers=admin).json['items']] == ['genuine']
    hill = '/api/fr3/destinations/local_penang_hill/ratings-reviews'

    def assert_summary(rating, count):
        result = client.get(hill, headers=viewer).json['result']
        assert (result['rating'], result['reviews'], len(result['user_reviews'])) == (rating, count, count)
        assert len({review['username'] for review in result['user_reviews']}) == count
        summary = client.get('/api/fr3/local-ratings', headers=viewer).json['items']['local_penang_hill']
        assert summary == {'rating': rating, 'reviews': count, 'fypPreview': True}
        assert client.get(hill, headers=headers('other')).json['result']['reviews'] == 1

    assert_summary(3.8, 11)
    target = next(row for row in rows if row['moderationCategory'] == 'flagged'
                  and row['destinationId'] == 'local_penang_hill')
    path = f"{url}/{target['id']}"
    command = {'decision': 'keep', 'expectedRevision': target['reviewRevision'], 'comment': 'Reviewed for demo.'}
    assert client.post(path + '/review', headers=viewer, query_string=source, json=command).status_code == 403
    approved = client.post(path + '/review', headers=admin, query_string=source, json=command)
    assert approved.status_code == 200
    assert client.post(path + '/review', headers=admin, query_string=source, json=command).status_code == 409
    with pytest.raises(ReviewConflict):
        moderate_review(db.document(DATASET_PATH), target, {})
    assert_summary(3.9, 12)
    history = client.get(path + '/history', headers=admin, query_string=source).json['items']
    assert [(event['actor'], event['outcome']) for event in history] == [
        ('administrator', 'approve'), ('system', 'pending'),
    ]
    hidden = client.post(path + '/review', headers=admin, query_string=source, json={
        'decision': 'hide', 'expectedRevision': review_revision(approved.json['feedback']),
    })
    assert hidden.status_code == 200
    assert_summary(3.8, 11)
    uncertain = next(row for row in rows if row['moderationCategory'] == 'needs_review')
    rejection = client.post(f"{url}/{uncertain['id']}/review", headers=admin, query_string=source, json={
        'decision': 'reject', 'expectedRevision': uncertain['reviewRevision'],
    })
    assert rejection.json['feedback']['moderationDecision']['outcome'] == 'reject'
    assert all(db.document(path).get().to_dict() == row for path, row in {**base, **expansion}.items())
    assert _create_expansion(db, base, expansion, firestore) == 'already_applied'
    assert list(db.collection('public_destination_reviews').stream()) == []
