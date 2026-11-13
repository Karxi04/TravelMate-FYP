from copy import deepcopy
from unittest.mock import patch

import pytest

from modules.fr08_hotel_booking.routes import _attach_booking_to_itinerary


def _trip(**overrides):
    return {
        'id': 'trip_1', 'travellerId': 'test_traveller_uid',
        'startDate': '2026-10-14', 'endDate': '2026-10-16',
        'destinationArea': 'Penang', 'budgetEstimate': 0,
        **overrides,
    }


def _booking(**overrides):
    return {
        'id': 'booking_1', 'travellerId': 'test_traveller_uid',
        'bookingStatus': 'confirmed', 'hotelCost': 200, 'hotelCurrency': 'MYR',
        'selectedHotel': {'name': 'Hotel', 'currency': 'MYR'},
        'stayCriteria': {
            'destination': 'George Town, Penang',
            'checkin': '2026-10-14', 'checkout': '2026-10-16',
            'adults': 2, 'roomQuantity': 1, 'occupancies': [{'adults': 2}],
        },
        **overrides,
    }


def _attach(app, booking, trip=None, payload=None):
    writes = []
    records = {'itineraries': {'trip_1': deepcopy(trip or _trip())},
               'hotel_bookings': {'booking_1': deepcopy(booking)}}

    def update(collection, document_id, data):
        writes.append((collection, document_id, deepcopy(data)))
        records[collection][document_id].update(data)
        return deepcopy(records[collection][document_id])

    with app.test_request_context('/'), \
         patch('modules.fr08_hotel_booking.routes._own_itinerary', return_value=records['itineraries']['trip_1'] if trip is not None or trip is None else None), \
         patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=update):
        result, itinerary = _attach_booking_to_itinerary(
            'booking_1', deepcopy(booking), payload or {'itineraryId': 'trip_1'})
    return result, itinerary, records, writes


@pytest.mark.parametrize('checkin,checkout,expected', [
    ('2026-10-14', '2026-10-16', 'succeeded'),  # checkout equals trip end
    ('2026-10-15', '2026-10-16', 'succeeded'),  # partial stay
    ('2026-10-13', '2026-10-16', 'incompatible'),
    ('2026-10-14', '2026-10-17', 'incompatible'),
])
def test_hotel_trip_date_boundary(app, checkin, checkout, expected):
    booking = _booking(stayCriteria={**_booking()['stayCriteria'], 'checkin': checkin, 'checkout': checkout})
    result, itinerary, records, _ = _attach(app, booking)
    assert result['itineraryAttachmentStatus'] == expected
    assert (itinerary is not None) is (expected == 'succeeded')
    assert records['hotel_bookings']['booking_1']['hotelCost'] == 200


def test_proven_destination_mismatch_is_rejected(app):
    booking = _booking(stayCriteria={**_booking()['stayCriteria'], 'destination': 'Kuala Lumpur'})
    result, itinerary, _, _ = _attach(app, booking)
    assert itinerary is None
    assert result['itineraryAttachmentStatus'] == 'incompatible'
    assert 'destination' in result['itineraryAttachmentError'].lower()


def test_legacy_booking_requires_scoped_acknowledgement(app):
    booking = _booking(stayCriteria={})
    result, itinerary, records, _ = _attach(app, booking)
    assert itinerary is None
    assert result['itineraryAttachmentStatus'] == 'compatibility_unverified'
    assert records['itineraries']['trip_1'].get('hotelBookingId') is None

    result, itinerary, records, _ = _attach(
        app, booking, payload={'itineraryId': 'trip_1', 'acknowledgeCompatibilityUnverified': True})
    assert result['itineraryAttachmentStatus'] == 'succeeded'
    assert itinerary['hotelBookingId'] == 'booking_1'
    assert result.get('stayCriteria') == {}


def test_unowned_trip_is_not_attached(app):
    booking = _booking()
    with app.test_request_context('/'), \
         patch('modules.fr08_hotel_booking.routes._own_itinerary', return_value=None), \
         patch('modules.fr08_hotel_booking.routes.updateRecord', side_effect=lambda _c, _id, value: value):
        result, itinerary = _attach_booking_to_itinerary('booking_1', booking, {'itineraryId': 'other_trip'})
    assert itinerary is None
    assert result['itineraryAttachmentStatus'] == 'failed'


def test_duplicate_attachment_is_idempotent(app):
    booking = _booking()
    result, itinerary, records, writes = _attach(app, booking, _trip(hotelBookingId='booking_1'))
    assert result['itineraryAttachmentStatus'] == 'succeeded'
    assert itinerary['hotelBookingId'] == 'booking_1'
    assert all(collection != 'itineraries' for collection, _, _ in writes)
    assert records['hotel_bookings']['booking_1']['hotelCost'] == 200


def test_compatible_trip_picker_returns_only_owned_matching_ordinary_trips(client, mock_traveller_auth):
    snapshot = 'hotel_prebook_' + 'a' * 40
    record = {
        'travellerId': 'test_traveller_uid', 'status': 'succeeded',
        'acceptedPrebookSnapshot': {'id': snapshot, 'expiresAt': '2099-01-01T00:00:00Z'},
        'criteria': _booking()['stayCriteria'],
    }
    trips = [
        _trip(), _trip(id='foreign', travellerId='someone-else'),
        _trip(id='outside', endDate='2026-10-15'),
        _trip(id='different', destinationArea='Kuala Lumpur'),
        _trip(id='package', packageTrip=True),
    ]
    with patch('modules.fr08_hotel_booking.routes.retrieveRecord', side_effect=[record, trips]) as read:
        response = client.get('/api/fr8/hotels/compatible-trips',
                              query_string={'acceptedPrebookSnapshotId': snapshot},
                              headers={'Authorization': 'Bearer valid_test_token'})
    assert response.status_code == 200, response.json
    assert [trip['id'] for trip in response.json['items']] == ['trip_1']
    assert read.call_args.kwargs['filters'] == [('travellerId', '==', 'test_traveller_uid')]
