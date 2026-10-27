import 'package:flutter/foundation.dart';

/// Structured opening hours schedule parsed from various provider or catalog formats.
@immutable
class OpeningHoursSchedule {
  /// Whether a genuine seven-day weekly timetable is available.
  final bool hasWeeklySchedule;

  /// Ordered Monday-to-Sunday timetable entries.
  final List<MapEntry<String, String>> weeklyHours;

  /// Generic opening range (e.g. "9:00 AM – 8:00 PM") if only a single range is available.
  final String? genericHours;

  /// Current weekday in Malaysia local time (UTC+8).
  final String currentMalaysiaDay;

  /// Verified real-time status if provided by a live source ("Open now" or "Closed now").
  final String? realTimeStatus;

  /// Whether opening hours are completely unavailable or missing.
  final bool isUnavailable;

  const OpeningHoursSchedule({
    required this.hasWeeklySchedule,
    required this.weeklyHours,
    this.genericHours,
    required this.currentMalaysiaDay,
    this.realTimeStatus,
    required this.isUnavailable,
  });
}

/// Truthful parser and formatter for destination opening hours.
///
/// Supports:
/// - Structured 7-day maps (`weeklyHours`, `operating_hours`)
/// - Provider weekday strings (`weekday_text`)
/// - Google Places `periods`
/// - Single generic ranges (`openingHours`, `open_state`)
/// - Split opening periods and overnight hours
/// - Malaysia local timezone calculation (UTC+8)
class OpeningHoursUtils {
  static const List<String> daysOfWeek = [
    'Monday',
    'Tuesday',
    'Wednesday',
    'Thursday',
    'Friday',
    'Saturday',
    'Sunday',
  ];

  static final Map<String, String> _dayAliases = {
    'mon': 'Monday',
    'monday': 'Monday',
    'tue': 'Tuesday',
    'tues': 'Tuesday',
    'tuesday': 'Tuesday',
    'wed': 'Wednesday',
    'wednesday': 'Wednesday',
    'thu': 'Thursday',
    'thur': 'Thursday',
    'thurs': 'Thursday',
    'thursday': 'Thursday',
    'fri': 'Friday',
    'friday': 'Friday',
    'sat': 'Saturday',
    'saturday': 'Saturday',
    'sun': 'Sunday',
    'sunday': 'Sunday',
  };

  /// Returns the current day of the week in Malaysia timezone (UTC+8).
  static String currentMalaysiaDay([DateTime? now]) {
    final dt = (now ?? DateTime.now()).toUtc().add(const Duration(hours: 8));
    final index = dt.weekday - 1; // 1 = Monday (index 0) ... 7 = Sunday (index 6)
    if (index >= 0 && index < daysOfWeek.length) {
      return daysOfWeek[index];
    }
    return 'Monday';
  }

  static String _formatHourMinute(int hour, int minute) {
    final period = hour < 12 ? 'AM' : 'PM';
    var h12 = hour % 12;
    if (h12 == 0) h12 = 12;
    final mStr = minute.toString().padLeft(2, '0');
    return '$h12:$mStr $period';
  }

  static String _formatTimeDigits(String time) {
    final digits = time.replaceAll(RegExp(r'\D'), '');
    if (digits.length == 3) {
      final h = int.tryParse(digits.substring(0, 1)) ?? 0;
      final m = int.tryParse(digits.substring(1)) ?? 0;
      return _formatHourMinute(h, m);
    } else if (digits.length == 4) {
      final h = int.tryParse(digits.substring(0, 2)) ?? 0;
      final m = int.tryParse(digits.substring(2)) ?? 0;
      return _formatHourMinute(h, m);
    }
    return time;
  }

  static String _formatTimePart(String part) {
    final trimmed = part.trim();
    if (trimmed.isEmpty) return '';

    // If already has AM/PM, normalize spacing
    final amPmMatch = RegExp(
      r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$',
      caseSensitive: false,
    ).firstMatch(trimmed);
    if (amPmMatch != null) {
      final h = int.tryParse(amPmMatch.group(1)!) ?? 0;
      final m = amPmMatch.group(2) != null
          ? int.tryParse(amPmMatch.group(2)!) ?? 0
          : 0;
      final period = amPmMatch.group(3)!.toUpperCase();
      var h12 = h % 12;
      if (h12 == 0) h12 = 12;
      final mStr = m.toString().padLeft(2, '0');
      return '$h12:$mStr $period';
    }

    // 24-hour time e.g. 09:00, 9:00, 16:00
    final match24 = RegExp(r'^(\d{1,2}):(\d{2})$').firstMatch(trimmed);
    if (match24 != null) {
      final h = int.tryParse(match24.group(1)!) ?? 0;
      final m = int.tryParse(match24.group(2)!) ?? 0;
      return _formatHourMinute(h, m);
    }

    return trimmed;
  }

  static String _formatSingleRange(String range) {
    final trimmed = range.trim();
    if (trimmed.isEmpty) return '';

    final lower = trimmed.toLowerCase();
    if (lower == 'closed') return 'Closed';
    if (lower == 'open 24 hours' ||
        lower == '24 hours' ||
        lower == '00:00-23:59' ||
        lower == '00:00–23:59' ||
        lower == '00:00-24:00' ||
        lower == 'open all day') {
      return 'Open 24 hours';
    }

    // Match range separator: hyphen, en-dash, em-dash, " to "
    final rangeMatch = RegExp(
      r'^(.*?)\s*(?:[-–—]|(?:\bto\b))\s*(.*?)$',
      caseSensitive: false,
    ).firstMatch(trimmed);
    if (rangeMatch != null) {
      final start = _formatTimePart(rangeMatch.group(1)!);
      final end = _formatTimePart(rangeMatch.group(2)!);
      if (start.isNotEmpty && end.isNotEmpty) {
        return '$start – $end';
      }
    }

    return trimmed;
  }

  /// Formats raw hours string (supporting split periods separated by comma or semicolon).
  static String formatHoursString(dynamic raw) {
    if (raw == null) return '';
    final str = raw.toString().trim();
    if (str.isEmpty) return '';
    final lower = str.toLowerCase();
    if (lower == 'null' ||
        lower == 'n/a' ||
        lower == 'na' ||
        lower == '-' ||
        lower == 'unknown' ||
        lower.contains('not listed') ||
        lower.contains('unavailable')) {
      return '';
    }

    final parts = str
        .split(RegExp(r'[,;]\s*'))
        .where((p) => p.trim().isNotEmpty)
        .toList();
    if (parts.isEmpty) return '';

    final formatted = parts.map(_formatSingleRange).toList();
    return formatted.join(', ');
  }

  /// Parses destination payload and returns a structured [OpeningHoursSchedule].
  static OpeningHoursSchedule parse(
    Map<String, dynamic>? detail, {
    DateTime? now,
  }) {
    final currentDay = currentMalaysiaDay(now);

    if (detail == null || detail.isEmpty) {
      return OpeningHoursSchedule(
        hasWeeklySchedule: false,
        weeklyHours: const [],
        currentMalaysiaDay: currentDay,
        isUnavailable: true,
      );
    }

    // 1. Verified real-time status if explicitly present
    String? realTimeStatus;
    if (detail['realtime_open'] == true || detail['open_now'] == true) {
      realTimeStatus = 'Open now';
    } else if (detail['realtime_open'] == false || detail['open_now'] == false) {
      realTimeStatus = 'Closed now';
    }

    final Map<String, String> scheduleByDay = {};

    // Source A: Map in 'weeklyHours', 'weekly_hours', or 'operating_hours'
    final weeklyRaw = detail['weeklyHours'] ??
        detail['weekly_hours'] ??
        detail['operating_hours'];
    if (weeklyRaw is Map) {
      for (final entry in weeklyRaw.entries) {
        final keyNorm = _dayAliases[entry.key.toString().trim().toLowerCase()];
        if (keyNorm != null) {
          final formatted = formatHoursString(entry.value);
          if (formatted.isNotEmpty) {
            scheduleByDay[keyNorm] = formatted;
          }
        }
      }
    }

    // Source B: List of strings (weekday_text format or list of maps)
    dynamic weekdayTextList;
    if (weeklyRaw is List) {
      weekdayTextList = weeklyRaw;
    } else if (detail['weekday_text'] is List) {
      weekdayTextList = detail['weekday_text'];
    } else if (detail['opening_hours'] is Map &&
        detail['opening_hours']['weekday_text'] is List) {
      weekdayTextList = detail['opening_hours']['weekday_text'];
    } else if (detail['hours'] is List) {
      weekdayTextList = detail['hours'];
    }

    if (weekdayTextList is List && scheduleByDay.length < 7) {
      for (final item in weekdayTextList) {
        if (item is String) {
          final colonIndex = item.indexOf(':');
          if (colonIndex > 0) {
            final dayPart = item.substring(0, colonIndex).trim().toLowerCase();
            final hoursPart = item.substring(colonIndex + 1).trim();
            final keyNorm = _dayAliases[dayPart];
            if (keyNorm != null) {
              final formatted = formatHoursString(hoursPart);
              if (formatted.isNotEmpty) {
                scheduleByDay[keyNorm] = formatted;
              }
            }
          }
        } else if (item is Map) {
          final dayPart = (item['day'] ?? item['weekday'] ?? '')
              .toString()
              .trim()
              .toLowerCase();
          final hoursPart = item['hours'] ?? item['time'] ?? '';
          final keyNorm = _dayAliases[dayPart];
          if (keyNorm != null) {
            final formatted = formatHoursString(hoursPart);
            if (formatted.isNotEmpty) {
              scheduleByDay[keyNorm] = formatted;
            }
          }
        }
      }
    }

    // Source C: Google Places 'periods'
    List? periodsList;
    if (detail['opening_hours'] is Map &&
        detail['opening_hours']['periods'] is List) {
      periodsList = detail['opening_hours']['periods'] as List;
    } else if (detail['periods'] is List) {
      periodsList = detail['periods'] as List;
    }

    if (periodsList != null && scheduleByDay.length < 7) {
      final Map<int, List<String>> periodsByDay = {
        0: [],
        1: [],
        2: [],
        3: [],
        4: [],
        5: [],
        6: [],
      };

      for (final period in periodsList) {
        if (period is Map) {
          final open = period['open'];
          final close = period['close'];
          if (open is Map) {
            final day = int.tryParse(open['day'].toString());
            final openTime = open['time']?.toString() ?? '';
            if (day != null && periodsByDay.containsKey(day)) {
              if (close is Map) {
                final closeTime = close['time']?.toString() ?? '';
                final range =
                    '${_formatTimeDigits(openTime)} – ${_formatTimeDigits(closeTime)}';
                periodsByDay[day]!.add(range);
              } else {
                periodsByDay[day]!.add('Open 24 hours');
              }
            }
          }
        }
      }

      final dayMapping = {
        1: 'Monday',
        2: 'Tuesday',
        3: 'Wednesday',
        4: 'Thursday',
        5: 'Friday',
        6: 'Saturday',
        0: 'Sunday',
      };

      for (final entry in dayMapping.entries) {
        final ranges = periodsByDay[entry.key]!;
        if (ranges.isNotEmpty) {
          scheduleByDay[entry.value] = ranges.join(', ');
        } else {
          scheduleByDay[entry.value] = 'Closed';
        }
      }
    }

    // Check if genuine 7-day schedule is present
    if (scheduleByDay.length == 7) {
      final ordered = daysOfWeek
          .map((day) => MapEntry(day, scheduleByDay[day] ?? 'Closed'))
          .toList();
      return OpeningHoursSchedule(
        hasWeeklySchedule: true,
        weeklyHours: ordered,
        currentMalaysiaDay: currentDay,
        realTimeStatus: realTimeStatus,
        isUnavailable: false,
      );
    }

    // If not a full 7-day schedule, check for generic single range
    final genericRaw = detail['open_state'] ??
        detail['openingHours'] ??
        detail['hours'];
    if (genericRaw != null && genericRaw is! Map && genericRaw is! List) {
      final formatted = formatHoursString(genericRaw);
      if (formatted.isNotEmpty) {
        return OpeningHoursSchedule(
          hasWeeklySchedule: false,
          weeklyHours: const [],
          genericHours: formatted,
          currentMalaysiaDay: currentDay,
          realTimeStatus: realTimeStatus,
          isUnavailable: false,
        );
      }
    }

    return OpeningHoursSchedule(
      hasWeeklySchedule: false,
      weeklyHours: const [],
      currentMalaysiaDay: currentDay,
      realTimeStatus: realTimeStatus,
      isUnavailable: true,
    );
  }
}
