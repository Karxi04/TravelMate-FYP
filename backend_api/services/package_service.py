from datetime import date
from math import isfinite
from services.operator_hotel_service import safe_hotel_snapshot, safe_room_snapshot


PACKAGE_FIELDS = {
    'schemaVersion', 'title', 'packageTitle', 'shortDescription',
    'fullDescription', 'description', 'destination', 'destinationName',
    'destinationArea', 'category', 'heroImage', 'imageUrl', 'galleryImages',
    'durationDays', 'durationNights', 'currency', 'adultPrice', 'price',
    'childPrice', 'originalPrice', 'promotionalPrice', 'promotionStart',
    'promotionEnd', 'priceBasis', 'taxIncluded', 'taxNotes',
    'minimumTravellers', 'maximumTravellers', 'maxTravellers',
    'departureDates', 'departureLocation', 'meetingPoint', 'departureNotes',
    'itineraryDays', 'highlights', 'inclusions', 'exclusions',
    'accommodationName', 'accommodationCategory', 'roomType',
    'accommodationNotes', 'accommodationHotel', 'transportTypes', 'transportNotes',
    'accommodationRoom', 'accommodationIncluded', 'transportIncluded', 'guideActivitiesIncluded',
    'cancellationPolicy', 'refundPolicy', 'bookingTerms', 'importantNotes',
    'whatToBring', 'availabilityStatus',
    'validFrom', 'validUntil',
}

PACKAGE_AVAILABILITY_STATUSES = {'available', 'unavailable'}


def _text(value):
    return str(value or '').strip()


def _list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = str(value).replace('\r', '').split('\n')
        if len(values) == 1 and ',' in values[0]:
            values = values[0].split(',')
    return [str(item).strip() for item in values if str(item).strip()]


def _number(value):
    if value in (None, '') or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _integer(value):
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _boolean(value):
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {'1', 'true', 'yes', 'on'}


def _itinerary(value):
    if not isinstance(value, list):
        return []
    days = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        days.append({
            'dayNumber': index + 1,
            'title': _text(raw.get('title')),
            'description': _text(raw.get('description')),
            'activities': _list(raw.get('activities')),
            'meals': _list(raw.get('meals')),
            'accommodation': _text(raw.get('accommodation')),
            'transportNotes': _text(raw.get('transportNotes')),
        })
    return days


def normalise_package(payload, existing=None):
    raw = {**(existing or {}), **(payload or {})}
    package = {key: raw[key] for key in PACKAGE_FIELDS if key in raw}

    title = _text(raw.get('title') or raw.get('packageTitle'))
    destination = _text(raw.get('destination') or raw.get('destinationName'))
    description = _text(raw.get('fullDescription') or raw.get('description'))
    hero = _text(raw.get('heroImage') or raw.get('imageUrl'))
    adult_price = _number(raw.get('adultPrice') if 'adultPrice' in raw else raw.get('price'))
    maximum = _integer(raw.get('maximumTravellers') if 'maximumTravellers' in raw else raw.get('maxTravellers'))

    package.update({
        'title': title,
        'packageTitle': title,
        'destination': destination,
        'destinationName': destination,
        'fullDescription': description,
        'description': description,
        'heroImage': hero,
        'imageUrl': hero,
        'currency': _text(raw.get('currency') or 'MYR').upper(),
        'priceBasis': _text(raw.get('priceBasis') or 'per_person'),
        'taxIncluded': _boolean(raw.get('taxIncluded')),
        # New packages intentionally start available; approval remains a
        # separate administrator-controlled publication decision.
        'availabilityStatus': _text(raw.get('availabilityStatus') or 'available').lower(),
    })
    if adult_price is not None:
        package['adultPrice'] = adult_price
        package['price'] = adult_price
    if maximum is not None:
        package['maximumTravellers'] = maximum
        package['maxTravellers'] = maximum

    for field in ('durationDays', 'durationNights', 'minimumTravellers'):
        if field in raw:
            value = _integer(raw.get(field))
            if value is not None:
                package[field] = value
    for field in ('childPrice', 'originalPrice', 'promotionalPrice'):
        if field in raw:
            value = _number(raw.get(field))
            package[field] = value if value is not None else ''
    for field in (
        'galleryImages', 'departureDates', 'highlights', 'inclusions',
        'exclusions', 'transportTypes', 'whatToBring',
    ):
        if field in raw:
            package[field] = _list(raw.get(field))
    if 'itineraryDays' in raw:
        package['itineraryDays'] = _itinerary(raw.get('itineraryDays'))
    if 'schemaVersion' in raw:
        package['schemaVersion'] = _integer(raw.get('schemaVersion')) or 2
    if 'accommodationHotel' in raw:
        package['accommodationHotel'] = safe_hotel_snapshot(raw['accommodationHotel'])
    if 'accommodationRoom' in raw:
        hotel = package.get('accommodationHotel') or {}
        package['accommodationRoom'] = safe_room_snapshot(raw['accommodationRoom'], hotel.get('hotelId'))
    return package


def package_for_read(item):
    return {**item, **normalise_package(item)}


def package_update_changes_reviewed_content(existing, payload):
    """Return whether an operator update changes admin-reviewed content.

    Availability is an operator-controlled runtime switch. Changing only that
    switch must not force an otherwise approved package through review again.
    """
    before = normalise_package(existing)
    after = normalise_package(payload, existing)
    reviewed_fields = PACKAGE_FIELDS - {'availabilityStatus'}
    return any(before.get(field) != after.get(field) for field in reviewed_fields)


def _valid_date(value):
    try:
        date.fromisoformat(_text(value))
        return True
    except ValueError:
        return False


def package_validation_error(data):
    raw = data or {}
    for key in ('accommodationIncluded', 'transportIncluded', 'guideActivitiesIncluded'):
        if key in raw and not isinstance(raw[key], bool):
            return f'{key} must be true or false.'
    for key, maximum in [('title', 200), ('packageTitle', 200), ('destination', 500),
                         ('destinationName', 500), ('shortDescription', 1000),
                         ('fullDescription', 10000), ('description', 10000), ('currency', 3)]:
        if key in raw and (not isinstance(raw[key], str) or len(raw[key]) > maximum):
            return f'{key} must be text of at most {maximum} characters.'
    if 'itineraryDays' in raw:
        if not isinstance(raw['itineraryDays'], list) or any(
            not isinstance(day, dict) for day in raw['itineraryDays']
        ):
            return 'Itinerary days must be a structured list.'
        for day in raw['itineraryDays']:
            if not _text(day.get('title')) or not _text(day.get('description')):
                return 'Each itinerary day needs a title and description.'
            if 'activities' in day and not isinstance(day['activities'], list):
                return 'Itinerary activities must be a list.'
            if 'meals' in day and not isinstance(day['meals'], list):
                return 'Itinerary meals must be a list.'

    package = normalise_package(raw)
    if 'availabilityStatus' in raw and package.get('availabilityStatus') not in PACKAGE_AVAILABILITY_STATUSES:
        return 'Availability status must be available or unavailable.'
    if not package.get('title'):
        return 'Package title is required.'
    if not package.get('destination'):
        return 'Destination is required.'
    days = _integer(raw.get('durationDays', package.get('durationDays')))
    if days is None or days < 1:
        return 'Duration must be at least one day.'
    nights = _integer(raw.get('durationNights')) if 'durationNights' in raw else None
    if 'durationNights' in raw and (nights is None or nights < 0):
        return 'Nights cannot be negative.'
    adult = _number(raw.get('adultPrice') if 'adultPrice' in raw else raw.get('price'))
    if adult is None or adult < 0:
        return 'Adult price must be zero or greater.'
    currency = package.get('currency', '')
    if len(currency) != 3 or not currency.isalpha():
        return 'Currency must use a three-letter code such as MYR.'
    if package.get('priceBasis') not in {'per_person', 'per_group'}:
        return 'Price basis must be per person or per group.'

    for field, label in (
        ('childPrice', 'Child price'), ('originalPrice', 'Original price'),
        ('promotionalPrice', 'Promotional price'),
    ):
        if raw.get(field) not in (None, ''):
            value = _number(raw.get(field))
            if value is None or value < 0:
                return f'{label} must be zero or greater.'
    original = _number(raw.get('originalPrice'))
    promotional = _number(raw.get('promotionalPrice'))
    if original is not None and promotional is not None and promotional > original:
        return 'Promotional price cannot exceed the original price.'

    minimum = _integer(raw.get('minimumTravellers')) if raw.get('minimumTravellers') not in (None, '') else None
    maximum_raw = raw.get('maximumTravellers') if 'maximumTravellers' in raw else raw.get('maxTravellers')
    maximum = _integer(maximum_raw) if maximum_raw not in (None, '') else None
    if raw.get('minimumTravellers') not in (None, '') and minimum is None:
        return 'Minimum travellers must be a whole number.'
    if maximum_raw not in (None, '') and maximum is None:
        return 'Maximum travellers must be a whole number.'
    if minimum is not None and minimum < 1:
        return 'Minimum travellers must be at least one.'
    if maximum is not None and maximum < 1:
        return 'Maximum travellers must be at least one.'
    if minimum is not None and maximum is not None and minimum > maximum:
        return 'Minimum travellers cannot exceed maximum travellers.'

    departure_dates = raw.get('departureDates')
    if departure_dates is not None:
        if not isinstance(departure_dates, list) or any(not _valid_date(value) for value in departure_dates):
            return 'Departure dates must be valid dates.'
    for field in ('promotionStart', 'promotionEnd'):
        if raw.get(field) and not _valid_date(raw[field]):
            return 'Promotion dates must be valid dates.'
    if raw.get('promotionStart') and raw.get('promotionEnd') and raw['promotionStart'] > raw['promotionEnd']:
        return 'Promotion start date cannot be after its end date.'
    for field in ('validFrom', 'validUntil'):
        if raw.get(field) and not _valid_date(raw[field]):
            return 'Package validity dates must be valid dates.'
    if raw.get('validFrom') and raw.get('validUntil') and raw['validFrom'] > raw['validUntil']:
        return 'Package start date cannot be after its end date.'
    return None


def package_submission_error(data):
    error = package_validation_error(data)
    if error:
        return error
    package = normalise_package(data)
    if not package.get('fullDescription'):
        return 'A full package description is required before submission.'
    if package.get('schemaVersion') == 2 and not package.get('itineraryDays'):
        return 'Add at least one itinerary day before submission.'
    if package.get('accommodationIncluded') is True:
        if not _text(package.get('accommodationName')) or _text(package.get('accommodationName')).lower() in {'none', 'n/a', 'not included'}:
            return 'Specify the accommodation promised in this package.'
        if not _text(package.get('roomType')):
            return 'Specify Room Configuration for the included room or entire property.'
    if any(key in package for key in ('accommodationIncluded', 'transportIncluded', 'guideActivitiesIncluded')):
        from services.package_checkout_contract import derive_required_services
        requirements = derive_required_services(package,review_optional_extras=True)
        for key, meta in requirements.items():
            if key + 'Included' in package and meta['uncertain']:
                evidence = '; '.join(meta.get('conflictingClauses') or [])
                return (f'{key}Included: inclusion choice conflicts with the package brochure. '
                        f'Conflicting text: {evidence}. Correct this inclusion choice or the brochure to match the intended sale. '
                        'Guide / activities includes either a guided service OR promised admission / reserved tickets / arranged activities.'
                        if key == 'guideActivities' else
                        f'{key}Included: inclusion choice conflicts with the package brochure. Conflicting text: {evidence}. '
                        'Correct this inclusion choice or the brochure to match the intended sale.')
    return None
