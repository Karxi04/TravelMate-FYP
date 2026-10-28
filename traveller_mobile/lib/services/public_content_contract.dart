/// Client-side defense in depth for the server-authored public projections.
/// Firestore rules and the backend projection are the security boundary.
class PublicContentContract {
  static const _packageFields = {
    'id', 'schemaVersion', 'title', 'packageTitle', 'shortDescription',
    'fullDescription', 'description', 'destination', 'destinationName',
    'destinationArea', 'category', 'heroImage', 'imageUrl', 'galleryImages',
    'durationDays', 'durationNights', 'currency', 'adultPrice', 'price',
    'childPrice', 'originalPrice', 'promotionalPrice', 'promotionStart',
    'promotionEnd', 'priceBasis', 'taxIncluded', 'taxNotes',
    'minimumTravellers', 'maximumTravellers', 'maxTravellers',
    'departureDates', 'departureLocation', 'meetingPoint', 'departureNotes',
    'itineraryDays', 'highlights', 'inclusions', 'exclusions',
    'accommodationName', 'accommodationCategory', 'roomType',
    'accommodationNotes', 'transportTypes', 'transportNotes',
    'cancellationPolicy', 'refundPolicy', 'bookingTerms', 'importantNotes',
    'whatToBring', 'availabilityStatus', 'validFrom', 'validUntil',
    'createdAt', 'updatedAt',
    'operatorName', 'operatorEmail', 'operatorPhone', 'activeCampaigns',
  };
  static const _campaignFields = {
    'id', 'campaignTitle', 'description', 'packageId', 'startDate', 'endDate',
    'campaignStatus', 'discountType', 'discountValue', 'promoCode',
    'bannerImageUrl', 'termsConditions', 'packageTitle', 'destinationName',
    'packagePrice', 'packageImageUrl', 'operatorName', 'operatorEmail',
    'operatorPhone',
  };
  static const _reviewFields = {
    'id', 'destinationId', 'destinationName', 'destinationAddress', 'rating',
    'comment', 'travellerName', 'submittedAt', 'updatedAt', 'source',
    'username', 'description', 'date', 'reviewKey',
  };

  static Map<String, dynamic> package(Map<String, dynamic> raw) {
    final result = _copy(raw, _packageFields);
    result['itineraryDays'] = _maps(raw['itineraryDays'], {
      'dayNumber', 'title', 'description', 'activities', 'meals',
      'accommodation', 'transportNotes',
    });
    result['activeCampaigns'] = _maps(raw['activeCampaigns'], _campaignFields)
        .where(activeCampaign)
        .toList();
    return result;
  }

  static Map<String, dynamic> campaign(Map<String, dynamic> raw) =>
      _copy(raw, _campaignFields);

  static Map<String, dynamic> review(Map<String, dynamic> raw) =>
      _copy(raw, _reviewFields);

  static bool activeCampaign(Map<String, dynamic> item) {
    final status = (item['campaignStatus'] ?? 'approved').toString().toLowerCase();
    if (!{'approved', 'active'}.contains(status)) return false;
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final start = DateTime.tryParse((item['startDate'] ?? '').toString());
    final end = DateTime.tryParse((item['endDate'] ?? '').toString());
    if (start != null && today.isBefore(DateTime(start.year, start.month, start.day))) return false;
    if (end != null && today.isAfter(DateTime(end.year, end.month, end.day))) return false;
    return true;
  }

  static Map<String, dynamic> _copy(
    Map<String, dynamic> raw,
    Set<String> fields,
  ) => {
        for (final entry in raw.entries)
          if (fields.contains(entry.key)) entry.key: entry.value,
      };

  static List<Map<String, dynamic>> _maps(dynamic value, Set<String> fields) =>
      value is List
          ? value
              .whereType<Map>()
              .map((item) => _copy(Map<String, dynamic>.from(item), fields))
              .toList()
          : <Map<String, dynamic>>[];
}
