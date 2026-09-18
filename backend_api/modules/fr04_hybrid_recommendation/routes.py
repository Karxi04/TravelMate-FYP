import os
from flask import Blueprint, jsonify, g, request
from auth_utils import auth_required
from utils import utc_now_iso
from services.serpapi_service import retrieveDestinationResults
from services.local_catalog import DESTINATIONS
from sequence_contract.firebase_firestore import retrieveRecord, storeRecord
from sequence_contract.domain_functions import (
    prepareRecommendationInput,
    applyContentBasedFiltering,
    applyCollaborativeFiltering,
    calculateRecommendationScore,
    rankRecommendations,
)

bp = Blueprint('fr04_recommendations', __name__, url_prefix='/api/fr4')


def _fallback_mode():
    return os.getenv('FALLBACK_MODE', 'false').lower() in {'1', 'true', 'yes'}


def _provider_destinations(query, location):
    result = retrieveDestinationResults(query, location)
    items = list(result.get('local_results', []) or [])
    normalized = []
    for raw in items:
        item = dict(raw or {})
        did = str(item.get('place_id') or item.get('data_id') or item.get('title') or '')
        if not did:
            continue
        item['destinationId'] = did
        item['category'] = item.get('category') or item.get('type') or ''
        item['description'] = item.get('description') or item.get('type') or item.get('address') or ''
        normalized.append(item)
    return normalized


@bp.post('/recommendations/generate')
@auth_required(['traveller'])
def generate():
    pref = retrieveRecord('travel_preferences', g.uid)
    if not pref:
        return jsonify({'ok': False, 'error': 'Complete travel preferences first'}), 400

    payload = request.get_json(silent=True) or {}
    destination_area = str(payload.get('destinationArea') or payload.get('location') or 'Malaysia').strip()
    search_query = str(payload.get('query') or '').strip()
    if not search_query:
        interests = pref.get('interests') or []
        interest_text = ' '.join(str(x) for x in interests[:3])
        search_query = f"{interest_text} tourist attractions {destination_area}".strip()

    candidates = []
    source = 'cache'

    # Prefer live destination information when SerpApi is configured.
    if os.getenv('SERPAPI_KEY', '').strip():
        try:
            candidates = _provider_destinations(search_query, destination_area)
            source = 'serpapi'
            for item in candidates[:30]:
                did = str(item.get('destinationId') or '')
                if did:
                    storeRecord('destination_cache', item, did, merge=True)
        except Exception:
            candidates = []

    if not candidates:
        cached = retrieveRecord('destination_cache', limit=150)
        if cached:
            candidates = cached
            source = 'cache'

    if not candidates and _fallback_mode():
        candidates = [dict(x) for x in DESTINATIONS]
        source = 'local'

    if not candidates:
        return jsonify({'ok': False, 'error': 'No recommendation candidates are available. Configure SerpApi or enable FALLBACK_MODE.'}), 502

    collaborative = [x for x in retrieveRecord('feedback', limit=500) if str(x.get('feedbackStatus','visible')).lower() == 'visible']
    peer_profiles_raw = retrieveRecord('travel_preferences', limit=500)
    peer_profiles = {
        str(row.get('travellerId') or row.get('id') or ''): row
        for row in (peer_profiles_raw or [])
        if str(row.get('travellerId') or row.get('id') or '')
    }

    prepared = prepareRecommendationInput(pref, candidates, collaborative)
    content = applyContentBasedFiltering(prepared)
    combined = applyCollaborativeFiltering(
        content,
        collaborative,
        peerPreferences=peer_profiles,
        currentPreference=pref,
    )
    scored = calculateRecommendationScore(combined)
    ranked = rankRecommendations(scored)[:12]

    record = {
        'travellerId': g.uid,
        'generatedAt': utc_now_iso(),
        'destinationArea': destination_area,
        'source': source,
        'engine': {
            'contentBasedFiltering': True,
            'collaborativeFiltering': True,
            'weightedScoring': {'content': 0.60, 'collaborative': 0.30, 'popularity': 0.10},
            'ranking': True,
        },
        'items': ranked,
    }
    storeRecord('recommendations', record, g.uid, merge=True)

    return jsonify({
        'ok': True,
        'recommendations': ranked,
        'source': source,
        'engine': record['engine'],
    })


@bp.get('/recommendations')
@auth_required(['traveller'])
def get_recommendations():
    record = retrieveRecord('recommendations', g.uid) or {}
    return jsonify({
        'ok': True,
        'recommendation': record,
        'recommendations': record.get('items', []),
        'source': record.get('source', ''),
        'engine': record.get('engine', {}),
    })
