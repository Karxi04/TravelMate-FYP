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


PHONE_RE = re.compile(r"^\+?[0-9\s\-()]{7,25}$")
VALID_GENDERS = {'Prefer not to say', 'Female', 'Male', 'Other', ''}


def getUpdatedProfileValidationError(data):
    if not isinstance(data, dict):
        return 'Payload must be a JSON object.'

    # Name validation: must contain letters, not only numbers/symbols, 2-100 chars
    if 'name' in data:
        val = data['name']
        if not isinstance(val, str):
            return 'Name must be a string.'
        s = val.strip()
        if not s or len(s) < 2 or len(s) > 100:
            return 'Invalid name. Must contain letters and be between 2 and 100 characters.'
        if not any(c.isalpha() for c in s):
            return 'Name cannot consist only of digits or symbols.'
        if not all(c.isalnum() or c.isspace() or c in "'-." for c in s):
            return 'Name contains invalid characters.'

    # Phone validation
    if 'phoneNo' in data:
        val = data['phoneNo']
        if val is not None and str(val).strip():
            if not isinstance(val, str) or not PHONE_RE.match(val.strip()):
                return 'Invalid phone number format.'

    # Date of Birth validation
    if 'dateOfBirth' in data:
        val = data['dateOfBirth']
        if val is not None and str(val).strip():
            if not isinstance(val, str):
                return 'Date of birth must be a string.'
            try:
                dt = datetime.strptime(val.strip(), "%Y-%m-%d").date()
            except Exception:
                return 'Invalid date of birth. Must be a valid date in YYYY-MM-DD format.'
            if dt > date.today():
                return 'Date of birth cannot be in the future.'
            if dt < date(1900, 1, 1):
                return 'Date of birth is out of range.'

    # Nationality validation
    if 'nationality' in data:
        val = data['nationality']
        if val is not None and not isinstance(val, str):
            return 'Nationality must be a string.'
        if isinstance(val, str) and len(val) > 100:
            return 'Nationality must not exceed 100 characters.'

    # Current City validation
    if 'currentCity' in data:
        val = data['currentCity']
        if val is not None and not isinstance(val, str):
            return 'Current city must be a string.'
        if isinstance(val, str) and len(val) > 100:
            return 'Current city must not exceed 100 characters.'

    # Gender validation
    if 'gender' in data:
        val = data['gender']
        if val is not None and str(val).strip():
            if str(val).strip() not in VALID_GENDERS:
                return 'Invalid gender option.'

    # Emergency Contact validation
    e_name = str(data.get('emergencyContactName', '') or '').strip()
    e_phone = str(data.get('emergencyContact', '') or '').strip()
    e_rel = str(data.get('emergencyRelationship', '') or '').strip()

    if 'emergencyContactName' in data or 'emergencyContact' in data:
        if e_name and not e_phone:
            return 'Emergency contact phone is required when contact name is provided.'
        if e_phone and not e_name:
            return 'Emergency contact name is required when contact phone is provided.'
        if e_phone and not PHONE_RE.match(e_phone):
            return 'Invalid emergency contact phone number.'
        if len(e_name) > 100:
            return 'Emergency contact name must not exceed 100 characters.'
        if len(e_rel) > 50:
            return 'Emergency relationship must not exceed 50 characters.'

    # Travel Bio validation
    if 'travelBio' in data:
        val = data['travelBio']
        if val is not None and not isinstance(val, str):
            return 'Travel bio must be a string.'
        if isinstance(val, str) and len(val) > 2000:
            return 'Travel bio exceeds maximum allowed length of 2000 characters.'

    return None


def validateUpdatedProfile(data):
    return getUpdatedProfileValidationError(data) is None


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


def flightSearchValidationError(data):
    from services.flight_airports import MALAYSIAN_AIRPORTS
    departure = str(data.get('departure_id', '')).strip().upper()
    arrival = str(data.get('arrival_id', '')).strip().upper()
    for label, code in [('origin', departure), ('destination', arrival)]:
        if not code:
            return f'Choose an {label} airport.' if label == 'origin' else 'Choose a destination airport.'
        if code not in MALAYSIAN_AIRPORTS:
            return f'Choose a supported Malaysian {label} airport from the location list.'
    if departure == arrival:
        return 'Origin and destination airports must be different.'
    outbound = _parse_iso_date(data.get('outbound_date'))
    if not outbound or outbound < date.today():
        return 'Choose a current or future departure date.'
    return_date = data.get('return_date')
    if return_date:
        inbound = _parse_iso_date(return_date)
        if not inbound or inbound < outbound:
            return 'Return date must be valid and on or after departure.'
    return None


def validateFlightSearchCriteria(data):
    return flightSearchValidationError(data) is None


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
