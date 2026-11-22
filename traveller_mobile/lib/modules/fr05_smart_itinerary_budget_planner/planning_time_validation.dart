/// Draft feedback only; the Backend rechecks all constraints before applying.
int? planningMinutes(Object? value) {
  if (value is! String ||
      !RegExp(r'^(?:[01]\d|2[0-3]):[0-5]\d$').hasMatch(value)) return null;
  final parts = value.split(':').map(int.parse).toList();
  return parts[0] * 60 + parts[1];
}

Map<String, dynamic> _map(Object? value) =>
    value is Map ? Map<String, dynamic>.from(value) : {};
List<Map<String, dynamic>> _rows(Object? value) =>
    value is List ? value.map(_map).toList() : [];

({
  DateTime? arrival,
  DateTime? departure,
  bool incomplete
}) planningTravelBounds(Map<String, dynamic> trip, Map<String, dynamic> prefs) {
  DateTime? stamp(Object? date, Object? time) => planningMinutes(time) == null
      ? null
      : DateTime.tryParse('${date.toString().split('T').first}T$time');
  final flight = _map(trip['selectedFlight']);
  final out = _rows(flight['outboundSegments']),
      back = _rows(flight['returnSegments']);
  final assumptions = _map(trip['planningAssumptions']);
  if (flight.isNotEmpty) {
    final arrival = out.isEmpty
        ? null
        : stamp(out.last['arrivalDate'], out.last['arrivalTime']);
    final departure = back.isEmpty
        ? null
        : stamp(back.first['departureDate'], back.first['departureTime']);
    return (
      arrival: arrival?.add(Duration(
          minutes: (assumptions['arrivalClearanceMinutes'] as num? ?? 90)
                  .toInt() +
              (assumptions['arrivalTransferMinutes'] as num? ?? 90).toInt())),
      departure: departure?.subtract(Duration(
          minutes: (assumptions['departureTransferMinutes'] as num? ?? 90)
                  .toInt() +
              (assumptions['departureCheckinMinutes'] as num? ?? 120).toInt())),
      incomplete: arrival == null || back.isNotEmpty && departure == null
    );
  }
  final transport = _map(prefs['transport']);
  final buffer = int.tryParse('${transport['bufferMinutes'] ?? 0}') ?? 0;
  return (
    arrival: stamp(transport['arrivalDate'], transport['arrivalTime'])
        ?.add(Duration(minutes: buffer)),
    departure: stamp(transport['departureDate'], transport['departureTime'])
        ?.subtract(Duration(minutes: buffer)),
    incomplete: false
  );
}

String? planningTimeError(Map<String, dynamic> trip, Map<String, dynamic> prefs,
    List<Map<String, dynamic>> blocks) {
  final start = DateTime.tryParse('${trip['startDate']}'.split('T').first);
  final finish = DateTime.tryParse('${trip['endDate']}'.split('T').first);
  if (start == null || finish == null) return 'Check the trip dates.';
  final count = finish.difference(start).inDays + 1;
  final transport = _map(prefs['transport']);
  for (final kind in ['arrival', 'departure']) {
    if ((transport['${kind}Date'] == null) !=
        (transport['${kind}Time'] == null))
      return 'Choose both the $kind date and time, or clear the estimate.';
  }
  if (transport['arrivalDate'] != null &&
      transport['departureDate'] != null &&
      '${transport['arrivalDate']}T${transport['arrivalTime']}'.compareTo(
              '${transport['departureDate']}T${transport['departureTime']}') >=
          0) return 'Estimated departure must be after arrival.';
  final bounds = planningTravelBounds(trip, prefs);
  bool before(DateTime time) =>
      bounds.arrival != null && time.isBefore(bounds.arrival!);
  bool after(DateTime time) =>
      bounds.departure != null && time.isAfter(bounds.departure!);
  DateTime at(int day, int minutes) =>
      start.add(Duration(days: day - 1, minutes: minutes));
  for (final row in _rows(prefs['days'])) {
    if (row['restDay'] == true) continue;
    final left = planningMinutes(row['startTime']),
        right = planningMinutes(row['endTime']);
    final day = row['dayNo'];
    if (day is! int || day < 1 || day > count)
      return 'Choose a valid trip day.';
    if (left == null || right == null || right <= left)
      return 'Day $day: end time must be later than start time on the same day.';
    if (before(at(day, left)) || after(at(day, right)))
      return 'Day $day: these hours conflict with your travel times. Choose hours inside the arrival and departure limits.';
    for (final activity in _rows(trip['activities'])) {
      final a = planningMinutes(activity['scheduledStartTime']),
          b = planningMinutes(activity['scheduledEndTime']);
      final fixed = [
            'fixed',
            'locked',
            'manualTime',
            'userFixed',
            'isLocked',
            'protected',
            'userEdited',
            'manualOrder'
          ].any((key) => activity[key] == true) ||
          activity['paymentId'] != null ||
          activity['bookingId'] != null;
      if (fixed &&
          activity['dayNo'] == day &&
          a != null &&
          b != null &&
          (a < left || b > right)) {
        return 'Day $day: these hours exclude a fixed activity. Review its time or keep a wider window.';
      }
    }
  }
  for (final kind in ['arrival', 'departure']) {
    final row = _map(prefs[kind]);
    final time = row[kind == 'arrival' ? 'startTime' : 'endTime'];
    if ({'custom', 'rest'}.contains(row['choice']) &&
        planningMinutes(time) == null)
      return 'Choose your preferred $kind sightseeing time.';
    if (time != null && planningMinutes(time) != null) {
      final flight = _map(trip['selectedFlight']);
      final segments = _rows(
          flight[kind == 'arrival' ? 'outboundSegments' : 'returnSegments']);
      final rawDate = segments.isNotEmpty
          ? (kind == 'arrival'
              ? segments.last['arrivalDate']
              : segments.first['departureDate'])
          : transport['${kind}Date'];
      final date = rawDate == null
          ? null
          : DateTime.tryParse('$rawDate'.split('T').first);
      final day = date == null
          ? (kind == 'arrival' ? 1 : count)
          : date.difference(start).inDays + 1;
      final value = at(day, planningMinutes(time)!);
      if (kind == 'arrival' ? before(value) : after(value))
        return 'Your $kind sightseeing time conflicts with the travel limit.';
      final knownDays = _map(_map(trip['planningAvailability'])['days']);
      final window = _map(knownDays[value.toIso8601String().substring(0, 10)]);
      final override =
          _rows(prefs['days']).where((row) => row['dayNo'] == day).firstOrNull;
      final left =
          planningMinutes(override?['startTime']) ?? window['baseStartMinutes'];
      final right =
          planningMinutes(override?['endTime']) ?? window['baseEndMinutes'];
      if (override?['restDay'] != true &&
          (kind == 'arrival' &&
                  right is int &&
                  planningMinutes(time)! >= right ||
              kind == 'departure' &&
                  left is int &&
                  planningMinutes(time)! <= left)) {
        return 'Your $kind preference leaves no sightseeing time. Change the time or choose no sightseeing.';
      }
    }
  }
  if (count == 1) {
    final arrival = planningMinutes(_map(prefs['arrival'])['startTime']);
    final departure = planningMinutes(_map(prefs['departure'])['endTime']);
    if (arrival != null && departure != null && arrival >= departure)
      return 'Sightseeing must end after it starts on the same day.';
  }
  for (var i = 0; i < blocks.length; i++) {
    final row = blocks[i], day = blocks[i]['dayNo'];
    if (day is! int || day < 1 || day > count)
      return 'Choose a valid day for your personal activity.';
    final left = planningMinutes(row['startTime']),
        right = planningMinutes(row['endTime']);
    if (row['startTime'] == null && row['endTime'] == null) continue;
    if (left == null || right == null || right <= left)
      return 'Choose both times, with the end after the start on the same day.';
    final destination = (row['boundary'] ??
            ({'custom', 'hotel_luggage'}.contains(row['type'])
                ? 'destination'
                : 'personal')) ==
        'destination';
    if (destination && (before(at(day, left)) || after(at(day, right))))
      return 'Day $day: this destination activity conflicts with your travel times. Edit its time or context.';
    for (final other in blocks.take(i)) {
      final a = planningMinutes(other['startTime']),
          b = planningMinutes(other['endTime']);
      if (other['dayNo'] == day &&
          a != null &&
          b != null &&
          left < b &&
          a < right)
        return 'Your ${row['label'] ?? 'personal activity'} overlaps another personal activity on Day $day. Edit time, change day or leave it unscheduled.';
    }
    for (final activity in _rows(trip['activities'])) {
      final a = planningMinutes(activity['scheduledStartTime']),
          b = planningMinutes(activity['scheduledEndTime']);
      final fixed = ['fixed', 'locked', 'manualTime', 'userFixed', 'isLocked']
              .any((key) => activity[key] == true) ||
          activity['paymentId'] != null ||
          activity['bookingId'] != null;
      if (fixed &&
          activity['dayNo'] == day &&
          a != null &&
          b != null &&
          left < b &&
          a < right)
        return 'Day $day: this time overlaps a fixed activity. Edit your personal activity time.';
    }
  }
  return null;
}
