"""Source-controlled evaluation data and real routes, with every live boundary blocked."""
from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock
import pytest

from services import demonstration_recommendations as demo, national_evaluation_reviews as national, fyp_reviews
from services.malaysian_locality import normalize_destination_scope, validate_candidate
from services.recommendation_review_evidence import approved_contributions, review_summaries, popularity_evidence
from services.review_service import genuine_review, screen_submission, review_id
from services.review_destination import review_candidate_id
from services.destination_research import attraction_identities
from services.local_catalog import DESTINATIONS
from scripts.plan_penang_fyp_reviews import build_plan
from scripts.plan_penang_fyp_expansion import build_plan as expansion
from test_local_reviews import memory, headers


@pytest.fixture
def nationwide(client, memory, monkeypatch):
    original, added = build_plan(), expansion()
    places = original['documents']['fyp_review_datasets/penang_v1']['destinations']
    rows = [{**r, 'id': path.rsplit('/', 1)[-1]} for path, r in
            [*original['documents'].items(), *added['documents'].items()] if 'rating' in r]
    monkeypatch.setattr(demo, 'private_dataset', lambda: ('isolated', places))
    monkeypatch.setattr(demo, 'dataset_reviews', lambda *_: deepcopy(rows))
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH', '')
    from modules.fr04_hybrid_recommendation import routes
    profile = deepcopy(demo.SIMULATED_PROFILES['culture'])
    def read(collection, identity=None, **kwargs):
        assert collection == 'travel_preferences' and identity in {'owner', 'second'}
        return deepcopy(profile)
    monkeypatch.setattr(routes, 'retrieveRecord', read)
    monkeypatch.setattr(routes, 'cached_candidates', lambda *_: [])
    blocked = Mock(side_effect=AssertionError('No genuine persistence or provider operation'))
    for name in ('storeRecord', 'loadRecommendationSnapshot', 'retrieveRecordsById', '_provider_destinations', 'transactPreferenceLearning'):
        monkeypatch.setattr(routes, name, blocked)
    client.application.config.update(LOCAL_FYP_SAMPLE_REVIEWS=True, RECOMMENDATION_EVIDENCE_MODE='fyp_evaluation')
    return profile, blocked, places, rows


def generate(client, area, **extra):
    response = client.post('/api/fr4/recommendations/generate',
        headers={**headers(), 'X-TravelMate-Review-Context': 'fyp-v1'},
        json={'destinationArea': area, 'limit': 50, **extra})
    assert response.status_code == 200, response.json
    return response.json


def test_structured_source_data_has_real_identities_profiles_screening_and_no_duplicate_ids(nationwide):
    candidates = national.destinations()
    assert len(candidates) == 86 and len(national.profiles()) == 8
    assert set(candidates) <= {r['destinationId'] for r in [*attraction_identities(), *DESTINATIONS]}
    rows = [r for identity in candidates for r in national.sources(identity)]
    assert len(rows) == len({r['id'] for r in rows}) == 688
    assert {r['rating'] for r in rows} == {1, 2, 3, 4, 5}
    assert len({r['comment'] for r in rows}) == 688
    for row in rows:
        assert row['synthetic'] is True and not genuine_review(row)
        assert row['source'] == 'fyp_private' and row['dataset'] == national.DATASET and row['datasetVersion'] == 1
        assert row['id'] == review_id(row['travellerId'], row['destinationId'])
        assert national.profiles()[row['travellerId']]['synthetic'] is True
        screened = screen_submission(row['comment'], row['rating'])
        assert row['moderationStatus'] == row['initialModerationStatus'] == screened['moderationStatus']
        assert row['screening']['risk'] == row['initialScreeningRisk'] == screened['screening']['risk']
        assert datetime.fromisoformat(row['submittedAt']).utcoffset() is not None
    for candidate in candidates.values():
        assert candidate['gps_coordinates'] and candidate['geographicEligibility']['eligible']
        if candidate.get('source') == 'official_identity':
            assert candidate['metadataStatus'] == 'identity_and_coordinates'
            assert candidate['detailsAvailable'] is False and candidate['identitySourceUrl']
            assert 'estimatedCost' not in candidate and 'openingHours' not in candidate
    assert not approved_contributions(rows)
    assert sum(map(len, approved_contributions(rows, demonstration=True).values())) == 661
    assert sum(r['moderationStatus']=='pending_review' for r in rows)==27
    assert len({r['destinationId'] for r in attraction_identities()}) == 400


@pytest.mark.parametrize('invalid',[{'synthetic':False},{'source':'travelmate'},{'dataset':'genuine'},{'datasetVersion':2}])
def test_contribution_provenance_cannot_be_silently_reclassified(nationwide,monkeypatch,invalid):
    identity='local_my_perak_zoo_taiping'
    national.destinations()  # Validate the real source identities before mutating an isolated copy.
    profiles,records=deepcopy(national._definitions())
    records[identity]['contributions'][0].update(invalid)
    monkeypatch.setattr(national,'_definitions',lambda:(profiles,records))
    with pytest.raises(ValueError):
        national._sources.__wrapped__(identity)


@pytest.mark.parametrize('area', ['Penang', 'Kuala Lumpur', 'Selangor', 'Kedah', 'Perak', 'Melaka', 'Johor',
    'Pahang', 'Sabah', 'Sarawak', 'Perlis', 'Putrajaya', 'Negeri Sembilan', 'Terengganu', 'Kelantan', 'Labuan',
    'Malaysia', 'Langkawi', 'George Town, Penang', 'Kota Kinabalu, Sabah', 'Kuala Selangor, Selangor'])
def test_actual_normal_generation_uses_the_requested_scope_and_matching_reviews(client, nationwide, area):
    body = generate(client, area)
    scope = body['snapshot']['canonicalDestinationScope']
    places, rows = demo.load_sources(scope)
    identities = {review_candidate_id(r) for r in places}
    assert rows and all(review_candidate_id(r) in identities for r in rows)
    assert len(rows) == len({r['id'] for r in rows})
    assert all(validate_candidate(r, scope)[0] for r in body['recommendations'])
    assert body['recommendationEvidenceMode'] == 'fyp_evaluation'
    assert body['recommendationGenerationId'].startswith('fyp-evaluation-')
    assert body['evidenceProvenance']['approvedContributions'] == sum(map(len, approved_contributions(rows, demonstration=True).values()))
    assert body['evidenceProvenance']['localReviewPolicy'] == 'approved_local_only'
    expected_datasets=sorted({r.get('dataset') or 'penang_private' for r in rows})
    assert body['evidenceProvenance']['datasets']==expected_datasets
    assert body['evidenceProvenance']['dataset']=='+'.join(expected_datasets)
    approved = approved_contributions(rows, demonstration=True)
    for item in body['recommendations']:
        group = approved.get(review_candidate_id(item), [])
        if group:
            assert item['popularitySource'] == 'demonstration_approved_reviews'
            assert item['popularityEvidence']['reviewCount'] == len(group)
            assert item['demonstrationReviewSummary']['reviews'] == len(group)
            assert item['popularityEvidence']['rating'] == pytest.approx(sum(r['rating'] for r in group) / len(group))
    assert not nationwide[1].called


def test_non_penang_generation_never_reads_the_private_penang_dataset(client, nationwide, monkeypatch):
    blocked = Mock(side_effect=AssertionError('Unrelated Penang reads are forbidden'))
    monkeypatch.setattr(demo, 'private_dataset', blocked)
    for area in ['Kuala Lumpur', 'Melaka', 'Johor', 'Ipoh, Perak']:
        generate(client, area)
    assert not blocked.called


def test_uncovered_valid_locality_can_use_verified_cache_fallback_without_live_search(client,nationwide,monkeypatch):
    from modules.fr04_hybrid_recommendation import routes
    from services.destination_candidates import normalise
    scope=normalize_destination_scope('Kulim, Kedah')
    assert demo.load_sources(scope)==([],[])
    place={'destinationId':'isolated-kulim-museum','title':'Isolated museum','type':'Museum',
           'city':'Kulim','state':'Kedah','address':'Kulim, Kedah, Malaysia',
           'ratingSource':'provider','rating':4.5,'reviews':100,'cachedAt':'2026-11-21T00:00:00Z'}
    monkeypatch.setattr(routes,'cached_candidates',lambda _read,selected:normalise([place],selected,source='cache'))
    body=generate(client,'Kulim, Kedah')
    assert len(body['recommendations'])==1
    row=body['recommendations'][0]
    assert row['popularityScore']==50 and row['popularityEvidence']['rating'] is None
    assert row['collaborativeScore']==50 and row['collaborativeRatingCount']==0
    assert body['evidenceProvenance']['approvedContributions']==0
    assert body['evidenceProvenance']['datasets']==[]
    monkeypatch.setattr(routes,'cached_candidates',lambda *_:[])
    assert generate(client,'Kulim, Kedah')['recommendations']==[]
    assert not nationwide[1].called


def test_full_coverage_independent_aggregate_profiles_negative_evidence_and_genuine_isolation(nationwide):
    candidates, rows = demo.load_sources('Malaysia')
    assert len(candidates) == len({review_candidate_id(p) for p in candidates}) == 100
    assert len(rows) == 909 and sum(map(len, approved_contributions(rows, demonstration=True).values())) == 874
    assert fyp_reviews.PENANG_DESTINATION_IDS <= {review_candidate_id(p) for p in candidates}
    results = [{r['destinationId']: r for r in demo.evaluate(profile, candidates, rows, evidence_mode='fyp_evaluation')}
               for profile in demo.SIMULATED_PROFILES.values()]
    for identity in national.destinations():
        assert all(result[identity]['collaborativeRatingCount'] > 0 for result in results)
        assert len({result[identity]['popularityScore'] for result in results}) == 1
    assert any(len({result[identity]['collaborativeScore'] for result in results}) > 1 for identity in national.destinations())
    assert len({tuple(result) for result in results}) > 1  # Ranked insertion order differs naturally.
    changed = deepcopy(rows)
    for row in changed:
        row.update(rating=1, comment='A terrible and disappointing visit. I left frustrated.')
        row.update(screen_submission(row['comment'], 1))
    lower = {r['destinationId']: r for r in demo.evaluate(demo.SIMULATED_PROFILES['culture'], candidates, changed, evidence_mode='fyp_evaluation')}
    assert all(lower[k]['popularityScore'] < results[0][k]['popularityScore'] for k in lower)
    assert all(lower[k]['collaborativeScore'] <= results[0][k]['collaborativeScore'] for k in lower)
    assert not approved_contributions(rows)
    assert all(p['synthetic'] is True for p in demo.simulated_profiles(rows).values())


def test_new_data_moderation_duplicates_and_provider_neutral_fallback(nationwide):
    identity = 'local_my_perak_zoo_taiping'
    rows = national.sources(identity)
    changed = deepcopy(rows)
    changed[0]['moderationStatus'] = 'pending_review'
    changed[1]['moderationStatus'] = 'removed'
    changed[2]['rating'] = True
    groups = approved_contributions(changed + [changed[-1]], demonstration=True)
    expected = len([r for r in changed[3:] if r['moderationStatus']=='reviewed'])
    assert len(groups[identity]) == expected and expected in {4,5}
    summary = review_summaries(groups, demonstration=True)
    place = {**national.destinations()[identity], 'ratingSource': 'provider', 'rating': 4.5, 'reviews': 1234}
    assert popularity_evidence(place, summary, demonstration=True)['reviewCount'] == expected
    assert popularity_evidence(place, {}, demonstration=True)['score'] == 50
    assert popularity_evidence({**place, 'ratingSource': 'unknown'}, {}, demonstration=True)['score'] == 50
    assert national.sources(identity) == rows


def test_nationwide_local_badges_and_single_review_list_share_approved_counts(client, nationwide, monkeypatch):
    from modules.fr03_destination_search_information import routes
    monkeypatch.setattr(routes, '_private_review_dataset', lambda **_: None)
    identities = ['local_my_perak_zoo_taiping', 'local_my_penang_the_top_komtar',
                  'local_melaka_cruise', 'local_my_kuala_lumpur_aquaria_klcc', 'local_my_sarawak_darul_hana_bridge']
    for account in ['owner', 'second', 'new-registration']:
        auth = {**headers(account), 'X-TravelMate-Review-Context': 'fyp-v1'}
        badges = client.get('/api/fr3/local-ratings', headers=auth).json['items']
        for identity in identities:
            expected = approved_contributions(fyp_reviews.regional_demo_reviews(identity), demonstration=True)[identity]
            result = client.get('/api/fr3/destinations/'+identity+'/ratings-reviews', headers=auth).json['result']
            assert result['reviews'] == len(result['user_reviews']) == len(expected)
            assert len({r['id'] for r in result['user_reviews']}) == len(expected)
            assert (result['rating'], result['reviews']) == (badges[identity]['rating'], badges[identity]['reviews'])
            assert result['genuineSummary'] == {'rating': None, 'reviews': 0}
            assert all(r['synthetic'] is True for r in result['user_reviews'])
            genuine = client.get('/api/fr3/destinations/'+identity+'/ratings-reviews', headers=headers(account)).json['result']
            assert genuine['reviews'] == 0
            if national.destinations()[identity].get('source')=='official_identity':
                detail=client.get('/api/fr3/destinations/'+identity,headers=auth)
                assert detail.status_code==200 and detail.json['destination']['destinationId']==identity
                assert detail.json['detailsAvailable'] is False  # No invented hours/prices.


def test_new_regional_contribution_keeps_existing_admin_cas_and_history(client,nationwide,monkeypatch,tmp_path,memory):
    from modules.fr13_administrator_management import routes
    monkeypatch.setenv('FYP_REVIEW_STAGING_PATH',str(tmp_path/'nationwide-overlay.sqlite3'))
    from services.review_staging import initialize
    initialize()
    monkeypatch.setattr(routes,'private_dataset',lambda:None)
    before=deepcopy(memory)
    listed=client.get('/api/fr13/feedback?source=all',headers=headers('admin'))
    assert listed.status_code==200
    target=next(r for r in listed.json['items'] if r.get('dataset')==national.DATASET and r['destinationId']=='local_my_perak_zoo_taiping')
    path='/api/fr13/feedback/'+target['id']
    payload={'decision':'hide','expectedRevision':target['reviewRevision']}
    assert client.post(path+'/review?source=fyp_regional',headers=headers('admin'),json=payload).status_code==200
    assert client.post(path+'/review?source=fyp_regional',headers=headers('admin'),json=payload).status_code==409
    _,rows=demo.load_sources('Perak')
    assert not {target['id']} & {r['id'] for r in approved_contributions(rows,demonstration=True)[target['destinationId']]}
    assert len(client.get(path+'/history?source=fyp_regional',headers=headers('admin')).json['items'])==2
    assert memory==before


def test_expanded_dataset_does_not_evict_legacy_moderation_source_revisions(nationwide,monkeypatch):
    from services.review_service import review_revision
    clock=['2026-11-21T04:00:00+00:00']
    monkeypatch.setattr('services.review_service.utc_now_iso',lambda:clock[0])
    fyp_reviews._regional_sources.cache_clear()
    try:
        initial=fyp_reviews._regional_sources('local_batu_caves')[0]
        fyp_reviews.all_regional_reviews()  # The expanded list exceeds the old 64-entry cache.
        for i in range(150):
            assert fyp_reviews.regional_demo_reviews('isolated-unreviewed-'+str(i))==[]
        clock[0]='2026-11-21T04:05:00+00:00'
        assert review_revision(fyp_reviews._regional_sources('local_batu_caves')[0])==review_revision(initial)
    finally:
        fyp_reviews._regional_sources.cache_clear()


def test_names_and_aliases_do_not_move_attractions_across_scopes(nationwide):
    from services.destination_candidates import normalise, same_place
    places, _ = demo.load_sources('Selangor')
    assert 'local_my_kuala_lumpur_royal_selangor' not in {r['destinationId'] for r in places}
    correct = national.destinations()['local_my_perak_zoo_taiping']
    unrelated = {**correct, 'destinationId': 'isolated-same-name',
                 'place_id':'isolated-same-name','reviewDestinationId':'isolated-same-name','state': 'Johor',
                 'city': 'Johor Bahru', 'address': 'Johor Bahru, Johor, Malaysia', 'gps_coordinates': {}}
    assert not same_place(correct, unrelated)
    assert [r['destinationId'] for r in normalise([correct, unrelated], normalize_destination_scope('Perak'))] == [correct['destinationId']]
    penang, rows = demo.load_sources('Penang')
    assert 'local_kek_lok_si' in {review_candidate_id(r) for r in penang}
    assert review_candidate_id({'destinationId': 'kek_lok_si'}) == 'local_kek_lok_si'
    assert len(rows) == len({r['id'] for r in rows})


def test_home_listing_regeneration_account_scope_and_one_hour_expiry(client, nationwide, monkeypatch):
    body = generate(client, 'Melaka')
    first = body['recommendationGenerationId']
    auth = {**headers(), 'X-TravelMate-Review-Context': 'fyp-v1'}
    path = '/api/fr4/recommendations'
    home = client.get(path, headers=auth).json
    listing = client.get(path, headers=auth, query_string={'generationId': first, 'limit': 50}).json
    assert home['recommendationGenerationId'] == listing['recommendationGenerationId'] == first
    assert home['recommendations'] == listing['recommendations'][:len(home['recommendations'])]
    assert client.get(path, headers={**headers('second'), 'X-TravelMate-Review-Context': 'fyp-v1'}, query_string={'generationId': first}).status_code == 404
    second = generate(client, 'Melaka', previousGenerationId=first)['recommendationGenerationId']
    assert first != second
    monkeypatch.setattr(demo, 'monotonic', lambda: 10**12)
    assert client.get(path, headers=auth, query_string={'generationId': second}).status_code == 404
    assert not nationwide[1].called
