import 'dart:async';
import 'package:flutter/material.dart';
import '../../widgets/local_place_rating.dart';
import 'budget_comparison_screen.dart';
import 'budget_breakdown.dart';
import 'flight_adjustment_preview_sheet.dart';
import 'activity_payload_helper.dart';
import 'models/budget_model.dart';
import 'package_trip_details_screen.dart';
import 'trip_status_helper.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr03_destination_search_information/destination_details_screen.dart';
import '../fr06_weather_forecast/weather_screen.dart';
import '../fr07_flight_search/flight_screen.dart';
import '../fr08_hotel_booking/hotel_screen.dart';
import '../fr08_hotel_booking/hotel_details_screen.dart';
import 'packing_checklist_screen.dart';
import '../fr09_payment/payment_history_screen.dart';

class TripDetailsScreen extends StatefulWidget {
  final String tripId;
  final ApiService? api;
  final DateTime? referenceDate;

  const TripDetailsScreen({
    super.key,
    required this.tripId,
    this.api,
    this.referenceDate,
  });

  @override
  State<TripDetailsScreen> createState() => _TripDetailsScreenState();
}

class _TripDetailsScreenState extends State<TripDetailsScreen>
    with WidgetsBindingObserver {
  static const _placeImageFields = <String>[
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

  late final ApiService api;
  Map<String, dynamic>? trip;
  bool loading = true;
  bool busy = false;
  bool editingItinerary = false;
  int selectedDay = 1;
  String? loadError;

  Future<void> load() async {
    if (mounted) {
      setState(() {
        loading = true;
        loadError = null;
      });
    }
    try {
      final data = await api.get('/api/fr5/itineraries');
      final items = (data['items'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      Map<String, dynamic>? found;
      for (final item in items) {
        if (item['id'].toString() == widget.tripId) {
          found = item;
          break;
        }
      }
      if (!mounted) return;
      setState(() {
        trip = found;
        if (found != null) {
          selectedDay = selectedDay.clamp(1, _tripDays(found));
        }
      });
    } catch (_) {
      if (mounted) {
        setState(() => loadError = 'We could not load this trip right now.');
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  List<Map<String, dynamic>> get activities =>
      (trip?['activities'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();

  int _tripDays(Map<String, dynamic> t) {
    final start = DateTime.tryParse((t['startDate'] ?? '').toString());
    final end = DateTime.tryParse((t['endDate'] ?? '').toString());
    if (start != null && end != null)
      return (end.difference(start).inDays + 1).clamp(1, 14).toInt();
    return int.tryParse('${t['tripDays'] ?? 1}') ?? 1;
  }

  int? _tripAdults(Map<String, dynamic> t) {
    for (final key in ['adults', 'adultCount', 'travellerAdults']) {
      final value = int.tryParse('${t[key] ?? ''}');
      if (value != null && value > 0) return value;
    }
    return null;
  }

  int? _tripChildren(Map<String, dynamic> t) {
    for (final key in ['children', 'childCount', 'travellerChildren']) {
      final value = int.tryParse('${t[key] ?? ''}');
      if (value != null && value >= 0) return value;
    }
    return null;
  }

  String _dateRange(Map<String, dynamic> t) {
    final range = (t['tripDateRangeLabel'] ?? '').toString();
    if (range.isNotEmpty) return range;
    final start = (t['startDate'] ?? '').toString();
    final end = (t['endDate'] ?? '').toString();
    if (start.isNotEmpty && end.isNotEmpty) return '$start to $end';
    return 'Dates not set';
  }

  String _timeText(Map<String, dynamic> activity) {
    final range = (activity['timeRangeLabel'] ?? '').toString();
    if (range.isNotEmpty) return range;
    final slot = (activity['timeSlot'] ?? '').toString();
    return slot.isEmpty ? 'Time not arranged' : slot;
  }

  String _durationText(Map<String, dynamic> activity) {
    final duration =
        int.tryParse('${activity['recommendedDurationMinutes'] ?? 0}') ?? 0;
    if (duration <= 0) return '';
    if (duration < 60) return '$duration min';
    final hours = duration ~/ 60;
    final minutes = duration % 60;
    return minutes == 0 ? '${hours}h' : '${hours}h ${minutes}m';
  }

  bool _isProvisional(Map<String, dynamic> activity) {
    final feasibility =
        (activity['scheduleFeasibility'] ?? '').toString().toLowerCase();
    if (feasibility == 'provisional') return true;
    if (feasibility == 'feasible_with_reported_hours') return false;
    final status =
        (activity['openingHoursStatus'] ?? '').toString().toLowerCase();
    return status == 'unknown';
  }

  bool _isVerifiedFree(Map<String, dynamic> activity) {
    // 1. Fail closed if there are pricing issues
    final issues = activity['pricingIssues'] as List? ?? const [];
    if (issues.isNotEmpty) return false;

    // 2. Authoritative selection price status must not be unresolved, conditional, or unverified
    final status =
        (activity['selectionPriceStatus'] ?? '').toString().toLowerCase();
    if (status == 'unresolved' ||
        status == 'conditional' ||
        status == 'unverified') {
      return false;
    }

    // 3. Provenance must be verified_ticket
    final provenance =
        (activity['costProvenance'] ?? '').toString().toLowerCase();
    if (provenance != 'verified_ticket') return false;

    // 4. Must have a valid pricing evidence map
    if (activity['pricingEvidence'] is! Map) return false;
    final evidence =
        Map<String, dynamic>.from(activity['pricingEvidence'] as Map);

    final evidenceIssues = evidence['pricingIssues'] as List? ?? const [];
    if (evidenceIssues.isNotEmpty) return false;

    // 5. Evidence applicability must be explicitly 'applicable' or 'all'
    final applicability =
        (evidence['applicability'] ?? '').toString().toLowerCase();
    if (applicability != 'applicable' && applicability != 'all') {
      return false;
    }

    // 6. Eligibility must not indicate missing evidence or conditional restrictions
    final eligibility = (evidence['eligibility'] ?? '').toString().toLowerCase();
    if (eligibility.contains('unverified') ||
        eligibility.contains('missing') ||
        eligibility.contains('required')) {
      return false;
    }

    // 7. Source URL or citation must be present and non-empty
    final sourceUrl = (evidence['priceSourceUrl'] ??
            evidence['sourceUrl'] ??
            evidence['citation'] ??
            activity['priceSourceUrl'] ??
            '')
        .toString()
        .trim();
    if (sourceUrl.isEmpty) return false;

    // 8. Explicit negative verification evidence must be rejected
    if (evidence['verified'] == false || activity['verified'] == false) {
      return false;
    }

    // 9. Valid verification date from supported backend contract is required
    final dateRaw = (evidence['priceVerifiedAt'] ??
            evidence['verifiedAt'] ??
            evidence['verificationDate'] ??
            activity['priceVerifiedAt'] ??
            '')
        .toString()
        .trim();
    if (dateRaw.isEmpty) return false;
    final parsedDate = DateTime.tryParse(dateRaw);
    if (parsedDate == null) return false;

    // 10. Cost / unitPrice must be strictly 0
    final unitPrice = double.tryParse(
        '${activity['unitPrice'] ?? evidence['unitPrice'] ?? ''}');
    final cost = double.tryParse(
            '${activity['effectiveCost'] ?? activity['estimatedCost'] ?? ''}') ??
        0.0;
    if (unitPrice != null && unitPrice > 0) return false;
    if (cost > 0) return false;

    return true;
  }

  bool _isPriceConditional(Map<String, dynamic> activity) {
    final status =
        (activity['selectionPriceStatus'] ?? '').toString().toLowerCase();
    if (status == 'conditional') return true;
    final evidence = activity['pricingEvidence'] is Map
        ? Map<String, dynamic>.from(activity['pricingEvidence'] as Map)
        : null;
    if (evidence != null &&
        (evidence['applicability'] ?? '').toString().toLowerCase() ==
            'conditional') {
      return true;
    }
    return false;
  }

  bool _isPriceVerified(Map<String, dynamic> activity) {
    final unitPrice = double.tryParse('${activity['unitPrice'] ?? ''}');
    final cost = double.tryParse(
            '${activity['effectiveCost'] ?? activity['estimatedCost'] ?? ''}') ??
        0.0;
    final isZeroCost = (unitPrice != null && unitPrice == 0) || (cost == 0);
    if (isZeroCost) {
      return _isVerifiedFree(activity);
    }
    if (_isPriceConditional(activity)) return false;
    final status =
        (activity['selectionPriceStatus'] ?? '').toString().toLowerCase();
    final provenance =
        (activity['costProvenance'] ?? '').toString().toLowerCase();
    final evidence = activity['pricingEvidence'] is Map
        ? Map<String, dynamic>.from(activity['pricingEvidence'] as Map)
        : null;
    final issues = activity['pricingIssues'] as List? ?? const [];
    if (issues.isNotEmpty) return false;

    if (evidence != null) {
      if (evidence['verified'] == false || activity['verified'] == false) {
        return false;
      }
      final app = (evidence['applicability'] ?? '').toString().toLowerCase();
      if (app == 'applicable' && provenance == 'verified_ticket') {
        return true;
      }
      if (evidence['verified'] == true &&
          app != 'conditional' &&
          app != 'unverified') {
        return true;
      }
    }
    return status == 'verified' && provenance == 'verified_ticket';
  }

  bool _isPriceUnverified(Map<String, dynamic> activity) {
    if (_isVerifiedFree(activity) ||
        _isPriceConditional(activity) ||
        _isPriceVerified(activity)) {
      return false;
    }
    return true;
  }

  bool _isBudgetAwareApplied(Map<String, dynamic> t) {
    if (t['budgetAwareSelection'] is Map) {
      final bas = t['budgetAwareSelection'] as Map;
      if (bas['applied'] == true) return true;
    }
    if (t['generationContext'] is Map) {
      final gc = t['generationContext'] as Map;
      if (gc['budgetAwareSelectionApplied'] == true) return true;
    }
    return false;
  }

  String _unselectedActivityName(Map<String, dynamic> entry) {
    if (entry['activity'] is Map) {
      final act = Map<String, dynamic>.from(entry['activity'] as Map);
      for (final key in [
        'activityName',
        'title',
        'name',
        'ticketProduct',
        'experienceName'
      ]) {
        final val = (act[key] ?? '').toString().trim();
        if (val.isNotEmpty && !val.startsWith('{')) return val;
      }
    }
    for (final key in ['activityName', 'title', 'name']) {
      final val = (entry[key] ?? '').toString().trim();
      if (val.isNotEmpty && !val.startsWith('{')) return val;
    }
    return 'Suggested place';
  }

  String _friendlyUnselectedReason(Map<String, dynamic> entry) {
    final rawExp = (entry['explanation'] ?? '').toString().trim();
    if (rawExp.isNotEmpty &&
        !rawExp.startsWith('{') &&
        !rawExp.startsWith('[')) {
      return rawExp;
    }
    final rawReason =
        (entry['reasonCode'] ?? entry['reason'] ?? entry['unscheduledReason'] ?? '')
            .toString()
            .trim();
    final r = rawReason.toLowerCase();
    if (r == 'known_budget_exceeded' || r.contains('budget')) {
      return 'Exceeds remaining activity budget allowance.';
    }
    if (r == 'joint_schedule_infeasible' ||
        r.contains('schedule') ||
        r.contains('opening')) {
      return 'Could not fit schedule or opening hours safely.';
    }
    if (r == 'unresolved_price' || r.contains('unresolved')) {
      return 'Admission price unverified (deferred for confirmed places).';
    }
    if (r == 'local_quality_replacement' || r.contains('replacement')) {
      return 'Replaced by activities with higher travel preference match.';
    }
    if (r == 'lower_priority' || r.contains('score')) {
      return 'Lower match for selected pace and travel preferences.';
    }
    if (r == 'closed_on_dates' || r.contains('closed')) {
      return 'Closed during planned trip dates.';
    }
    if (r == 'missing_geographic_coordinates') {
      return 'Location coordinates unverified.';
    }
    if (r == 'ineligible_candidate') {
      return 'Not eligible for selected trip criteria.';
    }
    if (rawReason.isNotEmpty &&
        !rawReason.startsWith('{') &&
        !rawReason.startsWith('[')) {
      return rawReason;
    }
    return 'Kept as suggestion for future visits.';
  }

  String? _formatSelectionRationale(dynamic raw) {
    if (raw == null) return null;

    if (raw is String) {
      final trimmed = raw.trim();
      if (trimmed.isEmpty ||
          trimmed.startsWith('[') ||
          trimmed.startsWith('{')) {
        return null;
      }
      return trimmed;
    }

    if (raw is List) {
      final sentences = <String>[];
      for (final element in raw) {
        if (element == null) continue;
        if (element is String) {
          final t = element.trim();
          if (t.isNotEmpty && !t.startsWith('[') && !t.startsWith('{')) {
            if (!sentences.contains(t)) sentences.add(t);
          }
        } else if (element is Map) {
          final text = (element['explanation'] ??
                  element['summary'] ??
                  element['text'] ??
                  element['note'] ??
                  element['reason'] ??
                  '')
              .toString()
              .trim();
          if (text.isNotEmpty &&
              !text.startsWith('{') &&
              !text.startsWith('[')) {
            if (!sentences.contains(text)) sentences.add(text);
          }
        }
      }
      if (sentences.isEmpty) return null;
      return sentences.take(2).join(' ');
    }

    if (raw is Map) {
      final text = (raw['summary'] ??
              raw['explanation'] ??
              raw['text'] ??
              raw['description'] ??
              '')
          .toString()
          .trim();
      if (text.isNotEmpty && !text.startsWith('{') && !text.startsWith('[')) {
        return text;
      }
      return null;
    }

    return null;
  }

  List<String> _activityNotes(Map<String, dynamic> activity) {
    final notes = <String>[];
    final weather = (activity['weatherNote'] ?? '').toString();
    if (weather.isNotEmpty &&
        weather != 'No major weather rearrangement required.')
      notes.add(weather);
    for (final note in (activity['scheduleNotes'] as List? ?? [])) {
      var text = note.toString();
      if (text.contains('Fits one reported opening period; current hours and special-date closures are not verified.')) {
        text = 'Hours unverified on special dates. Fits one reported opening period.';
      }
      if (text.trim().isNotEmpty && !notes.contains(text)) notes.add(text);
    }
    if (_isProvisional(activity) &&
        !notes.any((n) =>
            n.toLowerCase().contains('opening hours') ||
            n.toLowerCase().contains('unverified') ||
            n.toLowerCase().contains('provisional'))) {
      notes.add(
          'Operating hours for the planned date are not confirmed. Confirm with the venue before visiting.');
    }
    if (_isPriceConditional(activity) &&
        !notes.any((n) => n.toLowerCase().contains('tariff'))) {
      notes.add(
          'Admission tariff varies by visitor category or transport option. Verify before visiting.');
    } else if (_isPriceUnverified(activity) &&
        !notes.any((n) =>
            n.toLowerCase().contains('admission') ||
            n.toLowerCase().contains('ticket') ||
            n.toLowerCase().contains('price'))) {
      notes.add(
          'Admission price is unverified. Check ticket prices before your visit.');
    }
    return notes.take(2).toList();
  }

  String _lifecycleLabel(dynamic raw) {
    return switch ((raw ?? 'draft').toString()) {
      'generating' => 'Building itinerary',
      'planned' => 'Planned',
      'generation_failed' => 'Needs attention',
      _ => 'Draft',
    };
  }

  AppStatusTone _lifecycleTone(dynamic raw) {
    return switch ((raw ?? 'draft').toString()) {
      'planned' => AppStatusTone.success,
      'generation_failed' => AppStatusTone.error,
      'generating' => AppStatusTone.info,
      _ => AppStatusTone.neutral,
    };
  }

  IconData _lifecycleIcon(dynamic raw) {
    return switch ((raw ?? 'draft').toString()) {
      'planned' => Icons.check_circle_outline_rounded,
      'generation_failed' => Icons.error_outline_rounded,
      'generating' => Icons.hourglass_top_rounded,
      _ => Icons.edit_note_rounded,
    };
  }

  String _shortDate(String raw) {
    final date = DateTime.tryParse(raw);
    if (date == null) return raw;
    const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec'
    ];
    return '${weekdays[date.weekday - 1]}, ${date.day} ${months[date.month - 1]}';
  }

  String _friendlyDateRange(Map<String, dynamic> t) {
    final start = DateTime.tryParse((t['startDate'] ?? '').toString());
    final end = DateTime.tryParse((t['endDate'] ?? '').toString());
    if (start == null || end == null) return _dateRange(t);
    const months = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec'
    ];
    if (start.year == end.year && start.month == end.month) {
      return '${start.day}–${end.day} ${months[start.month - 1]} ${start.year}';
    }
    return '${start.day} ${months[start.month - 1]} – ${end.day} ${months[end.month - 1]} ${end.year}';
  }

  List<Map<String, dynamic>> _dailySchedules(Map<String, dynamic> t) {
    final stored = (t['dailySchedule'] as List? ?? const [])
        .whereType<Map>()
        .map((day) => Map<String, dynamic>.from(day))
        .toList();
    final start = DateTime.tryParse((t['startDate'] ?? '').toString());
    if (stored.isNotEmpty) {
      final byDay = <int, Map<String, dynamic>>{
        for (final day in stored)
          if (int.tryParse('${day['dayNo']}') != null)
            int.parse('${day['dayNo']}'): day,
      };
      return List.generate(_tripDays(t), (index) {
        final dayNo = index + 1;
        final day = Map<String, dynamic>.from(
            byDay[dayNo] ?? <String, dynamic>{'activities': const []});
        day['dayNo'] = dayNo;
        if (start != null) {
          day['dayDate'] = start
              .add(Duration(days: index))
              .toIso8601String()
              .split('T')
              .first;
        }
        return day;
      });
    }
    return List.generate(_tripDays(t), (index) {
      final dayNo = index + 1;
      final dayActivities = activities
          .where((item) => int.tryParse('${item['dayNo']}') == dayNo)
          .toList();
      return <String, dynamic>{
        'dayNo': dayNo,
        'dayDate': start == null
            ? ''
            : start
                .add(Duration(days: index))
                .toIso8601String()
                .split('T')
                .first,
        'activities': dayActivities,
        'planningBlocks': const <Map<String, dynamic>>[],
        'estimatedCost': dayActivities.fold<double>(
          0,
          (sum, item) =>
              sum + (double.tryParse('${item['estimatedCost']}') ?? 0),
        ),
        'weather': const <String, dynamic>{'source': 'unavailable'},
      };
    });
  }

  Map<String, dynamic> _selectedSchedule(Map<String, dynamic> t) {
    final days = _dailySchedules(t);
    for (final day in days) {
      if (int.tryParse('${day['dayNo']}') == selectedDay) return day;
    }
    return days.isEmpty ? <String, dynamic>{} : days.first;
  }

  List<Map<String, dynamic>> _dayActivities(Map<String, dynamic> day) {
    final source = day['activities'] is List
        ? day['activities'] as List
        : activities
            .where((item) => int.tryParse('${item['dayNo']}') == selectedDay)
            .toList();
    final result = source
        .whereType<Map>()
        .map((item) =>
            _mergeCurrentActivitySnapshot(Map<String, dynamic>.from(item)))
        .toList();
    result.sort((a, b) => (a['scheduledStartTime'] ?? a['timeSlot'] ?? '')
        .toString()
        .compareTo(
            (b['scheduledStartTime'] ?? b['timeSlot'] ?? '').toString()));
    return result;
  }

  Map<String, dynamic> _mergeCurrentActivitySnapshot(
      Map<String, dynamic> scheduled) {
    final activityId = (scheduled['activityId'] ?? '').toString();
    final destinationId = (scheduled['destinationId'] ?? '').toString();
    Map<String, dynamic>? current;
    for (final candidate in activities) {
      if (activityId.isNotEmpty &&
          (candidate['activityId'] ?? '').toString() == activityId) {
        current = candidate;
        break;
      }
    }
    if (current == null && destinationId.isNotEmpty) {
      for (final candidate in activities) {
        if ((candidate['destinationId'] ?? '').toString() == destinationId) {
          current = candidate;
          break;
        }
      }
    }
    if (current == null) return scheduled;
    final merged = <String, dynamic>{...current, ...scheduled};
    for (final field in _placeImageFields) {
      final value = current[field];
      if (_hasImageValue(value)) {
        merged[field] = value;
      }
    }
    return merged;
  }

  bool _hasImageValue(dynamic value) {
    if (value is String) return value.trim().isNotEmpty;
    if (value is List) return value.isNotEmpty;
    if (value is Map) return value.isNotEmpty;
    return false;
  }

  List<Map<String, dynamic>> _planningBlocks(Map<String, dynamic> day) =>
      (day['planningBlocks'] as List? ?? const [])
          .whereType<Map>()
          .map((block) => Map<String, dynamic>.from(block))
          .toList();

  String _weatherSummary(Map<String, dynamic> weather) {
    if ((weather['source'] ?? '').toString() == 'unavailable') {
      return 'Forecast unavailable';
    }
    final description = (weather['description'] ?? weather['condition'] ?? '')
        .toString()
        .trim();
    final temperature = weather['temperature'] ??
        weather['temperatureMax'] ??
        weather['temperature_2m_max'];
    final parts = <String>[];
    if (weather['heavyRainLikely'] == true) {
      parts.add('Rain expected');
    } else if (description.isNotEmpty) {
      parts.add(description);
    } else {
      final code = int.tryParse('${weather['weatherCode'] ?? ''}');
      parts.add(
          code != null && code >= 51 ? 'Rain possible' : 'Forecast available');
    }
    if (temperature != null) parts.add('${temperature.toString()}°C');
    return parts.join(' · ');
  }

  String _failureMessage(Map<String, dynamic> t) {
    return switch ((t['generationFailureStage'] ?? '').toString()) {
      'budget_calculation' =>
        'We couldn’t finish the budget. Your trip draft is safe.',
      'snapshot_validation' =>
        'Your saved recommendations need to be refreshed before this itinerary can be rebuilt.',
      _ => 'We couldn’t finish this itinerary. Your trip draft is safe.',
    };
  }

  String _friendlyUnscheduledReason(Map<String, dynamic> item) {
    final rawReason = (item['unscheduledReason'] ?? '').toString();
    final reason = rawReason.toLowerCase();
    if (reason.contains('closed on all trip days') ||
        reason.contains('is closed during')) {
      return 'This place is closed during your trip dates.';
    }
    if (reason.contains('unverified')) {
      return 'Couldn’t fit in schedule. Opening hours are unverified; check with venue.';
    }
    if (reason.contains('opening')) {
      return 'It couldn’t fit within the available opening hours.';
    }
    if (rawReason.isNotEmpty &&
        !reason.contains('could not fit within available time')) {
      return rawReason;
    }
    return 'There wasn’t enough time to fit this place safely.';
  }

  bool _hasFlightDateMismatch(
      Map<String, dynamic> t, Map<String, dynamic> flight) {
    final tripStartStr = (t['startDate'] ?? '').toString();
    final tripEndStr = (t['endDate'] ?? '').toString();
    if (tripStartStr.length < 10 || tripEndStr.length < 10) return false;
    final tripStart = DateTime.tryParse(tripStartStr.substring(0, 10));
    final tripEnd = DateTime.tryParse(tripEndStr.substring(0, 10));
    if (tripStart == null || tripEnd == null || tripEnd.isBefore(tripStart)) {
      return false;
    }

    final dates = <DateTime>[];
    void addDate(dynamic raw) {
      if (raw == null) return;
      final str = raw.toString();
      if (str.length >= 10) {
        final d = DateTime.tryParse(str.substring(0, 10));
        if (d != null) dates.add(d);
      }
    }

    for (final segList in [
      flight['outboundSegments'],
      flight['returnSegments']
    ]) {
      if (segList is List) {
        for (final seg in segList) {
          if (seg is Map) {
            addDate(seg['departureDate']);
            addDate(seg['arrivalDate']);
          }
        }
      }
    }

    if (dates.isEmpty) {
      addDate(flight['outboundDate']);
      addDate(flight['returnDate']);
      addDate(flight['departureDate']);
      addDate(flight['arrivalDate']);
    }

    if (dates.isEmpty) return false;

    return dates.any((d) => d.isBefore(tripStart) || d.isAfter(tripEnd));
  }

  List<Widget> _attachedTravelCards(Map<String, dynamic> t) {
    final cards = <Widget>[];
    if (t['selectedFlight'] is Map) {
      final flight = Map<String, dynamic>.from(t['selectedFlight'] as Map);
      final bool isOneWay = flight['tripType'] == 'one_way';
      final returnSegments = (flight['returnSegments'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      final bool isRoundTrip = !isOneWay &&
          (flight['tripType'] == 'round_trip' ||
              flight['roundTripComplete'] == true ||
              returnSegments.isNotEmpty ||
              (flight['returnDate'] ?? '').toString().isNotEmpty);

      String? returnSummary;
      if (isRoundTrip) {
        if (returnSegments.isNotEmpty) {
          final ret = returnSegments.first;
          final retDept = ret['departureAirportCode'] ?? ret['departureAirport'] ?? '-';
          final retArr = ret['arrivalAirportCode'] ?? ret['arrivalAirport'] ?? '-';
          final retDeptTime = ret['departureTime'] ?? '';
          final retArrTime = ret['arrivalTime'] ?? '';
          returnSummary = '$retDept to $retArr • $retDeptTime to $retArrTime'.trim();
        } else if ((flight['returnDate'] ?? '').toString().isNotEmpty) {
          returnSummary = 'Return date: ${flight['returnDate']}';
        }
      }

      final bool hasDateMismatch = _hasFlightDateMismatch(t, flight);

      cards.add(InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Attached flight',
                style: TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 6),
            if (hasDateMismatch) ...[
              Container(
                key: const ValueKey('flight-date-mismatch-warning'),
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppColors.warningSoft,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AppColors.warning.withValues(alpha: 0.35)),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.warning_amber_rounded,
                        size: 18, color: AppColors.warning),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        "Flight dates do not match this Trip's dates. Review your travel plan before relying on this itinerary.",
                        style: TextStyle(
                          fontSize: 12,
                          color: AppColors.warning,
                          fontWeight: FontWeight.w600,
                          height: 1.3,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            Text(
                '${flight['airline'] ?? 'Flight'} ${flight['flightNumber'] ?? ''}',
                style: const TextStyle(fontWeight: FontWeight.w700)),
            Text(
              'Outbound: ${flight['departureAirport'] ?? '-'} to ${flight['arrivalAirport'] ?? '-'} • ${flight['departureTime'] ?? '-'} to ${flight['arrivalTime'] ?? '-'}',
              style:
                  const TextStyle(fontSize: 12, color: InkWashColors.mutedInk),
            ),
            if (isOneWay) ...[
              const SizedBox(height: 2),
              const Text(
                'One-way flight',
                style: TextStyle(
                    fontSize: 12,
                    color: InkWashColors.mutedInk,
                    fontWeight: FontWeight.w600),
              ),
            ],
            if (isRoundTrip && returnSummary != null) ...[
              const SizedBox(height: 2),
              Text(
                'Return: $returnSummary',
                style: const TextStyle(fontSize: 12, color: InkWashColors.mutedInk),
              ),
            ],
            const SizedBox(height: 4),
            Text('Flight cost: RM ${t['flightCost'] ?? flight['price'] ?? 0}',
                style: const TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 2),
            const Text(
              'Planning estimate only • No airline ticket issued',
              style: TextStyle(
                  fontSize: 11,
                  color: InkWashColors.mutedInk,
                  fontStyle: FontStyle.italic),
            ),
            const SizedBox(height: 8),
            Wrap(spacing: 8, children: [
              OutlinedButton.icon(
                key: const ValueKey('adjust-flight-itinerary-btn'),
                onPressed: busy ? null : _previewFlightAdjustment,
                icon: const Icon(Icons.auto_fix_high_rounded),
                label: const Text('Adjust itinerary'),
              ),
              OutlinedButton.icon(
                key: const ValueKey('replace-flight-btn'),
                onPressed: busy ? null : () => _replaceFlight(t),
                icon: const Icon(Icons.swap_horiz_rounded),
                label: const Text('Replace Flight'),
              ),
              OutlinedButton.icon(
                key: const ValueKey('remove-flight-btn'),
                onPressed: busy ? null : _removeFlight,
                icon: const Icon(Icons.remove_circle_outline_rounded),
                label: const Text('Remove Flight'),
              ),
            ]),
          ],
        ),
      ));
    }
    if (t['selectedHotel'] is Map) {
      final hotel = Map<String, dynamic>.from(t['selectedHotel'] as Map);
      cards.add(InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Attached hotel',
                style: TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 6),
            Text((hotel['name'] ?? 'Hotel').toString(),
                style: const TextStyle(fontWeight: FontWeight.w700)),
            Text(
              '${hotel['roomName'] ?? 'Room'} - ${hotel['refundable'] == true ? 'Refundable' : hotel['refundable'] == false ? 'Non-refundable' : 'Cancellation terms unavailable'}',
              style:
                  const TextStyle(fontSize: 12, color: InkWashColors.mutedInk),
            ),
            Text(
              'Hotel cost: ${hotel['currency'] ?? 'MYR'} ${t['hotelCost'] ?? hotel['price'] ?? 0}',
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            if ((t['hotelBookingId'] ?? '').toString().isNotEmpty)
              Text('Hotel record ID: ${t['hotelBookingId']}',
                  style: const TextStyle(
                      fontSize: 12, color: InkWashColors.mutedInk)),
            const SizedBox(height: 10),
            Wrap(spacing: 8, children: [
              OutlinedButton.icon(
                onPressed: () => Navigator.push(context, MaterialPageRoute(
                    builder: (_) => HotelDetailsScreen(hotel: hotel))),
                icon: const Icon(Icons.info_outline_rounded),
                label: const Text('View details'),
              ),
              OutlinedButton.icon(
                onPressed: busy ? null : () => _replaceHotel(t),
                icon: const Icon(Icons.swap_horiz_rounded),
                label: const Text('Replace'),
              ),
              TextButton.icon(
                onPressed: busy ? null : _removeHotel,
                icon: const Icon(Icons.link_off_rounded),
                label: const Text('Remove from trip'),
              ),
            ]),
          ],
        ),
      ));
    }
    if (t['selectedCarRental'] is Map) {
      final rental = Map<String, dynamic>.from(t['selectedCarRental'] as Map);
      cards.add(InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Attached car rental',
                style: TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 6),
            Text((rental['vehicleName'] ?? 'Vehicle').toString(),
                style: const TextStyle(fontWeight: FontWeight.w700)),
            Text(
              '${rental['vehicleType'] ?? 'Vehicle'} - ${rental['rentalDays'] ?? '-'} day(s) - ${rental['pickupLocation'] ?? '-'}',
              style:
                  const TextStyle(fontSize: 12, color: InkWashColors.mutedInk),
            ),
            Text(
              'Car rental cost: ${rental['currency'] ?? 'MYR'} ${t['carRentalCost'] ?? rental['totalPrice'] ?? 0}',
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
          ],
        ),
      ));
    }
    return cards;
  }

  Future<void> _removeHotel() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove hotel from trip?'),
        content: const Text(
            'This removes the itinerary association only. Booking and payment history are kept.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Keep')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Remove')),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => busy = true);
    try {
      final data = await api
          .post('/api/fr5/itineraries/${widget.tripId}/hotel-selection/remove');
      if (mounted)
        setState(
            () => trip = Map<String, dynamic>.from(data['itinerary'] as Map));
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _replaceHotel(Map<String, dynamic> t) async {
    await Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) => HotelScreen(
                  api: api,
                  targetTripId: widget.tripId,
                  initialDestination: (t['destinationArea'] ?? '').toString(),
                  initialCheckin: (t['startDate'] ?? '').toString(),
                  initialCheckout: (t['endDate'] ?? '').toString(),
                  initialAdults: _tripAdults(t),
                  initialChildren: _tripChildren(t),
                  requiresGuestConfirmation: _tripAdults(t) == null,
                )));
    if (mounted) await load();
  }

  Future<void> _removeFlight() async {
    final t = trip;
    final flightCost = t?['flightCost'] ?? t?['selectedFlight']?['price'] ?? 0;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove flight from trip?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Are you sure you want to remove this flight planning reference?',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 12),
            Text(
                '• Flight cost (RM $flightCost) will be deducted from your committed transport budget.'),
            const SizedBox(height: 4),
            const Text('• Hotel and car rental bookings remain unaffected.'),
            const SizedBox(height: 4),
            const Text(
                '• Planned activities on travel dates will remain in your itinerary and may need manual review.'),
            const SizedBox(height: 4),
            const Text('• Manually protected activities will stay protected.'),
          ],
        ),
        actions: [
          TextButton(
            key: const ValueKey('cancel-remove-flight-btn'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep Flight'),
          ),
          FilledButton(
            key: const ValueKey('confirm-remove-flight-btn'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Remove Flight'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => busy = true);
    try {
      final data = await api.post(
          '/api/fr7/itineraries/${widget.tripId}/flight-selection/remove');
      if (mounted) {
        setState(() {
          trip = Map<String, dynamic>.from(data['itinerary'] as Map);
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Flight removed from trip. Budget updated.'),
          ),
        );
      }
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _previewFlightAdjustment() async {
    final result = await FlightAdjustmentPreviewSheet.show(
      context: context,
      api: api,
      tripId: widget.tripId,
      trip: trip ?? {},
    );
    if (result != null && result['itinerary'] is Map) {
      if (mounted) {
        setState(() =>
            trip = Map<String, dynamic>.from(result['itinerary'] as Map));
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Flight-aware itinerary changes applied.')));
      }
    }
  }

  Future<void> _replaceFlight(Map<String, dynamic> t) async {
    final flight = t['selectedFlight'] is Map
        ? Map<String, dynamic>.from(t['selectedFlight'] as Map)
        : <String, dynamic>{};
    final bool isOneWay = flight['tripType'] == 'one_way';
    final result = await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => FlightScreen(
          api: api,
          targetTripId: widget.tripId,
          targetTrip: t,
          initialDeparture: (flight['departureAirport'] ?? '').toString(),
          initialArrival:
              (flight['arrivalAirport'] ?? t['destinationArea'] ?? '')
                  .toString(),
          initialOutboundDate:
              (flight['outboundDate'] ?? t['startDate'] ?? '').toString(),
          initialReturnDate: isOneWay
              ? null
              : (flight['returnDate'] ?? t['endDate'] ?? '').toString(),
        ),
      ),
    );
    if (mounted) {
      if (result is Map && result['id'] != null) {
        setState(() => trip = Map<String, dynamic>.from(result));
      }
      await load();
    }
  }

  Future<void> editTrip() async {
    final t = trip;
    if (t == null) return;
    final title = TextEditingController(text: (t['title'] ?? '').toString());
    final destination =
        TextEditingController(text: (t['destinationArea'] ?? '').toString());
    final start =
        TextEditingController(text: (t['startDate'] ?? '').toString());
    final end = TextEditingController(text: (t['endDate'] ?? '').toString());
    final travellers =
        TextEditingController(text: '${t['travellerCount'] ?? 1}');
    final budget = TextEditingController(text: '${t['budgetLimit'] ?? 0}');

    Future<void> pickDate(
        BuildContext c, TextEditingController controller) async {
      final initial = DateTime.tryParse(controller.text) ??
          DateTime.now().add(const Duration(days: 7));
      final today = DateTime.now();
      final firstDate = DateTime(today.year, today.month, today.day);
      final picked = await showDatePicker(
        context: c,
        initialDate: initial.isBefore(firstDate) ? firstDate : initial,
        firstDate: firstDate,
        lastDate: DateTime.now().add(const Duration(days: 730)),
      );
      if (picked != null) {
        controller.text =
            '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
      }
    }

    final payload = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetContext) => Padding(
        padding: EdgeInsets.fromLTRB(
            18, 0, 18, MediaQuery.of(sheetContext).viewInsets.bottom + 22),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Edit trip details',
                  style: Theme.of(sheetContext).textTheme.headlineSmall),
              const SizedBox(height: AppSpacing.md),
              AppTextField(
                  controller: title,
                  label: 'Trip title',
                  prefixIcon: Icons.title_rounded),
              const SizedBox(height: AppSpacing.sm),
              AppTextField(
                  controller: destination,
                  label: 'Destination',
                  prefixIcon: Icons.location_on_outlined),
              const SizedBox(height: AppSpacing.sm),
              AppTextField(
                controller: start,
                readOnly: true,
                onTap: () => pickDate(sheetContext, start),
                label: 'Start date',
                prefixIcon: Icons.calendar_month_outlined,
              ),
              const SizedBox(height: AppSpacing.sm),
              AppTextField(
                controller: end,
                readOnly: true,
                onTap: () => pickDate(sheetContext, end),
                label: 'End date',
                prefixIcon: Icons.event_outlined,
              ),
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  Expanded(
                      child: AppTextField(
                          controller: travellers,
                          keyboardType: TextInputType.number,
                          label: 'Travellers')),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                      child: AppTextField(
                          controller: budget,
                          keyboardType: TextInputType.number,
                          label: 'Budget (RM)')),
                ],
              ),
              const SizedBox(height: AppSpacing.md),
              PrimaryButton(
                onPressed: () {
                  if (title.text.trim().isEmpty ||
                      destination.text.trim().isEmpty) return;
                  final startDate = DateTime.tryParse(start.text.trim());
                  final endDate = DateTime.tryParse(end.text.trim());
                  if (startDate == null ||
                      endDate == null ||
                      endDate.isBefore(startDate)) {
                    showError(sheetContext,
                        'End date must be on or after the start date.');
                    return;
                  }
                  Navigator.pop(sheetContext, {
                    'title': title.text.trim(),
                    'destinationArea': destination.text.trim(),
                    'startDate': start.text.trim(),
                    'endDate': end.text.trim(),
                    'travellerCount': int.tryParse(travellers.text) ?? 1,
                    'budgetLimit': double.tryParse(budget.text) ?? 0,
                  });
                },
                icon: Icons.save_outlined,
                label: 'Save trip details',
              ),
            ],
          ),
        ),
      ),
    );
    if (payload == null) return;
    try {
      await api.put('/api/fr5/itineraries/${widget.tripId}', payload);
      await load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> addPlaces() async {
    final t = trip;
    if (t == null) return;
    final selected = await Navigator.push<List<Map<String, dynamic>>>(
      context,
      MaterialPageRoute(
        builder: (_) => TripPlacePickerScreen(
          initialLocation: (t['destinationArea'] ?? 'Malaysia').toString(),
          api: api,
          trip: t,
          initialDay: selectedDay,
        ),
      ),
    );
    if (selected == null || selected.isEmpty) return;
    final targetDay = selected.first['dayNo'] is int
        ? selected.first['dayNo'] as int
        : selectedDay;
    setState(() => busy = true);
    try {
      for (final place in selected) {
        final day = place['dayNo'] is int ? place['dayNo'] as int : targetDay;
        final payload = buildActivityPayload(place, dayNo: day);
        await api.post(
            '/api/fr5/itineraries/${widget.tripId}/activities', payload);
      }
      await load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text(
                  '${selected.length} place${selected.length == 1 ? '' : 's'} added to Day $targetDay.')),
        );
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> removeActivity(Map<String, dynamic> activity) async {
    setState(() => busy = true);
    try {
      await api.delete(
          '/api/fr5/itineraries/${widget.tripId}/activities/${activity['activityId']}');
      await load();
    } catch (_) {
      if (mounted) showError(context, 'We could not remove this activity.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> confirmRemoveActivity(Map<String, dynamic> activity) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Remove this activity?'),
        content: Text(
          '${activity['activityName'] ?? 'This place'} will be removed and the remaining itinerary will be recalculated.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Keep activity'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: TextButton.styleFrom(foregroundColor: AppColors.error),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed == true) await removeActivity(activity);
  }

  Future<void> reorderDay(int oldIndex, int newIndex) async {
    final day = trip == null ? <String, dynamic>{} : _selectedSchedule(trip!);
    final dayList = _dayActivities(day);
    if (newIndex > oldIndex) newIndex -= 1;
    final moved = dayList.removeAt(oldIndex);
    dayList.insert(newIndex, moved);
    final replacement = dayList.iterator;
    var next = replacement.moveNext() ? replacement.current : null;
    final list = activities.map((item) {
      if (int.tryParse('${item['dayNo']}') != selectedDay || next == null) {
        return item;
      }
      final value = next!;
      next = replacement.moveNext() ? replacement.current : null;
      return value;
    }).toList();
    if (mounted) {
      setState(() {
        final copy = Map<String, dynamic>.from(trip!);
        copy['activities'] = list;
        trip = copy;
      });
    }
    final ids = list
        .map((e) => e['activityId']?.toString() ?? '')
        .where((e) => e.isNotEmpty)
        .toList();
    try {
      await api.post(
          '/api/fr5/itineraries/${widget.tripId}/activities/rearrange',
          {'orderedActivityIds': ids});
      await load();
    } catch (_) {
      if (mounted) showError(context, 'We could not reorder this day.');
      await load();
    }
  }

  Future<void> moveActivity(
      Map<String, dynamic> activity, int targetDay) async {
    if (targetDay == selectedDay) return;
    setState(() => busy = true);
    try {
      await api.put(
        '/api/fr5/itineraries/${widget.tripId}/activities/${activity['activityId']}',
        {'dayNo': targetDay},
      );
      selectedDay = targetDay;
      await load();
    } catch (_) {
      if (mounted) showError(context, 'We could not move this activity.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> generate() async {
    final t = trip;
    if (t == null || busy) return;
    setState(() => busy = true);
    try {
      final result =
          await api.post('/api/fr5/itineraries/${widget.tripId}/generate', {
        'destinationName': t['destinationArea'] ?? '',
        if ((t['recommendationGenerationId'] ?? '').toString().isNotEmpty)
          'recommendationGenerationId': t['recommendationGenerationId'],
      });
      if (result is Map && result['ok'] != true) {
        throw Exception(result['error'] ?? 'Trip generation failed.');
      }
      await load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Trip days and activity timing updated.')));
      }
    } catch (_) {
      await load();
      if (mounted) {
        showError(context, 'We could not finish updating this itinerary.');
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> showBudget() async {
    try {
      final data =
          await api.get('/api/fr5/itineraries/${widget.tripId}/budget');

      if (data is! Map || data['ok'] == false || data['budget'] is! Map) {
        throw StateError('Budget details are unavailable. Please try again.');
      }
      final budgetModel = BudgetModel.fromJson(
        Map<String, dynamic>.from(data['budget'] as Map),
        fallbackLimit: double.tryParse('${trip?['budgetLimit']}') ?? 0,
      );

      if (!mounted) return;
      setState(() {
        if (trip != null) {
          trip = {
            ...trip!,
            'budgetEstimate': Map<String, dynamic>.from(data['budget'] as Map),
          };
        }
      });

      Navigator.push(
          context,
          MaterialPageRoute(
              builder: (context) => BudgetComparisonScreen(
                    budget: budgetModel,
                    userBudget: budgetModel.budgetLimit,
                    tripId: widget.tripId,
                  )));
    } catch (e) {
      if (mounted) {
        showError(context, e);
      }
    }
  }

  Future<void> viewPlace(Map<String, dynamic> activity) async {
    final id = (activity['destinationId'] ?? '').toString();
    Map<String, dynamic> initial = {
      'destinationId': id,
      'place_id': id,
      'title': activity['activityName'] ?? 'Place',
      'address': activity['address'] ?? '',
      'category': activity['category'] ?? '',
      'openingHours': activity['openingHours'] ?? '',
      'estimatedCost': activity['estimatedCost'] ?? 0,
      'indoor': activity['indoor'] ?? false,
      for (final field in _placeImageFields)
        if (activity[field] != null) field: activity[field],
    };
    try {
      if (id.isNotEmpty) {
        final data =
            await api.get('/api/fr3/destinations/${Uri.encodeComponent(id)}');
        if (data['destination'] is Map) {
          initial = {
            ...initial,
            ...Map<String, dynamic>.from(data['destination'] as Map),
          };
        }
      }
    } catch (_) {}
    if (!mounted) return;
    await Navigator.push(
        context,
        MaterialPageRoute(
            builder: (_) =>
                DestinationDetailsScreen(initialDestination: initial)));
  }

  Timer? _midnightTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    api = widget.api ?? ApiService();
    _scheduleMidnightTimer();
    Future.microtask(load);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _midnightTimer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && mounted) {
      setState(() {});
      _scheduleMidnightTimer();
    }
  }

  void _scheduleMidnightTimer() {
    _midnightTimer?.cancel();
    final delay = TripStatusHelper.durationUntilMidnight();
    _midnightTimer = Timer(delay, () {
      if (mounted) {
        setState(() {});
        _scheduleMidnightTimer();
      }
    });
  }

  Widget _tripHeader(Map<String, dynamic> t) {
    final travellerCount = int.tryParse('${t['travellerCount'] ?? 1}') ?? 1;
    final temporal = TripStatusHelper.resolveStatus(
      t,
      referenceDate: widget.referenceDate,
    );
    final lifecycleRaw = (t['status'] ?? 'draft').toString().toLowerCase();
    final isDraft = lifecycleRaw == 'draft';
    final isGenerating = lifecycleRaw == 'generating';
    final isFailed = lifecycleRaw == 'generation_failed';

    return InkCard(
      color: AppColors.surfaceElevated,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text((t['title'] ?? 'Your trip').toString(),
              style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: AppSpacing.xxs),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.location_on_outlined,
                size: AppSizes.iconSmall, color: AppColors.textSecondary),
            const SizedBox(width: AppSpacing.xxs),
            Expanded(
              child: Text(
                (t['destinationArea'] ?? 'Destination not set').toString(),
                style: Theme.of(context).textTheme.bodyLarge,
              ),
            ),
          ]),
          const SizedBox(height: AppSpacing.sm),
          Wrap(spacing: AppSpacing.xs, runSpacing: AppSpacing.xs, children: [
            StatusChip(
              text: _friendlyDateRange(t),
              icon: Icons.calendar_today_outlined,
              tone: AppStatusTone.neutral,
            ),
            StatusChip(
              text:
                  '$travellerCount traveller${travellerCount == 1 ? '' : 's'}',
              icon: Icons.people_outline_rounded,
              tone: AppStatusTone.neutral,
            ),
            if (temporal != null)
              StatusChip(
                key: const ValueKey('trip-temporal-status-chip'),
                text: temporal.label,
                icon: temporal.icon,
                tone: temporal.tone,
              ),
            if (isDraft)
              StatusChip(
                text: _lifecycleLabel(t['status']),
                icon: _lifecycleIcon(t['status']),
                tone: _lifecycleTone(t['status']),
              ),
            if (isGenerating)
              StatusChip(
                text: _lifecycleLabel(t['status']),
                icon: _lifecycleIcon(t['status']),
                tone: _lifecycleTone(t['status']),
              ),
            if (isFailed)
              StatusChip(
                text: _lifecycleLabel(t['status']),
                icon: _lifecycleIcon(t['status']),
                tone: _lifecycleTone(t['status']),
              ),
            if (temporal == null && !isDraft && !isGenerating && !isFailed)
              StatusChip(
                text: _lifecycleLabel(t['status']),
                icon: _lifecycleIcon(t['status']),
                tone: _lifecycleTone(t['status']),
              ),
          ]),
        ],
      ),
    );
  }

  Widget _generationState(Map<String, dynamic> t) {
    if (t['status'] == 'generating') {
      return InkCard(
        color: AppColors.infoSoft,
        child: Column(children: [
          const AppLoadingState(message: 'Building your itinerary…'),
          Text(
            'We’re arranging activities around time, distance, opening hours and budget.',
            textAlign: TextAlign.center,
            style: Theme.of(context)
                .textTheme
                .bodyMedium
                ?.copyWith(color: AppColors.textSecondary),
          ),
        ]),
      );
    }
    return AppErrorState(
      title: 'Trip generation did not finish',
      message: _failureMessage(t),
      retryLabel: 'Retry generation',
      onRetry: t['retryable'] == true && !busy ? generate : null,
    );
  }

  Widget _dayNavigation(Map<String, dynamic> t) {
    final days = _dailySchedules(t);
    return SizedBox(
      height: 66,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: days.length,
        separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.xs),
        itemBuilder: (context, index) {
          final day = days[index];
          final dayNo = int.tryParse('${day['dayNo']}') ?? index + 1;
          final selected = dayNo == selectedDay;
          return Semantics(
            button: true,
            selected: selected,
            label: 'Show day $dayNo',
            child: ChoiceChip(
              key: ValueKey('trip-day-$dayNo'),
              selected: selected,
              onSelected: (_) => setState(() {
                selectedDay = dayNo;
                editingItinerary = false;
              }),
              label: Column(mainAxisSize: MainAxisSize.min, children: [
                Text('Day $dayNo'),
                if ((day['dayDate'] ?? '').toString().isNotEmpty)
                  Text(_shortDate(day['dayDate'].toString()),
                      style: Theme.of(context).textTheme.bodySmall),
              ]),
            ),
          );
        },
      ),
    );
  }

  String _money(num value) =>
      value % 1 == 0 ? value.toInt().toString() : value.toStringAsFixed(2);

  Widget _daySummary(Map<String, dynamic> t, Map<String, dynamic> day) {
    final dayItems = _dayActivities(day);
    final weather = day['weather'] is Map
        ? Map<String, dynamic>.from(day['weather'] as Map)
        : <String, dynamic>{'source': 'unavailable'};
    final storedCost = double.tryParse('${day['estimatedCost'] ?? ''}');
    final cost = storedCost ??
        dayItems.fold<double>(
          0,
          (sum, item) =>
              sum + (double.tryParse('${item['estimatedCost']}') ?? 0),
        );
    return InkCard(
      color: AppColors.primarySoft,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(
          'Day $selectedDay · ${t['destinationArea'] ?? 'Your destination'}',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        if ((day['dayDate'] ?? '').toString().isNotEmpty) ...[
          const SizedBox(height: AppSpacing.xxs),
          Text(
            _shortDate(day['dayDate'].toString()),
            style: Theme.of(context)
                .textTheme
                .bodyMedium
                ?.copyWith(color: AppColors.textSecondary),
          ),
        ],
        const SizedBox(height: AppSpacing.sm),
        Wrap(spacing: AppSpacing.xs, runSpacing: AppSpacing.xs, children: [
          StatusChip(
            key: const ValueKey('day-weather-summary'),
            text: _weatherSummary(weather),
            icon: weather['source'] == 'unavailable'
                ? Icons.cloud_off_outlined
                : weather['heavyRainLikely'] == true
                    ? Icons.umbrella_outlined
                    : Icons.cloud_outlined,
            tone: weather['heavyRainLikely'] == true
                ? AppStatusTone.warning
                : AppStatusTone.neutral,
          ),
          StatusChip(
            text:
                '${dayItems.length} activit${dayItems.length == 1 ? 'y' : 'ies'}',
            icon: Icons.place_outlined,
            tone: AppStatusTone.neutral,
          ),
          if (cost > 0)
            StatusChip(
              text: 'RM ${_money(cost)} estimated',
              icon: Icons.account_balance_wallet_outlined,
              tone: AppStatusTone.neutral,
            ),
        ]),
      ]),
    );
  }

  Widget _travelTransition(Map<String, dynamic> activity) {
    final minutes =
        int.tryParse('${activity['travelDurationMinutes'] ?? 0}') ?? 0;
    if (minutes <= 0) return const SizedBox.shrink();
    final distance = double.tryParse('${activity['travelDistanceKm'] ?? ''}');
    final confirmed = {'provider', 'confirmed'}
        .contains((activity['travelTimeSource'] ?? '').toString());
    final distanceText = distance == null
        ? null
        : distance % 1 == 0
            ? distance.toInt().toString()
            : distance.toStringAsFixed(1);
    final text = [
      confirmed ? '$minutes min' : '~$minutes min estimated',
      if (distance != null && distance > 0) '$distanceText km',
    ].join(' · ');
    return Semantics(
      label: 'Travel to next activity, $text',
      child: Padding(
        padding: const EdgeInsets.only(
            left: AppSpacing.md, top: AppSpacing.xs, bottom: AppSpacing.xs),
        child: Row(children: [
          const Icon(Icons.south_rounded,
              size: AppSizes.iconSmall, color: AppColors.textSecondary),
          const SizedBox(width: AppSpacing.xs),
          Text(text,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: AppColors.textSecondary)),
        ]),
      ),
    );
  }

  Widget _activityCard(Map<String, dynamic> activity) {
    final category =
        (activity['category'] ?? activity['type'] ?? '').toString().trim();
    final cost = double.tryParse('${activity['estimatedCost'] ?? 0}') ?? 0;
    final notes = _activityNotes(activity);
    final isProvisional = _isProvisional(activity);
    final isFree = _isVerifiedFree(activity);
    final isConditional = _isPriceConditional(activity);
    final isPriceUnverified = _isPriceUnverified(activity);
    final isVerifiedPaid = _isPriceVerified(activity) && !isFree;

    final showLeftNote = isProvisional || isPriceUnverified;
    final leftNoteText = (isProvisional && isPriceUnverified)
        ? 'Hours & price\nunverified'
        : isProvisional
            ? 'Hours\nunverified'
            : 'Price\nunverified';

    final semanticsHours = isProvisional ? ', Hours unverified' : '';
    final semanticsPricing = isFree
        ? ', Free admission'
        : isConditional
            ? ', Tariff conditional'
            : isPriceUnverified
                ? ', Price unverified'
                : '';

    return Semantics(
      container: true,
      label:
          '${_timeText(activity)}$semanticsHours$semanticsPricing, ${activity['activityName'] ?? 'Activity'}',
      child: InkCard(
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            width: 66,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  (activity['scheduledStartTime'] ??
                          activity['timeSlot'] ??
                          'Time TBC')
                      .toString(),
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(color: AppColors.primaryStrong),
                ),
                if (showLeftNote) ...[
                  const SizedBox(height: 2),
                  Text(
                    leftNoteText,
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          color: AppColors.textSecondary,
                          fontSize: 9.5,
                          fontWeight: FontWeight.w600,
                          height: 1.15,
                        ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          TravelPlaceImage(
            place: activity,
            width: 70,
            height: 70,
            borderRadius: AppRadii.control,
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: InkWell(
              onTap: () => viewPlace(activity),
              borderRadius: AppRadii.control,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text((activity['activityName'] ?? 'Activity').toString(),
                        style: Theme.of(context).textTheme.titleMedium),
                    LocalPlaceRating(place:activity),
                    const SizedBox(height: AppSpacing.xxs),
                    Wrap(
                        spacing: AppSpacing.xs,
                        runSpacing: AppSpacing.xxs,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          if (isProvisional)
                            const StatusChip(
                              text: 'Hours unverified',
                              tone: AppStatusTone.neutral,
                            ),
                          if (isFree)
                            const StatusChip(
                              text: 'Free admission',
                              tone: AppStatusTone.success,
                              icon: Icons.check_circle_outline_rounded,
                            ),
                          if (isConditional)
                            const StatusChip(
                              text: 'Tariff conditional',
                              tone: AppStatusTone.neutral,
                              icon: Icons.info_outline_rounded,
                            ),
                          if (isPriceUnverified)
                            const StatusChip(
                              text: 'Admission unverified',
                              tone: AppStatusTone.neutral,
                              icon: Icons.help_outline_rounded,
                            ),
                          if (category.isNotEmpty)
                            Text(category,
                                style: Theme.of(context).textTheme.bodySmall),
                          if (_durationText(activity).isNotEmpty)
                            Text(_durationText(activity),
                                style: Theme.of(context).textTheme.bodySmall),
                          if (isConditional && cost > 0)
                            Text('~RM ${_money(cost)} tariff',
                                style: Theme.of(context).textTheme.bodySmall)
                          else if (isPriceUnverified && cost > 0)
                            Text('~RM ${_money(cost)} estimate',
                                style: Theme.of(context).textTheme.bodySmall)
                          else if (isPriceUnverified && cost <= 0)
                            Text('Price TBC',
                                style: Theme.of(context).textTheme.bodySmall)
                          else if (isVerifiedPaid && cost > 0)
                            Text('RM ${_money(cost)} verified',
                                style: Theme.of(context).textTheme.bodySmall)
                          else if (!isFree && cost > 0)
                            Text('RM ${_money(cost)} estimated',
                                style: Theme.of(context).textTheme.bodySmall),
                        ]),
                    if (notes.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        notes.first,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context)
                            .textTheme
                            .bodySmall
                            ?.copyWith(color: AppColors.textSecondary),
                      ),
                    ],
                  ]),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _planningBlock(Map<String, dynamic> block) {
    final duration = int.tryParse('${block['durationMinutes'] ?? 0}') ?? 0;
    return Semantics(
      container: true,
      label:
          '${block['startTime'] ?? ''}, ${block['label'] ?? 'Planning break'}',
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
        child: Row(children: [
          SizedBox(
            width: 58,
            child: Text((block['startTime'] ?? '').toString(),
                style: Theme.of(context).textTheme.titleSmall),
          ),
          const SizedBox(width: AppSpacing.xs),
          const Icon(Icons.restaurant_outlined, color: AppColors.textSecondary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text((block['label'] ?? 'Lunch / Rest').toString(),
                  style: Theme.of(context).textTheme.titleMedium),
              if (duration > 0)
                Text(
                  _durationText({'recommendedDurationMinutes': duration}),
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
            ]),
          ),
        ]),
      ),
    );
  }

  List<Widget> _timeline(Map<String, dynamic> day) {
    final entries = <Map<String, dynamic>>[
      ..._dayActivities(day).map((item) => {
            'kind': 'activity',
            'time': item['scheduledStartTime'] ?? item['timeSlot'] ?? '',
            'value': item,
          }),
      ..._planningBlocks(day).map((block) => {
            'kind': 'block',
            'time': block['startTime'] ?? '',
            'value': block,
          }),
    ]..sort((a, b) => a['time'].toString().compareTo(b['time'].toString()));
    final widgets = <Widget>[];
    var activitySeen = false;
    for (final entry in entries) {
      final value = Map<String, dynamic>.from(entry['value'] as Map);
      if (entry['kind'] == 'activity') {
        if (activitySeen) widgets.add(_travelTransition(value));
        widgets.add(_activityCard(value));
        activitySeen = true;
      } else {
        widgets.add(_planningBlock(value));
      }
    }
    return widgets;
  }

  Future<void> _activityMenuAction(
      String value, Map<String, dynamic> activity) async {
    if (value == 'view') return viewPlace(activity);
    if (value == 'remove') return confirmRemoveActivity(activity);
    if (value.startsWith('day:')) {
      final day = int.tryParse(value.substring(4));
      if (day != null) await moveActivity(activity, day);
    }
  }

  Widget _editTimeline(Map<String, dynamic> t, Map<String, dynamic> day) {
    final dayItems = _dayActivities(day);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      InkCard(
        color: AppColors.infoSoft,
        child: Text(
          'Drag to reorder this day. Use the menu to move or remove an activity. TravelMate recalculates timing and budget after each change.',
          style: Theme.of(context).textTheme.bodyMedium,
        ),
      ),
      const SizedBox(height: AppSpacing.sm),
      ReorderableListView.builder(
        key: const ValueKey('edit-itinerary-list'),
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        buildDefaultDragHandles: false,
        itemCount: dayItems.length,
        onReorder: busy ? (_, __) {} : reorderDay,
        itemBuilder: (context, index) {
          final activity = dayItems[index];
          return Padding(
            key: ValueKey('edit-${activity['activityId'] ?? index}'),
            padding: const EdgeInsets.only(bottom: AppSpacing.xs),
            child: InkCard(
              child: Row(children: [
                ReorderableDragStartListener(
                  index: index,
                  child: const SizedBox.square(
                    dimension: AppSizes.minimumTapTarget,
                    child: Icon(Icons.drag_indicator_rounded,
                        semanticLabel: 'Drag to reorder',
                        color: AppColors.textSecondary),
                  ),
                ),
                const SizedBox(width: AppSpacing.xs),
                Expanded(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                            (activity['activityName'] ?? 'Activity').toString(),
                            style: Theme.of(context).textTheme.titleMedium),
                        Text(
                          '${activity['scheduledStartTime'] ?? activity['timeSlot'] ?? 'Time TBC'} · ${_durationText(activity)}${_isProvisional(activity) ? ' · Hours unverified' : ''}',
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(color: AppColors.textSecondary),
                        ),
                      ]),
                ),
                PopupMenuButton<String>(
                  tooltip: 'Activity actions',
                  onSelected: (value) => _activityMenuAction(value, activity),
                  itemBuilder: (_) => [
                    const PopupMenuItem(
                        value: 'view', child: Text('View place')),
                    for (var dayNo = 1; dayNo <= _tripDays(t); dayNo++)
                      if (dayNo != selectedDay)
                        PopupMenuItem(
                            value: 'day:$dayNo',
                            child: Text('Move to Day $dayNo')),
                    const PopupMenuDivider(),
                    const PopupMenuItem(
                      value: 'remove',
                      child: Text('Remove activity',
                          style: TextStyle(color: AppColors.error)),
                    ),
                  ],
                ),
              ]),
            ),
          );
        },
      ),
      const SizedBox(height: AppSpacing.xs),
      SecondaryButton(
        label: 'Search and add places',
        icon: Icons.add_location_alt_outlined,
        onPressed: busy ? null : addPlaces,
      ),
    ]);
  }

  Widget _budgetAwareTransparencyCard(Map<String, dynamic> t) {
    final bas = t['budgetAwareSelection'] is Map
        ? Map<String, dynamic>.from(t['budgetAwareSelection'] as Map)
        : <String, dynamic>{};
    final isProvisional = bas['isProvisional'] == true ||
        activities.any((a) => _isPriceUnverified(a) || _isProvisional(a));
    final rationale = _formatSelectionRationale(bas['selectionRationale']);
    final unselected = (bas['unselectedActivities'] as List? ?? const [])
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();

    final bool allAdmissionsVerified = activities.isNotEmpty &&
        activities.every((a) => _isPriceVerified(a) || _isVerifiedFree(a));
    final String statusChipLabel = isProvisional
        ? 'Provisional estimate'
        : (allAdmissionsVerified ? 'Admission verified' : 'Known estimated costs');
    final AppStatusTone statusChipTone = isProvisional
        ? AppStatusTone.neutral
        : (allAdmissionsVerified ? AppStatusTone.success : AppStatusTone.info);

    return InkCard(
      key: const ValueKey('budget-aware-transparency-card'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            crossAxisAlignment: WrapCrossAlignment.center,
            alignment: WrapAlignment.spaceBetween,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.tune_rounded,
                      size: AppSizes.icon, color: AppColors.primaryStrong),
                  const SizedBox(width: AppSpacing.xs),
                  Flexible(
                    child: Text(
                      'Budget-aware itinerary',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                ],
              ),
              StatusChip(
                text: statusChipLabel,
                tone: statusChipTone,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            isProvisional
                ? 'Planned with available cost information. Some admission fees or schedule constraints remain unverified. Allowances for food and transport are estimated.'
                : 'Planned considering your travel style, schedule feasibility, and confirmed admission fees. Food and transport allowances remain estimated.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppColors.textSecondary,
                  height: 1.35,
                ),
          ),
          if (rationale != null && rationale.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(
              rationale,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    fontStyle: FontStyle.italic,
                    color: AppColors.textSecondary,
                  ),
            ),
          ],
          if (unselected.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xs),
            ExpansionTile(
              key: const ValueKey('unselected-activities-expansion'),
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text(
                'Other places considered (${unselected.length})',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
              children: [
                for (final item in unselected)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.info_outline,
                            size: 16, color: AppColors.textSecondary),
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _unselectedActivityName(item),
                                style: Theme.of(context)
                                    .textTheme
                                    .bodySmall
                                    ?.copyWith(fontWeight: FontWeight.w600),
                              ),
                              Text(
                                _friendlyUnselectedReason(item),
                                style: Theme.of(context)
                                    .textTheme
                                    .bodySmall
                                    ?.copyWith(color: AppColors.textSecondary),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ],
          const SizedBox(height: AppSpacing.xs),
          Text(
            'Unresolved admission costs are not guaranteed within the initial budget. Food and transport allowances do not confirm payments or reservations.',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: AppColors.textSecondary,
                  fontStyle: FontStyle.italic,
                ),
          ),
        ],
      ),
    );
  }

  Widget _budgetSection(Map<String, dynamic> t) {
    final budget = BudgetModel.fromJson(
      t['budgetEstimate'] is Map
          ? Map<String, dynamic>.from(t['budgetEstimate'] as Map)
          : <String, dynamic>{},
      fallbackLimit: double.tryParse('${t['budgetLimit']}') ?? 0,
    );
    return InkCard(
      key: const ValueKey('trip-budget-progress'),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Text('Trip budget',
                style: Theme.of(context).textTheme.titleLarge),
          ),
          TertiaryButton(label: 'View details', onPressed: showBudget),
        ]),
        BudgetBreakdown(budget: budget, limit: budget.budgetLimit),
      ]),
    );
  }

  Widget _unscheduledSection(List<Map<String, dynamic>> unscheduled) {
    if (unscheduled.isEmpty) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      AppSectionHeader(
        title: 'Couldn’t fit into your schedule',
        subtitle:
            '${unscheduled.length} suggestion${unscheduled.length == 1 ? '' : 's'} kept for later.',
      ),
      const SizedBox(height: AppSpacing.sm),
      ...unscheduled.map(
        (item) => Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.xs),
          child: InkCard(
            child: Row(children: [
              const Icon(Icons.schedule_outlined, color: AppColors.warning),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                          (item['activityName'] ?? 'Suggested place')
                              .toString(),
                          style: Theme.of(context).textTheme.titleMedium),
                      Text(
                        _friendlyUnscheduledReason(item),
                        style: Theme.of(context)
                            .textTheme
                            .bodySmall
                            ?.copyWith(color: AppColors.textSecondary),
                      ),
                    ]),
              ),
              TextButton(
                  onPressed: () => viewPlace(item), child: const Text('View')),
            ]),
          ),
        ),
      ),
    ]);
  }

  Widget _tripEssentials(Map<String, dynamic> t) {
    final list = activities;
    final attachments = _attachedTravelCards(t);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const AppSectionHeader(
          title: 'Trip essentials',
          subtitle: 'Bookings and supporting travel tools.'),
      if (attachments.isNotEmpty) ...[
        const SizedBox(height: AppSpacing.sm),
        ...attachments.map((card) => Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: card,
            )),
      ],
      const SizedBox(height: AppSpacing.sm),
      Wrap(spacing: AppSpacing.xs, runSpacing: AppSpacing.xs, children: [
        SecondaryButton(
          label: 'Weather',
          icon: Icons.cloud_outlined,
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => WeatherScreen(
                initialPlace: (t['destinationArea'] ?? '').toString(),
                tripStartDate: (t['startDate'] ?? '').toString(),
                tripEndDate: (t['endDate'] ?? '').toString(),
                tripActivities: list,
              ),
            ),
          ),
        ),
        SecondaryButton(
          label: 'Flights',
          icon: Icons.flight_takeoff_rounded,
          onPressed: () async {
            await Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => FlightScreen(
                api: api,
                initialOutboundDate: (t['startDate'] ?? '').toString(),
                initialReturnDate: (t['endDate'] ?? '').toString(),
              ),
            ),
            );
            if (mounted) await load();
          },
        ),
        SecondaryButton(
          label: 'Hotels',
          icon: Icons.hotel_rounded,
          onPressed: () async {
            await Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => HotelScreen(
                  api: api,
                  targetTripId: widget.tripId,
                  initialDestination: (t['destinationArea'] ?? '').toString(),
                  initialCheckin: (t['startDate'] ?? '').toString(),
                  initialCheckout: (t['endDate'] ?? '').toString(),
                  initialAdults: _tripAdults(t),
                  initialChildren: _tripChildren(t),
                  requiresGuestConfirmation: _tripAdults(t) == null,
                ),
              ),
            );
            if (mounted) await load();
          },
        ),
        SecondaryButton(
          label: 'Packing checklist',
          icon: Icons.checklist_rounded,
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => PackingChecklistScreen(
                tripId: (t['id'] ?? widget.tripId).toString(),
                tripTitle: (t['title'] ?? 'Trip').toString(),
                destination: (t['destinationArea'] ?? '').toString(),
                durationDays: t['durationDays'] as int?,
                api: api,
              ),
            ),
          ),
        ),
        SecondaryButton(
          label: 'Travel Records',
          icon: Icons.bookmark_outline_rounded,
          onPressed: () => Navigator.push(context, MaterialPageRoute(
            builder: (_) => TravelRecordsScreen(api: api))),
        ),
      ]),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final t = trip;
    if (loading && t == null) {
      return TravelMatePageScaffold(
        appBar: AppBar(title: const Text('Trip details')),
        body: const AppLoadingState(message: 'Loading your trip…'),
      );
    }
    if (t == null) {
      return TravelMatePageScaffold(
        appBar: AppBar(title: const Text('Trip details')),
        body: AppErrorState(
          title: 'Trip unavailable',
          message: loadError ?? 'This trip could not be found.',
          onRetry: load,
        ),
      );
    }
    if (t['tripType'] == 'package' || t['packageTrip'] == true) {
      return PackageTripDetailsScreen(
        tripId: widget.tripId,
        api: api,
        initialTrip: t,
      );
    }
    final unscheduled = (t['unscheduledSuggestions'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
    final day = _selectedSchedule(t);
    final dayItems = _dayActivities(day);
    final generating = t['status'] == 'generating';
    final failed = t['status'] == 'generation_failed';
    return TravelMatePageScaffold(
      appBar: AppBar(
        title: const Text('Trip details'),
        actions: [
          IconButton(
            onPressed: editTrip,
            icon: const Icon(Icons.edit_outlined),
            tooltip: 'Edit trip details',
          ),
          IconButton(
            onPressed: loading ? null : load,
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh trip',
          ),
        ],
      ),
      padding: EdgeInsets.zero,
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          key: const ValueKey('trip-details-scroll'),
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.md,
            AppSpacing.xs,
            AppSpacing.md,
            AppSpacing.xxl,
          ),
          children: [
            _tripHeader(t),
            if (generating || failed) ...[
              const SizedBox(height: AppSpacing.md),
              _generationState(t),
            ],
            if (!generating) ...[
              if (_isBudgetAwareApplied(t)) ...[
                const SizedBox(height: AppSpacing.md),
                _budgetAwareTransparencyCard(t),
              ],
              const SizedBox(height: AppSpacing.lg),
              _dayNavigation(t),
              const SizedBox(height: AppSpacing.sm),
              _daySummary(t, day),
              const SizedBox(height: AppSpacing.md),
              AppSectionHeader(
                title: 'Day $selectedDay itinerary',
                subtitle: editingItinerary
                    ? 'Editing this day'
                    : 'Activities, breaks and travel between stops.',
                actionLabel: dayItems.isEmpty
                    ? null
                    : editingItinerary
                        ? 'Done'
                        : 'Edit itinerary',
                onAction: dayItems.isEmpty
                    ? null
                    : () =>
                        setState(() => editingItinerary = !editingItinerary),
              ),
              const SizedBox(height: AppSpacing.sm),
              if (dayItems.isEmpty)
                TravelEmptyState(
                  icon: Icons.route_outlined,
                  title: 'No activities for this day',
                  message:
                      'Add a place or recalculate the itinerary to build this day.',
                  actionLabel: 'Find places',
                  onAction: busy ? null : addPlaces,
                )
              else if (editingItinerary)
                _editTimeline(t, day)
              else
                ..._timeline(day),
              if (dayItems.isNotEmpty && !editingItinerary) ...[
                const SizedBox(height: AppSpacing.xs),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TertiaryButton(
                    label: 'Recalculate itinerary',
                    icon: Icons.auto_fix_high_rounded,
                    onPressed: busy ? null : generate,
                  ),
                ),
              ],
              const SizedBox(height: AppSpacing.lg),
              _budgetSection(t),
              if (unscheduled.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.lg),
                _unscheduledSection(unscheduled),
              ],
            ],
            const SizedBox(height: AppSpacing.lg),
            _tripEssentials(t),
          ],
        ),
      ),
    );
  }
}

class TripPlacePickerScreen extends StatefulWidget {
  final String initialLocation;
  final ApiService? api;
  final Map<String, dynamic>? trip;
  final int? initialDay;

  const TripPlacePickerScreen({
    super.key,
    required this.initialLocation,
    this.api,
    this.trip,
    this.initialDay,
  });

  @override
  State<TripPlacePickerScreen> createState() => _TripPlacePickerScreenState();
}

class _TripPlacePickerScreenState extends State<TripPlacePickerScreen> {
  late final ApiService api;
  late final TextEditingController query;
  late final TextEditingController location;
  late int chosenDay;
  List<Map<String, dynamic>> results = [];
  final Map<String, Map<String, dynamic>> selected = {};
  bool loading = false;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    chosenDay = widget.initialDay ?? 1;
    query = TextEditingController(text: 'attractions');
    location = TextEditingController(text: widget.initialLocation);
    Future.microtask(search);
  }

  @override
  void dispose() {
    query.dispose();
    location.dispose();
    super.dispose();
  }

  String idOf(Map<String, dynamic> item) =>
      (item['destinationId'] ?? item['place_id'] ?? item['title'] ?? '')
          .toString();

  Future<void> search() async {
    if (query.text.trim().isEmpty) return;
    setState(() => loading = true);
    try {
      final data = await api.get('/api/fr3/destinations/search', {
        'q': query.text.trim(),
        'location':
            location.text.trim().isEmpty ? 'Malaysia' : location.text.trim(),
      });
      if (!mounted) return;
      setState(() {
        results = (data['results'] as List? ?? [])
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Add places'),
        actions: [
          TextButton(
            onPressed: selected.isEmpty
                ? null
                : () {
                    final items = selected.values.map((place) {
                      final copy = Map<String, dynamic>.from(place);
                      copy['dayNo'] = chosenDay;
                      return copy;
                    }).toList();
                    Navigator.pop(context, items);
                  },
            child: Text('Add ${selected.length}'),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 10),
            child: Column(
              children: [
                TextField(
                  controller: query,
                  textInputAction: TextInputAction.search,
                  onSubmitted: (_) => search(),
                  decoration: const InputDecoration(
                      hintText: 'Search a place, dish or attraction',
                      prefixIcon: Icon(Icons.search_rounded)),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: location,
                  textInputAction: TextInputAction.search,
                  onSubmitted: (_) => search(),
                  decoration: const InputDecoration(
                      hintText: 'Location',
                      prefixIcon: Icon(Icons.location_on_outlined)),
                ),
                const SizedBox(height: 8),
                SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                        onPressed: loading ? null : search,
                        icon: const Icon(Icons.travel_explore_rounded),
                        label: const Text('Search'))),
                if (widget.trip != null &&
                    extractTripDayOptions(widget.trip!).length > 1) ...[
                  const SizedBox(height: 8),
                  InkWell(
                    key: const ValueKey('change-day-selector'),
                    onTap: () async {
                      final picked = await promptTripDaySelection(
                        context: context,
                        trip: widget.trip!,
                        initialDay: chosenDay,
                      );
                      if (picked != null && mounted) {
                        setState(() => chosenDay = picked);
                      }
                    },
                    borderRadius: BorderRadius.circular(8),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 8),
                      decoration: BoxDecoration(
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest
                            .withValues(alpha: 0.5),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                          color:
                              Theme.of(context).colorScheme.outlineVariant,
                        ),
                      ),
                      child: Row(
                        children: [
                          Icon(Icons.calendar_today_rounded,
                              size: 16,
                              color: Theme.of(context).colorScheme.primary),
                          const SizedBox(width: 8),
                          Text(
                            'Adding to: Day $chosenDay',
                            style: const TextStyle(
                                fontWeight: FontWeight.w600, fontSize: 13),
                          ),
                          const Spacer(),
                          Text(
                            'Change',
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.primary,
                                fontSize: 12,
                                fontWeight: FontWeight.bold),
                          ),
                          const SizedBox(width: 4),
                          Icon(Icons.arrow_drop_down_rounded,
                              size: 18,
                              color: Theme.of(context).colorScheme.primary),
                        ],
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: loading
                ? const Center(child: CircularProgressIndicator())
                : results.isEmpty
                    ? const Center(
                        child: Padding(
                            padding: EdgeInsets.all(24),
                            child: Text(
                                'No places found. Try another keyword or location.')))
                    : ListView.separated(
                        padding: const EdgeInsets.all(16),
                        itemCount: results.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 10),
                        itemBuilder: (context, index) {
                          final item = results[index];
                          final id = idOf(item);
                          final checked = selected.containsKey(id);
                          return InkCard(
                            padding: EdgeInsets.zero,
                            child: InkWell(
                              borderRadius: BorderRadius.circular(20),
                              onTap: () => setState(() {
                                if (checked) {
                                  selected.remove(id);
                                } else {
                                  selected[id] = item;
                                }
                              }),
                              child: Row(
                                children: [
                                  TravelPlaceImage(
                                    place: item,
                                    width: 105,
                                    height: 105,
                                    borderRadius: const BorderRadius.horizontal(
                                        left: Radius.circular(20)),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                            (item['title'] ??
                                                    item['name'] ??
                                                    'Place')
                                                .toString(),
                                            style: const TextStyle(
                                                fontWeight: FontWeight.w900)),
                                        const SizedBox(height: 3),
                                        Text((item['address'] ?? '').toString(),
                                            maxLines: 2,
                                            overflow: TextOverflow.ellipsis,
                                            style: const TextStyle(
                                                fontSize: 12,
                                                color: InkWashColors.mutedInk)),
                                        const SizedBox(height: 5),
                                        Text(
                                            '${item['category'] ?? item['type'] ?? ''}',
                                            style:
                                                const TextStyle(fontSize: 12)),
                                        LocalPlaceRating(place:item),
                                      ],
                                    ),
                                  ),
                                  Checkbox(
                                      value: checked,
                                      onChanged: (_) => setState(() {
                                            if (checked) {
                                              selected.remove(id);
                                            } else {
                                              selected[id] = item;
                                            }
                                          })),
                                  const SizedBox(width: 6),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}
