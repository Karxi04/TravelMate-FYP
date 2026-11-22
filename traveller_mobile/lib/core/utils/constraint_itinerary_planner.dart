import 'dart:math';

import 'itinerary_identity.dart';
import 'opening_hours_utils.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/planning_time_validation.dart';
import 'malaysian_locality.dart';
import 'recommendation_taxonomy.dart';

const localDaysPolicy = 'local-days-v1';
const _unknownJourney =
    'Could not establish a reliable journey to this stop. Confirm its location or plan a separate day.';
const _distantStop =
    'This stop is too far from the other stops or accommodation for this sightseeing day. Choose a nearer stop or plan an intercity transfer.';
const localActivityFields = [
  'city',
  'state',
  'country',
  'district',
  'locality',
  'normalizedGeography',
  'geographyConflict',
  'metadataConflict',
  'type_id',
  'type_ids',
  'tags',
  'interests',
  'subtype',
  'verifiedDestinationEvidence',
  'providerTravelFromDestinationId',
  'providerTravelDurationMinutes',
  'providerTravelDistanceKm',
  'providerTravelMode',
];

const Map<String, List<int>> itineraryPaceWindows = {
  'relaxed': [600, 1200],
  'moderate': [540, 1260],
  'active': [480, 1290],
};

double _number(dynamic value, [double fallback = 0]) => double.tryParse('${value ?? ''}') ?? fallback;

String _time(int minutes) =>
    '${(minutes ~/ 60).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}';

String _date(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

String _pace(Map<String, dynamic> trip) {
  final value = (trip['travelPace'] ?? trip['pace'] ?? trip['preferredPace'] ?? '').toString().toLowerCase();
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
  final match = RegExp(r'\b(\d{1,2})(?::|\.)?(\d{0,2})\s*(AM|PM)?\b', caseSensitive: false).firstMatch(value.trim());
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

({String status, int? start, int? end, List<(int, int)> periods, bool provisional}) _opening(
    Map<String, dynamic> item, DateTime day) {
  final detail = {...item};
  // Reuse destination hours; current "open now" is not a future timetable.
  for (final key in ['operating_hours', 'opening_hours', 'openingHours', 'hours']) {
    final value = detail[key];
    if (value is String && RegExp(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s*:', caseSensitive: false).hasMatch(value)) {
      detail['weekday_text'] = value.split(RegExp(r';|\n'));
      detail.remove(key);
      break;
    }
  }
  final schedule = OpeningHoursUtils.parse(detail);
  final permanent = item['permanently_closed'] == true ||
      item['business_status'] == 'CLOSED_PERMANENTLY' ||
      RegExp(r'permanently\s+closed|closed\s+permanently', caseSensitive: false)
          .hasMatch('${item['openingHours'] ?? ''}');
  String hours(DateTime date) =>
      schedule.hasWeeklySchedule ? schedule.weeklyHours[date.weekday - 1].value : schedule.genericHours ?? '';
  List<(int, int)> periods(String text) {
    if (text.toLowerCase().contains('24 hour') || text.toLowerCase().contains('24/7')) return [(0, 1440)];
    if (RegExp(r'\b(?:now|currently)\b', caseSensitive: false).hasMatch(text)) return [];
    return [
      for (final match in RegExp(
              r'(\d{1,2}(?::|\.)?\d{0,2}\s*(?:AM|PM)?)\s*(?:–|—|-)\s*(\d{1,2}(?::|\.)?\d{0,2}\s*(?:AM|PM)?)',
              caseSensitive: false)
          .allMatches(text))
        if (_clock(match.group(1)!) != null && _clock(match.group(2)!) != null)
          (
            _clock(match.group(1)!)!,
            _clock(match.group(2)!)! + (_clock(match.group(2)!)! <= _clock(match.group(1)!)! ? 1440 : 0)
          )
    ];
  }

  final text = hours(day);
  final ranges = permanent
      ? <(int, int)>[]
      : [
          ...periods(hours(day.subtract(const Duration(days: 1))))
              .where((period) => period.$2 > 1440)
              .map((period) => (0, period.$2 - 1440)),
          ...periods(text)
        ]
    ..sort((a, b) => a.$1.compareTo(b.$1));
  final status = permanent || ranges.isEmpty && text.toLowerCase() == 'closed'
      ? 'closed'
      : ranges.isEmpty
          ? 'unknown'
          : 'open';
  return (
    status: status,
    start: ranges.firstOrNull?.$1,
    end: ranges.isEmpty ? null : ranges.map((row) => row.$2).reduce(max),
    periods: ranges,
    provisional: status == 'unknown' ||
        item['openingHoursStale'] == true ||
        RegExp(r'\b(?:now|currently)\b', caseSensitive: false).hasMatch(text)
  );
}

bool _protected(Map<String, dynamic> row) =>
    const [
      'completedAt',
      'paidAt',
      'paymentId',
      'paymentRecordId',
      'bookingId',
      'bookingReference',
      'hotelBookingId',
      'supplierArrangementId',
      'checkoutOrderId',
      'paid',
      'completed',
      'locked',
      'isLocked',
      'fixed',
      'protected',
      'userFixed',
      'manualTime',
      'manualOrder',
      'userEdited',
      'packageIncluded',
      'required'
    ].any((key) => row[key] != null && row[key] != false && row[key] != 0 && row[key] != '') ||
    const ['manual', 'user'].contains(row['editProvenance']) ||
    const ['status', 'paymentStatus', 'bookingStatus'].any((key) =>
        const ['paid', 'succeeded', 'completed', 'booked', 'confirmed', 'settled', 'fulfilled'].contains('${row[key] ?? ''}'.toLowerCase()));

List<int> _dayWindow(Map<String, dynamic> trip, DateTime day, int dayNo, List<int> base) {
  final prefs = Map<String, dynamic>.from(trip['travelDayPreferences'] as Map? ?? {});
  final overrides = (prefs['days'] as List? ?? []).whereType<Map>();
  for (final row in overrides) {
    if (row['restDay'] == true) continue;
    final left = planningMinutes(row['startTime']), right = planningMinutes(row['endTime']);
    if (row['dayNo'] is! int ||
        row['dayNo'] < 1 ||
        row['dayNo'] > _days(trip) ||
        left == null ||
        right == null ||
        left >= right) {
      throw ArgumentError('Choose a valid same-day sightseeing window.');
    }
  }
  final override = overrides.where((row) => row['dayNo'] == dayNo).firstOrNull;
  final bounds = planningTravelBounds(trip, prefs);
  var start = planningMinutes(override?['startTime']) ?? base[0];
  var end = planningMinutes(override?['endTime']) ?? base[1];
  final arrivalDay = bounds.arrival == null ? dayNo == 1 : _date(day) == _date(bounds.arrival!);
  final departureDay = bounds.departure == null ? dayNo == _days(trip) : _date(day) == _date(bounds.departure!);
  if (arrivalDay) start = max(start, planningMinutes((prefs['arrival'] as Map?)?['startTime']) ?? 0);
  if (departureDay) end = min(end, planningMinutes((prefs['departure'] as Map?)?['endTime']) ?? 1440);
  if (bounds.arrival != null) {
    if (_date(day).compareTo(_date(bounds.arrival!)) < 0) return [start, start];
    if (arrivalDay) start = max(start, bounds.arrival!.hour * 60 + bounds.arrival!.minute);
  }
  if (bounds.departure != null) {
    if (_date(day).compareTo(_date(bounds.departure!)) > 0) return [start, start];
    if (departureDay) end = min(end, bounds.departure!.hour * 60 + bounds.departure!.minute);
  }
  if (override?['restDay'] == true ||
      arrivalDay && (prefs['arrival'] as Map?)?['choice'] == 'none' ||
      departureDay && (prefs['departure'] as Map?)?['choice'] == 'none') end = start;
  return [start, end];
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
  var remaining =
      (trip['activities'] as List? ?? []).whereType<Map>().map((item) => Map<String, dynamic>.from(item)).toList();
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
      if (_protected(row) || row['dayNo'] != null && repeats.any((repeat) => sameAttraction(row, repeat)))
        row['activityId'],
  };
  if (tripWide && inputIds.length != remaining.length) {
    throw StateError('Generated schedule contains duplicate activity identifiers.');
  }
  final travellers = max(1, _number(trip['travellerCount'] ?? trip['numberOfTravellers'], 1).round());
  final days = _days(trip);
  final startDate = DateTime.tryParse('${trip['startDate'] ?? ''}') ?? DateTime.now();
  final pace = _pace(trip);
  final baseWindow = [...itineraryPaceWindows[pace]!];
  final rhythm = (trip['sleepingType'] ?? '').toString().toLowerCase();
  if (rhythm == 'early riser') {
    baseWindow[0] = max(450, baseWindow[0] - 60);
    baseWindow[1] -= 60;
  } else if (rhythm == 'night owl') {
    baseWindow[0] = max(baseWindow[0], 660);
  } else if (rhythm == 'comfort-focused') {
    baseWindow[0] = max(baseWindow[0], 600);
  }
  final defaultRest = rhythm == 'night owl' ? [840, 900] : [750, rhythm == 'comfort-focused' ? 840 : 810];
  final preferences = (trip['planningPreferences'] as Map?) ?? const {};
  final profiled = preferences.isNotEmpty;
  final localDays = trip['geographyPlanningPolicy'] == localDaysPolicy;
  final mode = _sightseeingMode(trip);
  final limits = _localLimits[mode]!;
  final dailyLimit = (limits.day * (pace == 'relaxed' ? .75 : 1)).floor();
  final requested = trip['interests'] ?? trip['requestedInterests'] ?? preferences['interests'];
  final interests = RecommendationTaxonomy.conceptsFor(requested);
  final hikeFocused = trip['hikingFocused'] == true ||
      (requested is List &&
          requested
              .any((value) => const {'hiking', 'hike', 'trekking'}.contains(value.toString().trim().toLowerCase())));
  final usedConcepts = <String>{};
  final reasons = <dynamic, String>{};
  final sightseeingAnchors = <Map<String, dynamic>>[];
  final experiences = {
    if (localDays)
      for (final item in remaining) item['activityId']: _experience(item)
  };
  final concepts = {
    if (localDays && interests.isNotEmpty)
      for (final item in remaining)
        item['activityId']: RecommendationTaxonomy.primaryConcepts({...item, 'title': item['activityName']})
  };
  final tripExperiences = <String, int>{};
  final baseInfo = trip['accommodationBase'] ?? trip['selectedHotel'];
  final baseCandidate = baseInfo is Map ? Map<String, dynamic>.from(baseInfo) : null;
  var base = baseCandidate != null && _coordinates(baseCandidate) != null && !_conflictingLocation(baseCandidate)
      ? baseCandidate
      : null;
  Map<String, dynamic>? focus = base;
  final transfer = localDays ? trip['confirmedIntercityTransfer'] as Map? : null;
  var transferApplied = false;
  final rank = {for (var i = 0; i < remaining.length; i++) remaining[i]['activityId']: i};
  final maxVisits = (profiled || localDays && pace == 'relaxed') && !respectDayAssignments
      ? const {'relaxed': 2, 'moderate': 3, 'active': 5}[pace]
      : null;
  final weather = _weatherByDate(forecast);
  final scheduled = <Map<String, dynamic>>[];
  final daily = <Map<String, dynamic>>[];

  for (var dayIndex = 0; dayIndex < days; dayIndex++) {
    final dayNo = dayIndex + 1;
    final dayDate = startDate.add(Duration(days: dayIndex));
    final dateKey = _date(dayDate);
    final window = _dayWindow(trip, dayDate, dayNo, baseWindow);
    final blocks =
        (trip['planningBlocks'] as List? ?? []).whereType<Map>().where((row) => row['dayNo'] == dayNo).toList();
    final rest = blocks.any((row) => row['type'] == 'meal') ? [0, 0] : defaultRest;
    final dayWeather = weather[dateKey] ??
        {
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
          ? _localLeg(focus, target, transferMode.toString())
          : null;
      if (leg != null &&
          leg.source != 'unverified_access_buffer' &&
          (leg.minutes > limits.leg || (leg.distance ?? 0) > limits.km) &&
          leg.minutes + 60 <= min(600, 1260 - current) &&
          transferMode != 'walk') {
        transferApplied = true;
        final duration = leg.minutes + 60;
        transferBlock = {
          'type': 'intercity_transfer',
          'label': 'Intercity transfer and breaks',
          'startTime': _time(current),
          'endTime': _time(current + duration),
          'durationMinutes': duration,
          'estimated': true,
          'destinationId': target!['destinationId'],
        };
        base = null;
        focus = target;
      }
    }
    var visitLimit = maxVisits;
    bool canStartDay(Map<String, dynamic> item) {
      final opening = _opening(item, dayDate);
      var start = max(window[0], opening.start ?? 0);
      final duration = _duration(item).minutes;
      if (start < rest[1] && start + duration > rest[0]) start = rest[1];
      return opening.status != 'closed' && start + duration <= min(window[1], opening.end ?? 1440);
    }

    final flexible = localDays && !respectDayAssignments && !preserveOrder;
    final transferDay = transfer?['dayNo'];
    final lastLocalDay = transferDay is int && transferDay > dayNo && transferDay <= days ? transferDay - 1 : days;
    final futureLocalDays = lastLocalDay - dayNo;
    if (flexible) {
      visitLimit = min(maxVisits ?? 5, max(1, remaining.length - futureLocalDays));
    }
    while (transferBlock == null && remaining.isNotEmpty && (visitLimit == null || dayItems.length < visitLimit)) {
      final eligible = remaining
          .where((item) =>
              (!respectDayAssignments && !pinned.contains(item['activityId'])) ||
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
            if (focus != null && coverageOrder != 0) return coverageOrder;
            if (focus == null) {
              List<Map<String, dynamic>> cluster(Map<String, dynamic> item) => eligible.where((other) {
                    final leg = _localLeg(item, other, mode);
                    return leg != null && (leg.distance ?? double.infinity) <= limits.km && leg.minutes <= limits.leg;
                  }).toList();
              final clusterA = cluster(a);
              final clusterB = cluster(b);
              Set<String> coverage(List<Map<String, dynamic>> rows) => {
                    for (final row in rows) ...?concepts[row['activityId']],
                  }.intersection(interests);
              final categoryOrder = coverage(clusterB).length.compareTo(coverage(clusterA).length);
              if (categoryOrder != 0) return categoryOrder;
              final variety = clusterB
                  .map((row) => experiences[row['activityId']])
                  .whereType<String>()
                  .where((v) => v.isNotEmpty)
                  .toSet()
                  .length
                  .compareTo(clusterA
                      .map((row) => experiences[row['activityId']])
                      .whereType<String>()
                      .where((v) => v.isNotEmpty)
                      .toSet()
                      .length);
              if (variety != 0) return variety;
              final grouping = min(4, clusterB.length).compareTo(min(4, clusterA.length));
              if (grouping != 0) return grouping;
            }
            if (coverageOrder != 0) return coverageOrder;
            final expA = experiences[a['activityId']];
            final expB = experiences[b['activityId']];
            final dailyVariety = (experienceCounts[expA] ?? 0).compareTo(experienceCounts[expB] ?? 0);
            if (dailyVariety != 0) return dailyVariety;
            final tripVariety = (tripExperiences[expA] ?? 0).compareTo(tripExperiences[expB] ?? 0);
            if (tripVariety != 0) return tripVariety;
            if (previous != null) {
              final proximity =
                  ((_localDistance(previous, a) ?? 0) ~/ 4).compareTo((_localDistance(previous, b) ?? 0) ~/ 4);
              if (proximity != 0) return proximity;
            }
          }
          if (pace == 'relaxed' && visitLimit == 2 && !respectDayAssignments)
            return rank[a['activityId']]!.compareTo(rank[b['activityId']]!);
          final closeA = _opening(a, dayDate).end ?? 1440;
          final closeB = _opening(b, dayDate).end ?? 1440;
          if (closeA != closeB) return closeA.compareTo(closeB);
          if (profiled) return rank[a['activityId']]!.compareTo(rank[b['activityId']]!);
          return (_distance(previous ?? a, a) ?? 99999).compareTo(_distance(previous ?? b, b) ?? 99999);
        });
      }
      Map<String, dynamic>? tryVisit(Map<String, dynamic> item, [List<Map<String, dynamic>> trial = const []]) {
        final prior = trial.isEmpty ? previous : trial.last;
        final cursor = trial.isEmpty ? current : planningMinutes(trial.last['scheduledEndTime'])!;
        if ([...dayItems, ...trial].any((visit) =>
            sameAttraction(item, visit) &&
            (savedDays[item['activityId']] != dayNo || savedDays[visit['activityId']] != dayNo))) {
          return null;
        }
        final opening = _opening(item, dayDate);
        if (opening.status == 'closed') return null;
        final duration = _duration(item);
        final travel = localDays ? _localLeg(prior, item, mode) : _travel(prior, item);
        final anchor = focus ?? [...dayItems, ...trial].firstOrNull;
        final anchorDistance = localDays && anchor != null ? _localDistance(anchor, item) : null;
        final itemId = item['activityId'];
        if (travel == null || (localDays && anchor != null && anchorDistance == null)) {
          reasons[itemId] = _unknownJourney;
          return null;
        }
        if (localDays &&
            (travel.minutes > limits.leg ||
                (travel.distance ?? 0) > limits.km ||
                (anchorDistance ?? 0) > limits.km ||
                dailyTravel +
                        trial.fold<int>(0, (sum, row) => sum + row['travelDurationMinutes'] as int) +
                        travel.minutes >
                    dailyLimit)) {
          reasons[itemId] = _distantStop;
          return null;
        }
        final budgetLimit = _number(trip['budgetLimit']);
        if (localDays && interests.length > 1 && budgetLimit > 0) {
          final estimate = trip['budgetEstimate'] as Map? ?? const {};
          final previousActivityCost = _number(estimate['activities']);
          final fixedCost = max(0, _number(estimate['totalEstimatedCost']) - previousActivityCost);
          final activityCost = [...scheduled, ...trial, item]
              .fold<double>(0, (sum, row) => sum + (plannedActivityAmount(row, travellers) ?? 0));
          if (fixedCost + activityCost > budgetLimit) {
            reasons[itemId] = 'This activity would exceed the total trip budget using the current estimates.';
            return null;
          }
        }
        final experience = experiences[itemId] ?? '';
        final repeatLimit = hikeFocused || experience == 'meal' ? 2 : 1;
        if (localDays &&
            const {'hike', 'meal'}.contains(experience) &&
            (experienceCounts[experience] ?? 0) + trial.where((row) => _experience(row) == experience).length >=
                repeatLimit) {
          reasons[itemId] =
              'This day already includes similar activities. Try another day to allow time for rest and variety.';
          return null;
        }
        var arrival = cursor + travel.minutes;
        if (localDays && cursor < rest[1] && arrival > rest[0]) {
          arrival = rest[1] + travel.minutes;
        }
        final reserved = <(int, int)>[
          for (final block in blocks)
            if (planningMinutes(block['startTime']) != null && planningMinutes(block['endTime']) != null)
              (planningMinutes(block['startTime'])!, planningMinutes(block['endTime'])!),
          for (final row in (source['activities'] as List? ?? []).whereType<Map>())
            if (row['activityId'] != itemId &&
                row['dayNo'] == dayNo &&
                _protected(Map<String, dynamic>.from(row)) &&
                planningMinutes(row['scheduledStartTime'] ?? row['timeSlot']) != null &&
                planningMinutes(row['scheduledEndTime']) != null)
              (
                planningMinutes(row['scheduledStartTime'] ?? row['timeSlot'])!,
                planningMinutes(row['scheduledEndTime'])!
              )
        ]..sort((a, b) => a.$1.compareTo(b.$1));
        final fixed = _protected(item) && (item['scheduledStartTime'] != null ||
            _protected({...item}..remove('required')..remove('packageIncluded')));
        final fixedStart = planningMinutes(item['scheduledStartTime'] ?? item['timeSlot']);
        final fixedEnd = planningMinutes(item['scheduledEndTime']);
        if (fixed && (fixedStart == null || fixedStart < arrival || fixedEnd != null && fixedEnd <= fixedStart))
          return null;
        final minutes = fixed && fixedEnd != null ? fixedEnd - fixedStart! : duration.minutes;
        int? itemStart, itemEnd;
        for (final period in opening.periods.isEmpty ? [(0, 1440)] : opening.periods) {
          var start = fixed ? fixedStart! : max(arrival, period.$1);
          for (var pass = 0; pass <= reserved.length + 1; pass++) {
            final before = start;
            if (!fixed && start < rest[1] && start + minutes > rest[0]) start = rest[1];
            for (final block in reserved) {
              if (start < block.$2 && start + minutes > block.$1) start = block.$2;
            }
            if (fixed && start != before) return null;
            if (start == before) break;
          }
          if (start >= period.$1 && start + minutes <= min(window[1], period.$2)) {
            itemStart = start;
            itemEnd = start + minutes;
            break;
          }
        }
        if (itemStart == null || itemEnd == null) return null;
        return {
          ...item,
          'recommendedDurationMinutes': minutes,
          'durationSource': duration.source,
          'durationEstimated': duration.source != 'provider',
          'travelBufferMinutes': travel.minutes,
          'travelDurationMinutes': travel.minutes,
          'travelDistanceKm': localDays && travel.distance != null
              ? double.parse(travel.distance!.toStringAsFixed(2))
              : travel.distance,
          'travelTimeSource': travel.source,
          'openingHoursStatus': opening.status,
          'scheduleFeasibility': opening.provisional ? 'provisional' : 'feasible_with_reported_hours',
          'openingHoursEvidence': {
            'source': item['openingHoursSource'] ?? 'unspecified',
            'freshness': item['openingHoursStale'] == true ? 'reported_stale' : 'unverified'
          },
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
            if (opening.provisional)
              'Provisional visit time: opening hours are unknown, transient or stale. Confirm with the venue before visiting.'
            else
              'Fits one reported opening period; current hours and special-date closures are not verified.',
            if (travel.source == 'unverified_access_buffer')
              localDays
                  ? 'Access transfer requires confirmation; the planning buffer is not a verified journey time or walking route.'
                  : 'Access transfer requires confirmation; 25 minutes is a planning buffer, not a verified journey time or walking route.',
            if (prior != null && travel.source == 'estimated_haversine')
              'Grouped with a nearby attraction to reduce estimated travel time.',
            if (opening.end != null && opening.end! <= 1080) 'Scheduled before closing at ${_time(opening.end!)}.',
          ],
        };
      }

      if (pace == 'relaxed' && visitLimit == 2 && !preserveOrder && !respectDayAssignments && dayItems.isEmpty) {
        // Bounded two-visit lookahead, with the same feasibility checks as scheduling.
        final candidates = eligible.take(20).toList();
        final pairs = [
          for (var i = 0; i < candidates.length; i++)
            for (var j = i + 1; j < candidates.length; j++) (i, j)
        ]..sort((a, b) {
            final total = (a.$1 + a.$2).compareTo(b.$1 + b.$2);
            return total != 0 ? total : a.$1.compareTo(b.$1);
          });
        final firstVisits = <int, Map<String, dynamic>?>{};
        for (final pair in pairs) {
          final feasible = <(int, int, int)>[];
          for (final order in [pair, (pair.$2, pair.$1)]) {
            final first = firstVisits.putIfAbsent(order.$1, () => tryVisit(candidates[order.$1]));
            final second = first == null ? null : tryVisit(candidates[order.$2], [first]);
            if (second != null)
              feasible.add((
                planningMinutes(second['scheduledEndTime'])!,
                (first!['travelDurationMinutes'] as int) + (second['travelDurationMinutes'] as int),
                order.$1
              ));
          }
          feasible.sort((a, b) {
            final end = a.$1.compareTo(b.$1);
            if (end != 0) return end;
            final travel = a.$2.compareTo(b.$2);
            return travel != 0 ? travel : a.$3.compareTo(b.$3);
          });
          if (feasible.isNotEmpty) {
            final first = candidates[feasible.first.$3];
            eligible.remove(first);
            eligible.insert(0, first);
            break;
          }
        }
      }
      Map<String, dynamic>? chosen;
      var chosenEnd = 0;
      for (final item in eligible) {
        chosen = tryVisit(item);
        if (chosen == null) continue;
        if (localDays) {
          final experience = experiences[item['activityId']] ?? '';
          if (experience.isNotEmpty) {
            experienceCounts.update(experience, (count) => count + 1, ifAbsent: () => 1);
            tripExperiences.update(experience, (count) => count + 1, ifAbsent: () => 1);
          }
          usedConcepts.addAll(concepts[item['activityId']] ?? const {});
          dailyTravel += chosen['travelDurationMinutes'] as int;
          if (_coordinates(item) != null) focus ??= item;
        }
        chosenEnd = planningMinutes(chosen['scheduledEndTime'])!;
        break;
      }
      if (chosen == null) break;
      remaining.removeWhere((item) => '${item['activityId']}' == '${chosen!['activityId']}');
      dayItems.add(chosen);
      scheduled.add(chosen);
      previous = chosen;
      current = chosenEnd;
      if (flexible) {
        final compatible = focus == null
            ? remaining.length
            : remaining
                .where((item) => (_localDistance(focus!, item) ?? double.infinity) <= limits.km && canStartDay(item))
                .length;
        visitLimit =
            min(visitLimit!, max(dayItems.length, ((dayItems.length + compatible) / (futureLocalDays + 1)).ceil()));
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
      'planningBlocks': [
        ...blocks,
        ...(transferBlock != null
            ? [transferBlock]
            : dayItems.isEmpty || rest[1] <= rest[0]
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
                  ])
      ],
      'weather': dayWeather,
      'estimatedMinutes': dayItems.fold<int>(
          (transferBlock?['durationMinutes'] as int?) ?? 0,
          (sum, item) =>
              sum +
              _number(item['recommendedDurationMinutes']).round() +
              _number(item['travelDurationMinutes']).round()),
      'estimatedCost': dayItems.fold<double>(0, (sum, item) => sum + (plannedActivityAmount(item, travellers) ?? 0)),
    });
  }
  String unscheduledReason(Map<String, dynamic> item) {
    if (List.generate(days, (i) => _opening(item, startDate.add(Duration(days: i))))
        .every((opening) => opening.status == 'closed')) {
      return 'Attraction is closed on all trip days.';
    }
    if (sightseeingAnchors.isNotEmpty) {
      if (_conflictingLocation(item) || _coordinates(item) == null) return _unknownJourney;
      if (sightseeingAnchors.every((anchor) => (_localDistance(anchor, item) ?? 0) > limits.km)) return _distantStop;
    }
    return reasons[item['activityId']] ?? 'Could not fit within available time, travel, and opening-hour constraints.';
  }

  final unscheduled = remaining
      .map((item) => {
            ...item,
            'unscheduledReason': unscheduledReason(item),
          })
      .toList();
  if (tripWide &&
      (scheduled.length + unscheduled.length != inputIds.length ||
          ![...scheduled, ...unscheduled].map((row) => row['activityId']).toSet().containsAll(inputIds))) {
    throw StateError('Generated schedule contains inconsistent activity identifiers.');
  }
  return {
    ...trip,
    'activities': scheduled,
    'unscheduledSuggestions': unscheduled,
    if (localDays)
      'interestCoverage': {
        'requested': interests.toList()..sort(),
        'candidates': {
          for (final interest in interests) interest: concepts.values.where((value) => value.contains(interest)).length
        },
        'scheduled': {
          for (final interest in interests)
            interest: scheduled.where((row) => concepts[row['activityId']]?.contains(interest) == true).length
        },
        'unrepresented': interests.difference(usedConcepts).toList()..sort(),
        'limitation': interests.difference(usedConcepts).isEmpty
            ? null
            : 'Some interests could not be included within the selected area, dates, budget and travel constraints.',
      },
    if (transfer != null) 'intercityTransferStatus': transferApplied ? 'planned' : 'needs_review',
    'scheduledActivityCount': scheduled.length,
    'unscheduledActivityCount': unscheduled.length,
    'tripDays': days,
    'paceApplied': pace,
    'dailyPlanningWindow': {'startTime': _time(baseWindow[0]), 'endTime': _time(baseWindow[1])},
    'tripDateRangeLabel': '${_date(startDate)} to ${_date(startDate.add(Duration(days: days - 1)))}',
    'dailySchedule': daily,
    'totalScheduledMinutes': daily.fold<int>(0, (sum, day) => sum + _number(day['estimatedMinutes']).round()),
  };
}
