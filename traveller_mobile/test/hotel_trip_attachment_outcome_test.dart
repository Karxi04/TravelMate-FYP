import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_trip_attachment.dart';

void main() {
  test('maps compatible, incompatible and legacy backend responses safely', () {
    expect(hotelTripAttachmentOutcome('succeeded'),
        HotelTripAttachmentOutcome.attached);
    expect(hotelTripAttachmentOutcome('incompatible'),
        HotelTripAttachmentOutcome.incompatible);
    expect(hotelTripAttachmentOutcome('compatibility_unverified'),
        HotelTripAttachmentOutcome.unverified);
    expect(hotelTripAttachmentOutcome('failed'),
        HotelTripAttachmentOutcome.failed);
  });

  test('does not treat an unknown response as a successful attachment', () {
    expect(hotelTripAttachmentOutcome(null),
        HotelTripAttachmentOutcome.notRequested);
    expect(hotelTripAttachmentOutcome('pending'),
        HotelTripAttachmentOutcome.notRequested);
  });
}
