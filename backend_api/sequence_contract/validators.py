import re
from math import isfinite
from datetime import date, datetime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AIRPORT_RE = re.compile(r"^[A-Z]{3}$")
TRAVEL_MODES = {'flight', 'own_vehicle', 'public_transport', 'other', 'undecided'}
ACCOMMODATION_CHOICES = {'paid_hotel', 'staying_with_family', 'return_home', 'other', 'undecided'}
CAR_RENTAL_CHOICES = {'selected', 'not_required', 'undecided'}


def _parse_iso_date(value):
    try:
        return datetime.strptime(str(value or '').strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _non_negative_number(value):
    try:
        return float(value or 0) >= 0
    except Exception:
        return False


def _positive_int(value, default=1):
    try:
        return int(value or default) > 0
    except Exception:
        return False


def validateRequiredInformation(data, requiredFields=None):
    fields = requiredFields or ["name", "email", "password"]
    return all(str(data.get(field, "")).strip() for field in fields)


def validateEmailFormat(email):
    return bool(EMAIL_RE.match(str(email or '').strip()))


def validatePasswordRequirement(password):
    return len(str(password or '')) >= 6


def validateLoginInput(email, password):
    return validateEmailFormat(email) and bool(str(password or '').strip())


def validateEmailAddress(email):
    return validateEmailFormat(email)


def validateUpdatedProfile(data):
    if 'name' in data and not str(data.get('name', '')).strip():
        return False
    return True


def validateAccountAction(data):
    role_ok = 'role' not in data or data.get('role') in {'traveller','operator','admin'}
    status_ok = 'status' not in data or data.get('status') in {'active','deactivated'}
    verification_ok = (
        'verificationStatus' not in data
        or data.get('verificationStatus') in {'pending','approved','verified','rejected'}
    )
    return (
        role_ok
        and status_ok
        and verification_ok
        and bool(set(data) & {'role','status','verificationStatus'})
    )


def validatePreferenceAnswers(data):
    required = ['travelPersonality','travelType','interests','budgetRange','travelPace','travelPurpose']
    return all(data.get(x) for x in required) and bool(data.get('interests'))


def validateUpdatedPreferences(data):
    return validatePreferenceAnswers(data)


def validateSearchInput(searchInput):
    return bool(str(searchInput or '').strip())


def validateFilterOption(filterOption):
    return filterOption is None or isinstance(filterOption, (str, dict))


def validateSortingOption(sortOption):
    return sortOption in {None, '', 'rating', 'name', 'match', 'price_low', 'price_high'}


def validateSelectedDestination(destination):
    if isinstance(destination, dict):
        return bool(destination.get('destinationId') or destination.get('place_id') or destination.get('data_id'))
    return bool(str(destination or '').strip())


def validateItineraryInput(data):
    title_ok = bool(str(data.get('title', '')).strip())
    start = _parse_iso_date(data.get('startDate'))
    end = _parse_iso_date(data.get('endDate'))
    budget_ok = _non_negative_number(data.get('budgetLimit', 0))
    travellers_ok = _positive_int(data.get('travellerCount', 1))
    choices_ok = (
        data.get('travelMode', 'undecided') in TRAVEL_MODES
        and data.get('accommodationChoice', 'undecided') in ACCOMMODATION_CHOICES
        and data.get('carRentalChoice', 'undecided') in CAR_RENTAL_CHOICES
    )
    return title_ok and bool(start) and bool(end) and start <= end and budget_ok and travellers_ok and choices_ok


def validateItineraryForSaving(data):
    return bool(data) and bool(str(data.get('title','')).strip())


def validateDestinationInput(value):
    return bool(str(value or '').strip())


def validateFlightSearchCriteria(data):
    departure = str(data.get('departure_id', '')).strip().upper()
    arrival = str(data.get('arrival_id', '')).strip().upper()
    outbound = _parse_iso_date(data.get('outbound_date'))
    return_date = data.get('return_date')
    inbound = _parse_iso_date(return_date) if return_date else None
    if not (AIRPORT_RE.fullmatch(departure) and AIRPORT_RE.fullmatch(arrival) and outbound):
        return False
    if departure == arrival or outbound < date.today():
        return False
    return not inbound or inbound >= outbound


def validateSelectedFlight(flight):
    return isinstance(flight, dict) and bool(flight)


def validateHotelSearchCriteria(data):
    checkin = _parse_iso_date(data.get('checkin'))
    checkout = _parse_iso_date(data.get('checkout'))
    destination_ok = bool(data.get('destination') or data.get('aiSearch') or data.get('placeId') or data.get('hotelIds'))
    adults_ok = _positive_int(data.get('adults', 1))
    return bool(checkin and checkout and checkout > checkin and destination_ok and adults_ok)


def validateBookingDetails(data):
    return bool(data.get('prebookId') or data.get('validationId'))


def validatePaymentInput(data):
    try:
        return float(data.get('amount', 0) or 0) > 0
    except Exception:
        return False


def validateRatingAndComment(data):
    try:
        rating = int(data.get('rating', 0) or 0)
    except Exception:
        return False
    return bool(data.get('destinationId')) and 1 <= rating <= 5


def validateFeedback(data):
    if 'rating' in data:
        try:
            rating = int(data['rating'])
        except Exception:
            return False
        if not 1 <= rating <= 5:
            return False
    return True


def validateQuestion(question):
    return bool(str(question or '').strip())


def validatePackageData(data):
    from services.package_service import package_validation_error
    return package_validation_error(data) is None


def validatePackageCompleteness(data):
    from services.package_service import package_submission_error
    return package_submission_error(data) is None


def validateCampaignDatesAndContent(data):
    if not isinstance(data, dict) or not isinstance(data.get('campaignTitle'), str): return False
    if not 1 <= len(data['campaignTitle'].strip()) <= 200: return False
    start, end = data.get('startDate'), data.get('endDate')
    start_date = _parse_iso_date(start)
    end_date = _parse_iso_date(end)
    if not (start_date and end_date and start_date <= end_date): return False
    if 'discountType' in data or 'discountValue' in data:
        kind, value = data.get('discountType'), data.get('discountValue')
        if not isinstance(kind, str) or kind not in {'percentage', 'fixed'} or isinstance(value, bool): return False
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return False
        if not isfinite(amount) or amount < 0 or (kind == 'percentage' and amount > 100): return False
    return all(isinstance(data.get(key, ''), str) and len(data.get(key, '')) <= maximum
               for key, maximum in [('description', 5000), ('promoCode', 100), ('termsConditions', 5000)])


def validateReportCriteria(data):
    report_type = str(data.get('reportType', 'system_summary') or '').strip()
    if not report_type:
        return False
    start = data.get('startDate')
    end = data.get('endDate')
    if start or end:
        start_date = _parse_iso_date(start)
        end_date = _parse_iso_date(end)
        return bool(start_date and end_date and start_date <= end_date)
    return True


def validateAdminDestinationRecord(data):
    return bool(str(data.get('title') or data.get('destinationName') or '').strip())


def validateAdminActivityRecord(data):
    return bool(str(data.get('activityName') or data.get('title') or '').strip())


def validateCarRentalSearchCriteria(data):
    pickup = _parse_iso_date(data.get('pickupDate'))
    dropoff = _parse_iso_date(data.get('dropoffDate'))
    return bool(
        str(data.get('pickupLocation') or '').strip()
        and pickup
        and dropoff
        and dropoff >= pickup
        and _positive_int(data.get('driverCount', 1))
    )
