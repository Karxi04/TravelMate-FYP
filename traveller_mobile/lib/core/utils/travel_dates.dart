const _months = <String, int>{
  'jan': 1,
  'january': 1,
  'feb': 2,
  'february': 2,
  'mar': 3,
  'march': 3,
  'apr': 4,
  'april': 4,
  'may': 5,
  'jun': 6,
  'june': 6,
  'jul': 7,
  'july': 7,
  'aug': 8,
  'august': 8,
  'sep': 9,
  'sept': 9,
  'september': 9,
  'oct': 10,
  'october': 10,
  'nov': 11,
  'november': 11,
  'dec': 12,
  'december': 12,
};

DateTime malaysianToday() {
  final now = DateTime.now().toUtc().add(const Duration(hours: 8));
  return DateTime.utc(now.year, now.month, now.day);
}

/// The same explicit range grammar as the Flask assistant, for standalone mode.
(DateTime, DateTime)? parseTravelDateRange(String message, {DateTime? today}) {
  final month = (_months.keys.toList()
        ..sort((a, b) => b.length.compareTo(a.length)))
      .join('|');
  message = message.replaceAllMapped(
      RegExp(
          r'\b(\d{1,2})\s*(?:to|until|[-–—])\s*(\d{1,2})\s+(' +
              month +
              r')\b(?:\s+(\d{4}))?',
          caseSensitive: false),
      (m) => '${m[1]} ${m[3]} ${m[4] ?? ''} to ${m[2]} ${m[3]} ${m[4] ?? ''}');
  final points = RegExp(
          r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{4})?|\d{1,2}(?:st|nd|rd|th)?\s+(?:' +
              month +
              r')\b(?:\s*,?\s*\d{4})?)',
          caseSensitive: false)
      .allMatches(message)
      .toList();
  if (points.length < 2) {
    if (points.isNotEmpty &&
        RegExp(r'\b(?:until|till|through|to)\b', caseSensitive: false)
            .hasMatch(message.substring(points.first.end))) {
      throw const FormatException('Please provide both travel dates.');
    }
    return null;
  }
  if (points.length != 2 ||
      !RegExp(r'^\s*(?:until|till|to|through|[-–—])\s*$', caseSensitive: false)
          .hasMatch(message.substring(points[0].end, points[1].start))) {
    throw const FormatException(
        'Which two dates should I use? Join one start and end date with to or until.');
  }
  (int, int, int?) parts(String raw) {
    if (RegExp(r'^\d{4}-').hasMatch(raw)) {
      final n = raw.split('-').map(int.parse).toList();
      return (n[2], n[1], n[0]);
    }
    if (raw.contains('/')) {
      final n = raw.split('/').map(int.parse).toList();
      if (n[0] <= 12 && n[1] <= 12 && n[0] != n[1])
        throw const FormatException(
            'Please use month names or ISO dates to clarify the date order.');
      return (n[0], n[1], n.length == 3 ? n[2] : null);
    }
    final m = RegExp(
            r'^(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)(?:\s*,?\s*(\d{4}))?$',
            caseSensitive: false)
        .firstMatch(raw)!;
    return (
      int.parse(m[1]!),
      _months[m[2]!.toLowerCase()]!,
      int.tryParse(m[3] ?? '')
    );
  }

  final first = parts(points[0][0]!);
  final last = parts(points[1][0]!);
  final now = today ?? malaysianToday();
  var year = first.$3 ?? last.$3 ?? now.year;
  if (first.$3 == null &&
      last.$3 == null &&
      (first.$2 < now.month || (first.$2 == now.month && first.$1 < now.day)))
    year++;
  if (first.$3 == null && last.$3 != null && first.$2 > last.$2) year--;
  final endYear = last.$3 ?? (year + (last.$2 < first.$2 ? 1 : 0));
  final start = DateTime.utc(year, first.$2, first.$1),
      end = DateTime.utc(endYear, last.$2, last.$1);
  if (start.month != first.$2 ||
      start.day != first.$1 ||
      end.month != last.$2 ||
      end.day != last.$1)
    throw const FormatException(
        'Those calendar dates are invalid. Please correct the range.');
  if (end.isBefore(start))
    throw const FormatException(
        'The end date is before the start date. Please correct the range.');
  if (start.isBefore(DateTime.utc(now.year, now.month, now.day)))
    throw const FormatException(
        'Those dates are in the past. Please choose future dates.');
  if (end.difference(start).inDays + 1 > 14)
    throw const FormatException(
        'The chat planner supports up to 14 calendar days.');
  return (start, end);
}
