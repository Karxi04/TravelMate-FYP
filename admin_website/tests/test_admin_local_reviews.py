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
