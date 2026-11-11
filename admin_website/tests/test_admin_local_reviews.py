from unittest.mock import MagicMock
from test_admin_approval_availability import app, auth_client, _patch_admin_api


def test_pending_review_form_is_escaped_and_approval_is_explicit(auth_client):
    review = {'id': 'review', 'destinationName': 'Synthetic Place', 'rating': 5,
        'comment': '<script>alert(1)</script>', 'feedbackStatus': 'visible',
        'moderationStatus': 'pending_review', 'updatedAt': 'revision',
        'screening': {'risk': 'flagged', 'flags': ['rating_sentiment_mismatch'],
                      'sentiment': {'label': 'negative', 'ratingMismatch': True}}}
    response = MagicMock(ok=True)
    response.json.return_value = {'ok': True, 'items': [review]}
    with _patch_admin_api(lambda *args, **kwargs: response):
        page = auth_client.get('/admin/feedback')
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html and '<script>alert(1)</script>' not in html
    assert 'Approve' in html and 'Reject' in html and 'Flagged' in html
    assert 'Comment tone: Negative' in html and 'Check the star rating against the comment' in html
    assert 'class="badge warning"' in html
    assert 'name="expectedUpdatedAt" value="revision"' in html


def test_admin_review_action_forwards_revision_and_rejection(auth_client):
    captured = []
    response = MagicMock(ok=True)
    response.json.return_value = {'ok': True}
    def api(method, path, **kwargs):
        captured.append((method, path, kwargs))
        return response
    with _patch_admin_api(api):
        result = auth_client.post('/admin/feedback/review/review', data={
            'decision': 'remove', 'comment': 'Spam', 'expectedUpdatedAt': 'revision'})
    assert result.status_code == 302
    assert captured[0][2]['json'] == {'decision': 'remove', 'comment': 'Spam', 'expectedUpdatedAt': 'revision'}


def test_moderation_filters_counts_and_history(auth_client):
    rows = [
        {'id': 'normal', 'destinationName': 'Penang Hill', 'moderationCategory': 'automatic',
         'moderationDecision': {'actor': 'system', 'policyVersion': 'travelmate-review-auto-v1'}},
        {'id': 'flagged', 'destinationName': 'Unrelated Place', 'moderationCategory': 'flagged'},
        {'id': 'uncertain', 'destinationName': 'Chew Jetty', 'moderationCategory': 'needs_review'},
        {'id': 'manual', 'destinationName': 'Manual Place', 'moderationCategory': 'manual'},
        {'id': 'hidden', 'destinationName': 'Hidden Place', 'moderationCategory': 'hidden'},
    ]
    def api(method, path, **kwargs):
        response = MagicMock(ok=True)
        items = rows if path == '/api/fr13/feedback' else [
            {'actor': 'administrator', 'outcome': 'approve', 'note': 'Earlier decision'}]
        response.json.return_value = {'items': items}
        return response
    with _patch_admin_api(api):
        queue = auth_client.get('/admin/feedback').get_data(as_text=True)
        normal = auth_client.get('/admin/feedback?status=normal&q=penang&history=normal').get_data(as_text=True)
    assert 'Unrelated Place' in queue and 'Chew Jetty' in queue and 'Penang Hill' not in queue
    assert 'Penang Hill' in normal and 'Manual Place' not in normal and 'Unrelated Place' not in normal
    assert '1 automatic · 1 manual' in normal and 'Earlier decision' in normal


def test_private_source_is_carried_to_filters_history_and_actions(auth_client):
    calls = []
    response = MagicMock(ok=True)
    row = {'id': 'penang', 'destinationName': 'Penang Hill', 'travellerName': 'Mira S.',
           'moderationCategory': 'flagged', 'reviewRevision': 'expected',
           'reviewSource': 'fyp_penang'}
    genuine = {'id': 'penang', 'destinationName': 'Genuine place', 'travellerName': 'Genuine reviewer',
               'moderationCategory': 'manual', 'reviewSource': 'traveller'}

    def api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        response.json.return_value = {'items': [] if path.endswith('/history') else [row, genuine]}
        return response

    with _patch_admin_api(api):
        page = auth_client.get('/admin/feedback?status=all&history_source=fyp_penang&history=penang')
        result = auth_client.post('/admin/feedback/penang/review', data={
            'source': 'fyp_penang', 'decision': 'keep', 'expectedRevision': 'expected',
        })
    html = page.get_data(as_text=True)
    assert 'Review source' not in html and 'FYP Penang Reviews' not in html
    assert 'Penang Hill' in html and 'Genuine place' in html
    assert 'name="source" value="fyp_penang"' in html and 'name="source" value="traveller"' in html
    assert html.count('<details open>') == 1
    assert [path for _, path, _ in calls] == [
        '/api/fr13/feedback', '/api/fr13/feedback/penang/history', '/api/fr13/feedback/penang/review',
    ]
    assert calls[0][2]['params'] == {'source': 'all'}
    assert all(kwargs['params'] == {'source': 'fyp_penang'} for _, _, kwargs in calls[1:])
    assert calls[-1][2]['json']['expectedRevision'] == 'expected'
    assert result.status_code == 302 and 'source=' not in result.location
