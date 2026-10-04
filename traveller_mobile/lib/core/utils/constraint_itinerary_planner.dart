import 'dart:math';

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
  return latitude == null || longitude == null ? null : [latitude, longitude];
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
  return radius * 2 * atan2(sqrt(h), sqrt(1 - h));
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
  final distance = _distance(previous, item);
  if (distance == null) return (minutes: 25, distance: null, source: 'estimated_default');
  return (
    minutes: max(8, (((distance * 1.25) / 28) * 60 + 8).round()),
    distance: double.parse(distance.toStringAsFixed(2)),
    source: 'estimated_haversine'
  );
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

Map<String, dynamic> planConstraintAwareItinerary(
  Map<String, dynamic> source, {
  Map<String, dynamic> forecast = const {},
  bool preserveOrder = false,
  bool respectDayAssignments = false,
}) {
  final trip = Map<String, dynamic>.from(source);
  final remaining = (trip['activities'] as List? ?? [])
      .whereType<Map>()
      .map((item) => Map<String, dynamic>.from(item))
      .toList();
  for (final raw in (trip['unscheduledSuggestions'] as List? ?? []).whereType<Map>()) {
    final item = Map<String, dynamic>.from(raw)..remove('unscheduledReason');
    if (!remaining.any((existing) => '${existing['activityId']}' == '${item['activityId']}')) {
      remaining.add(item);
    }
  }
  final days = _days(trip);
  final startDate = DateTime.tryParse('${trip['startDate'] ?? ''}') ?? DateTime.now();
  final pace = _pace(trip);
  final window = itineraryPaceWindows[pace]!;
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
    Map<String, dynamic>? previous;
    final dayItems = <Map<String, dynamic>>[];
    while (remaining.isNotEmpty) {
      final eligible = remaining
          .where((item) => !respectDayAssignments || _number(item['dayNo'], dayNo.toDouble()).round() == dayNo)
          .toList();
      if (eligible.isEmpty) break;
      if (!preserveOrder) {
        eligible.sort((a, b) {
          final rainA = dayWeather['heavyRainLikely'] == true && _indoor(a) ? 0 : 1;
          final rainB = dayWeather['heavyRainLikely'] == true && _indoor(b) ? 0 : 1;
          if (rainA != rainB) return rainA.compareTo(rainB);
          final closeA = _opening(a['openingHours']).end ?? 1440;
          final closeB = _opening(b['openingHours']).end ?? 1440;
          if (closeA != closeB) return closeA.compareTo(closeB);
          return (_distance(previous ?? a, a) ?? 99999).compareTo(_distance(previous ?? b, b) ?? 99999);
        });
      }
      Map<String, dynamic>? chosen;
      var chosenEnd = 0;
      for (final item in eligible) {
        final opening = _opening(item['openingHours']);
        if (opening.status == 'closed') continue;
        final duration = _duration(item);
        final travel = _travel(previous, item);
        var itemStart = max(current + travel.minutes, opening.start ?? 0);
        if (itemStart < 810 && itemStart + duration.minutes > 750) itemStart = 810;
        final itemEnd = itemStart + duration.minutes;
        if (itemEnd > window[1] || (opening.end != null && itemEnd > opening.end!)) continue;
        chosen = {
          ...item,
          'recommendedDurationMinutes': duration.minutes,
          'durationSource': duration.source,
          'durationEstimated': duration.source != 'provider',
          'travelBufferMinutes': travel.minutes,
          'travelDurationMinutes': travel.minutes,
          'travelDistanceKm': travel.distance,
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
            if (previous != null && travel.source == 'estimated_haversine')
              'Grouped with a nearby attraction to reduce estimated travel time.',
            if (opening.end != null && opening.end! <= 1080)
              'Scheduled before closing at ${_time(opening.end!)}.',
          ],
        };
        chosenEnd = itemEnd;
        break;
      }
      if (chosen == null) break;
      remaining.removeWhere((item) => '${item['activityId']}' == '${chosen!['activityId']}');
      dayItems.add(chosen);
      scheduled.add(chosen);
      previous = chosen;
      current = chosenEnd;
    }
    daily.add({
      'dayNo': dayNo,
      'dayDate': dateKey,
      'dayLabel': 'Day $dayNo · $dateKey',
      'planningWindow': {'startTime': _time(window[0]), 'endTime': _time(window[1]), 'pace': pace},
      'activities': dayItems,
      'planningBlocks': dayItems.isEmpty
          ? []
          : [
              {
                'type': 'meal_rest',
                'label': 'Lunch and rest',
                'startTime': '12:30',
                'endTime': '13:30',
                'durationMinutes': 60,
                'estimated': true,
              }
            ],
      'weather': dayWeather,
      'estimatedMinutes': dayItems.fold<int>(
          0,
          (sum, item) =>
              sum + _number(item['recommendedDurationMinutes']).round() + _number(item['travelDurationMinutes']).round()),
      'estimatedCost': dayItems.fold<double>(0, (sum, item) => sum + _number(item['estimatedCost'])),
    });
  }
  final unscheduled = remaining
      .map((item) => {
            ...item,
            'unscheduledReason': _opening(item['openingHours']).status == 'closed'
                ? 'Attraction is closed on all trip days.'
                : 'Could not fit within available time, travel, and opening-hour constraints.',
          })
      .toList();
  return {
    ...trip,
    'activities': scheduled,
    'unscheduledSuggestions': unscheduled,
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
