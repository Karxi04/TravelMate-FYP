import 'package:flutter/material.dart';

import '../../widgets/travel_widgets.dart';

/// Temporal classification categories for TravelMate trips.
enum TripTemporalStatus {
  planned,
  ongoing,
  expired;

  String get label => switch (this) {
        TripTemporalStatus.planned => 'Planned',
        TripTemporalStatus.ongoing => 'Ongoing',
        TripTemporalStatus.expired => 'Expired',
      };

  IconData get icon => switch (this) {
        TripTemporalStatus.planned => Icons.schedule_rounded,
        TripTemporalStatus.ongoing => Icons.explore_rounded,
        TripTemporalStatus.expired => Icons.history_rounded,
      };

  AppStatusTone get tone => switch (this) {
        TripTemporalStatus.planned => AppStatusTone.info, // Calm blue
        TripTemporalStatus.ongoing => AppStatusTone.success, // Green
        TripTemporalStatus.expired => AppStatusTone.neutral, // Neutral grey
      };
}

/// Filter options for the Trips list.
enum TripFilter {
  all,
  planned,
  ongoing,
  expired;

  String get label => switch (this) {
        TripFilter.all => 'All',
        TripFilter.planned => 'Planned',
        TripFilter.ongoing => 'Ongoing',
        TripFilter.expired => 'Expired',
      };
}

/// Authoritative helper for TravelMate trip temporal classification,
/// calendar date parsing in Asia/Kuala_Lumpur (UTC+08:00), and sorting.
class TripStatusHelper {
  /// UTC offset for Malaysia (UTC+08:00, no daylight-saving adjustments).
  static const int malaysiaUtcOffsetHours = 8;

  /// Optional override for deterministic unit and widget testing.
  static DateTime? customToday;

  /// Returns current DateTime in Asia/Kuala_Lumpur (UTC+08:00).
  static DateTime getMalaysiaNow([DateTime? customNow]) {
    if (customToday != null) return customToday!;
    final now = (customNow ?? DateTime.now()).toUtc();
    return now.add(const Duration(hours: malaysiaUtcOffsetHours));
  }

  /// Returns today's calendar date (hour=0, min=0, sec=0) in Asia/Kuala_Lumpur.
  static DateTime getMalaysiaToday([DateTime? customNow]) {
    if (customToday != null) {
      return DateTime(customToday!.year, customToday!.month, customToday!.day);
    }
    final now = getMalaysiaNow(customNow);
    return DateTime(now.year, now.month, now.day);
  }

  /// Parses a calendar date string (YYYY-MM-DD) into a calendar DateTime.
  /// Strictly rejects malformed dates, invalid leap year dates, or out-of-range components.
  static DateTime? parseCalendarDate(dynamic raw) {
    if (raw == null) return null;
    final str = raw.toString().trim();
    if (str.isEmpty) return null;

    final match = RegExp(r'^(\d{4})-(\d{1,2})-(\d{1,2})').firstMatch(str);
    if (match == null) return null;

    final year = int.tryParse(match.group(1)!);
    final month = int.tryParse(match.group(2)!);
    final day = int.tryParse(match.group(3)!);

    if (year == null || month == null || day == null) return null;
    if (year < 1900 || year > 2200) return null;
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;

    try {
      final parsed = DateTime(year, month, day);
      // Guard against month roll-over for invalid days (e.g. Feb 30 or Feb 29 on non-leap year)
      if (parsed.year != year || parsed.month != month || parsed.day != day) {
        return null;
      }
      return parsed;
    } catch (_) {
      return null;
    }
  }

  /// Extracts authoritative start and end dates from a Trip map.
  /// Uses top-level startDate and endDate.
  /// If endDate is absent but startDate and tripDays are valid, calculates fallback endDate.
  static (DateTime?, DateTime?) getTripDateRange(Map<String, dynamic> trip) {
    final start = parseCalendarDate(trip['startDate']);
    DateTime? end = parseCalendarDate(trip['endDate']);

    if (start != null && end == null) {
      final days = int.tryParse('${trip['tripDays'] ?? ''}');
      if (days != null && days >= 1) {
        end = start.add(Duration(days: days - 1));
      }
    }

    if (start != null && end != null && end.isBefore(start)) {
      // endDate earlier than startDate is invalid
      return (null, null);
    }

    return (start, end);
  }

  /// Resolves the temporal status for a given Trip document.
  /// - PLANNED: today < startDate
  /// - ONGOING: startDate <= today <= endDate
  /// - EXPIRED: today > endDate
  /// Comparisons are strictly on calendar dates (end date is inclusive).
  /// Returns null if travel dates are invalid or missing.
  static TripTemporalStatus? resolveStatus(
    Map<String, dynamic> trip, {
    DateTime? referenceDate,
  }) {
    final (start, end) = getTripDateRange(trip);
    if (start == null || end == null) return null;

    final today = referenceDate != null
        ? DateTime(referenceDate.year, referenceDate.month, referenceDate.day)
        : getMalaysiaToday();

    if (today.isBefore(start)) {
      return TripTemporalStatus.planned;
    } else if (today.isAfter(end)) {
      return TripTemporalStatus.expired;
    } else {
      return TripTemporalStatus.ongoing;
    }
  }

  /// Calculates duration until the next midnight in Asia/Kuala_Lumpur.
  static Duration durationUntilMidnight([DateTime? customNow]) {
    final now = getMalaysiaNow(customNow);
    final nextMidnight = DateTime(now.year, now.month, now.day).add(const Duration(days: 1));
    final diff = nextMidnight.difference(DateTime(now.year, now.month, now.day, now.hour, now.minute, now.second));
    return diff > Duration.zero ? diff + const Duration(seconds: 1) : const Duration(seconds: 1);
  }

  /// Sorts and filters trips according to the Section 7 policy:
  /// 1. Filters by temporal status if not [TripFilter.all].
  /// 2. For [TripFilter.all], groups by:
  ///    a. Ongoing trips (active)
  ///    b. Planned trips (soonest starting upcoming first)
  ///    c. Expired trips (most recently completed first)
  ///    d. Unclassified trips (invalid/missing dates)
  static List<Map<String, dynamic>> sortAndFilterTrips(
    List<Map<String, dynamic>> trips, {
    TripFilter filter = TripFilter.all,
    DateTime? referenceDate,
  }) {
    final ref = referenceDate ?? getMalaysiaToday();

    // First filter if a specific category is chosen
    List<Map<String, dynamic>> matching;
    if (filter == TripFilter.all) {
      matching = List<Map<String, dynamic>>.from(trips);
    } else {
      matching = trips.where((trip) {
        final status = resolveStatus(trip, referenceDate: ref);
        return switch (filter) {
          TripFilter.planned => status == TripTemporalStatus.planned,
          TripFilter.ongoing => status == TripTemporalStatus.ongoing,
          TripFilter.expired => status == TripTemporalStatus.expired,
          TripFilter.all => true,
        };
      }).toList();
    }

    // Sort according to temporal policy
    matching.sort((a, b) {
      final statusA = resolveStatus(a, referenceDate: ref);
      final statusB = resolveStatus(b, referenceDate: ref);

      final rankA = _statusRank(statusA);
      final rankB = _statusRank(statusB);

      if (rankA != rankB) {
        return rankA.compareTo(rankB);
      }

      final (startA, endA) = getTripDateRange(a);
      final (startB, endB) = getTripDateRange(b);

      if (statusA == TripTemporalStatus.ongoing) {
        // Ongoing: show trips ending soonest first, then earlier start
        final endComp = (endA ?? DateTime(2099)).compareTo(endB ?? DateTime(2099));
        if (endComp != 0) return endComp;
        return (startA ?? DateTime(2099)).compareTo(startB ?? DateTime(2099));
      } else if (statusA == TripTemporalStatus.planned) {
        // Planned: soonest upcoming start date first
        return (startA ?? DateTime(2099)).compareTo(startB ?? DateTime(2099));
      } else if (statusA == TripTemporalStatus.expired) {
        // Expired: most recently completed first (end date descending)
        return (endB ?? DateTime(1970)).compareTo(endA ?? DateTime(1970));
      }

      return 0;
    });

    return matching;
  }

  static int _statusRank(TripTemporalStatus? s) => switch (s) {
        TripTemporalStatus.ongoing => 0,
        TripTemporalStatus.planned => 1,
        TripTemporalStatus.expired => 2,
        null => 3,
      };
}
