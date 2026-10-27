"""Public FR05 input only; trusted server record builders do not use this boundary."""
from math import isfinite

from sequence_contract.validators import (
    ACCOMMODATION_CHOICES, CAR_RENTAL_CHOICES, TRAVEL_MODES,
)


EDITABLE_FIELDS = {
    'title', 'destinationArea', 'destinationName', 'destinationCountry',
    'startDate', 'endDate', 'travellerCount', 'budgetLimit', 'originLocation',
    'travelMode', 'accommodationChoice', 'carRentalChoice', 'travelPace',
}
GENERATION_FIELDS = {'generationRequestId', 'recommendationGenerationId'}
ERROR = 'Invalid or non-editable trip fields. Use the supported trip editing or selection actions.'
ACTIVITY_TEXT = {
    'activityName', 'title', 'destinationId', 'address', 'state', 'city',
    'timeSlot', 'type', 'category', 'description', 'openingHours', 'durationSource',
    'pricingUnit', 'costCategory', 'costProvenance', 'priceSourceUrl', 'priceVerifiedAt',
}
ACTIVITY_NUMBERS = {'estimatedCost', 'unitPrice', 'recommendedDurationMinutes', 'providerDurationMinutes'}
IMAGE_FIELDS = {'thumbnail', 'image', 'imageUrl', 'mainPhoto', 'main_photo', 'photo',
                'photos', 'images', 'heroImage', 'galleryImages'}
EVIDENCE_FIELDS = {
    'venueId', 'googlePlaceId', 'ticketProductId', 'ticketProduct', 'unitPrice',
    'pricingUnit', 'currency', 'applicability', 'eligibility', 'priceSourceUrl',
    'limitations', 'priceVerifiedAt', 'researchBatch', 'identityEvidence', 'matchedBy',
}


def _finite_number(value):
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


def _number(value, *, positive=False, integer=False):
    return (_finite_number(value)
            and (value > 0 if positive else value >= 0)
            and (not integer or int(value) == value))


def _flat_object(value, fields):
    return (isinstance(value, dict) and set(value) <= fields
            and all(isinstance(item, (str, bool)) or item is None or _finite_number(item)
                    for item in value.values()))


def _image(value):
    if value is None or isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(_image(item) for item in value)
    return _flat_object(value, {'url', 'imageUrl', 'thumbnail', 'photo_reference',
                                'width', 'height', 'attribution', 'title'})


def _activity(value):
    allowed = ACTIVITY_TEXT | ACTIVITY_NUMBERS | IMAGE_FIELDS | {
        'dayNo', 'indoor', 'overlapsAllowance', 'gps_coordinates', 'gpsCoordinates', 'pricingEvidence',
    }
    if not isinstance(value, dict) or not set(value) <= allowed:
        return False
    for key, item in value.items():
        if key in ACTIVITY_TEXT and not isinstance(item, str):
            return False
        if key in ACTIVITY_NUMBERS and item is not None and not _number(item):
            return False
        if key == 'dayNo' and not _number(item, positive=True, integer=True):
            return False
        if key in {'indoor', 'overlapsAllowance'} and not isinstance(item, bool):
            return False
        if key in IMAGE_FIELDS and not _image(item):
            return False
        if key == 'pricingEvidence' and not _flat_object(item, EVIDENCE_FIELDS):
            return False
        if key in {'gps_coordinates', 'gpsCoordinates'}:
            if not isinstance(item, dict) or not set(item) <= {'latitude', 'longitude'}:
                return False
            if any(not _finite_number(coord)
                   or abs(coord) > (90 if axis == 'latitude' else 180)
                   for axis, coord in item.items()):
                return False
    return True


def validate_trip_write(payload, *, update=False, generation=False):
    """Reject the whole request before deriving or persisting any patch.

    Unknown names (including aliases/dotted paths) are forbidden, not stripped.
    A hotel booking ID is only a lookup command; the existing owned-booking resolver
    supplies its snapshot and amount. Other selections use their dedicated routes.
    """
    allowed = EDITABLE_FIELDS | ({'hotelBookingId'} if update else {'activities'})
    if generation:
        allowed |= GENERATION_FIELDS
    if not isinstance(payload, dict) or not payload or not set(payload) <= allowed:
        raise ValueError(ERROR)
    for key, value in payload.items():
        if key == 'activities':
            if not isinstance(value, list) or not all(_activity(item) for item in value):
                raise ValueError(ERROR)
        elif key == 'travellerCount':
            if not _number(value, positive=True, integer=True):
                raise ValueError(ERROR)
        elif key == 'budgetLimit':
            if not _number(value):
                raise ValueError(ERROR)
        elif not isinstance(value, str):
            raise ValueError(ERROR)
        elif key in {'title', 'destinationArea', 'startDate', 'endDate', 'hotelBookingId'} and not value.strip():
            raise ValueError(ERROR)
    choices = {'travelMode': TRAVEL_MODES, 'accommodationChoice': ACCOMMODATION_CHOICES,
               'carRentalChoice': CAR_RENTAL_CHOICES}
    if any(key in payload and payload[key] not in options for key, options in choices.items()):
        raise ValueError(ERROR)
    return dict(payload)
