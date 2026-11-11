import json
import re
from pathlib import Path

import pytest
from services.local_catalog import DESTINATIONS
from services.review_service import current_screen, screen_review, screen_submission
from test_local_reviews import headers, memory


FIXTURES = Path(__file__).parent / 'fixtures'
DATASET = json.loads((FIXTURES / 'penang_synthetic_reviews.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize(('rating', 'comment', 'label', 'risk'), [
    (5, 'Terrible experience. Everything was disappointing and frustrating.', 'negative', 'flagged'),
    (1, 'Amazing destination with beautiful scenery. I absolutely loved the entire experience.', 'positive', 'flagged'),
    (4, 'The visit was awful, uncomfortable and disappointing.', 'negative', 'flagged'),
    (2, 'The place was fantastic and the experience exceeded my expectations.', 'positive', 'flagged'),
    (5, 'The place wasn’t good. The queues were frustrating.', 'negative', 'flagged'),
    (2, 'Not bad lah. It was just an average walk.', 'mixed', 'low'),
    (4, 'Sedap, and the setting was pleasant.', 'positive', 'low'),
    (1, 'Tak bagus and the place felt teruk.', 'negative', 'low'),
    (3, 'Overall it was okay, about average.', 'neutral', 'low'),
    (5, 'Beautiful views, but the wait was frustrating, uncomfortable and disappointing.', 'mixed', 'low'),
    (1, 'I liked the scenery. Great views and a wonderful garden, but it felt uncomfortable.', 'mixed', 'low'),
    (1, 'The view was beautiful.', 'positive', 'uncertain'),
    (5, 'There are four paths leading towards the water.', 'uncertain', 'uncertain'),
    (5, 'Not only beautiful but also a lovely place to sit.', 'positive', 'low'),
    (5, 'Terrible, terrible, terrible visit.', 'negative', 'uncertain'),
    (2, 'I would not say it was worth visiting.', 'negative', 'low'),
    (5, 'The sunset was beautiful and I enjoyed a slow walk.', 'positive', 'low'),
    (2, 'Slow service and a disappointing outing overall.', 'negative', 'low'),
])
def test_rating_sentiment_triage(rating, comment, label, risk):
    result = screen_review(comment, rating)
    assert result['sentiment']['label'] == label
    assert result['risk'] == risk
    assert result['sentiment']['ratingMismatch'] is (risk == 'flagged')
    assert ('rating_sentiment_mismatch' in result['flags']) is (risk == 'flagged')


def test_legacy_review_without_a_valid_rating_has_uncertain_alignment():
    screening = current_screen({'comment': 'Beautiful views and a wonderful visit.'})
    assert screening['sentiment']['label'] == 'positive'
    assert screening['sentiment']['ratingAlignment'] == 'uncertain'
    assert screening['risk'] == 'uncertain'


@pytest.mark.parametrize(('rating', 'comment', 'risk'), [
    (5, 'Beautiful views and a wonderful outing.', 'low'),
    (3, 'Nice views but long queues.', 'low'),
    (1, 'The queues were frustrating and the visit was disappointing.', 'low'),
    (5, 'Terrible experience. The visit was frustrating and disappointing.', 'flagged'),
    (1, 'Amazing views and a beautiful garden. I loved the visit.', 'flagged'),
    (3, 'Buy now https://example.invalid', 'flagged'),
    (4, 'There are four paths near the water.', 'uncertain'),
    (5, 'Beautiful and clean but the wait was terrible.', 'uncertain'),
    (5, 'Amazing views', 'uncertain'),
])
def test_automatic_policy_requires_sufficient_matching_evidence(rating, comment, risk):
    result = screen_submission(comment, rating)
    assert result['screening']['risk'] == risk
    assert result['moderationStatus'] == ('reviewed' if risk == 'low' else 'pending_review')


def test_fixture_uses_distinct_existing_catalogue_and_demo_ids():
    assert DATASET['synthetic'] is True
    backend = {place['destinationId'] for place in DESTINATIONS}
    standalone_source = (FIXTURES.parents[2] /
                         'traveller_mobile/lib/services/standalone_api_service.dart').read_text(encoding='utf-8')
    standalone = set(re.findall(r"'destinationId': '([^']+)'|id: '([^']+)'", standalone_source))
    demo = json.loads((FIXTURES / 'penang_core_demo.json').read_text(encoding='utf-8'))['candidates']
    catalogues = {'backend_catalogue': backend,
                  'standalone': {left or right for left, right in standalone},
                  'demo_fixture': {place['destinationId'] for place in demo}}
    groups = {}
    for row in DATASET['reviews']:
        assert row['destinationId'] in catalogues[row['catalogue']]
        groups.setdefault(row['destinationId'], []).append(row['expectedSentiment'])
    assert len(groups) == 12
    assert all(sorted(labels) == ['mixed', 'negative', 'positive'] for labels in groups.values())
    assert len({row['comment'] for row in DATASET['reviews']}) == 36


@pytest.mark.parametrize('row', DATASET['reviews'],
                         ids=lambda row: f"{row['destinationId']}-{row['rating']}")
def test_penang_sample_through_real_submission(client, memory, row):
    payload = {field: row[field] for field in ('destinationId', 'destinationName', 'rating', 'comment')}
    response = client.post('/api/fr10/feedback', headers=headers(), json=payload)
    assert response.status_code == 201
    saved = memory['feedback', response.json['id']]
    assert saved['moderationStatus'] == 'reviewed'
    assert saved['moderationDecision']['actor'] == 'system'
    assert saved['moderationDecision']['policyVersion'] == saved['screening']['policyVersion']
    screening = saved['screening']
    assert screening['sentiment']['label'] == row['expectedSentiment']
    assert screening['sentiment']['ratingAlignment'] == 'compatible'
    assert screening['sentiment']['ratingMismatch'] is False
    assert screening['flags'] == []
    assert screening['risk'] == row['expectedRisk']


def test_rating_only_and_comment_only_edits_and_admin_rescreen(client, memory):
    created = client.post('/api/fr10/feedback', headers=headers(), json={
        'destinationId': 'local_penang_hill',
        'rating': 5,
        'comment': 'Beautiful scenery and a wonderful outing.',
    }).json['feedback']
    identity = created['id']
    assert created['screening']['risk'] == 'low'
    review_url = f'/api/fr13/feedback/{identity}/review'
    public_url = '/api/fr3/destinations/local_penang_hill/ratings-reviews'
    assert client.post(review_url, headers=headers('admin'), json={'decision': 'keep'}).status_code == 200
    assert client.get(public_url, headers=headers()).json['result']['rating'] == 5
    edited = client.put(f'/api/fr10/feedback/{identity}', headers=headers(), json={'rating': 1})
    assert edited.status_code == 200
    flagged = edited.json['feedback']
    assert flagged['comment'] == created['comment']
    assert flagged['screening']['sentiment']['ratingMismatch'] is True
    assert flagged['moderationStatus'] == 'pending_review'
    assert client.get(public_url, headers=headers()).json['result']['rating'] is None

    # Existing standalone/legacy sources may lack trustworthy server screening.
    memory['feedback', identity]['screening'] = {'risk': 'low'}
    queue = client.get('/api/fr13/feedback', headers=headers('admin'))
    assert queue.json['items'][0]['screening']['risk'] == 'flagged'
    assert current_screen(memory['feedback', identity])['sentiment']['ratingMismatch']
    corrected = client.put(f'/api/fr10/feedback/{identity}', headers=headers(), json={
        'comment': 'The wait was frustrating and the visit was disappointing.',
    }).json['feedback']
    assert corrected['rating'] == 1
    assert corrected['screening']['risk'] == 'low'
    assert corrected['moderationStatus'] == 'reviewed'
    assert corrected['moderationDecision']['actor'] == 'system'
    approved = client.post(review_url, headers=headers('admin'), json={'decision': 'keep'})
    assert approved.json['feedback']['screening']['risk'] == 'low'
    result = client.get(public_url, headers=headers()).json['result']
    assert (result['rating'], result['reviews']) == (1, 1)
    assert 'screening' not in result['user_reviews'][0]
    client.post(review_url, headers=headers('admin'), json={'decision': 'remove'})
    assert client.get(public_url, headers=headers()).json['result']['reviews'] == 0


def test_legacy_pending_review_retry_does_not_auto_approve(client, memory):
    comment = 'Beautiful scenery and a wonderful outing.'
    memory['feedback', 'legacy'] = {
        'id': 'legacy', 'travellerId': 'owner', 'destinationId': 'local_penang_hill',
        'rating': 5, 'comment': comment, 'feedbackStatus': 'visible',
        'moderationStatus': 'pending_review',
    }
    endpoint = '/api/fr10/feedback'
    repeated = client.post(endpoint, headers=headers(), json={
        'destinationId': 'local_penang_hill', 'rating': 5, 'comment': comment,
    })
    assert repeated.status_code == 200
    assert repeated.json['feedback']['moderationStatus'] == 'pending_review'
    unchanged = client.put(endpoint + '/legacy', headers=headers(), json={'rating': 5})
    assert unchanged.json['feedback']['moderationStatus'] == 'pending_review'
    assert client.get('/api/fr13/feedback', headers=headers('admin')).json['items'][0]['moderationCategory'] == 'needs_review'
