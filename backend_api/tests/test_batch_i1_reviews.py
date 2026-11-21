from copy import deepcopy
from unittest.mock import patch

import pytest

from test_local_reviews import memory, headers
from services.fyp_reviews import regional_demo_reviews, regional_demo_destinations
from services.review_service import review_revision


def test_private_combined_summary_matches_list_cards_and_moderation(client, memory, monkeypatch, tmp_path):
    from modules.fr03_destination_search_information import routes
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH', str(tmp_path / 'review-overlay.sqlite3'))
    from services.review_staging import initialize
    initialize()
    monkeypatch.setattr('modules.fr13_administrator_management.routes.private_dataset', lambda: None)
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    monkeypatch.setattr(routes, '_private_review_dataset', lambda **kw: None)
    memory['feedback', 'real'] = {'id': 'real', 'travellerId': 'owner', 'destinationId': 'local_batu_caves',
        'rating': 5, 'comment': 'Beautiful visit.', 'moderationStatus': 'reviewed', 'feedbackStatus': 'visible'}
    initial = deepcopy(memory)
    context = {'X-TravelMate-Review-Context': 'fyp-v1'}
    path = '/api/fr3/destinations/local_batu_caves/ratings-reviews'
    for account in ['owner', 'second', 'new-account']:
        result = client.get(path, headers={**headers(account), **context}).json['result']
        assert result['reviews'] == len(result['user_reviews']) == 12
        assert result['rating'] == round(sum(row['rating'] for row in result['user_reviews']) / 12, 1)
        assert result['genuineSummary'] == {'rating': 5, 'reviews': 1}
        summary = client.get('/api/fr3/local-ratings', headers={**headers(account), **context}).json['items']['local_batu_caves']
        assert (summary['rating'], summary['reviews']) == (result['rating'], result['reviews'])
    public = client.get(path, headers=headers()).json['result']
    assert (public['rating'], public['reviews']) == (5, 1)
    assert all(not row.get('synthetic') for row in public['user_reviews'])
    admin = '/api/fr13/feedback'
    listed = client.get(admin, headers=headers('admin'), query_string={'source': 'all'}).json['items']
    target = next(row for row in listed if row['reviewSource'] == 'fyp_regional' and row['destinationId'] == 'local_batu_caves')
    payload = {'decision': 'hide', 'expectedRevision': target['reviewRevision']}
    post = client.post(admin + '/' + target['id'] + '/review?source=fyp_regional', headers=headers('admin'), json=payload)
    assert post.status_code == 200, post.json
    stale = client.post(admin + '/' + target['id'] + '/review?source=fyp_regional', headers=headers('admin'), json=payload)
    assert stale.status_code == 409
    fresh = client.get(path, headers={**headers(), **context}).json['result']
    assert fresh['reviews'] == 11 and all(row['id'] != target['id'] for row in fresh['user_reviews'])
    card = client.get('/api/fr3/local-ratings', headers={**headers(), **context}).json['items']['local_batu_caves']
    assert (card['rating'], card['reviews']) == (fresh['rating'], fresh['reviews'])
    history = client.get(admin + '/' + target['id'] + '/history?source=fyp_regional', headers=headers('admin')).json['items']
    assert history[0]['outcome'] == 'hide' and len(history) == 2
    assert memory == initial  # Source fixture and genuine collection unchanged.


def test_regional_coverage_is_canonical_and_overlay_read_only_by_default(client, memory, monkeypatch):
    monkeypatch.delenv('FYP_REVIEW_STAGING_PATH', raising=False)
    monkeypatch.setattr('modules.fr13_administrator_management.routes.private_dataset', lambda: None)
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = True
    places = regional_demo_destinations()
    assert len({row['state'] for row in places.values()} | {'Penang'}) == 16
    rows = [row for identity in places for row in regional_demo_reviews(identity)]
    assert len(rows) == len({row['id'] for row in rows}) == 149
    assert len([row for row in rows if row['dataset']=='fyp-regional-v1'])==45
    assert all(row['synthetic'] and row['destinationId'] in places for row in rows)
    url = '/api/fr13/feedback'
    listed = client.get(url + '?source=all', headers=headers('admin')).json['items']
    # private Penang reads are mocked away so this proves local-only regional behaviour.
    regional = [row for row in listed if row['reviewSource'] == 'fyp_regional']
    assert len(regional) == 805 and all(row['moderationWritable'] is False for row in regional)
    assert len([row for row in regional if row['dataset']=='fyp-regional-v1'])==45
    assert {row['id'] for row in rows} <= {row['id'] for row in regional}
    row = regional[0]
    response = client.post(url + '/' + row['id'] + '/review?source=fyp_regional', headers=headers('admin'),
                           json={'decision': 'hide', 'expectedRevision': row['reviewRevision']})
    assert response.status_code == 409 and not memory
    assert client.get(url + '?source=fyp_regional', headers=headers()).status_code == 403
    client.application.config['LOCAL_FYP_SAMPLE_REVIEWS'] = False
    assert client.get(url + '?source=fyp_regional', headers=headers('admin')).status_code == 403


def test_reading_overlay_never_creates_database(monkeypatch, tmp_path):
    from services.review_staging import overlay_rows, staging_path, ReviewStagingUnavailable
    target = tmp_path / 'untouched.sqlite3'
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH', str(target))
    with pytest.raises(ReviewStagingUnavailable):
        overlay_rows([{'id':'a'}])
    assert not target.exists()
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH', 'C:/unsafe/overlay.sqlite3')
    with pytest.raises(ValueError):
        staging_path()
