import 'dart:convert';

DateTime? _calendarDate(dynamic value) {
  final raw = '$value';
  if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(raw)) return null;
  final parsed = DateTime.tryParse(raw);
  if (parsed == null || parsed.toIso8601String().substring(0, 10) != raw)
    return null;
  return DateTime.utc(parsed.year, parsed.month, parsed.day);
}

DateTime? notificationTripStart(Map trip) {
  final start = _calendarDate(trip['startDate']);
  final end = _calendarDate(trip['endDate'] ?? trip['startDate']);
  return start != null && end != null && !end.isBefore(start) ? start : null;
}

/// Offline mode only evaluates owned saved trips and real cached forecasts.
/// Financial/fulfilment events and Smart Packing need the authenticated backend.
List<Map<String, dynamic>> localTripNotifications(
    String uid,
    List<Map<String, dynamic>> trips,
    Map<String, Map<String, dynamic>> forecasts,
    DateTime now) {
  final myt = now.toUtc().add(const Duration(hours: 8));
  final today = DateTime.utc(myt.year, myt.month, myt.day);
  final events = <Map<String, dynamic>>[];
  void add(
      String category, List source, String title, String message, Map target) {
    final id =
        base64Url.encode(utf8.encode(jsonEncode([uid, category, source])));
    events.add({
      'id': id,
      'travellerId': uid,
      'category': category,
      'sourceEventId': id,
      'title': title,
      'message': message,
      'target': target,
      'createdAt': now.toUtc().toIso8601String(),
      'read': false
    });
  }

  for (final trip in trips) {
    if (trip['travellerId'] != uid ||
        trip['deletedAt'] != null ||
        [
          'cancelled',
          'canceled',
          'archived',
          'deleted',
          'payment_failed',
          'payment_cancelled'
        ].contains(trip['status']) ||
        trip['fulfillmentStatus'] == 'fulfillment_declined') continue;
    final raw = '${trip['startDate'] ?? ''}';
    final start = notificationTripStart(trip);
    if (start == null) continue;
    final end = _calendarDate(trip['endDate'] ?? raw)!;
    final delta = start.difference(today).inDays;
    final tid = '${trip['id'] ?? ''}';
    if (tid.isEmpty) continue;
    final target = {
      'screen': trip['packageTrip'] == true || trip['tripType'] == 'package'
          ? 'package_trip'
          : 'trip',
      'tripId': tid
    };
    if (delta == 3 || delta == 1)
      add(
          'upcoming_trip',
          [tid, raw, delta],
          'Upcoming trip',
          '${trip['title'] ?? 'Your trip'} starts in $delta day(s), on $raw.',
          target);
    if (delta < 0 || delta > 6) continue;
    final daily = forecasts[tid]?['daily'];
    if (daily is! Map || daily['time'] is! List) continue;
    final dates = daily['time'] as List;
    for (var index = 0; index < dates.length; index++) {
      final day = _calendarDate(dates[index]);
      if (day == null ||
          day.isBefore(start) ||
          day.isAfter(end) ||
          day.isBefore(today)) continue;
      dynamic value(String key) =>
          daily[key] is List && (daily[key] as List).length > index
              ? daily[key][index]
              : null;
      final code = value('weather_code');
      final probability = value('precipitation_probability_max');
      final rainy =
          probability is num && probability >= 80 && probability <= 100;
      final concern = [95, 96, 99].contains(code)
          ? 'thunderstorm'
          : [63, 65, 67, 81, 82].contains(code) || rainy
              ? 'rain'
              : null;
      if (concern != null)
        add(
            'weather',
            [tid, dates[index], concern],
            'Trip forecast advisory',
            'The Open-Meteo forecast for ${dates[index]} indicates possible $concern. Review your plans. This is a forecast advisory, not an official severe-weather alert.',
            target);
    }
  }
  return events;
}
