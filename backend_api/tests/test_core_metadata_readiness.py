from copy import deepcopy
from modules.fr11_chatbot_travel_assistant.nlp_extractor import build_structured_trip_plan, extract_interests, extract_excluded_interests, extract_excluded_activity_types


def test_fresh_chat_preserves_existing_hours_coordinates_and_specific_price():
    candidate={'destinationId':'provider_known','title':'Isolated museum fixture','category':'Culture',
        'address':'Penang, Malaysia','openingHours':'13:00-17:00',
        'gpsCoordinates':{'latitude':5.4,'longitude':100.3},'pricingUnit':'per_person','unitPrice':12,
        'costProvenance':'verified_ticket','costCategory':'admission','priceSourceUrl':'https://example.test/tariff',
        'priceVerifiedAt':'2026-11-08'}
    before=deepcopy(candidate)
    plan,status=build_structured_trip_plan('Penang',days=1,start_date='2027-06-12',end_date='2027-06-12',
        catalog=[candidate],preference_profile={'interests':['Culture'],'travelPace':'Relaxed'})
    assert status=='ready'
    activity=plan['activities'][0]
    assert activity['openingHours']=='13:00-17:00' and activity['gps_coordinates']==candidate['gpsCoordinates']
    assert activity['unitPrice']==12 and activity['priceVerifiedAt']=='2026-11-08'
    assert candidate==before


def test_existing_evidence_qualified_free_entry_used_only_for_matching_fresh_candidate():
    candidate={'destinationId':'local_botanical_gardens','title':'Penang Botanic Gardens','address':'Penang, Malaysia',
        'gps_coordinates':{'latitude':5.4377324,'longitude':100.2906982},'category':'Nature'}
    plan,_=build_structured_trip_plan('Penang',days=1,start_date='2027-06-12',end_date='2027-06-12',catalog=[candidate])
    activity=plan['activities'][0]
    assert activity['unitPrice']==0 and activity['costProvenance']=='verified_ticket'
    assert activity['priceSourceUrl'].startswith('https://botanicalgardens.penang.gov.my/')
    assert activity['priceVerifiedAt']=='2026-11-14' and activity['openingHours']=='06:30-19:00'
    assert activity['openingHoursSourceUrl']==activity['priceSourceUrl']
    assert 'unitPrice' not in candidate
    unknown={**candidate,'destinationId':'unknown','title':'Other park'}
    plan,_=build_structured_trip_plan('Penang',days=1,start_date='2027-06-12',end_date='2027-06-12',catalog=[unknown])
    assert plan['budgetEstimate']['incomplete']
    assert plan['activities'][0].get('costProvenance')!='verified_ticket'


def test_finite_nlp_common_likes_dislikes_family_and_narrow_exclusions():
    assert 'Family' in extract_interests('I like kid-friendly attractions and nature.')
    assert 'Nature' in extract_interests('I like kid-friendly attractions and nature.')
    assert 'Shopping' in extract_excluded_interests('I dislike shopping, but I enjoy heritage.')
    assert 'Museum' in extract_excluded_activity_types('I am not a fan of museums.')
    assert 'Culture' not in extract_excluded_interests('No museums, but I love heritage.')
    assert 'Culture' in extract_excluded_interests('I dislike heritage.')
