import 'dart:math';

import 'itinerary_identity.dart';
import 'malaysian_locality.dart';
import 'recommendation_taxonomy.dart';

const localDaysPolicy = 'local-days-v1';
const _unknownJourney =
    'Could not establish a reliable journey to this stop. Confirm its location or plan a separate day.';
const _distantStop =
    'This stop is too far from the other stops or accommodation for this sightseeing day. Choose a nearer stop or plan an intercity transfer.';
const localActivityFields = [
  'city', 'state', 'country', 'district', 'locality', 'normalizedGeography',
  'geographyConflict', 'metadataConflict', 'type_id', 'type_ids', 'tags',
  'providerTravelFromDestinationId', 'providerTravelDurationMinutes',
  'providerTravelDistanceKm', 'providerTravelMode',
];

const Map<String, List<int>> itineraryPaceWindows = {
  'relaxed': [600, 1200],
  'moderate': [540, 1260],
  'active': [480, 1290],
};

double _number(dynamic value, [double fallback = 0]) =>
    double.tryParse('${value ?? ''}') ?? fallback;

String _time(int minutes) =>
    '${(minutes ~/ 60).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}';

String _date(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

String _pace(Map<String, dynamic> trip) {
  final value = (trip['travelPace'] ?? trip['pace'] ?? trip['preferredPace'] ?? '')
      .toString()
      .toLowerCase();
  if (value.contains('relax') || value.contains('slow') || value.contains('leisure')) {
    return 'relaxed';
  }
  if (value.contains('active') || value.contains('fast') || value.contains('packed')) {
    return 'active';
  }
  return 'moderate';
}

int _days(Map<String, dynamic> trip) {
  final start = DateTime.tryParse('${trip['startDate'] ?? ''}');
  final end = DateTime.tryParse('${trip['endDate'] ?? ''}');
  if (start != null && end != null) {
    return (end.difference(start).inDays + 1).clamp(1, 14);
  }
  return _number(trip['tripDays'], 1).round().clamp(1, 14);
}

int? _clock(String value) {
  final match = RegExp(r'\b(\d{1,2})(?::|\.)?(\d{0,2})\s*(AM|PM)?\b', caseSensitive: false)
      .firstMatch(value.trim());
  if (match == null) return null;
  var hour = int.tryParse(match.group(1) ?? '');
  final minute = int.tryParse(match.group(2)?.isEmpty == true ? '0' : match.group(2) ?? '0');
  if (hour == null || minute == null || minute > 59) return null;
  final suffix = (match.group(3) ?? '').toUpperCase();
  if (suffix.isNotEmpty) {
    if (hour < 1 || hour > 12) return null;
    hour = (hour % 12) + (suffix == 'PM' ? 12 : 0);
  }
  return hour <= 23 ? hour * 60 + minute : null;
}

({String status, int? start, int? end}) _opening(dynamic value) {
  final text = '${value ?? ''}'.trim();
  final lower = text.toLowerCase();
  if (text.isEmpty) return (status: 'unknown', start: null, end: null);
  if (RegExp(r'\bclosed\b').hasMatch(lower)) {
    return (status: 'closed', start: null, end: null);
  }
  if (lower.contains('open all day') || lower.contains('24 hour') || lower.contains('24/7')) {
    return (status: 'open', start: 0, end: 1439);
  }
  final match = RegExp(
          r'(\d{1,2}(?::|\.)?\d{0,2}\s*(?:AM|PM)?)\s*(?:–|—|-)\s*(\d{1,2}(?::|\.)?\d{0,2}\s*(?:AM|PM)?)',
          caseSensitive: false)
      .firstMatch(text);
  if (match == null) return (status: 'unknown', start: null, end: null);
  final start = _clock(match.group(1) ?? '');
  final end = _clock(match.group(2) ?? '');
  if (start == null || end == null || end <= start) {
    return (status: 'unknown', start: null, end: null);
  }
  return (status: 'open', start: start, end: end);
}

({int minutes, String source}) _duration(Map<String, dynamic> item) {
  final source = '${item['durationSource'] ?? ''}'.toLowerCase();
  final provider = item['providerDurationMinutes'];
  if (provider != null || source == 'provider' || source == 'confirmed') {
    return (
      minutes: _number(provider ?? item['recommendedDurationMinutes'], 105).round().clamp(30, 480),
      source: 'provider'
    );
  }
  final label = '${item['category'] ?? item['type'] ?? item['activityName'] ?? ''}'.toLowerCase();
  var minutes = 105;
  if (label.contains('food') || label.contains('restaurant') || label.contains('cafe')) minutes = 75;
  if (label.contains('shopping') || label.contains('market') || label.contains('mall')) minutes = 120;
  if (label.contains('nature') || label.contains('beach') || label.contains('park')) minutes = 135;
  if (label.contains('theme park') || label.contains('amusement')) minutes = 180;
  if (item['recommendedDurationMinutes'] != null) {
    minutes = _number(item['recommendedDurationMinutes'], minutes.toDouble()).round().clamp(30, 480);
  }
  return (minutes: minutes, source: 'category_estimate');
}

List<double>? _coordinates(Map<String, dynamic> item) {
  final gps = item['gps_coordinates'] ?? item['gpsCoordinates'];
  if (gps is! Map) return null;
  final latitude = double.tryParse('${gps['latitude'] ?? ''}');
  final longitude = double.tryParse('${gps['longitude'] ?? ''}');
  if (latitude == null || longitude == null || !latitude.isFinite ||
      !longitude.isFinite || latitude.abs() > 90 || longitude.abs() > 180) {
    return null;
  }
  return [latitude, longitude];
}

double? _distance(Map<String, dynamic> first, Map<String, dynamic> second) {
  final a = _coordinates(first);
  final b = _coordinates(second);
  if (a == null || b == null) return null;
  const radius = 6371.0;
  final lat1 = a[0] * pi / 180;
  final lat2 = b[0] * pi / 180;
  final dLat = lat2 - lat1;
  final dLon = (b[1] - a[1]) * pi / 180;
  final h = pow(sin(dLat / 2), 2) + cos(lat1) * cos(lat2) * pow(sin(dLon / 2), 2);
  return radius * 2 * atan2(sqrt(h), sqrt(max(0, 1 - h)));
}

({int minutes, double? distance, String source}) _travel(
    Map<String, dynamic>? previous, Map<String, dynamic> item) {
  if (previous == null) return (minutes: 0, distance: 0, source: 'not_applicable');
  if ((item['travelTimeSource'] == 'provider' || item['travelTimeSource'] == 'confirmed') &&
      item['travelDurationMinutes'] != null) {
    return (
      minutes: max(1, _number(item['travelDurationMinutes']).round()),
      distance: double.tryParse('${item['travelDistanceKm'] ?? ''}'),
      source: 'provider'
    );
  }
  if ((item['supportingAccess'] as List? ?? []).isNotEmpty ||
      (previous['supportingAccess'] as List? ?? []).isNotEmpty) {
    return (minutes: 25, distance: null, source: 'unverified_access_buffer');
  }
  final distance = _distance(previous, item);
  if (distance == null) return (minutes: 25, distance: null, source: 'estimated_default');
  return (
    minutes: max(8, (((distance * 1.25) / 28) * 60 + 8).round()),
    distance: double.parse(distance.toStringAsFixed(2)),
    source: 'estimated_haversine'
  );
}

const _localLimits = {
  'walk': (km: 3, leg: 45, day: 75, speed: 4.5),
  'drive': (km: 35, leg: 75, day: 135, speed: 32.0),
  'public': (km: 25, leg: 65, day: 110, speed: 23.0),
};

String _sightseeingMode(Map<String, dynamic> trip) {
  final mode = (trip['transportMode'] ?? trip['preferredTransport'] ?? trip['travelMode']).toString().toLowerCase();
  if (const {'walk', 'walking', 'on foot'}.contains(mode)) return 'walk';
  if (const {'car', 'drive', 'driving', 'private car', 'taxi', 'own_vehicle'}.contains(mode)) return 'drive';
  return 'public';
}

bool _conflictingLocation(Map<String, dynamic> item) =>
    item['metadataConflict'] == true || item['geographyConflict'] == true ||
    (item['normalizedGeography'] as Map?)?['conflict'] == true ||
    (MalaysianLocality.validateCandidate(item, const {})['normalizedGeography'] as Map)['conflict'] == true;

double? _localDistance(Map<String, dynamic> origin, Map<String, dynamic> target) =>
    _conflictingLocation(origin) || _conflictingLocation(target) ? null : _distance(origin, target);

({int minutes, double? distance, String source})? _localLeg(
    Map<String, dynamic>? previous, Map<String, dynamic> item, String mode) {
  if (_conflictingLocation(item)) return null;
  if (previous == null) return (minutes: 0, distance: 0, source: 'not_applicable');
  final distance = _localDistance(previous, item);
  if (distance == null) return null;
  final minutes = _number(item['providerTravelDurationMinutes']);
  if (previous['destinationId'] != null &&
      previous['destinationId'] == item['providerTravelFromDestinationId'] &&
      item['providerTravelMode'] == mode && minutes.isFinite && minutes > 0) {
    final roadDistance = _number(item['providerTravelDistanceKm'], distance);
    return (minutes: minutes.ceil(), distance: roadDistance.isFinite ? max(distance, roadDistance) : distance, source: 'provider');
  }
  final estimated = (distance * 1.25 / _localLimits[mode]!.speed * 60).ceil();
  final total = max(5, estimated + (mode == 'walk' ? 0 : 8));
  if ((item['supportingAccess'] as List? ?? []).isNotEmpty ||
      (previous['supportingAccess'] as List? ?? []).isNotEmpty) {
    return (minutes: max(25, total), distance: distance, source: 'unverified_access_buffer');
  }
  return (minutes: total, distance: distance, source: 'estimated_haversine');
}

String _experience(Map<String, dynamic> item) {
  final label = [for (final key in ['activityName', 'category', 'type', 'type_id']) item[key],
    ...(item['type_ids'] as List? ?? const [])]
      .whereType<String>().join(' ').toLowerCase().replaceAll('_', ' ');
  const groups = {
    'hike': r'\b(?:hik(?:e|ing)|trek(?:king)?)(?:\b|_)',
    'beach': r'\b(?:beach|pantai)\b',
    'garden': r'\b(?:garden|botanic|taman)',
    'viewpoint': r'\b(?:viewpoint|lookout|viewing deck)\b',
    'wildlife': r'\b(?:wildlife|zoo|bird park|sanctuary)\b',
    'museum': r'\b(?:museum|gallery)\b',
    'religious': r'\b(?:temple|mosque|church|shrine)\b',
    'heritage': r'\b(?:heritage|historical|historic|fort)\b',
    'market': r'\b(?:market|bazaar|pasar)\b',
    'mall': r'\b(?:mall|shopping cent(?:re|er))\b',
    'meal': r'\b(?:cafe|restaurant|food court|hawker cent(?:re|er))\b',
  };
  for (final entry in groups.entries) {
    if (RegExp(entry.value).hasMatch(label)) return entry.key;
  }
  return '';
}

Map<String, Map<String, dynamic>> _weatherByDate(Map<String, dynamic> forecast) {
  final daily = forecast['daily'];
  if (daily is! Map) return {};
  final dates = daily['time'] as List? ?? [];
  final rain = daily['precipitation_probability_max'] as List? ?? [];
  final codes = daily['weather_code'] as List? ?? [];
  final result = <String, Map<String, dynamic>>{};
  for (var i = 0; i < dates.length; i++) {
    final key = '${dates[i]}'.substring(0, min(10, '${dates[i]}'.length));
    final probability = i < rain.length ? _number(rain[i]) : 0;
    final code = i < codes.length ? _number(codes[i]).round() : 0;
    result[key] = {
      'date': key,
      'precipitationProbability': probability,
      'weatherCode': code,
      'heavyRainLikely': probability >= 55 || (code >= 51 && code <= 99),
      'source': 'forecast',
    };
  }
  return result;
}

bool _indoor(Map<String, dynamic> item) {
  final label = '${item['category'] ?? item['type'] ?? ''}'.toLowerCase();
  return item['indoor'] == true ||
      ['indoor', 'museum', 'mall', 'gallery', 'food', 'restaurant'].any(label.contains);
}

/// A missing amount stays unknown in the budget, and contributes no numeric estimate.
double? plannedActivityAmount(Map activity, int travellers) {
  final unit = activity['pricingUnit'];
  final amount = double.tryParse((activity['unitPrice'] ?? activity['estimatedCost']).toString());
  final currency = (activity['currency'] ?? 'MYR').toString().toUpperCase();
  final recognisedUnit = ['per_person', 'per_group', 'already_aggregated'].contains(unit);
  final evidencedZero = amount == 0 && recognisedUnit &&
      ['verified_ticket', 'catalog_estimate', 'user_entered'].contains(activity['costProvenance']);
  if (currency != 'MYR' || amount == null || !amount.isFinite || amount < 0 ||
      (amount == 0 && !evidencedZero)) return null;
  return amount * (unit == 'per_person' ? travellers : 1);
}

Map<String, dynamic> planConstraintAwareItinerary(
  Map<String, dynamic> source, {
  Map<String, dynamic> forecast = const {},
  bool preserveOrder = false,
  bool respectDayAssignments = false,
}) {
  final trip = Map<String, dynamic>.from(source);
  var remaining = (trip['activities'] as List? ?? [])
      .whereType<Map>()
      .map((item) => Map<String, dynamic>.from(item))
      .toList();
  for (final raw in (trip['unscheduledSuggestions'] as List? ?? []).whereType<Map>()) {
    final item = Map<String, dynamic>.from(raw)..remove('unscheduledReason');
    if (!remaining.any((existing) => '${existing['activityId']}' == '${item['activityId']}')) {
      remaining.add(item);
    }
  }
  final tripWide = trip['attractionIdentityPolicy'] == attractionIdentityPolicy;
  if (tripWide) remaining = consolidateGeneratedCandidates(remaining);
  final inputIds = remaining.map((row) => row['activityId']).toSet();
  final savedDays = {
    for (final day in (source['dailySchedule'] as List? ?? []).whereType<Map>())
      for (final row in (day['activities'] as List? ?? []).whereType<Map>())
        if (row['activityId'] != null) row['activityId']: day['dayNo'],
  };
  final repeats = remaining.where((row) => row['intentionalRepeat'] == true).toList();
  final pinned = {
    for (final row in remaining)
      if (row['dayNo'] != null && repeats.any((repeat) => sameAttraction(row, repeat)))
        row['activityId'],
  };
  if (tripWide && inputIds.length != remaining.length) {
    throw StateError('Generated schedule contains duplicate activity identifiers.');
  }
  final travellers = max(1, _number(trip['travellerCount'] ?? trip['numberOfTravellers'], 1).round());
  final days = _days(trip);
  final startDate = DateTime.tryParse('${trip['startDate'] ?? ''}') ?? DateTime.now();
  final pace = _pace(trip);
  final window = [...itineraryPaceWindows[pace]!];
  final rhythm = (trip['sleepingType'] ?? '').toString().toLowerCase();
  if (rhythm == 'early riser') {
    window[0] = max(450, window[0] - 60);
    window[1] -= 60;
  } else if (rhythm == 'night owl') {
    window[0] = max(window[0], 660);
  } else if (rhythm == 'comfort-focused') {
    window[0] = max(window[0], 600);
  }
  final rest = rhythm == 'night owl' ? [840, 900] : [750, rhythm == 'comfort-focused' ? 840 : 810];
  final preferences = (trip['planningPreferences'] as Map?) ?? const {};
  final profiled = preferences.isNotEmpty;
  final localDays = trip['geographyPlanningPolicy'] == localDaysPolicy;
  final mode = _sightseeingMode(trip);
  final limits = _localLimits[mode]!;
  final dailyLimit = (limits.day * (pace == 'relaxed' ? .75 : 1)).floor();
  final requested = trip['interests'] ?? trip['requestedInterests'] ?? preferences['interests'];
  final interests = RecommendationTaxonomy.conceptsFor(requested);
  final hikeFocused = trip['hikingFocused'] == true ||
      (requested is List && requested.any((value) =>
          const {'hiking', 'hike', 'trekking'}.contains(value.toString().trim().toLowerCase())));
  final usedConcepts = <String>{};
  final reasons = <dynamic, String>{};
  final sightseeingAnchors = <Map<String, dynamic>>[];
  final experiences = {if (localDays) for (final item in remaining) item['activityId']: _experience(item)};
  final concepts = {if (localDays && interests.isNotEmpty) for (final item in remaining)
    item['activityId']: RecommendationTaxonomy.primaryConcepts({...item, 'title': item['activityName']})};
  final tripExperiences = <String, int>{};
  final baseInfo = trip['accommodationBase'] ?? trip['selectedHotel'];
  final baseCandidate = baseInfo is Map ? Map<String, dynamic>.from(baseInfo) : null;
  var base = baseCandidate != null && _coordinates(baseCandidate) != null &&
      !_conflictingLocation(baseCandidate) ? baseCandidate : null;
  Map<String, dynamic>? focus = base;
  final transfer = localDays ? trip['confirmedIntercityTransfer'] as Map? : null;
  var transferApplied = false;
  final rank = {for (var i = 0; i < remaining.length; i++) remaining[i]['activityId']: i};
  final maxVisits = (profiled || localDays && pace == 'relaxed') && !respectDayAssignments
      ? const {'relaxed': 2, 'moderate': 3, 'active': 5}[pace] : null;
  final weather = _weatherByDate(forecast);
  final scheduled = <Map<String, dynamic>>[];
  final daily = <Map<String, dynamic>>[];

  for (var dayIndex = 0; dayIndex < days; dayIndex++) {
    final dayNo = dayIndex + 1;
    final dateKey = _date(startDate.add(Duration(days: dayIndex)));
    final dayWeather = weather[dateKey] ?? {
      'date': dateKey,
      'source': 'unavailable',
      'message': 'Weather forecast unavailable for this date.',
      'heavyRainLikely': false,
    };
    var current = window[0];
    Map<String, dynamic>? previous = localDays ? base : null;
    final dayItems = <Map<String, dynamic>>[];
    final experienceCounts = <String, int>{};
    var dailyTravel = 0;
    Map<String, dynamic>? transferBlock;
    if (transfer?['dayNo'] == dayNo && focus != null) {
      final target = remaining.where((item) => item['destinationId'] == transfer?['toDestinationId']).firstOrNull;
      final transferMode = transfer?['mode'] ?? mode;
      final leg = target != null && _localLimits.containsKey(transferMode)
          ? _localLeg(focus, target, transferMode.toString()) : null;
      if (leg != null && leg.source != 'unverified_access_buffer' && (leg.minutes > limits.leg || (leg.distance ?? 0) > limits.km) &&
          leg.minutes + 60 <= min(600, 1260 - current) && transferMode != 'walk') {
        transferApplied = true;
        final duration = leg.minutes + 60;
        transferBlock = {
          'type': 'intercity_transfer', 'label': 'Intercity transfer and breaks',
          'startTime': _time(current), 'endTime': _time(current + duration),
          'durationMinutes': duration, 'estimated': true, 'destinationId': target!['destinationId'],
        };
        base = null;
        focus = target;
      }
    }
    var visitLimit = maxVisits;
    bool canStartDay(Map<String, dynamic> item) {
      final opening = _opening(item['openingHours']);
      var start = max(window[0], opening.start ?? 0);
      final duration = _duration(item).minutes;
      if (start < rest[1] && start + duration > rest[0]) start = rest[1];
      return opening.status != 'closed' && start + duration <= min(window[1], opening.end ?? 1440);
    }
    final flexible = localDays && !respectDayAssignments && !preserveOrder;
    final transferDay = transfer?['dayNo'];
    final lastLocalDay = transferDay is int && transferDay > dayNo && transferDay <= days
        ? transferDay - 1 : days;
    final futureLocalDays = lastLocalDay - dayNo;
    if (flexible) {
      visitLimit = min(maxVisits ?? 5, max(1, remaining.length - futureLocalDays));
    }
    while (transferBlock == null && remaining.isNotEmpty &&
        (visitLimit == null || dayItems.length < visitLimit)) {
      final eligible = remaining
          .where((item) => (!respectDayAssignments && !pinned.contains(item['activityId'])) ||
              _number(item['dayNo'], dayNo.toDouble()).round() == dayNo)
          .toList();
      if (eligible.isEmpty) break;
      if (!preserveOrder) {
        eligible.sort((a, b) {
          final rainA = dayWeather['heavyRainLikely'] == true && _indoor(a) ? 0 : 1;
          final rainB = dayWeather['heavyRainLikely'] == true && _indoor(b) ? 0 : 1;
          if (rainA != rainB) return rainA.compareTo(rainB);
          if (localDays) {
            final missing = interests.difference(usedConcepts);
            int coverage(Map<String, dynamic> item) =>
                concepts[item['activityId']]?.intersection(missing).isNotEmpty == true ? 0 : 1;
            final coverageOrder = coverage(a).compareTo(coverage(b));
            if (coverageOrder != 0) return coverageOrder;
            if (focus == null) {
              int neighbours(Map<String, dynamic> item) => min(4, eligible.where((other) =>
                  (_localDistance(item, other) ?? double.infinity) <= limits.km).length);
              final grouping = neighbours(b).compareTo(neighbours(a));
              if (grouping != 0) return grouping;
            }
            final expA = experiences[a['activityId']];
            final expB = experiences[b['activityId']];
            final dailyVariety = (experienceCounts[expA] ?? 0).compareTo(experienceCounts[expB] ?? 0);
            if (dailyVariety != 0) return dailyVariety;
            final tripVariety = (tripExperiences[expA] ?? 0).compareTo(tripExperiences[expB] ?? 0);
            if (tripVariety != 0) return tripVariety;
            if (previous != null) {
              final proximity = ((_localDistance(previous, a) ?? 0) ~/ 4)
                  .compareTo((_localDistance(previous, b) ?? 0) ~/ 4);
              if (proximity != 0) return proximity;
            }
          }
          final closeA = _opening(a['openingHours']).end ?? 1440;
          final closeB = _opening(b['openingHours']).end ?? 1440;
          if (closeA != closeB) return closeA.compareTo(closeB);
          if (profiled) return rank[a['activityId']]!.compareTo(rank[b['activityId']]!);
          return (_distance(previous ?? a, a) ?? 99999).compareTo(_distance(previous ?? b, b) ?? 99999);
        });
      }
      Map<String, dynamic>? chosen;
      var chosenEnd = 0;
      for (final item in eligible) {
        if (dayItems.any((visit) => sameAttraction(item, visit) &&
            (savedDays[item['activityId']] != dayNo || savedDays[visit['activityId']] != dayNo))) {
          continue;
        }
        final opening = _opening(item['openingHours']);
        if (opening.status == 'closed') continue;
        final duration = _duration(item);
        final travel = localDays ? _localLeg(previous, item, mode) : _travel(previous, item);
        final anchor = focus ?? dayItems.firstOrNull;
        final anchorDistance = localDays && anchor != null ? _localDistance(anchor, item) : null;
        final itemId = item['activityId'];
        if (travel == null || (localDays && anchor != null && anchorDistance == null)) {
          reasons[itemId] = _unknownJourney;
          continue;
        }
        if (localDays && (travel.minutes > limits.leg || (travel.distance ?? 0) > limits.km ||
            (anchorDistance ?? 0) > limits.km || dailyTravel + travel.minutes > dailyLimit)) {
          reasons[itemId] = _distantStop;
          continue;
        }
        final experience = experiences[itemId] ?? '';
        final repeatLimit = hikeFocused || experience == 'meal' ? 2 : 1;
        if (localDays && const {'hike', 'meal'}.contains(experience) &&
            (experienceCounts[experience] ?? 0) >= repeatLimit) {
          reasons[itemId] = 'This day already includes similar activities. Try another day to allow time for rest and variety.';
          continue;
        }
        var arrival = current + travel.minutes;
        if (localDays && current < rest[1] && arrival > rest[0]) {
          arrival = rest[1] + travel.minutes;
        }
        var itemStart = max(arrival, opening.start ?? 0);
        if (itemStart < rest[1] && itemStart + duration.minutes > rest[0]) itemStart = rest[1];
        final itemEnd = itemStart + duration.minutes;
        if (itemEnd > window[1] || (opening.end != null && itemEnd > opening.end!)) continue;
        chosen = {
          ...item,
          'recommendedDurationMinutes': duration.minutes,
          'durationSource': duration.source,
          'durationEstimated': duration.source != 'provider',
          'travelBufferMinutes': travel.minutes,
          'travelDurationMinutes': travel.minutes,
          'travelDistanceKm': localDays && travel.distance != null
              ? double.parse(travel.distance!.toStringAsFixed(2)) : travel.distance,
          'travelTimeSource': travel.source,
          'openingHoursStatus': opening.status,
          'dayNo': dayNo,
          'dayDate': dateKey,
          'dayLabel': 'Day $dayNo · $dateKey',
          'sequenceNo': scheduled.length + 1,
          'timeSlot': _time(itemStart),
          'scheduledStartTime': _time(itemStart),
          'scheduledEndTime': _time(itemEnd),
          'timeRangeLabel': '${_time(itemStart)} - ${_time(itemEnd)}',
          'weather': dayWeather,
          'weatherNote': dayWeather['heavyRainLikely'] == true
              ? (_indoor(item)
                  ? 'Indoor activity prioritised because heavy rain is forecast for this date.'
                  : 'Rain is forecast; keep an indoor alternative available.')
              : '',
          'scheduleNotes': [
            if (travel.source == 'unverified_access_buffer')
              localDays
                  ? 'Access transfer requires confirmation; the planning buffer is not a verified journey time or walking route.'
                  : 'Access transfer requires confirmation; 25 minutes is a planning buffer, not a verified journey time or walking route.',
            if (previous != null && travel.source == 'estimated_haversine')
              'Grouped with a nearby attraction to reduce estimated travel time.',
            if (opening.end != null && opening.end! <= 1080)
              'Scheduled before closing at ${_time(opening.end!)}.',
          ],
        };
        if (localDays) {
          if (experience.isNotEmpty) {
            experienceCounts.update(experience, (count) => count + 1, ifAbsent: () => 1);
            tripExperiences.update(experience, (count) => count + 1, ifAbsent: () => 1);
          }
          usedConcepts.addAll(concepts[itemId] ?? const {});
          dailyTravel += travel.minutes;
          if (_coordinates(item) != null) focus ??= item;
        }
        chosenEnd = itemEnd;
        break;
      }
      if (chosen == null) break;
      remaining.removeWhere((item) => '${item['activityId']}' == '${chosen!['activityId']}');
      dayItems.add(chosen);
      scheduled.add(chosen);
      previous = chosen;
      current = chosenEnd;
      if (flexible && dayItems.length == 1) {
        final compatible = focus == null ? remaining.length : remaining.where((item) =>
            (_localDistance(focus!, item) ?? double.infinity) <= limits.km && canStartDay(item)).length;
        visitLimit = min(visitLimit!, max(1, 1 + compatible - futureLocalDays));
      }
    }
    if (localDays && dayItems.isNotEmpty && focus != null && !sightseeingAnchors.contains(focus)) {
      sightseeingAnchors.add(focus);
    }
    daily.add({
      'dayNo': dayNo,
      'dayDate': dateKey,
      'dayLabel': 'Day $dayNo · $dateKey',
      'planningWindow': {'startTime': _time(window[0]), 'endTime': _time(window[1]), 'pace': pace},
      'activities': dayItems,
      'planningBlocks': transferBlock != null ? [transferBlock] : dayItems.isEmpty
          ? []
          : [
              {
                'type': 'meal_rest',
                'label': 'Lunch and rest',
                'startTime': _time(rest[0]),
                'endTime': _time(rest[1]),
                'durationMinutes': rest[1] - rest[0],
                'estimated': true,
              }
            ],
      'weather': dayWeather,
      'estimatedMinutes': dayItems.fold<int>(
          (transferBlock?['durationMinutes'] as int?) ?? 0,
          (sum, item) =>
              sum + _number(item['recommendedDurationMinutes']).round() + _number(item['travelDurationMinutes']).round()),
      'estimatedCost': dayItems.fold<double>(0, (sum, item) => sum + (plannedActivityAmount(item, travellers) ?? 0)),
    });
  }
  String unscheduledReason(Map<String, dynamic> item) {
    if (_opening(item['openingHours']).status == 'closed') {
      return 'Attraction is closed on all trip days.';
    }
    if (sightseeingAnchors.isNotEmpty) {
      if (_conflictingLocation(item) || _coordinates(item) == null) return _unknownJourney;
      if (sightseeingAnchors.every((anchor) =>
          (_localDistance(anchor, item) ?? 0) > limits.km)) return _distantStop;
    }
    return reasons[item['activityId']] ?? 'Could not fit within available time, travel, and opening-hour constraints.';
  }
  final unscheduled = remaining
      .map((item) => {
            ...item,
            'unscheduledReason': unscheduledReason(item),
          })
      .toList();
  if (tripWide && (scheduled.length + unscheduled.length != inputIds.length ||
      ![...scheduled, ...unscheduled].map((row) => row['activityId']).toSet().containsAll(inputIds))) {
    throw StateError('Generated schedule contains inconsistent activity identifiers.');
  }
  return {
    ...trip,
    'activities': scheduled,
    'unscheduledSuggestions': unscheduled,
    if (transfer != null) 'intercityTransferStatus': transferApplied ? 'planned' : 'needs_review',
    'scheduledActivityCount': scheduled.length,
    'unscheduledActivityCount': unscheduled.length,
    'tripDays': days,
    'paceApplied': pace,
    'dailyPlanningWindow': {'startTime': _time(window[0]), 'endTime': _time(window[1])},
    'tripDateRangeLabel': '${_date(startDate)} to ${_date(startDate.add(Duration(days: days - 1)))}',
    'dailySchedule': daily,
    'totalScheduledMinutes': daily.fold<int>(0, (sum, day) => sum + _number(day['estimatedMinutes']).round()),
  };
}
