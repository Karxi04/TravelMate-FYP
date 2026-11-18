"""Frozen metadata judgements are separate from the production classification code."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sequence_contract import domain_functions as engine
from services.recommendation_discovery import is_planning_candidate, discovery_annotations
from services.recommendation_taxonomy import preference_concepts
from modules.fr05_smart_itinerary_budget_planner import routes as fr5

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/batch_h2_recommendation_quality.json').read_text())


def compare_profile(profile, budget_limit=None):
    raw = deepcopy(FIXTURE['candidates'])
    eligible = [row for row in raw if is_planning_candidate(row)]
    scored = engine.calculateRecommendationScore(engine.applyCollaborativeFiltering(
        engine.applyContentBasedFiltering(engine.prepareRecommendationInput(profile, eligible)), []))
    ranked = engine.diversifyRecommendations(engine.rankRecommendations(engine.deduplicateRecommendations(scored)),
                                             profile, limit=150, coverageAware=True)
    annotated = [{**row, **discovery_annotations(row, profile)} for row in ranked]
    selected = [row for row in annotated if row['discoveryEligible']]
    snapshot = {'recommendationGenerationId': 'h2-frozen', 'recommendationResults': selected,
                'planningPreferences': profile}
    original = deepcopy(snapshot)
    with patch.object(fr5, '_forecast_for', return_value=({}, None)):
        trip = deepcopy(FIXTURE['trip'])
        if budget_limit is not None:
            trip['budgetLimit'] = budget_limit
        plan = fr5._generate_itinerary_data(trip, {}, snapshot)
    assert snapshot == original
    concepts = preference_concepts(profile['interests'])
    relevant = set().union(*(set(FIXTURE['relevanceJudgements'].get(c, [])) for c in concepts))
    def precision(k, returned=False):
        prefix = selected[:k]
        return round(sum(row['destinationId'] in relevant for row in prefix) / (len(prefix) if returned else k), 4) if prefix else None
    return {
        'eligible': [row['destinationId'] for row in eligible],
        'relevantByInterest': {c: sorted(set(FIXTURE['relevanceJudgements'].get(c, [])) & {r['destinationId'] for r in eligible}) for c in sorted(concepts)},
        'ranking': [{'id': row['destinationId'], 'score': row['score'], 'content': row['contentScore'],
                     'collaborative': row['collaborativeScore'], 'popularity': row['popularityScore'],
                     'experienceTypes': row['experienceTypes'], 'matched': row['discoveryMatchedConcepts']}
                    for row in annotated],
        'selected': [row['destinationId'] for row in selected[:10]],
        'precisionAt5': precision(5), 'precisionAt10': precision(10),
        'returnedPrecisionAt5': precision(5, True), 'returnedPrecisionAt10': precision(10, True),
        'scheduled': [{'id': row['destinationId'], 'day': row['dayNo'],
                       'start': row.get('scheduledStartTime'), 'end': row.get('scheduledEndTime'),
                       'distanceKm': row.get('travelDistanceKm'), 'estimatedCost': row.get('estimatedCost')}
                      for row in plan['activities']],
        'deferred': [{'id': row.get('destinationId'), 'reason': row.get('unscheduledReason')}
                     for row in plan.get('unscheduledSuggestions', [])],
        'coverage': plan.get('interestCoverage'), 'budget': engine.calculateBudget(plan),
        'planningPreferences': plan.get('planningPreferences'),
    }


@pytest.mark.parametrize('name', FIXTURE['profiles'])
def test_frozen_profiles_use_relevant_places_and_preserve_planning_constraints(name):
    result = compare_profile(FIXTURE['profiles'][name])
    # Closed museum is an explicit conservative negative in the frozen judgements.
    # Discovery can show the venue; scheduling must defer it rather than assume it opens.
    relevant = set().union(*(set(ids) for ids in result['relevantByInterest'].values()))
    assert set(result['selected']) - relevant <= {'h2-closed'}
    assert result['returnedPrecisionAt5'] >= .75
    assert len(result['selected']) == len(set(result['selected']))
    assert all((row['distanceKm'] or 0) < 10 for row in result['scheduled'])
    assert result['budget']['totalEstimatedCost'] <= FIXTURE['trip']['budgetLimit']
    assert all(row['id'] != 'h2-closed' for row in result['scheduled'])
    assert result['planningPreferences'] == FIXTURE['profiles'][name]
    assert set(result['relevantByInterest']) == preference_concepts(FIXTURE['profiles'][name]['interests'])


def test_two_and_three_interest_schedules_explain_coverage_and_keep_the_formula():
    for name in ['Nature + Shopping', 'Three interests']:
        result = compare_profile(FIXTURE['profiles'][name])
        assert result['coverage']['unrepresented'] == []
        assert all(count > 0 for count in result['coverage']['scheduled'].values())
    result = compare_profile(FIXTURE['profiles']['Nature'])
    assert len({kind for row in result['ranking'][:5] for kind in row['experienceTypes']}) >= 3
    for row in result['ranking']:
        assert abs(row['score'] - round(.6*row['content']+.3*row['collaborative']+.1*row['popularity'], 2)) < .02


def test_fr11_uses_the_same_function_filter_as_fr5():
    from modules.fr11_chatbot_travel_assistant.nlp_extractor import filter_constraint_candidates
    invalid = next(row for row in FIXTURE['candidates'] if row['destinationId'] == 'h2-office')
    assert filter_constraint_candidates([invalid]) == []


def test_insufficient_group_budget_explains_missing_interests_without_forcing_free_stops():
    result = compare_profile(FIXTURE['profiles']['Nature + Shopping'], FIXTURE['budgetBoundary'])
    assert result['scheduled'] == []
    assert result['coverage']['unrepresented'] == ['nature', 'shopping']
    assert all('budget' in row['reason'].lower() for row in result['deferred'])


def test_synthetic_reviews_cannot_influence_collaborative_scores_or_hide_genuine_evidence():
    pref = {'interests': ['Nature']}
    candidates = [{'destinationId': 'garden'}]
    peer = {'peer': pref}
    real = {'travellerId': 'peer', 'destinationId': 'garden', 'rating': 2, 'updatedAt': '2030-01-01'}
    fake = {**real, 'rating': 5, 'synthetic': True, 'updatedAt': '2031-01-01'}
    def score(rows):
        return engine.applyCollaborativeFiltering(candidates, rows, peerPreferences=peer,
                                                  currentPreference=pref, currentTravellerId='viewer')
    assert score([fake]) == score([])
    assert score([fake, real]) == score([real])
    assert score([{**fake, 'synthetic': False, 'source': 'fyp_private'}]) == score([])
