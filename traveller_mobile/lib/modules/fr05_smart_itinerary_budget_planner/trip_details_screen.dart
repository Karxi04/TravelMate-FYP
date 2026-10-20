import 'package:flutter/material.dart';
import 'budget_comparison_screen.dart';
import 'models/budget_model.dart';
import 'package_trip_details_screen.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr03_destination_search_information/destination_details_screen.dart';
import '../fr06_weather_forecast/weather_screen.dart';
import '../fr07_flight_search/flight_screen.dart';
import '../fr08_hotel_booking/hotel_screen.dart';
import '../fr08_hotel_booking/car_rental_screen.dart';
import '../fr09_payment/payment_screen.dart';

class TripDetailsScreen extends StatefulWidget {
  final String tripId;
  final ApiService? api;

  const TripDetailsScreen({super.key, required this.tripId, this.api});

  @override
  State<TripDetailsScreen> createState() => _TripDetailsScreenState();
}

class _TripDetailsScreenState extends State<TripDetailsScreen> {
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

  List<String> _activityNotes(Map<String, dynamic> activity) {
    final notes = <String>[];
    final weather = (activity['weatherNote'] ?? '').toString();
    if (weather.isNotEmpty &&
        weather != 'No major weather rearrangement required.')
      notes.add(weather);
    for (final note in (activity['scheduleNotes'] as List? ?? [])) {
      final text = note.toString();
      if (text.trim().isNotEmpty && !notes.contains(text)) notes.add(text);
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
    final reason = (item['unscheduledReason'] ?? '').toString().toLowerCase();
    if (reason.contains('closed')) {
      return 'This place is closed during your trip dates.';
    }
    if (reason.contains('opening')) {
      return 'It couldn’t fit within the available opening hours.';
    }
    return 'There wasn’t enough time to fit this place safely.';
  }

  List<Widget> _attachedTravelCards(Map<String, dynamic> t) {
    final cards = <Widget>[];
    if (t['selectedFlight'] is Map) {
      final flight = Map<String, dynamic>.from(t['selectedFlight'] as Map);
      cards.add(InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Attached flight',
                style: TextStyle(fontWeight: FontWeight.w900)),
            const SizedBox(height: 6),
            Text(
                '${flight['airline'] ?? 'Flight'} ${flight['flightNumber'] ?? ''}',
                style: const TextStyle(fontWeight: FontWeight.w700)),
            Text(
              '${flight['departureAirport'] ?? '-'} to ${flight['arrivalAirport'] ?? '-'} - ${flight['departureTime'] ?? '-'} to ${flight['arrivalTime'] ?? '-'}',
              style:
                  const TextStyle(fontSize: 12, color: InkWashColors.mutedInk),
            ),
            if (t['flightCost'] != null)
              Text('Flight cost: RM ${t['flightCost']}',
                  style: const TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 8),
            Wrap(spacing: 8, children: [
              OutlinedButton.icon(
                onPressed: busy ? null : _previewFlightAdjustment,
                icon: const Icon(Icons.auto_fix_high_rounded),
                label: const Text('Adjust itinerary'),
              ),
              OutlinedButton.icon(
                onPressed: busy ? null : () => _replaceFlight(t),
                icon: const Icon(Icons.swap_horiz_rounded),
                label: const Text('Change'),
              ),
              OutlinedButton.icon(
                onPressed: busy ? null : _removeFlight,
                icon: const Icon(Icons.remove_circle_outline_rounded),
                label: const Text('Remove'),
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
              '${hotel['roomName'] ?? 'Room'} - ${hotel['refundable'] == true ? 'Refundable' : 'Non-refundable'}',
              style:
                  const TextStyle(fontSize: 12, color: InkWashColors.mutedInk),
            ),
            Text(
              'Hotel cost: ${hotel['currency'] ?? 'MYR'} ${t['hotelCost'] ?? hotel['price'] ?? 0}',
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            if ((t['hotelBookingId'] ?? '').toString().isNotEmpty)
              Text('Booking ID: ${t['hotelBookingId']}',
                  style: const TextStyle(
                      fontSize: 12, color: InkWashColors.mutedInk)),
            const SizedBox(height: 10),
            Wrap(spacing: 8, children: [
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
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove flight from trip?'),
        content: const Text('This removes the planning reference only.'),
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
      final data = await api.post(
          '/api/fr7/itineraries/${widget.tripId}/flight-selection/remove');
      if (mounted)
        setState(
            () => trip = Map<String, dynamic>.from(data['itinerary'] as Map));
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _previewFlightAdjustment() async {
    setState(() => busy = true);
    try {
      final data = await api.post(
          '/api/fr5/itineraries/${widget.tripId}/flight-adjustment/preview');
      final preview = data['preview'] is Map
          ? Map<String, dynamic>.from(data['preview'] as Map)
          : <String, dynamic>{};
      if (!mounted) return;
      final apply = await showDialog<bool>(
        context: context,
        builder: (dialogContext) {
          final changes = (preview['changes'] as List? ?? [])
              .whereType<Map>()
              .map((e) => Map<String, dynamic>.from(e))
              .toList();
          final unscheduled = (preview['newlyUnscheduled'] as List? ?? [])
              .whereType<Map>()
              .map((e) => Map<String, dynamic>.from(e))
              .toList();
          final conflicts = (preview['remainingConflicts'] as List? ?? [])
              .whereType<Map>()
              .map((e) => Map<String, dynamic>.from(e))
              .toList();
          final canApply = preview['canApply'] == true;
          return AlertDialog(
            title: const Text('Review flight-aware adjustment'),
            content: SizedBox(
              width: 520,
              child: SingleChildScrollView(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(canApply
                          ? 'TravelMate proposes changes only on the flight-affected dates. Your current trip stays saved until you apply this preview.'
                          : (preview['reason'] ??
                                  'The flight data is incomplete for a safe adjustment.')
                              .toString()),
                      const SizedBox(height: 12),
                      if (preview['availability'] is Map)
                        Text(
                            'Availability uses Penang local time and the stated TravelMate planning assumptions.'),
                      if (changes.isEmpty && canApply)
                        const Text('No activity timing changes are needed.'),
                      ...changes.map((change) => Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(
                                '${change['activityName'] ?? 'Activity'}: ${change['kind'] ?? 'retained'}${change['reason'] == null ? '' : ' — ${change['reason']}'}'),
                          )),
                      if (unscheduled.isNotEmpty) ...[
                        const SizedBox(height: 12),
                        const Text('Would become unscheduled',
                            style: TextStyle(fontWeight: FontWeight.w900)),
                        ...unscheduled.map((item) => Text(
                            '• ${item['activityName'] ?? item['activityId']}: ${item['unscheduledReason'] ?? 'Needs manual review'}')),
                      ],
                      if (conflicts.isNotEmpty) ...[
                        const SizedBox(height: 12),
                        const Text('Remaining conflicts',
                            style: TextStyle(fontWeight: FontWeight.w900)),
                        ...conflicts.map((item) => Text(
                            '• ${item['message'] ?? 'Manual review required'}')),
                      ],
                    ]),
              ),
            ),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(dialogContext, false),
                  child: const Text('Keep current plan')),
              FilledButton(
                  onPressed: canApply
                      ? () => Navigator.pop(dialogContext, true)
                      : null,
                  child: const Text('Apply changes')),
            ],
          );
        },
      );
      if (apply != true) return;
      final result = await api.post(
          '/api/fr5/itineraries/${widget.tripId}/flight-adjustment/apply',
          {'previewId': preview['previewId']});
      if (mounted && result['itinerary'] is Map) {
        setState(
            () => trip = Map<String, dynamic>.from(result['itinerary'] as Map));
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Flight-aware itinerary changes applied.')));
      }
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _replaceFlight(Map<String, dynamic> t) async {
    final flight = t['selectedFlight'] is Map
        ? Map<String, dynamic>.from(t['selectedFlight'] as Map)
        : <String, dynamic>{};
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => FlightScreen(
          initialDeparture: (flight['departureAirport'] ?? '').toString(),
          initialArrival:
              (flight['arrivalAirport'] ?? t['destinationArea'] ?? '')
                  .toString(),
          initialOutboundDate: (t['startDate'] ?? '').toString(),
          initialReturnDate: (t['endDate'] ?? '').toString(),
        ),
      ),
    );
    await load();
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
        ),
      ),
    );
    if (selected == null || selected.isEmpty) return;
    setState(() => busy = true);
    try {
      for (final place in selected) {
        await api.post('/api/fr5/itineraries/${widget.tripId}/activities', {
          'activityName':
              (place['title'] ?? place['name'] ?? 'Place').toString(),
          'destinationId':
              (place['destinationId'] ?? place['place_id'] ?? place['title'])
                  .toString(),
          'address': place['address'] ?? '',
          'estimatedCost': place['estimatedCost'] ?? 0,
          'gps_coordinates':
              place['gps_coordinates'] ?? place['gpsCoordinates'] ?? {},
          'type': place['type'] ?? place['category'] ?? '',
          'category': place['category'] ?? place['type'] ?? '',
          'description': place['description'] ?? '',
          'indoor': place['indoor'] ?? false,
          'openingHours': place['openingHours'] ?? '',
          'recommendedDurationMinutes':
              place['recommendedDurationMinutes'] ?? 90,
          for (final field in _placeImageFields)
            if (place[field] != null) field: place[field],
          'dayNo': 1,
        });
      }
      await load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text(
                  '${selected.length} place${selected.length == 1 ? '' : 's'} added to the trip.')),
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

      final budget = Map<String, dynamic>.from(data['budget'] as Map);

      final budgetModel = BudgetModel(
        accommodation: double.tryParse(budget['hotel'].toString()) ?? 0,
        food: double.tryParse(budget['food'].toString()) ?? 0,
        transportation: double.tryParse(budget['transport'].toString()) ?? 0,
        activities: double.tryParse(budget['activities'].toString()) ?? 0,
      );

      final limit = double.tryParse(budget['limit'].toString()) ?? 0;

      if (!mounted) return;

      Navigator.push(
          context,
          MaterialPageRoute(
              builder: (context) => BudgetComparisonScreen(
                    budget: budgetModel,
                    userBudget: limit,
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

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(load);
  }

  Widget _tripHeader(Map<String, dynamic> t) {
    final travellerCount = int.tryParse('${t['travellerCount'] ?? 1}') ?? 1;
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
    return Semantics(
      container: true,
      label:
          '${_timeText(activity)}, ${activity['activityName'] ?? 'Activity'}',
      child: InkCard(
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            width: 58,
            child: Text(
              (activity['scheduledStartTime'] ??
                      activity['timeSlot'] ??
                      'Time TBC')
                  .toString(),
              style: Theme.of(context)
                  .textTheme
                  .titleSmall
                  ?.copyWith(color: AppColors.primaryStrong),
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
                    const SizedBox(height: AppSpacing.xxs),
                    Wrap(
                        spacing: AppSpacing.xs,
                        runSpacing: AppSpacing.xxs,
                        children: [
                          if (category.isNotEmpty)
                            Text(category,
                                style: Theme.of(context).textTheme.bodySmall),
                          if (_durationText(activity).isNotEmpty)
                            Text(_durationText(activity),
                                style: Theme.of(context).textTheme.bodySmall),
                          if (cost > 0)
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
        color: AppColors.warningSoft,
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
                          '${activity['scheduledStartTime'] ?? activity['timeSlot'] ?? 'Time TBC'} · ${_durationText(activity)}',
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

  String _costKind(Map<String, dynamic> provenance, String key) {
    final value = (provenance[key] ?? '').toString();
    return value.startsWith('confirmed') || value == 'provided'
        ? 'confirmed'
        : 'estimated';
  }

  Widget _budgetSection(Map<String, dynamic> t) {
    if (t['budgetEstimate'] is! Map) return const SizedBox.shrink();
    final budget = Map<String, dynamic>.from(t['budgetEstimate'] as Map);
    final total = double.tryParse('${budget['total'] ?? 0}') ?? 0;
    final limit =
        double.tryParse('${budget['limit'] ?? t['budgetLimit'] ?? 0}') ?? 0;
    if (total <= 0 && limit <= 0) return const SizedBox.shrink();
    final provenance = budget['costProvenance'] is Map
        ? Map<String, dynamic>.from(budget['costProvenance'] as Map)
        : <String, dynamic>{};
    final categories = <(String, String, dynamic)>[
      ('Activities', 'activities', budget['activities']),
      ('Food', 'food', budget['food']),
      ('Transport', 'transport', budget['transport']),
      ('Stay', 'hotel', budget['hotel']),
      ('Flights', 'flight', budget['flight']),
      ('Car rental', 'carRental', budget['carRental']),
    ].where((entry) => (double.tryParse('${entry.$3 ?? 0}') ?? 0) > 0);
    final progress = limit <= 0 ? 0.0 : (total / limit).clamp(0.0, 1.0);
    final overBudget = limit > 0 && total > limit;
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
        Text(
          limit > 0
              ? 'RM ${_money(total)} of RM ${_money(limit)} estimated'
              : 'RM ${_money(total)} estimated',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        if (limit > 0) ...[
          const SizedBox(height: AppSpacing.sm),
          Semantics(
            label: '${(progress * 100).round()} percent of trip budget used',
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 9,
              borderRadius: BorderRadius.circular(AppRadii.pill),
              color: overBudget ? AppColors.error : AppColors.success,
              backgroundColor: AppColors.divider,
            ),
          ),
        ],
        if (categories.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.md),
          ...categories.map((entry) {
            final value = double.tryParse('${entry.$3}') ?? 0;
            return Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: Row(children: [
                Expanded(child: Text(entry.$1)),
                Text(
                  '${_costKind(provenance, entry.$2)} · RM ${_money(value)}',
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
              ]),
            );
          }),
        ],
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
    final selectedHotel = t['selectedHotel'] is Map
        ? Map<String, dynamic>.from(t['selectedHotel'] as Map)
        : <String, dynamic>{};
    final selectedFlight = t['selectedFlight'] is Map
        ? Map<String, dynamic>.from(t['selectedFlight'] as Map)
        : <String, dynamic>{};
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
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => FlightScreen(
                initialOutboundDate: (t['startDate'] ?? '').toString(),
                initialReturnDate: (t['endDate'] ?? '').toString(),
              ),
            ),
          ),
        ),
        SecondaryButton(
          label: 'Hotels',
          icon: Icons.hotel_rounded,
          onPressed: () async {
            await Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => HotelScreen(
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
          label: 'Car rental',
          icon: Icons.directions_car_outlined,
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => CarRentalScreen(
                initialPickupLocation: (t['destinationArea'] ?? '').toString(),
                initialPickupDate: (t['startDate'] ?? '').toString(),
                initialDropoffDate: (t['endDate'] ?? '').toString(),
              ),
            ),
          ),
        ),
        SecondaryButton(
          label: 'Payment',
          icon: Icons.credit_card_rounded,
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => PaymentScreen(
                initialBookingReference:
                    (selectedHotel['bookingReference'] ?? '').toString(),
                initialAmount: selectedHotel['price'] is num
                    ? (selectedHotel['price'] as num).toDouble()
                    : selectedFlight['price'] is num
                        ? (selectedFlight['price'] as num).toDouble()
                        : null,
                quoteType:
                    (selectedHotel['quoteId'] ?? '').toString().isNotEmpty
                        ? 'hotel'
                        : (selectedFlight['flightSearchId'] ?? '')
                                .toString()
                                .isNotEmpty
                            ? 'flight'
                            : '',
                quoteId: (selectedHotel['quoteId'] ?? '').toString(),
                offerId: (selectedHotel['offerId'] ?? '').toString(),
                acceptedPrebookSnapshotId:
                    (selectedHotel['acceptedPrebookSnapshotId'] ??
                            selectedHotel['snapshotId'] ??
                            '')
                        .toString(),
                acceptedPrebook: selectedHotel['acceptedPrebook'] is Map
                    ? Map<String, dynamic>.from(
                        selectedHotel['acceptedPrebook'] as Map)
                    : null,
                searchId: (selectedFlight['flightSearchId'] ?? '').toString(),
                optionId: (selectedFlight['flightOptionId'] ??
                        selectedFlight['optionId'] ??
                        '')
                    .toString(),
              ),
            ),
          ),
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

  const TripPlacePickerScreen({
    super.key,
    required this.initialLocation,
    this.api,
  });

  @override
  State<TripPlacePickerScreen> createState() => _TripPlacePickerScreenState();
}

class _TripPlacePickerScreenState extends State<TripPlacePickerScreen> {
  late final ApiService api;
  late final TextEditingController query;
  late final TextEditingController location;
  List<Map<String, dynamic>> results = [];
  final Map<String, Map<String, dynamic>> selected = {};
  bool loading = false;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
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
                : () => Navigator.pop(context, selected.values.toList()),
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
                                            '★ ${item['rating'] ?? '-'} • ${item['category'] ?? item['type'] ?? ''}',
                                            style:
                                                const TextStyle(fontSize: 12)),
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
