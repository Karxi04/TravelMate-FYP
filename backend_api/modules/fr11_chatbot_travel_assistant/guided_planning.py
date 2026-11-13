"""Progressive questions for activity discovery and save-ready itineraries."""
import re
from datetime import date, timedelta
from .nlp_extractor import classify_user_intent, classify_detailed_intent, extract_interests
from .travel_dates import malaysian_today

QUESTIONS = {
    'destinationArea': ("Sure! Where in Malaysia would you like to explore?", []),
    'tripDays': ("How much time do you have, or do you already know your travel dates?",
                 ['Half day', 'One day', 'Two days', 'Three days', 'Not sure']),
    'startDate': ("What dates should I use for a day-by-day itinerary? You can also keep these as activity ideas.",
                  ['Just ideas']),
    'budgetLimit': ("Do you have a total trip budget in MYR? You can skip this for a planning estimate.", ['Skip']),
    'travellerCount': ("How many people are travelling? You can skip this and preview for one traveller.", ['Skip']),
    'interests': ("What would you enjoy most? You can choose a few interests or ask for a mix.",
                  ['Food', 'Culture', 'Nature', 'Food and culture', 'No preference']),
}


def guided_requirements(message, state, preferences, dates_supplied=False):
    detailed = classify_detailed_intent(message, state)
    intent = classify_user_intent(message, state)
    if detailed in {'WEATHER_ENQUIRY', 'HOTEL_ENQUIRY', 'FLIGHT_ENQUIRY', 'CAR_RENTAL_ENQUIRY',
                    'BUDGET_ENQUIRY', 'FEATURE_EXPLANATION', 'FOREIGN_UNSUPPORTED'}:
        return None
    if state.get('tripMode') == 'road_trip':
        return None

    answer = re.sub(r'[.!?]+$', '', message.strip().lower())
    no_preference = answer in {'no preference', 'anything', 'any activities'}
    pending = state.get('guidedQuestion')
    goal = state.get('planningGoal')
    start_itinerary = re.fullmatch(r'(?:please )?plan (?:a|my) trip', answer)
    upgrade = bool(re.search(r'\b(?:make|turn|convert) (?:this|it|these) into (?:a |an )?(?:complete |full |dated )?(?:trip|itinerary)\b', answer))
    if (start_itinerary and not state.get('destinationArea')) or upgrade:
        state['guidedItinerary'] = True
    if detailed == 'ACTIVITY_DISCOVERY' and not (
            goal == 'itinerary' and state.get('guidedActive')
            and not re.search(r'\b(?:just|only|instead|things to do|activity ideas)\b', answer)):
        goal = 'activities'
    elif (start_itinerary or upgrade or detailed == 'ITINERARY_PLANNING'
          or (dates_supplied and goal != 'activities')
          or (answer == 'regenerate itinerary' and state.get('activePlan'))):
        goal = 'itinerary'
    elif not goal and (state.get('guidedActive') or intent == 'PLANNING_REQUEST'
                       or (state.get('destinationArea') and re.search(r'\b(?:travel|trip|plan)\b', answer))):
        goal = 'itinerary'
    elif not goal and detailed == 'DESTINATION_ENQUIRY' and state.get('destinationArea'):
        goal = 'activities'
    elif not goal:
        return None
    elif not (pending or intent in {'PLANNING_REQUEST', 'PROVISIONAL_EXPLORATION'} or dates_supplied
              or state.get('guidedActive') or no_preference or extract_interests(message)
              or (goal == 'itinerary' and re.search(r'\b(?:change|switch|move) (?:it |the trip )?to\b|\bless crowded\b', answer))
              or re.search(r'\b(?:relaxed|moderate|busy|slower|faster|pace)\b', answer)):
        return None

    state['planningGoal'] = goal
    state['guidedActive'] = True
    if isinstance(preferences, dict):
        for key in ('interests', 'travelPace', 'travelPersonality'):
            if key not in state and preferences.get(key):
                state[key] = preferences[key]

    if re.fullmatch(r'\d+(?:\.\d{1,2})?', answer):
        number = float(answer)
        if pending == 'budgetLimit' and 0 < number <= 1_000_000:
            state[pending] = number
        elif pending in {'tripDays', 'travellerCount'} and number.is_integer() and 1 <= number <= (14 if pending == 'tripDays' else 20):
            state[pending] = int(number)
            if pending == 'tripDays' and state.get('startDate') and not state.get('endDate'):
                start = date.fromisoformat(state['startDate'])
                state['endDate'] = (start + timedelta(days=int(number) - 1)).isoformat()
    skip = answer in {'skip', 'not sure', 'no preference', 'anything', 'any activities', 'just ideas', 'general ideas'}
    if pending == 'tripDays' and skip:
        state['activityWindow'] = 'flexible'
        state['planningGoal'] = goal = 'activities'
    if pending == 'startDate' and skip:
        state['planningGoal'] = goal = 'activities'
    if answer in {'a mix', 'mix', 'a bit of everything'}:
        state['interests'] = ['Food', 'Culture', 'Nature']
        state['interestsConfirmed'] = True
    elif (pending == 'interests' and skip) or (goal == 'activities' and no_preference):
        state['interests'] = []
        state['interestsConfirmed'] = True
    if pending in {'budgetLimit', 'travellerCount'} and skip:
        state[pending + 'Skipped'] = True
    if re.search(r'\b(?:moderate|balanced)\b', answer):
        state['travelPace'] = 'moderate'
    if re.search(r'\b(?:busy|active|faster)\b', answer):
        state['travelPace'] = 'active'

    def ask(key, *, preview=False):
        prompt, replies = QUESTIONS[key]
        state['guidedQuestion'] = key
        return {'clarification_needed': True, 'ready': False, 'missing': [key],
                'clarification_prompt': prompt, 'suggestedReplies': replies, 'preview': preview}

    if not state.get('destinationArea'):
        return ask('destinationArea')
    if goal == 'itinerary' and state.get('guidedItinerary') and not state.get('startDate'):
        return ask('startDate')
    if not any(state.get(key) for key in ('tripDays', 'activityWindow')):
        return ask('tripDays')
    if goal == 'activities':
        if not (state.get('interests') or state.get('interestsConfirmed') or state.get('excludedInterests')
                or state.get('excludedActivityTypes') or state.get('preferIndoor')):
            return ask('interests')
        state.pop('guidedQuestion', None)
        state['guidedActive'] = False
        return {'activities': True, 'ready': False}
    if not (state.get('startDate') and state.get('endDate')):
        return ask('startDate', preview=True)
    try:
        if date.fromisoformat(str(state['startDate'])[:10]) < malaysian_today():
            raise ValueError
    except ValueError:
        state.pop('startDate', None)
        state.pop('endDate', None)
        result = ask('startDate', preview=True)
        result['clarification_prompt'] = 'Please choose a future start and end date for your itinerary.'
        return result
    required = ('travellerCount', 'budgetLimit') if state.get('guidedItinerary') else ('budgetLimit', 'travellerCount')
    for key in required:
        if not (state.get(key) or state.get(key + 'Skipped')):
            return ask(key)
    if state.get('guidedItinerary') and not (
            state.get('interests') or state.get('interestsConfirmed') or state.get('excludedInterests')):
        return ask('interests')
    state.pop('guidedQuestion', None)
    state['guidedActive'] = False
    return {'clarification_needed': False, 'ready': True, 'missing': []}
