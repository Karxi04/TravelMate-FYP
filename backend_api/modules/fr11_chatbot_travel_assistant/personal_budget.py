"""Read-only explanations of FR5 estimates, not a second pricing engine."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sequence_contract.domain_functions import calculateBudget, buildLowerCostAlternatives
from services.activity_pricing import activity_pricing


def money(value):
    try:
        amount = Decimal(str(value))
        if not isinstance(value, bool) and amount.is_finite() and amount >= 0:
            return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def count(trip):
    value = trip.get('travellerCount', trip.get('numberOfTravellers'))
    try:
        amount = Decimal(str(value))
        return int(amount) if not isinstance(value, bool) and amount.is_finite() and 1 <= amount <= 100 and amount == int(amount) else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def duration(trip):
    try:
        days = (date.fromisoformat(trip['endDate']) - date.fromisoformat(trip['startDate'])).days + 1
        return days if 1 <= days <= 366 else None
    except (ValueError, KeyError, TypeError):
        days = trip.get('tripDays')
        return days if type(days) is int and 1 <= days <= 14 else None


def amount_text(value):
    return f'MYR {value:.2f}' if value is not None else 'unavailable'


def _allocation(value, days):
    cents = int(money(value) * 100)
    base, rest = divmod(cents, days)
    return [Decimal(base + (i < rest)) / 100 for i in range(days)]


def explain_budget(trip):
    """Use fresh owned input; never trust/write the budgetEstimate cache."""
    party, days = count(trip), duration(trip)
    if party is None or days is None:
        return {'available': False, 'reply': 'The saved traveller count or trip duration is unavailable. '
                'Open Trip Budget to review those details; I have not assumed one traveller or invented a total.'}
    source = deepcopy(trip)
    source['travellerCount'] = party
    if not isinstance(source.get('activities'), list) or not source['activities']:
        source['activities'] = [{**a, 'dayNo': row.get('dayNo', row.get('dayNumber'))}
            for row in source.get('dailySchedule', []) if isinstance(row, dict)
            for a in row.get('activities', []) if isinstance(a, dict)]
    estimate = calculateBudget(source)
    categories = []
    for key, item in estimate['expenseBreakdown'].items():
        state = item['state']
        unavailable = state in {'undecided', 'selected_unpriced', 'excluded_outside_scope', 'unit_unknown', 'unverified_estimate'}
        classification = ('unavailable' if unavailable else 'not_required' if state == 'not_required'
                          else 'known_quote' if key in {'hotel', 'flight'} and state == 'priced' else 'estimated')
        categories.append({'category': key, 'classification': classification,
                           'amount': None if unavailable else item['amount'],
                           'recordedModelAmount': item['amount'], 'source': item['provenance']})
    rows = [{'day': i + 1, 'activitySubtotal': Decimal(0), 'unknownActivities': 0} for i in range(days)]
    unassigned = Decimal(0)
    for activity in source['activities']:
        pricing = activity_pricing(activity, party)
        value = money(pricing['effectiveCost']) or Decimal(0)
        try:
            day = int(activity.get('dayNo'))
        except (ValueError, TypeError):
            day = 0
        if not 1 <= day <= days:
            unassigned += value
            continue
        rows[day - 1]['activitySubtotal'] += value
        rows[day - 1]['unknownActivities'] += bool(pricing['pricingIssues'])
    food, transport = [_allocation(estimate[key], days) for key in ('food', 'transport')]
    for index, row in enumerate(rows):
        row.update(foodAllocation=float(food[index]), transportAllocation=float(transport[index]),
                   modelledSubtotal=float(row['activitySubtotal'] + food[index] + transport[index]))
        row['activitySubtotal'] = float(row['activitySubtotal'])
    limit = money(trip.get('budgetLimit'))
    total = money(estimate['total'])
    lines = [f"{trip.get('title') or 'Saved trip'}: {party} travellers, {days} days.",
             f"Saved total group budget: {amount_text(limit)}. Modelled subtotal: {amount_text(total)}.",
             f"Modelled share per person: {amount_text((total / party).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))}; this is not a package per-person quote."]
    lines += [f"{row['category']}: {amount_text(money(row['amount']))} ({row['classification'].replace('_', ' ')}; {row['source']})." for row in categories]
    lines += ['Selected prices are not proof of payment or supplier confirmation. Food/local transport allowances are estimates. '
              'Missing costs are unavailable, not free.']
    if limit is not None:
        lines.append(f"Modelled subtotal exceeds the limit by {amount_text(total - limit)}." if total > limit else
                     'The modelled subtotal is below the limit; this does not establish affordability while costs are missing.'
                     if estimate['incomplete'] else f"Modelled balance: {amount_text(limit - total)}.")
    lines += estimate['estimateLimitations']
    return {'available': True, 'reply': '\n'.join(lines), 'currency': 'MYR', 'tripId': trip['id'],
            'travellerCount': party, 'days': days, 'budgetLimit': float(limit) if limit is not None else None,
            'modelledSubtotal': float(total), 'incomplete': estimate['incomplete'], 'categories': categories,
            'daily': rows, 'sharedTravelAndStay': round(estimate['flight'] + estimate['hotel'] + estimate['carRental'], 2),
            'unassignedActivitySubtotal': float(unassigned), 'dailyBasis': 'Activity prices by saved day; food and local transport allocated equally, remainder cents first. Flight/hotel/rental are shared, not charged again each day.',
            'advisoryAlternatives': buildLowerCostAlternatives(budgetEstimate=estimate, itinerary=source)}


def what_if(trip, *, budget=None, per_person=False, travellers=None):
    candidate = deepcopy(trip)
    party = travellers or count(trip)
    if party is None:
        return {'available': False, 'reply': 'The traveller count is unavailable, so I cannot convert a per-person amount to a group budget.'}
    candidate['travellerCount'] = party
    notes = []
    if budget is not None:
        candidate['budgetLimit'] = float(budget * party if per_person else budget)
        notes.append(f"Scenario budget is {amount_text(money(candidate['budgetLimit']))} for the group" +
                     (f' ({amount_text(budget)} per person × {party}).' if per_person else ', not per person.'))
    if travellers and travellers != count(trip):
        for kind in ('flight', 'hotel'):
            if candidate.get('selected' + kind.title()):
                candidate['selected' + kind.title()] = {**candidate['selected' + kind.title()], 'price': None, 'priceStatus': 'unknown'}
                for key in (f'{kind}Cost', 'hotelNightlyRate' if kind == 'hotel' else 'flightCost', 'nightlyRate' if kind == 'hotel' else 'flightCost'):
                    candidate.pop(key, None)
                notes.append(f'The selected {kind} must be requoted for the new party; no revised fare or availability is assumed.')
        if trip.get('foodCost') is not None:
            notes.append('The manually supplied group food allowance is held fixed, not automatically scaled for the changed party.')
    result = explain_budget(candidate)
    result['reply'] = 'What-if only; nothing was saved.\n' + '\n'.join(notes) + '\n' + result['reply']
    result['scenario'] = True
    return result


def cheaper_activity_previews(trip, candidates):
    """Reuse FR5's pure price, geography and schedule validation; never apply its patch."""
    from modules.fr05_smart_itinerary_budget_planner.routes import _resolve_activity_alternative, _activity_identity
    from services.pricing_registry import enrich_candidate_pricing
    from services.malaysian_locality import filter_candidates, normalize_destination_scope
    scoped, _ = filter_candidates(candidates, normalize_destination_scope(trip.get('destinationArea')))
    pool = {}
    for candidate in scoped[:150]:
        enriched = enrich_candidate_pricing(candidate)
        if (enriched.get('pricingEvidence') or {}).get('applicability') == 'applicable':
            pool.setdefault(_activity_identity(enriched), enriched)
    results, attempts = [], 0
    for activity in (trip.get('activities') or [])[:30]:
        for identity in pool:
            if attempts >= 96 or len(results) >= 5:
                return sorted(results, key=lambda r: -r['estimatedSavings'])
            attempts += 1
            try:
                replacement, _, savings = _resolve_activity_alternative(
                    deepcopy(trip), {'activityId': activity.get('activityId'), 'destinationId': identity}, pool)
            except (ValueError, TypeError, KeyError, OverflowError):
                continue
            results.append({'original': activity.get('activityName') or 'Saved activity',
                            'replacement': replacement['activityName'], 'estimatedSavings': savings,
                            'day': replacement.get('dayNo'), 'basis': 'Comparable recorded MYR admission; existing FR5 schedule/location checks passed.',
                            'applied': False})
    return sorted(results, key=lambda r: -r['estimatedSavings'])
