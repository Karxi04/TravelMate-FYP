"""Offline contracts only: no provider requests or live database access."""
from copy import deepcopy
import pytest
from services.destination_candidates import merge_candidates, normalise, facts_signature
from services.malaysian_locality import normalize_destination_scope
from services.recommendation_review_evidence import popularity_evidence
from test_penang_collaborative_evidence import generation


def provider(**extra):
    return {'destinationId': 'local_kek_lok_si', 'title': 'Kek Lok Si Temple',
            'address': 'Air Itam, Penang, Malaysia', 'rating': 4.5, 'reviews': 9000,
            'ratingSource': 'provider', 'cachedAt': '2026-11-18T00:00:00Z',
            'candidateSource': 'cache', **extra}


def test_newer_unverified_metadata_cannot_overwrite_trusted_provider_rating():
    old = provider()
    new = {**old, 'rating': 3.0, 'reviews': 1, 'ratingSource': 'unverified_local_catalog',
           'cachedAt': '2026-11-20T00:00:00Z', 'description': 'A newer destination description.'}
    original = deepcopy([old, new])
    row = merge_candidates([old], [new])[0]
    assert row['description'] == new['description']
    assert (row['rating'], row['reviews'], row['ratingSource']) == (4.5, 9000, 'provider')
    assert popularity_evidence(row)['score'] == 90
    assert [old, new] == original


def test_new_provider_rating_does_not_inherit_an_unrelated_old_review_count():
    old = provider()
    new = {key: value for key, value in provider(rating=4.0,
        candidateSource='live_provider', cachedAt='2026-11-20T00:00:00Z').items() if key != 'reviews'}
    row = merge_candidates([old], [new])[0]
    assert row['rating'] == 4
    assert row.get('reviews') is None
    assert popularity_evidence(row)['score'] == 64


def test_normalization_preserves_explicit_provider_source_across_snapshot_restoration():
    scope = normalize_destination_scope('Penang')
    for source in ['cache', 'snapshot']:
        row = normalise([provider()], scope, source=source)[0]
        assert row['ratingSource'] == 'provider'
        assert popularity_evidence(row)['score'] == 90


@pytest.mark.parametrize('patch', [
    {'ratingSource': 'unknown', 'rating': 5, 'reviews': 90000},
    {'ratingSource': 'provider', 'rating': None, 'reviews': 90000},
    {'ratingSource': 'provider', 'rating': True, 'reviews': 90000},
    {'ratingSource': 'provider', 'rating': 6, 'reviews': 90000},
    {'ratingSource': 'provider', 'rating': 5, 'synthetic': True},
])
def test_missing_invalid_and_private_evidence_cannot_replace_trusted_rating(patch):
    old = provider()
    new = {**old, **patch, 'cachedAt': '2026-11-20T00:00:00Z'}
    row = merge_candidates([old], [new])[0]
    assert (row['rating'], row['reviews'], row['ratingSource']) == (4.5, 9000, 'provider')
    if patch.get('synthetic'):
        assert popularity_evidence(row)['score'] == 50  # Private marker still prevents genuine use.


def test_newest_trusted_observation_replaces_pair_and_stale_provider_does_not_win():
    old = provider()
    new = provider(rating=4, reviews=100, cachedAt='2026-11-20T00:00:00Z')
    for groups in ([old, new], [new, old]):
        row = merge_candidates(groups)[0]
        assert (row['rating'], row['reviews']) == (4, 100)
        assert popularity_evidence(row)['score'] == 64.2


def test_confirmed_botanic_review_aliases_merge_without_guessing_provider_identities():
    old = provider(destinationId='local_botanical_gardens', title='Penang Botanic Gardens')
    other = provider(destinationId='ChIJWeDiIPHCSjAROzyNNz_QUx8', title='Botanical Gardens Penang',
                     cachedAt='2026-11-20T00:00:00Z')
    assert len(merge_candidates([old, other])) == 1
    unrelated = {**other, 'destinationId': 'isolated-unrelated-garden', 'title': 'Different garden'}
    assert len(merge_candidates([old, unrelated])) == 2


def test_new_description_timestamp_cannot_make_an_older_rating_win_a_later_merge():
    old = provider(cachedAt='2026-11-18T00:00:00Z')
    description = {**old, 'ratingSource':'unverified_local_catalog',
                   'cachedAt':'2026-11-20T00:00:00Z', 'description':'Newest description'}
    combined = merge_candidates([old, description])
    newer_rating = provider(rating=4, reviews=100, cachedAt='2026-11-19T00:00:00Z')
    row = merge_candidates(combined, [newer_rating])[0]
    assert row['description'] == 'Newest description'
    assert (row['rating'], row['reviews']) == (4, 100)


def test_live_rating_observation_time_is_not_refreshed_by_snapshot_restoration():
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    scope = normalize_destination_scope('Penang')
    row = normalise([provider()], scope, source='live_provider', now=now)[0]
    assert row['ratingEvidenceAt'] == now.isoformat()
    restored = normalise([row], scope, source='snapshot', now=now+timedelta(days=1))[0]
    assert restored['ratingEvidenceAt'] == now.isoformat()


def test_derived_rating_observation_does_not_fake_new_facts_but_source_changes_do():
    old = provider()
    combined = merge_candidates([old, {**old, 'ratingSource':'unverified_local_catalog'}])
    assert facts_signature([old]) == facts_signature(combined)
    assert facts_signature([old]) != facts_signature([{**old, 'ratingSource':'unknown'}])


def test_new_approval_only_affects_explicit_new_generation_and_latest_get(generation, client, monkeypatch):
    from modules.fr04_hybrid_recommendation import routes
    state, generate = generation
    state['feedback'] = [{'id': 'isolated-peer-review', 'travellerId': 'peer',
        'destinationId': 'penang_hill', 'rating': 4,
        'feedbackStatus': 'visible', 'moderationStatus': 'pending_review'}]
    read = routes.retrieveRecord
    def records(collection, identity=None, **options):
        if collection == 'recommendation_snapshots' and identity is None:
            return [{'id': key, **deepcopy(row)} for key, row in state['snapshots'].items()]
        return read(collection, identity, **options)
    monkeypatch.setattr(routes, 'retrieveRecord', records)
    old = generate()
    old_id = old['recommendationGenerationId']
    assert old['recommendations'][0]['collaborativeRatingCount'] == 0
    state['feedback'][0]['moderationStatus'] = 'approved'  # Isolated fixture only.
    headers = {'Authorization': 'Bearer isolated'}
    saved = client.get('/api/fr4/recommendations', headers=headers, query_string={'generationId': old_id})
    assert saved.json['recommendations'][0]['collaborativeRatingCount'] == 0
    new = generate()
    assert new['recommendationGenerationId'] != old_id
    row = new['recommendations'][0]
    assert row['collaborativeRatingCount'] == 1 and row['collaborativeScore'] > 50
    assert row['popularitySource'] == 'genuine_approved_local_reviews'
    assert row['popularityEvidence']['reviewCount'] == 1
    latest = client.get('/api/fr4/recommendations', headers=headers)
    assert latest.json['recommendationGenerationId'] == new['recommendationGenerationId']
    assert state['snapshots'][old_id]['recommendationResults'][0]['collaborativeRatingCount'] == 0
