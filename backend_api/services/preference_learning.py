"""Explainable, bounded preference learning for recommendation feedback.

The questionnaire remains the source of the base profile. This module keeps a
separate adaptive layer that can be rebuilt from each destination's current
explicit feedback state. No opaque model training is involved.
"""

from copy import deepcopy
import hashlib
from uuid import uuid4

from services.recommendation_taxonomy import CONCEPT_TERMS, display_concepts
from utils import utc_now_iso


AFFINITY_MIN = -1.0
AFFINITY_MAX = 1.0
MORE_LIKE_THIS_STEP = 0.15
NOT_FOR_ME_STEP = -0.12
LEARNED_INTEREST_STRENGTH = 0.10
VALID_FEEDBACK_TYPES = {'more_like_this', 'not_for_me'}


def canonical_concepts(values):
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    allowed = set(CONCEPT_TERMS)
    return sorted({str(value or '').strip().lower()
                   for value in values
                   if str(value or '').strip().lower() in allowed})


def feedback_delta(feedback_type):
    if feedback_type == 'more_like_this':
        return MORE_LIKE_THIS_STEP
    if feedback_type == 'not_for_me':
        return NOT_FOR_ME_STEP
    raise ValueError('Unsupported recommendation feedback type')


def _bounded(value):
    return round(max(AFFINITY_MIN, min(AFFINITY_MAX, float(value))), 4)


def _rebuild_learning(feedback_by_destination):
    totals = {}
    evidence = {}
    for state in (feedback_by_destination or {}).values():
        feedback_type = str(state.get('feedbackType') or '')
        if feedback_type not in VALID_FEEDBACK_TYPES:
            continue
        delta = feedback_delta(feedback_type)
        for concept in canonical_concepts(state.get('destinationConcepts', [])):
            totals[concept] = totals.get(concept, 0.0) + delta
            bucket = evidence.setdefault(
                concept, {'positiveCount': 0, 'negativeCount': 0})
            key = ('positiveCount' if feedback_type == 'more_like_this'
                   else 'negativeCount')
            bucket[key] += 1
    affinities = {key: _bounded(value) for key, value in totals.items()
                  if abs(value) > 0.0001}
    return affinities, evidence


def empty_learning_profile(user_id, now=None):
    timestamp = now or utc_now_iso()
    return {
        'userId': user_id,
        'travellerId': user_id,
        'affinities': {},
        'evidence': {},
        'feedbackByDestination': {},
        'learnedPreferenceVersion': '',
        'createdAt': timestamp,
        'updatedAt': timestamp,
    }


def apply_explicit_feedback(profile, *, user_id, destination_id,
                            feedback_type, destination_concepts,
                            recommendation_generation_id='',
                            source_context='recommendation_card', now=None,
                            event_id=None):
    """Return updated profile, append-only event, and whether state changed."""
    if feedback_type not in VALID_FEEDBACK_TYPES:
        raise ValueError('Unsupported recommendation feedback type')
    destination_id = str(destination_id or '').strip()
    if not destination_id:
        raise ValueError('destinationId is required')
    concepts = canonical_concepts(destination_concepts)
    if not concepts:
        raise ValueError('At least one supported destination concept is required')

    timestamp = now or utc_now_iso()
    updated = deepcopy(profile or empty_learning_profile(user_id, timestamp))
    states = deepcopy(updated.get('feedbackByDestination') or {})
    previous = deepcopy(states.get(destination_id) or {})
    previous_type = str(previous.get('feedbackType') or '')
    previous_concepts = canonical_concepts(
        previous.get('destinationConcepts', []))
    if previous_type == feedback_type and previous_concepts == concepts:
        return updated, None, False

    new_event_id = event_id or uuid4().hex
    states[destination_id] = {
        'destinationId': destination_id,
        'feedbackType': feedback_type,
        'destinationConcepts': concepts,
        'recommendationGenerationId': str(
            recommendation_generation_id or ''),
        'sourceContext': str(source_context or 'recommendation_card'),
        'eventId': new_event_id,
        'updatedAt': timestamp,
    }
    affinities, evidence = _rebuild_learning(states)
    updated.update({
        'userId': user_id,
        'travellerId': user_id,
        'affinities': affinities,
        'evidence': evidence,
        'feedbackByDestination': states,
        'learnedPreferenceVersion': f'learned_{new_event_id}',
        'createdAt': updated.get('createdAt') or timestamp,
        'updatedAt': timestamp,
    })
    event = {
        'feedbackEventId': new_event_id,
        'userId': user_id,
        'travellerId': user_id,
        'destinationId': destination_id,
        'recommendationGenerationId': str(
            recommendation_generation_id or ''),
        'feedbackType': feedback_type,
        'previousFeedbackType': previous_type,
        'destinationConcepts': concepts,
        'sourceContext': str(source_context or 'recommendation_card'),
        'supersedesEventId': str(previous.get('eventId') or ''),
        'timestamp': timestamp,
    }
    return updated, event, True


def reset_learning_profile(profile, *, user_id, now=None, event_id=None):
    timestamp = now or utc_now_iso()
    reset_event_id = event_id or uuid4().hex
    current = profile or empty_learning_profile(user_id, timestamp)
    had_learning = bool(current.get('feedbackByDestination') or
                        current.get('affinities'))
    reset = {
        **empty_learning_profile(user_id, timestamp),
        'createdAt': current.get('createdAt') or timestamp,
        'learnedPreferenceVersion': f'learned_reset_{reset_event_id}',
        'resetAt': timestamp,
        'updatedAt': timestamp,
    }
    event = {
        'feedbackEventId': reset_event_id,
        'userId': user_id,
        'travellerId': user_id,
        'feedbackType': 'reset',
        'previousFeedbackCount': len(
            current.get('feedbackByDestination') or {}),
        'timestamp': timestamp,
        'sourceContext': 'profile_reset',
    }
    return reset, event, had_learning


def effective_preference_profile(base_profile, learned_profile):
    """Add the adaptive layer without mutating questionnaire answers."""
    effective = deepcopy(base_profile or {})
    effective['learnedAffinities'] = deepcopy(
        (learned_profile or {}).get('affinities') or {})
    effective['learnedEvidence'] = deepcopy(
        (learned_profile or {}).get('evidence') or {})
    return effective


def effective_profile_version(base_version, learned_profile):
    learned_version = str(
        (learned_profile or {}).get('learnedPreferenceVersion') or '')
    if not learned_version:
        return str(base_version)
    encoded = f'{base_version}|{learned_version}'.encode('utf-8')
    return f'effective_{hashlib.sha256(encoded).hexdigest()[:20]}'


def public_learning_state(profile):
    profile = profile or {}
    affinities = profile.get('affinities') or {}
    tendencies = []
    for concept, value in sorted(affinities.items()):
        number = float(value or 0)
        if abs(number) < 0.10:
            continue
        label = display_concepts([concept])[0]
        tendencies.append({
            'concept': concept,
            'label': label,
            'direction': 'up' if number > 0 else 'down',
        })
    current = {
        destination_id: state.get('feedbackType')
        for destination_id, state in
        (profile.get('feedbackByDestination') or {}).items()
        if state.get('feedbackType') in VALID_FEEDBACK_TYPES
    }
    return {
        'learnedPreferenceVersion': profile.get(
            'learnedPreferenceVersion', ''),
        'currentFeedback': current,
        'tendencies': tendencies,
        'hasLearnedPreferences': bool(current),
        'updatedAt': profile.get('updatedAt', ''),
    }
