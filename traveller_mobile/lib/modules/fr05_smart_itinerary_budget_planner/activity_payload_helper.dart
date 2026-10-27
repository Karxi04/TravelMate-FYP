import 'package:flutter/material.dart';

/// Supported image keys for activity and destination payloads.
const List<String> kPlaceImageFields = [
  'thumbnail',
  'image',
  'imageUrl',
  'mainPhoto',
  'main_photo',
  'photo',
  'photos',
  'images',
  'heroImage',
  'galleryImages',
];

/// Allowed pricing evidence fields matching itinerary_write_contract.py.
const Set<String> kAllowedEvidenceFields = {
  'venueId',
  'googlePlaceId',
  'ticketProductId',
  'ticketProduct',
  'unitPrice',
  'pricingUnit',
  'currency',
  'applicability',
  'eligibility',
  'priceSourceUrl',
  'limitations',
  'priceVerifiedAt',
  'researchBatch',
  'identityEvidence',
  'matchedBy',
};

/// Builds an activity creation payload compliant with M-S1 itinerary write contract.
/// Preserves legitimate pricing and opening hours evidence without fabricating missing data.
Map<String, dynamic> buildActivityPayload(
  Map<String, dynamic> place, {
  int dayNo = 1,
}) {
  final name = (place['activityName'] ?? place['title'] ?? place['name'] ?? 'Place').toString().trim();
  final destId = (place['destinationId'] ?? place['place_id'] ?? place['id'] ?? place['title'] ?? '').toString().trim();
  final addr = (place['address'] ?? place['location'] ?? '').toString().trim();
  final cat = (place['category'] ?? place['type'] ?? '').toString().trim();
  final typ = (place['type'] ?? place['category'] ?? '').toString().trim();
  final desc = (place['description'] ?? '').toString().trim();
  final openH = (place['openingHours'] ?? place['open_state'] ?? '').toString().trim();
  final isIndoor = place['indoor'] == true;

  final duration = int.tryParse('${place['recommendedDurationMinutes'] ?? ''}') ?? 90;
  final effectiveDay = dayNo <= 0 ? 1 : dayNo;

  final payload = <String, dynamic>{
    'activityName': name.isEmpty ? 'Place' : name,
    'destinationId': destId,
    'address': addr,
    'dayNo': effectiveDay,
    'type': typ,
    'category': cat,
    'description': desc,
    'indoor': isIndoor,
    'openingHours': openH,
    'recommendedDurationMinutes': duration <= 0 ? 90 : duration,
  };

  // GPS Coordinates (must be valid finite numbers within latitude [-90, 90] and longitude [-180, 180])
  final coords = place['gps_coordinates'] ?? place['gpsCoordinates'];
  if (coords is Map) {
    final lat = num.tryParse('${coords['latitude'] ?? ''}');
    final lng = num.tryParse('${coords['longitude'] ?? ''}');
    if (lat != null && lng != null && lat.abs() <= 90 && lng.abs() <= 180) {
      payload['gps_coordinates'] = {
        'latitude': lat.toDouble(),
        'longitude': lng.toDouble(),
      };
    }
  }

  // Estimated Cost (must be non-negative finite number)
  final estCost = num.tryParse('${place['estimatedCost'] ?? ''}');
  if (estCost != null && estCost >= 0) {
    payload['estimatedCost'] = estCost.toDouble();
  } else {
    payload['estimatedCost'] = 0.0;
  }

  // Place images
  for (final field in kPlaceImageFields) {
    if (place[field] != null) {
      payload[field] = place[field];
    }
  }

  // Provider duration
  final providerDur = int.tryParse('${place['providerDurationMinutes'] ?? ''}');
  if (providerDur != null && providerDur > 0) {
    payload['providerDurationMinutes'] = providerDur;
  }
  if (place['durationSource'] is String && (place['durationSource'] as String).trim().isNotEmpty) {
    payload['durationSource'] = (place['durationSource'] as String).trim();
  }

  // Pricing evidence fields: preserve if present, never fabricate
  if (place['pricingUnit'] is String && (place['pricingUnit'] as String).trim().isNotEmpty) {
    payload['pricingUnit'] = (place['pricingUnit'] as String).trim();
  }

  final unitPriceNum = num.tryParse('${place['unitPrice'] ?? ''}');
  if (unitPriceNum != null && unitPriceNum >= 0) {
    payload['unitPrice'] = unitPriceNum.toDouble();
  }

  if (place['costCategory'] is String && (place['costCategory'] as String).trim().isNotEmpty) {
    payload['costCategory'] = (place['costCategory'] as String).trim();
  }

  if (place['costProvenance'] is String && (place['costProvenance'] as String).trim().isNotEmpty) {
    payload['costProvenance'] = (place['costProvenance'] as String).trim();
  }

  if (place['priceSourceUrl'] is String && (place['priceSourceUrl'] as String).trim().isNotEmpty) {
    payload['priceSourceUrl'] = (place['priceSourceUrl'] as String).trim();
  }

  if (place['priceVerifiedAt'] is String && (place['priceVerifiedAt'] as String).trim().isNotEmpty) {
    payload['priceVerifiedAt'] = (place['priceVerifiedAt'] as String).trim();
  }

  if (place['overlapsAllowance'] is bool) {
    payload['overlapsAllowance'] = place['overlapsAllowance'] as bool;
  }

  // Pricing evidence map: only copy allowlisted fields with flat scalar values
  if (place['pricingEvidence'] is Map) {
    final rawMap = place['pricingEvidence'] as Map;
    final cleanEvidence = <String, dynamic>{};
    for (final entry in rawMap.entries) {
      final key = entry.key.toString();
      if (kAllowedEvidenceFields.contains(key)) {
        final val = entry.value;
        if (val is String || val is bool || val == null) {
          cleanEvidence[key] = val;
        } else if (val is num) {
          cleanEvidence[key] = val.toDouble();
        }
      }
    }
    if (cleanEvidence.isNotEmpty) {
      payload['pricingEvidence'] = cleanEvidence;
    }
  }

  return payload;
}

/// Representation of a trip day option for day selection UI.
class TripDayOption {
  final int dayNo;
  final String dateLabel;
  final String displayLabel;

  const TripDayOption({
    required this.dayNo,
    required this.dateLabel,
    required this.displayLabel,
  });
}

/// Extracts available day options with human-readable dates for a trip.
List<TripDayOption> extractTripDayOptions(Map<String, dynamic> trip) {
  int totalDays = 1;
  final rawDays = int.tryParse('${trip['tripDays'] ?? ''}');
  if (rawDays != null && rawDays > 0) {
    totalDays = rawDays;
  } else {
    final schedule = trip['dailySchedule'] as List?;
    if (schedule != null && schedule.isNotEmpty) {
      totalDays = schedule.length;
    } else {
      final start = DateTime.tryParse('${trip['startDate'] ?? ''}');
      final end = DateTime.tryParse('${trip['endDate'] ?? ''}');
      if (start != null && end != null) {
        final diff = end.difference(start).inDays + 1;
        if (diff > 0) totalDays = diff;
      }
    }
  }

  final startDate = DateTime.tryParse('${trip['startDate'] ?? ''}');
  final scheduleList = (trip['dailySchedule'] as List? ?? const [])
      .whereType<Map>()
      .toList();

  final options = <TripDayOption>[];
  for (int i = 0; i < totalDays; i++) {
    final dayNo = i + 1;
    String dateStr = '';
    if (i < scheduleList.length) {
      final item = scheduleList[i];
      if (item['dayDate'] != null && '${item['dayDate']}'.trim().isNotEmpty) {
        dateStr = '${item['dayDate']}'.trim();
      }
    }
    if (dateStr.isEmpty && startDate != null) {
      dateStr = startDate.add(Duration(days: i)).toIso8601String().split('T').first;
    }

    final display = dateStr.isNotEmpty ? 'Day $dayNo · $dateStr' : 'Day $dayNo';
    options.add(TripDayOption(dayNo: dayNo, dateLabel: dateStr, displayLabel: display));
  }
  return options;
}

/// Prompts the user to select an intended trip day if the trip has multiple days.
/// If trip has only 1 day, immediately returns 1 without displaying a modal.
Future<int?> promptTripDaySelection({
  required BuildContext context,
  required Map<String, dynamic> trip,
  int? initialDay,
}) async {
  final options = extractTripDayOptions(trip);
  if (options.length <= 1) {
    return 1;
  }

  final chosenInitial = (initialDay != null && initialDay > 0 && initialDay <= options.length)
      ? initialDay
      : 1;

  return showModalBottomSheet<int>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (sheetContext) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Select Trip Day',
              style: Theme.of(sheetContext).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                  ) ??
                  const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 6),
            Text(
              'Choose which day to add this attraction to for "${trip['title'] ?? 'your trip'}".',
              style: TextStyle(
                color: Theme.of(sheetContext).colorScheme.onSurfaceVariant,
                fontSize: 14,
              ),
            ),
            const SizedBox(height: 16),
            Flexible(
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: options.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (context, index) {
                  final opt = options[index];
                  final isSelected = chosenInitial == opt.dayNo;
                  return ListTile(
                    key: ValueKey('day-option-${opt.dayNo}'),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    leading: CircleAvatar(
                      backgroundColor: isSelected
                          ? Theme.of(context).colorScheme.primary
                          : Theme.of(context).colorScheme.surfaceContainerHighest,
                      foregroundColor: isSelected
                          ? Theme.of(context).colorScheme.onPrimary
                          : Theme.of(context).colorScheme.onSurfaceVariant,
                      child: Text('${opt.dayNo}'),
                    ),
                    title: Text(
                      opt.displayLabel,
                      style: TextStyle(
                        fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
                      ),
                    ),
                    trailing: isSelected
                        ? Icon(
                            Icons.check_circle_rounded,
                            color: Theme.of(context).colorScheme.primary,
                          )
                        : const Icon(Icons.chevron_right_rounded),
                    onTap: () => Navigator.pop(sheetContext, opt.dayNo),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    ),
  );
}
