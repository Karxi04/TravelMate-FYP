from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.plan_penang_fyp_reviews import build_plan
from services.fyp_reviews import DATASET_PATH, PROJECT, dataset_for, dataset_reviews
from test_local_reviews import headers, memory


@pytest.fixture
def planned_dataset(monkeypatch):
    plan = build_plan()
    documents = plan['documents']
    ref = Mock()
    ref.get.return_value = SimpleNamespace(exists=True, to_dict=lambda: documents[DATASET_PATH])
    rows = [SimpleNamespace(id=path.rsplit('/', 1)[-1], to_dict=lambda row=row: row)
            for path, row in documents.items() if path != DATASET_PATH]
    ref.collection.return_value.limit.return_value.stream.return_value = rows
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
    ref.collection.return_value.limit.assert_called_once_with(37)


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
