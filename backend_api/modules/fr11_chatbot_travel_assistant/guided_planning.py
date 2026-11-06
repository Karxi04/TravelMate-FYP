"""Progressive requirements for the existing chat planner; no itinerary writes."""
import re
from datetime import date
from .nlp_extractor import classify_user_intent, classify_detailed_intent
from .travel_dates import malaysian_today

QUESTIONS = [
    ('destinationArea', 'Which Malaysian destination would you like to explore? For example Penang, Kuala Lumpur or Langkawi.'),
    ('tripDays', 'How many days would you like to travel, or what are your travel dates?'),
    ('startDate', 'What are your travel dates? For example 12 Dec to 16 Dec. I know the duration, but you have not chosen calendar dates yet.'),
    ('budgetLimit', 'What is your total trip budget in MYR?'),
    ('travellerCount', 'How many travellers are joining the trip?'),
    ('interests', 'Which activities interest you, such as food, culture, nature or shopping? You can also say no preference.'),
    ('travelPace', 'Would you prefer a relaxed, moderate or busy travel pace?'),
]


def guided_requirements(message, state, preferences, dates_supplied=False):
    planning = classify_user_intent(message, state) == 'PLANNING_REQUEST'
    if not planning and classify_detailed_intent(message, state) in {'WEATHER_ENQUIRY', 'HOTEL_ENQUIRY', 'FLIGHT_ENQUIRY', 'BUDGET_ENQUIRY', 'FEATURE_EXPLANATION'}:
        return None
    planning = planning or bool(state.get('guidedPlanning') and (
        (state.get('destinationArea') and re.search(r'\b(?:travel|trip|plan|itinerary)\b', message, re.I))
        or dates_supplied
    ))
    if not planning and not state.get('guidedActive'):
        return None
    if state.get('tripMode') == 'road_trip':
        return None
    state['guidedActive'] = True
    if state.get('dateClarification'):
        return {'clarification_needed': True, 'ready': False, 'missing': ['dates'], 'clarification_prompt': state['dateClarification']}
    preferences = preferences if isinstance(preferences, dict) else {}
    for key in ('interests', 'travelPace', 'travelPersonality'):
        if not state.get(key) and preferences.get(key):
            state[key] = preferences[key]
    answer = message.strip().lower()
    pending = state.get('guidedQuestion')
    if re.fullmatch(r'\d+(?:\.\d{1,2})?', answer):
        number = float(answer)
        if pending == 'budgetLimit' and number > 0:
            state[pending] = number
        elif pending in {'tripDays', 'travellerCount'} and number.is_integer() and 1 <= number <= (14 if pending == 'tripDays' else 20):
            state[pending] = int(number)
    if pending == 'interests' and re.search(r'no preference|anything|any activities', answer):
        state['interestsConfirmed'] = True
    for pace in ('relaxed', 'moderate', 'busy'):
        if re.search(r'\b' + pace + r'\b', answer):
            state['travelPace'] = pace
    if state.get('startDate'):
        try:
            if date.fromisoformat(str(state['startDate'])[:10]) < malaysian_today():
                state.pop('startDate', None); state.pop('endDate', None)
                state['guidedQuestion'] = 'tripDays'
                return {'clarification_needed': True, 'ready': False, 'missing': ['dates'],
                        'clarification_prompt': 'Those dates are in the past. What future dates or duration would you prefer?'}
        except ValueError:
            state.pop('startDate', None); state.pop('endDate', None)
    for key, question in QUESTIONS:
        present = state.get(key)
        if key == 'tripDays':
            present = present or state.get('startDate')
        if key == 'interests':
            present = present or state.get('interestsConfirmed')
        if not present:
            state['guidedQuestion'] = key
            return {'clarification_needed': True, 'ready': False, 'missing': [key], 'clarification_prompt': question}
    state.pop('guidedQuestion', None)
    state['guidedActive'] = False
    return {'clarification_needed': False, 'ready': True, 'missing': []}
