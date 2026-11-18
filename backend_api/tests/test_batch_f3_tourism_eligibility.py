from copy import deepcopy

import pytest

from modules.fr04_hybrid_recommendation.routes import _page
from modules.fr05_smart_itinerary_budget_planner.routes import _filter_destination_candidates
from modules.fr11_chatbot_travel_assistant.nlp_extractor import find_matching_catalog_destinations
from services.malaysian_locality import normalize_destination_scope
from services.recommendation_discovery import is_planning_candidate


@pytest.mark.parametrize('state,locality,office,category,attraction,visitor_type', [
    ('Penang', 'George Town', 'Pejabat Imigresen', 'Government office', 'Penang State Museum', 'Museum'),
    ('Kuala Lumpur', 'Kuala Lumpur', 'Local administration', 'local_government_office',
     'Royal Malaysia Police Museum', 'Museum'),
    ('Johor', 'Johor Bahru', 'Mahkamah Johor Bahru', 'Courthouse', 'City heritage gallery', 'Gallery'),
    ('Kedah', 'Alor Setar', 'Pejabat Daerah', 'Municipal office', 'State public garden', 'Public garden'),
    ('Sabah', 'Kota Kinabalu', 'Balai Polis', 'Tourist attraction', 'State museum', 'Museum'),
    ('Sarawak', 'Kuching', 'Public counter', 'Urban Transformation Centre', 'Cultural centre', 'Cultural centre'),
])
def test_administrative_facilities_are_excluded_from_tourist_paths(
        state, locality, office, category, attraction, visitor_type):
    scope = normalize_destination_scope(state)
    base = {'address': f'{locality}, {state}, Malaysia', 'state': state, 'city': locality, 'score': 90}
    bad = {**base, 'destinationId': 'office', 'title': office, 'type': category}
    good = {**base, 'destinationId': 'visitor', 'title': attraction, 'type': visitor_type,
            'types': [visitor_type, 'government office']}
    snapshot = {'requestedDestination': state, 'canonicalDestinationScope': scope,
                'recommendationResults': [bad, good]}
    original = deepcopy(snapshot)
    assert not is_planning_candidate(bad)
    assert is_planning_candidate(good)
    assert [row['destinationId'] for row in _page(snapshot, {})['recommendationResults']] == ['visitor']
    assert [row['destinationId'] for row in _filter_destination_candidates([bad, good], state)] == ['visitor']
    assert find_matching_catalog_destinations(locality, state, [bad, good]) == [good]
    assert snapshot == original


def test_government_ownership_alone_is_not_exclusion_and_generic_secondary_tags_do_not_override():
    assert is_planning_candidate({'title': 'State Government Gardens', 'type': 'Public garden'})
    assert is_planning_candidate({'title': 'Former Courthouse', 'type': 'Historical landmark'})
    assert not is_planning_candidate({'title': 'Immigration Office', 'type': 'Government office',
                                      'types': ['Tourist attraction', 'Museum']})
    assert not is_planning_candidate({'title': 'Kuala Lumpur branch', 'class': 'office', 'type': 'government'})
