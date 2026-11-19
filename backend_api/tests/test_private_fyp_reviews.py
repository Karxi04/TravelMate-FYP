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
    combined = client.get(url, headers=headers('admin'), query_string={'source': 'all'})
    assert combined.headers['Cache-Control'] == 'private, no-store'
    assert Counter(row['reviewSource'] for row in combined.json['items']) == {'fyp_penang': 36, 'traveller': 1}
    assert client.get(url, headers=headers('fyp-viewer'), query_string={'source': 'all'}).status_code == 403
    ref.collection('moderation').document.return_value.collection.return_value.stream.return_value = []
    path = f"{url}/{rows[0]['id']}"
    assert client.post(path + '/review', headers=headers('admin'), query_string={'source': 'all'},
                       json={'decision': 'hide'}).status_code == 400
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


def test_authorized_catalogue_access_does_not_override_genuine_ratings(client, memory, planned_dataset):
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
    assert private.json['result'] == real.json['result']
    assert private.json['reviewTestModeAvailable'] is True
    result = private.json['result']
    assert (result['rating'], result['reviews']) == (4, 1)
    assert [row['id'] for row in result['user_reviews']] == ['real']
    assert all('travellerId' not in row and 'screening' not in row for row in result['user_reviews'])
    assert real.headers['Cache-Control'] == private.headers['Cache-Control'] == 'private, no-store'
    assert 'Authorization' in private.headers['Vary']
    assert client.get(alias, headers=context).status_code == 401
    ratings = client.get('/api/fr3/local-ratings', headers=viewer).json['items']
    assert ratings['penang_hill'] == {'rating': 4.0, 'reviews': 1}
    assert client.get('/api/fr3/local-ratings', headers=headers('other')).json['items']['penang_hill'] == {
        'rating': 4.0, 'reviews': 1,
    }
    destinations = plan['documents'][DATASET_PATH]['destinations']
    for identity, place in destinations.items():
        assert (identity in ratings) == (identity == 'local_penang_hill')
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

    def assert_private_moderation_is_unpublished():
        result = client.get(hill, headers=viewer).json['result']
        assert (result['rating'], result['reviews'], len(result['user_reviews'])) == (4, 1, 1)
        summary = client.get('/api/fr3/local-ratings', headers=viewer).json['items']['local_penang_hill']
        assert summary == {'rating': 4, 'reviews': 1}
        assert client.get(hill, headers=headers('other')).json['result'] == result

    assert_private_moderation_is_unpublished()
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
    assert_private_moderation_is_unpublished()
    history = client.get(path + '/history', headers=admin, query_string=source).json['items']
    assert [(event['actor'], event['outcome']) for event in history] == [
        ('administrator', 'approve'), ('system', 'pending'),
    ]
    hidden = client.post(path + '/review', headers=admin, query_string=source, json={
        'decision': 'hide', 'expectedRevision': review_revision(approved.json['feedback']),
    })
    assert hidden.status_code == 200
    assert_private_moderation_is_unpublished()
    uncertain = next(row for row in rows if row['moderationCategory'] == 'needs_review')
    rejection = client.post(f"{url}/{uncertain['id']}/review", headers=admin, query_string=source, json={
        'decision': 'reject', 'expectedRevision': uncertain['reviewRevision'],
    })
    assert rejection.json['feedback']['moderationDecision']['outcome'] == 'reject'
    assert all(db.document(path).get().to_dict() == row for path, row in {**base, **expansion}.items())
    assert _create_expansion(db, base, expansion, firestore) == 'already_applied'
    assert list(db.collection('public_destination_reviews').stream()) == []


def test_local_demo_scope_returns_genuine_reviews_for_all_travellers(client, app, memory, planned_dataset):
    app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    memory['feedback', 'genuine'] = {
        'id': 'genuine', 'travellerId': 'author', 'destinationId': 'local_penang_hill',
        'rating': 4, 'moderationStatus': 'reviewed', 'feedbackStatus': 'visible',
        'comment': 'A genuine review.',
    }
    path = '/api/fr3/destinations/penang_hill/ratings-reviews'
    for uid in ('fyp-viewer', 'other', 'new-traveller'):
        auth = {**headers(uid), 'X-TravelMate-Review-Context': 'fyp-v1'}
        unified = client.get(path + '?view=unified', headers=auth)
        assert unified.status_code == 200
        assert 'no-store' in unified.headers['Cache-Control']
        combined = unified.json['result']
        assert combined['genuineSummary'] == {'rating': 4, 'reviews': 1}
        assert (combined['rating'], combined['reviews']) == (3.2, 4)
        assert combined['sampleSummary']['reviews'] == 3
        assert [row['source'] for row in combined['user_reviews']] == ['travelmate'] + ['fyp_private'] * 3
        assert all(row['synthetic'] for row in combined['user_reviews'][1:])
        samples = client.get(path + '?view=samples', headers=auth)
        assert samples.status_code == 404 and 'result' not in samples.json
        community = client.get(path + '?view=community', headers=auth).json
        assert community['result'] == combined
        assert (community['result']['rating'], community['result']['reviews']) == (3.2, 4)
        assert client.get(path, headers=auth).json['source'] == 'travelmate_database'
        assert client.get('/api/fr3/local-ratings', headers=auth).json['items']['penang_hill']['genuineSummary'] == {'rating': 4, 'reviews': 1}
        assert client.get('/api/fr3/local-ratings', headers=auth).json['items']['penang_hill']['reviews'] == 4
    assert client.get(path + '?view=samples').status_code == 401
    assert client.get(path + '?view=unified').status_code == 401
    app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = False
    assert client.get(path + '?view=samples', headers=auth).status_code == 404
    assert 'sampleSummary' not in client.get(
        path + '?view=unified', headers={**headers('fyp-viewer'), 'X-TravelMate-Review-Context': 'fyp-v1'}
    ).json['result']


def test_unified_reviews_preserve_genuine_data_when_private_preview_times_out(client, app, memory, planned_dataset, monkeypatch):
    app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    memory['feedback', 'community'] = {
        'id': 'community', 'travellerId': 'author', 'destinationId': 'penang_hill',
        'rating': 4, 'moderationStatus': 'approved', 'feedbackStatus': 'visible',
    }

    def unavailable(*args, **kwargs):
        raise TimeoutError('fixture details')

    monkeypatch.setattr('modules.fr03_destination_search_information.routes._private_review_dataset', unavailable)
    auth = {**headers('other'), 'X-TravelMate-Review-Context': 'fyp-v1'}
    result = client.get('/api/fr3/destinations/local_penang_hill/ratings-reviews?view=unified', headers=auth)
    assert result.status_code == 200
    assert result.json['exampleReviewStatus'] == 'unavailable'
    assert result.json['result']['reviews'] == 1
    assert result.json['result']['sampleSummary'] == {'rating': None, 'reviews': 0}
    assert [row['id'] for row in result.json['result']['user_reviews']] == ['community']


def test_all_existing_manifest_identities_remain_available_in_one_private_list(client, app, memory, planned_dataset):
    from services.fyp_reviews import PENANG_DESTINATION_IDS
    plan, _, _ = planned_dataset
    assert PENANG_DESTINATION_IDS == set(plan['documents'][DATASET_PATH]['destinations'])
    app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    for identity in sorted(PENANG_DESTINATION_IDS):
        body = client.get(f'/api/fr3/destinations/{identity}/ratings-reviews?view=unified',
                          headers={**headers('new-traveller'), 'X-TravelMate-Review-Context': 'fyp-v1'}).json
        assert body['result']['sampleSummary']['reviews'] == 3
        assert all(row['destinationId'] == identity and row['synthetic'] for row in body['result']['user_reviews'])
        assert body['result']['rating'] == body['result']['sampleSummary']['rating']
        assert body['result']['genuineSummary'] == {'rating': None, 'reviews': 0}


@pytest.mark.parametrize('identity,state,average', [
    ('local_klcc', 'Kuala Lumpur', 3.3),
    ('local_legoland_malaysia', 'Johor', 3.7),
    ('local_tunku_abdul_rahman', 'Sabah', 3.3),
    ('local_langkawi_skycab', 'Kedah', 4.0),
])
def test_regional_reviews_use_exact_catalog_identity_and_stay_private(
        client, app, memory, identity, state, average, monkeypatch):
    monkeypatch.setattr('modules.fr03_destination_search_information.routes._private_review_dataset', lambda **kw: None)
    from services.fyp_reviews import regional_demo_destinations, regional_demo_reviews
    from services.malaysian_locality import normalize_candidate_geography
    from services.recommendation_discovery import is_planning_candidate

    place = regional_demo_destinations()[identity]
    assert place['place_id'] == place['destinationId'] == identity
    assert normalize_candidate_geography(place)['state'] == state
    assert is_planning_candidate(place)
    rows = regional_demo_reviews(identity)
    assert len(rows) == 3 and all(row['synthetic'] and row['destinationId'] == identity for row in rows)
    assert len({row['id'] for key in regional_demo_destinations()
                for row in regional_demo_reviews(key)}) == 45

    memory['feedback', 'genuine'] = {'id': 'genuine', 'travellerId': 'owner', 'destinationId': identity,
        'rating': 4, 'comment': 'Genuine review.', 'moderationStatus': 'reviewed', 'feedbackStatus': 'visible'}
    memory['feedback', 'foreign'] = {**memory['feedback', 'genuine'], 'id': 'foreign',
        'destinationId': 'another-place', 'comment': 'Other attraction.'}
    memory['feedback', 'pending'] = {**memory['feedback', 'genuine'], 'id': 'pending',
        'travellerId': 'other', 'rating': 1, 'moderationStatus': 'pending_review'}
    auth = {**headers('ordinary-traveller'), 'X-TravelMate-Review-Context': 'fyp-v1'}
    path = f'/api/fr3/destinations/{identity}/ratings-reviews'
    app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    assert client.get(path + '?view=unified').status_code == 401
    data = client.get(path + '?view=unified', headers=auth)
    result = data.json['result']
    assert 'no-store' in data.headers['Cache-Control']
    assert result['genuineSummary'] == {'rating': 4, 'reviews': 1}
    assert result['reviews'] == 4
    assert result['rating'] == round((4 + sum(row['rating'] for row in rows)) / 4, 1)
    assert round(sum(row['rating'] for row in rows) / len(rows), 1) == average
    assert result['sampleSummary'] == {'rating': average, 'reviews': 3}
    assert [row['source'] for row in result['user_reviews']] == ['travelmate'] + ['fyp_private'] * 3
    assert client.get(path + '?view=samples', headers=auth).status_code == 404
    assert client.get(path + '?view=unified', headers=headers('ordinary-traveller')).json['result']['reviews'] == 1
    assert 'sampleSummary' not in client.get(path + '?view=unified', headers=headers('ordinary-traveller')).json['result']
    assert client.get('/api/fr3/local-ratings', headers=auth).json['items'][identity]['genuineSummary'] == {'rating': 4, 'reviews': 1}
    app.config['LOCAL_FYP_SAMPLE_REVIEWS'] = False
    response = client.get(path + '?view=unified', headers=auth).json['result']
    assert 'sampleSummary' not in response
    assert [row['id'] for row in response['user_reviews']] == ['genuine']
