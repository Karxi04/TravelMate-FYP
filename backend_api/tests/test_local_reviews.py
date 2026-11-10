from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from types import SimpleNamespace

import pytest
from services.review_service import pending_screen, screen_review, ReviewConflict, approved_reviews, current_screen, review_revision
from services.public_content_projection import public_review


def payload(rating=5, **extra):
    return {'destinationId': 'synthetic-place', 'destinationName': 'Synthetic Place',
            'rating': rating, 'comment': 'Beautiful views and a peaceful visit.', **extra}


def headers(uid='owner'):
    return {'Authorization': 'Bearer ' + uid}


@pytest.fixture
def memory(monkeypatch):
    records = {}
    lock = Lock()
    def get(collection, identity=None, filters=None, **kwargs):
        if collection == 'users':
            return {'name': identity, 'role': 'admin' if identity == 'admin' else 'traveller', 'status': 'active'}
        if identity:
            return deepcopy(records.get((collection, identity)))
        return [deepcopy(item) for (name, _), item in records.items() if name == collection
                and all(item.get(key) == value for key, _, value in filters or [])]
    def claim(collection, identity, data):
        with lock:
            key = (collection, identity)
            created = key not in records
            records.setdefault(key, {'id': identity, **deepcopy(data)})
            return deepcopy(records[key]), created
    def update(collection, identity, data, expected=None):
        with lock:
            current = records[(collection, identity)]
            if expected is not None and current != expected:
                raise ReviewConflict('Refresh and try again.')
            current.update(deepcopy(data))
            return deepcopy(current)
    def delete(collection, identity, expected=None):
        records.pop((collection, identity), None)
    for module in ('modules.fr10_feedback_rating.routes', 'modules.fr13_administrator_management.routes',
                   'modules.fr03_destination_search_information.routes'):
        monkeypatch.setattr(module + '.retrieveRecord', get)
    monkeypatch.setattr('modules.fr10_feedback_rating.routes.claimRecord', claim)
    monkeypatch.setattr('modules.fr10_feedback_rating.routes.updateRecord', update)
    monkeypatch.setattr('modules.fr10_feedback_rating.routes.deleteRecord', delete)
    monkeypatch.setattr('modules.fr13_administrator_management.routes.updateRecord', update)
    monkeypatch.setattr('auth_utils.auth.verify_id_token', lambda token, **kwargs: {'uid': token})
    monkeypatch.setattr('auth_utils.get_db', lambda: SimpleNamespace(collection=lambda _: SimpleNamespace(
        document=lambda uid: SimpleNamespace(get=lambda: SimpleNamespace(exists=True, to_dict=lambda: get('users', uid))))))
    return records


def test_submission_moderation_average_and_hide(client, memory):
    first = client.post('/api/fr10/feedback', json=payload(), headers=headers())
    assert first.status_code == 201
    identity = first.json['id']
    assert first.json['feedback']['screening']['risk'] == 'low'
    assert 'confidence' not in first.json['feedback']['screening']
    repeat = client.post('/api/fr10/feedback', json=payload(), headers=headers())
    assert repeat.status_code == 200 and repeat.json['id'] == identity
    changed = client.post('/api/fr10/feedback', json=payload(comment='A different experience.'), headers=headers())
    assert changed.status_code == 409
    url = '/api/fr3/destinations/synthetic-place/ratings-reviews'
    assert client.get(url, headers=headers()).json['result']['rating'] is None
    assert client.post(f'/api/fr13/feedback/{identity}/review', headers=headers(), json={'decision': 'keep'}).status_code == 403
    assert client.put(f'/api/fr10/feedback/{identity}', headers=headers('other'), json={'rating': 1}).status_code == 404
    assert client.post('/api/fr10/feedback', json=payload()).status_code == 401
    assert client.post(f'/api/fr13/feedback/{identity}/review', headers=headers('admin'), json={'decision': 'keep'}).status_code == 200
    second = client.post('/api/fr10/feedback', json=payload(3, comment='Click here https://example.invalid'), headers=headers('other'))
    assert second.json['feedback']['screening']['risk'] == 'flagged'
    assert client.post(f"/api/fr13/feedback/{second.json['id']}/review", headers=headers('admin'), json={'decision': 'keep'}).status_code == 200
    result = client.get(url, headers=headers()).json['result']
    assert (result['rating'], result['reviews']) == (4.0, 2)
    assert all('travellerId' not in row and 'screening' not in row for row in result['user_reviews'])
    client.post(f'/api/fr13/feedback/{identity}/review', headers=headers('admin'), json={'decision': 'remove'})
    assert client.get(url, headers=headers()).json['result']['rating'] == 3.0


@pytest.mark.parametrize('comment,flag', [('fuck this place', 'abusive_language'),
    ('buy now https://example.invalid', 'spam_or_unsafe_content'), ('good good good good good good good good', 'repeated_content')])
def test_real_local_screening(comment, flag):
    assert flag in screen_review(comment)['flags']


def test_screening_failure_stays_pending(monkeypatch):
    monkeypatch.setattr('services.review_service.screen_review', lambda *args: (_ for _ in ()).throw(RuntimeError('private')))
    result = pending_screen('A lovely place to visit.')
    assert result['moderationStatus'] == 'pending_review'
    assert result['screening']['risk'] == 'uncertain' and 'private' not in str(result)


def test_legacy_decisions_and_duplicates_are_not_migrated_or_assumed_approved():
    reviewed = {'id':'legacy', 'travellerId':'owner', 'rating':5, 'comment':'A lovely visit.',
        'moderationStatus':'reviewed', 'feedbackStatus':'visible', 'updatedAt':'2026-01-01'}
    newer = {**reviewed, 'id':'other-legacy', 'rating':3, 'updatedAt':'2026-02-01'}
    pending = {**reviewed, 'id':'pending', 'travellerId':'other', 'moderationStatus':'pending_review'}
    unknown = {key:value for key,value in pending.items() if key != 'moderationStatus'}
    rows = [reviewed,newer,pending,unknown]
    before = deepcopy(rows)
    assert approved_reviews(rows) == [newer] and rows == before
    assert 'publicationStatus' not in public_review(pending)
    assert public_review(newer)['publicationStatus'] == 'approved'
    assert current_screen({'comment':None, 'screening':'legacy-invalid'})['risk'] == 'uncertain'
    assert pending_screen(None)['screening']['risk'] == 'uncertain'


@pytest.mark.parametrize('bad', [payload(rating=True), payload(rating=2.5), payload(rating=6), payload(comment='tiny'),
    payload(comment='a' * 2001), payload(travellerId='spoof'), payload(moderationStatus='reviewed'),
    payload(travellerName='Admin'), payload(screening={'risk': 'low'}), payload(**{'moderationStatus.value': 'reviewed'})])
def test_submission_validation_and_spoofing(client, memory, bad):
    assert client.post('/api/fr10/feedback', headers=headers(), json=bad).status_code == 400
    assert memory == {}


def test_concurrent_retries_claim_one_record(app, memory):
    def submit(_):
        with app.test_client() as client:
            response = client.post('/api/fr10/feedback', headers=headers(), json=payload())
            assert response.status_code in (200, 201)
            return response.json['id']
    with ThreadPoolExecutor(max_workers=6) as pool:
        identities = list(pool.map(submit, range(12)))
    assert len(set(identities)) == 1 and len(memory) == 1


def test_existing_id_decision_and_stale_admin_protection(client, memory):
    memory[('feedback', 'legacy')] = {'id': 'legacy', **payload(), 'travellerId': 'owner',
        'feedbackStatus': 'visible', 'moderationStatus': 'reviewed', 'updatedAt': 'old'}
    response = client.post('/api/fr10/feedback', headers=headers(), json=payload())
    assert response.json['id'] == 'legacy' and response.json['feedback']['moderationStatus'] == 'reviewed'
    assert len(memory) == 1
    assert client.post('/api/fr13/feedback/legacy/review', headers=headers('admin'),
        json={'decision': 'keep', 'expectedUpdatedAt': 'stale'}).status_code == 409
    edited = client.put('/api/fr10/feedback/legacy', headers=headers(), json={'comment': '<script>alert(1)</script>'})
    assert edited.status_code == 200 and edited.json['feedback']['moderationStatus'] == 'pending_review'
    result = client.get('/api/fr3/destinations/synthetic-place/ratings-reviews', headers=headers()).json['result']
    assert result['reviews'] == 0


def test_contended_claim_reconciles_only_a_persisted_matching_review(client, memory, monkeypatch):
    from google.api_core.exceptions import Aborted
    def contended(collection, identity, data):
        memory[(collection, identity)] = {'id': identity, **data}
        raise Aborted('synthetic contention')
    monkeypatch.setattr('modules.fr10_feedback_rating.routes.claimRecord', contended)
    response = client.post('/api/fr10/feedback', headers=headers(), json=payload())
    assert response.status_code == 200 and response.json['reused'] is True
    memory.clear()
    monkeypatch.setattr('modules.fr10_feedback_rating.routes.claimRecord', lambda *args: (_ for _ in ()).throw(Aborted('private')))
    response = client.post('/api/fr10/feedback', headers=headers(), json=payload())
    assert response.status_code == 503 and 'private' not in response.get_data(as_text=True) and memory == {}


def test_admin_stale_form_detects_content_change_even_with_unchanged_client_timestamp(client, memory):
    created = client.post('/api/fr10/feedback', headers=headers(), json=payload()).json
    identity = created['id']
    old_revision = review_revision(created['feedback'])
    memory[('feedback', identity)]['comment'] = 'Changed while preserving the old timestamp.'
    response = client.post(f'/api/fr13/feedback/{identity}/review', headers=headers('admin'),
        json={'decision':'keep', 'expectedUpdatedAt':created['feedback']['updatedAt'], 'expectedRevision':old_revision})
    assert response.status_code == 409
    assert memory[('feedback', identity)]['moderationStatus'] == 'pending_review'
