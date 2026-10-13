enum HotelTripAttachmentOutcome {
  attached,
  unverified,
  incompatible,
  failed,
  notRequested,
}

HotelTripAttachmentOutcome hotelTripAttachmentOutcome(Object? value) {
  switch (value?.toString()) {
    case 'succeeded':
      return HotelTripAttachmentOutcome.attached;
    case 'compatibility_unverified':
      return HotelTripAttachmentOutcome.unverified;
    case 'incompatible':
      return HotelTripAttachmentOutcome.incompatible;
    case 'failed':
      return HotelTripAttachmentOutcome.failed;
    default:
      return HotelTripAttachmentOutcome.notRequested;
  }
}
