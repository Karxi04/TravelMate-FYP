"""Authorized isolated request shapes; no live Firebase or provider access."""
from copy import deepcopy
from unittest.mock import patch

import pytest
from google.cloud.firestore_v1 import GeoPoint

from modules.fr04_hybrid_recommendation import routes
from test_recommendation_relevance import repository, AUTH, UID
from services.recommendation_discovery import discovery_annotations, discovery_queries
from services.recommendation_taxonomy import candidate_concepts
from services.package_checkout_contract import derive_required_services, prepare_package_snapshot
from services.package_service import package_submission_error
from test_operator_hotel_integration import package


@pytest.mark.parametrize('kind', ['legacy_engine', 'geopoint', 'invalid_feedback'])
def test_reproduced_route_failures_recover_or_require_explicit_profile_review(client,mock_traveller_auth,repository,kind,caplog):
    client.application.config['PROPAGATE_EXCEPTIONS']=False
    repository.update('travel_preferences',UID,{'interests':['Photography','Food'],
        'travelPersonality':'Planner','travelPace':'Moderate'})
    repository.store('destination_cache',{'destinationId':'food','title':'Penang Hawker Centre','address':'Penang, Malaysia'},'food')
    pref=repository.read('travel_preferences',UID)
    record={'recommendationGenerationId':'isolated-generation','travellerId':UID,
        'requestedDestination':'Penang','engine':{'scoringVersion':'recovery_v3'},
        'preferenceProfileVersion':routes._preference_version(pref),
        'preferenceFingerprint':routes._profile_fingerprint(pref),
        'recommendationResults':[{'destinationId':'one','title':'Penang Street Art','address':'Penang, Malaysia','finalScore':61,'personalSuitabilityScore':90}]}
    if kind=='legacy_engine':record['engine']='legacy hybrid'
    if kind=='geopoint':record['recommendationResults'][0]['gps_coordinates']=GeoPoint(5.4141,100.3288)
    repository.store('recommendation_snapshots',record,'isolated-generation')
    if kind=='invalid_feedback':
        repository.store('learned_preference_profiles',{'feedbackByDestination':{'old':None}},UID)
        response=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang','scoreBasis':'personal_v2','minimumMatchScore':45})
    else:
        response=client.get('/api/fr4/recommendations',headers=AUTH,query_string={
            'generationId':'isolated-generation','destinationArea':'Penang','scoreBasis':'personal_v2','minimumMatchScore':45})
    assert response.status_code==(409 if kind=='invalid_feedback' else 200),response.json
    assert response.is_json
    assert response.headers['X-Request-ID']
    if kind=='legacy_engine':
        assert response.json['stale']
        original=deepcopy(repository.read('recommendation_snapshots','isolated-generation'))
        fresh=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={
            'previousGenerationId':'isolated-generation','destinationArea':'Penang','discoveryMode':'relevant_v1'})
        assert fresh.status_code==200 and fresh.json['recommendations']
        assert repository.read('recommendation_snapshots','isolated-generation')==original
    if kind=='geopoint':
        assert response.json['recommendations'][0]['gps_coordinates']=={'latitude':5.4141,'longitude':100.3288}
    if kind=='invalid_feedback':
        assert response.json['code']=='recommendation_profile_review'
        assert repository.read('learned_preference_profiles',UID)['feedbackByDestination']=={'old':None}


def test_dependency_failure_stays_failure_with_sanitized_correlation(client,mock_traveller_auth,caplog):
    from google.api_core.exceptions import ServiceUnavailable
    with patch.object(routes,'retrieveRecord',side_effect=ServiceUnavailable('private-token private-uid secret-record')):
        result=client.get('/api/fr4/recommendations',headers=AUTH)
    assert result.status_code==503 and result.json['ok'] is False
    assert 'recommendations' not in result.json
    assert result.json['requestId']==result.headers['X-Request-ID']
    assert result.json['requestId'] in caplog.text and 'ServiceUnavailable' in caplog.text
    assert not any(value in result.text+caplog.text for value in ['private-token','private-uid','secret-record'])


def test_programming_exception_remains_500_json_not_empty_success(client,mock_traveller_auth,caplog):
    with patch.object(routes,'retrieveRecord',side_effect=TypeError('private stored value')):
        response=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang'})
    assert response.status_code==500 and response.is_json
    assert response.json['code']=='recommendations_unavailable'
    assert 'private stored value' not in response.text+caplog.text
    assert 'TypeError' in caplog.text


def test_discovery_ignores_legacy_threshold_and_keeps_owned_snapshot_and_scores(client,mock_traveller_auth,repository):
    repository.update('travel_preferences',UID,{'interests':['Photography','Food'],'travelPersonality':'Planner','travelPace':'Moderate'})
    repository.store('recommendation_settings',{'minimumMatchScore':90,'scoreBasis':'personal_v2'},UID)
    for key,title in [('photo','Penang Street Art'),('food','Hawker food street'),('unrelated','Adventure climbing park')]:
        repository.store('destination_cache',{'destinationId':key,'title':title,'address':'Penang, Malaysia'},key)
    before=deepcopy(repository.read('recommendation_settings',UID))
    response=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={
        'destinationArea':'Penang','discoveryMode':'relevant_v1','minimumMatchScore':90})
    assert response.status_code==200,response.json
    ids={row['destinationId'] for row in response.json['recommendations']}
    assert ids=={'photo','food'}
    assert response.json['pagination']['thresholdApplied'] is False
    generation=response.json['recommendationGenerationId']
    snapshot=repository.read('recommendation_snapshots',generation)
    old=client.get('/api/fr4/recommendations',headers=AUTH,query_string={'generationId':generation,'scoreBasis':'hybrid_v1','minimumMatchScore':90}).json
    assert not old['recommendations']
    assert repository.read('recommendation_snapshots',generation)==snapshot
    assert repository.read('recommendation_settings',UID)==before
    assert response.json['engine']['weightedScoring']=={'content':.6,'collaborative':.3,'popularity':.1}
    mock_traveller_auth.return_value={'uid':'other'}
    assert client.get('/api/fr4/recommendations',headers=AUTH,query_string={'generationId':generation,'discoveryMode':'relevant_v1'}).status_code==404


@pytest.mark.parametrize('preference,expected', [({'interests':['Photography','Food']},True),
    ({'interests':['Food']},False),({'interests':['Unmapped']},False),
    ({'interests':['Photography'],'excludedInterests':['Photography']},False),
    ({'interests':['Photography'],'destinationFeedback':{'one':'not_for_me'}},False),
    ({'interests':['Food'],'learnedAffinities':{'photography':1}},False),
    ({'learnedAffinities':{'photography':.3}},True)])
def test_discovery_is_supported_alternative_interest_evidence_not_popularity(preference,expected):
    row={'destinationId':'one','destinationConcepts':['photography'],'rating':5,'popularityScore':100,'personalSuitabilityScore':5}
    assert discovery_annotations(row,preference)['discoveryEligible']==expected


def test_missing_interest_retrieval_is_bounded_and_never_writes_query_tags(client,mock_traveller_auth,repository,monkeypatch):
    repository.update('travel_preferences',UID,{'interests':['Photography','Food']})
    monkeypatch.setenv('SERPAPI_KEY','isolated-test-provider')
    def discover(query,scope,offset):
        return [{'destinationId':query,'title':'Street Art' if query=='street art' else 'Hawker centre','address':'Penang, Malaysia'}]
    with patch.object(routes,'_provider_destinations',side_effect=discover) as provider:
        result=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang','discoveryMode':'relevant_v1'})
    assert result.status_code==200,result.json
    assert [call.args[0] for call in provider.call_args_list]==['street art','hawker centres']
    assert {row['destinationId'] for row in result.json['recommendations']}=={'street art','hawker centres'}
    assert discovery_queries({'interests':['Photography','Food']},[{'title':'Street art'}])==['hawker centres']
    assert discovery_queries({'interests':['Photography','Food']},[{'title':'Street art hawker food'}])==['tourist attractions']
    assert discovery_queries({'interests':['Photography','Food'],'excludedInterests':['Food']},[])==['street art']
    assert discovery_queries({'interests':['Photography','Food'],'destinationFeedback':{'no':'not_for_me'}},
                             [{'destinationId':'no','title':'Street art'}])==['street art','hawker centres']
    assert all('tags' not in row for row in repository.read('destination_cache'))


BROCHURE=['Standard admission ticket to Penang Bird Park.',
          'Guided sightseeing experience at Butterworth Art Walk.','English-speaking tour escort.']


@pytest.mark.parametrize('exclusion', ['Optional bird-feeding activities (paid separately).',
    'Additional admission tickets and services not specifically mentioned in inclusions.',
    'Any admissions or services not listed in the package inclusions.',
    'Optional extra attraction tickets.', 'Additional paid activities not included.',
    'Additional admission tickets not included.'])
def test_optional_extras_do_not_negate_standard_admission_or_guided_service(exclusion):
    draft=package(inclusions=BROCHURE,exclusions=[exclusion],guideActivitiesIncluded=True,
                  accommodationIncluded=False,transportIncluded=False)
    original=deepcopy(draft)
    assert package_submission_error(draft) is None
    requirement=derive_required_services(draft,review_optional_extras=True)
    assert requirement['guideActivities']['required'] and not requirement['guideActivities']['uncertain']
    assert not requirement['accommodation']['required'] and not requirement['transport']['required']
    assert draft==original


@pytest.mark.parametrize('exclusion', ['Admission tickets are not included.',
    'Standard admission ticket to Penang Bird Park is paid separately.',
    'Optional admission to Penang Bird Park is not included.',
    'No guide or tour escort is included.'])
def test_real_inclusion_contradictions_still_block_submission(exclusion):
    draft=package(inclusions=BROCHURE,exclusions=[exclusion],guideActivitiesIncluded=True)
    assert 'guideActivitiesIncluded' in package_submission_error(draft)


def test_historical_supplier_interpretation_remains_unchanged_and_new_snapshot_version_is_explicit():
    old={'inclusions':BROCHURE,'exclusions':['Optional extra admission tickets.'],'guideActivitiesIncluded':True}
    original=deepcopy(old)
    assert derive_required_services(old)['guideActivities']['uncertain']
    draft=package(approvalStatus='approved',inclusions=BROCHURE,exclusions=old['exclusions'],guideActivitiesIncluded=True)
    snapshot=prepare_package_snapshot(draft,{'id':'test_operator_uid'})
    assert snapshot['supplierRequirementVersion']==2
    assert derive_required_services(snapshot)['guideActivities']['required']
    assert old==original


def test_owner_reviewed_photography_food_metrics_and_frozen_scores():
    from scripts.discovery_relevance_audit import evaluate
    result=evaluate()
    assert result['candidateCount']==17 and result['scoresUnchanged']
    assert result['afterDiscoveryMetrics']['precision@5']==1
    assert result['afterDiscoveryMetrics']['precision@10']==1
    assert result['afterDiscoveryMetrics']['interestCoverage@5']==1
    assert result['humanRelevantCount']==15 and result['relevantShownCount']==10
    assert len(result['missingHumanRelevantIds'])==5 and not result['invalidRecommendationIds']
    assert not result['oldHybrid80Ids'] and len(result['oldPersonal45Ids'])==10
    types={row['destinationId']:row['foodExperienceType'] for row in result['afterDiscovery']}
    assert types['demo_penang_wonderfood']=='food_museum'
    assert types['demo_penang_spice']=='culinary_culture'
    assert types['demo_penang_gurney_food']==types['demo_penang_chulia_curry_mee']=='dining'


@pytest.mark.parametrize('choice',[False,True])
@pytest.mark.parametrize('editing',[False,True])
def test_actual_operator_routes_preserve_submitted_boolean_and_submit_contract(client,mock_operator_auth,choice,editing,repository):
    from modules.fr12_tourism_operator_management import routes as operator
    draft=package(inclusions=BROCHURE,exclusions=['Optional extra admission tickets, paid separately.'],
                  accommodationIncluded=False,transportIncluded=False,guideActivitiesIncluded=choice)
    with patch.object(operator,'retrieveRecord',side_effect=repository.read),patch.object(operator,'storeRecord',side_effect=repository.store),patch.object(operator,'updateRecord',side_effect=repository.update):
        if editing:
            repository.store('tourism_packages',{**draft,'guideActivitiesIncluded':not choice},'butterworth')
            result=client.put('/api/fr12/packages/butterworth',headers=AUTH,json=draft)
            pid='butterworth'
        else:
            result=client.post('/api/fr12/packages',headers=AUTH,json=draft)
            pid=result.json.get('id')
        assert result.status_code==(200 if editing else 201),result.json
        saved=repository.read('tourism_packages',pid)
        assert saved['guideActivitiesIncluded'] is choice
        assert saved['inclusions']==BROCHURE
        submitted=client.post('/api/fr12/packages/'+pid+'/submit',headers=AUTH)
    assert submitted.status_code==(200 if choice else 400),submitted.json
    assert repository.read('tourism_packages',pid)['approvalStatus']==('pending' if choice else 'draft')


def test_public_health_advertises_only_the_recommendation_contract(client):
    response=client.get('/api/health')
    assert response.status_code==200
    assert response.json['recommendationContract']=='relevant_v1'
    assert not {'uid','projectId','credentials'} & response.json.keys()


@pytest.mark.parametrize('title,kind',[('Verified cooking school experience','cooking'),
    ('Verified cooking class','cooking'),('Food museum','food_museum'),
    ('Hawker centre','dining'),('Ordinary botanical garden',None)])
def test_food_offering_types_require_actual_metadata_not_human_labels(title,kind):
    candidate={'title':title,'destinationConcepts':sorted(candidate_concepts({'title':title}))}
    result=discovery_annotations(candidate,{'interests':['Food']})
    assert result['foodExperienceType']==kind
    assert result['discoveryEligible']==bool(kind)


def test_provider_failure_logs_only_correlation_and_type_and_preserves_real_cache(client,mock_traveller_auth,repository,monkeypatch,caplog):
    monkeypatch.setenv('SERPAPI_KEY','isolated-test-provider')
    with patch.object(routes,'_provider_destinations',side_effect=RuntimeError('private-provider-value')):
        result=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang','discoveryMode':'relevant_v1'})
    assert result.status_code==200 and result.json['recommendations'] and result.json['source']=='cache'
    assert 'recommendation_provider_unavailable' in caplog.text
    assert result.headers['X-Request-ID'] in caplog.text
    assert 'private-provider-value' not in caplog.text


def test_geographic_warning_does_not_log_stored_snapshot_identity(client,mock_traveller_auth,repository,caplog):
    repository.store('recommendation_snapshots',{'travellerId':UID,'recommendationGenerationId':'private-stored-identity',
        'requestedDestination':'Penang','recommendationResults':[{'destinationId':'public-place','address':'Kuala Lumpur, Malaysia'}]},'safe-id')
    result=client.get('/api/fr4/recommendations',headers=AUTH,query_string={'generationId':'safe-id'})
    assert result.status_code==200
    assert 'Response geographic guard' in caplog.text and 'private-stored-identity' not in caplog.text


def test_null_legacy_feedback_requires_review_without_mutation(client,mock_traveller_auth,repository):
    repository.store('learned_preference_profiles',{'feedbackByDestination':None},UID)
    result=client.post('/api/fr4/recommendations/generate',headers=AUTH,json={'destinationArea':'Penang','discoveryMode':'relevant_v1'})
    assert result.status_code==409 and result.json['code']=='recommendation_profile_review'
    assert repository.read('learned_preference_profiles',UID)['feedbackByDestination'] is None


@pytest.mark.parametrize('early_status',[403,429])
def test_early_global_response_keeps_status_and_safe_correlation(client,early_status):
    from flask import abort, jsonify
    @client.application.before_request
    def global_gate():
        if early_status==403:abort(403)
        return jsonify(ok=False,error='Rate limited.'),429
    response=client.get('/api/fr4/recommendations')
    assert response.status_code==early_status
    assert response.headers['X-Request-ID'] and response.is_json
