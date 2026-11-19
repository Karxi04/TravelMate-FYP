from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_local_reviews import memory, headers, payload
from services.review_service import screen_submission, review_revision


ADVICE = ('architecture lovers, hilltop views, and cultural sightseeing recommend time: '
          '1.5-2.5 hours can arrive early in the morning to avoid crowds and heat')


@pytest.mark.parametrize('comment,rating,label,status', [
    (ADVICE, 4, 'neutral', 'reviewed'),
    ('Beautiful architecture. Arrive early to avoid crowds and heat.', 4, 'positive', 'reviewed'),
    ('The museum entrance is beside the station. Allow two hours.', 4, 'neutral', 'reviewed'),
    ('Beautiful views but dirty facilities and rude service.', 4, 'mixed', 'pending_review'),
    ('Terrible experience with disappointing views and dirty facilities.', 5, 'negative', 'pending_review'),
    ('Beautiful views buy now https://spam.invalid', 5, 'positive', 'pending_review'),
    ('Beautiful views but fucking rude staff.', 5, 'mixed', 'pending_review'),
    ('Beautiful views but too crowded and disappointing.', 4, 'mixed', 'pending_review'),
])
def test_explainable_review_advice_without_moderation_bypass(comment, rating, label, status):
    result = screen_submission(comment, rating)
    assert result['screening']['sentiment']['label'] == label
    assert result['moderationStatus'] == status


def test_two_edits_noop_retry_stale_owner_and_legacy(client, memory):
    created = client.post('/api/fr10/feedback', headers=headers(), json=payload()).json
    identity = created['id']
    assert created['feedback']['editCount'] == 0
    url = '/api/fr10/feedback/' + identity
    for count, comment in enumerate(['Beautiful architecture and peaceful views.', 'A wonderful and memorable visit.'], 1):
        own = client.get('/api/fr10/feedback', headers=headers()).json['items'][0]
        body = {'comment': comment, 'expectedRevision': own['revision']}
        assert own['editsRemaining'] == 3 - count
        changed = client.put(url, headers=headers(), json=body)
        assert changed.status_code == 200
        assert changed.json['feedback']['editCount'] == count
        assert client.put(url, headers=headers(), json=body).json['feedback']['editCount'] == count
    before = deepcopy(memory)
    assert client.put(url, headers=headers(), json={'comment': 'A third meaningful review change.'}).status_code == 409
    assert client.put(url, headers=headers('other'), json={'comment': 'A different account.'}).status_code == 404
    assert client.put(url, headers=headers(), json={'editCount': 0}).status_code == 400
    assert memory == before
    memory['feedback', identity].pop('editCount')
    assert client.put(url, headers=headers(), json={'comment': 'Beautiful scenery on our second visit.'}).json['feedback']['editCount'] == 1
    old_revision = review_revision(memory['feedback', identity])
    client.post('/api/fr13/feedback/' + identity + '/review', headers=headers('admin'), json={'decision': 'keep'})
    assert client.put(url, headers=headers(), json={'comment': 'A stale pending update.', 'expectedRevision': old_revision}).status_code == 409
    assert memory['feedback', identity]['editCount'] == 1


def test_concurrent_edits_cannot_exceed_limit(app, client, memory):
    identity = client.post('/api/fr10/feedback', headers=headers(), json=payload()).json['id']
    def edit(index):
        with app.test_client() as connection:
            return connection.put('/api/fr10/feedback/' + identity, headers=headers(),
                                  json={'comment': f'Beautiful architecture and pleasant visit number {index}.'}).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(edit, range(12)))
    assert statuses.count(200) == 2
    assert set(statuses) <= {200, 409}
    assert memory['feedback', identity]['editCount'] == 2


@pytest.mark.parametrize('ratings,mean', [([], None), ([4], 4.0), ([4, 5], 4.5), ([1, 2, 4, 5], 3.0), ([1, 2, 3, 4, 5], 3.0)])
def test_genuine_rating_and_count_use_same_approved_owners(client, memory, ratings, mean):
    for i, rating in enumerate(ratings):
        memory['feedback', str(i)] = {**payload(rating), 'id': str(i), 'travellerId': str(i),
                                      'moderationStatus': 'reviewed', 'feedbackStatus': 'visible'}
    for status in ['pending_review', 'rejected']:
        memory['feedback', status] = {**payload(), 'id': status, 'travellerId': status,
                                      'moderationStatus': status, 'feedbackStatus': 'visible'}
    memory['feedback', 'synthetic'] = {**payload(), 'id': 'synthetic', 'travellerId': 'example',
                                      'moderationStatus': 'reviewed', 'feedbackStatus': 'visible', 'synthetic': True}
    result = client.get('/api/fr3/destinations/synthetic-place/ratings-reviews', headers=headers()).json['result']
    assert (result['rating'], result['reviews']) == (mean, len(ratings))
