import 'package:flutter/material.dart';
import 'budget_comparison_screen.dart';
import 'models/budget_model.dart';
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

  const TripDetailsScreen({super.key, required this.tripId});

  @override
  State<TripDetailsScreen> createState() => _TripDetailsScreenState();
}

class _TripDetailsScreenState extends State<TripDetailsScreen> {
  final api = ApiService();
  Map<String, dynamic>? trip;
  bool loading = true;
  bool busy = false;

  Future<void> load() async {
    setState(() => loading = true);
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
      setState(() => trip = found);
    } catch (e) {
      if (mounted) showError(context, e);
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

  String _dayText(Map<String, dynamic> activity) {
    final label = (activity['dayLabel'] ?? '').toString();
    if (label.isNotEmpty) return label;
    return 'Day ${activity['dayNo'] ?? 1}';
  }

  String _durationText(Map<String, dynamic> activity) {
    final duration =
        int.tryParse('${activity['recommendedDurationMinutes'] ?? 0}') ?? 0;
    final buffer = int.tryParse('${activity['travelBufferMinutes'] ?? 0}') ?? 0;
    final parts = <String>[];
    if (duration > 0) parts.add('$duration min visit');
    if (buffer > 0) parts.add('$buffer min travel buffer');
    return parts.join(' • ');
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

  List<String> _weatherNotes(Map<String, dynamic> t) {
    final context = t['generationContext'];
    if (context is! Map) return [];
    return (context['weatherNotes'] as List? ?? [])
        .map((e) => e.toString())
        .where((e) => e.trim().isNotEmpty)
        .take(2)
        .toList();
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
      final picked = await showDatePicker(
        context: c,
        initialDate: initial,
        firstDate: DateTime.now().subtract(const Duration(days: 1)),
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
              const Text('Edit trip details',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
              const SizedBox(height: 14),
              TextField(
                  controller: title,
                  decoration: const InputDecoration(
                      labelText: 'Trip title',
                      prefixIcon: Icon(Icons.title_rounded))),
              const SizedBox(height: 10),
              TextField(
                  controller: destination,
                  decoration: const InputDecoration(
                      labelText: 'Destination',
                      prefixIcon: Icon(Icons.location_on_outlined))),
              const SizedBox(height: 10),
              TextField(
                controller: start,
                readOnly: true,
                onTap: () => pickDate(sheetContext, start),
                decoration: const InputDecoration(
                    labelText: 'Start date',
                    prefixIcon: Icon(Icons.calendar_month_outlined)),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: end,
                readOnly: true,
                onTap: () => pickDate(sheetContext, end),
                decoration: const InputDecoration(
                    labelText: 'End date',
                    prefixIcon: Icon(Icons.event_outlined)),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                      child: TextField(
                          controller: travellers,
                          keyboardType: TextInputType.number,
                          decoration:
                              const InputDecoration(labelText: 'Travellers'))),
                  const SizedBox(width: 8),
                  Expanded(
                      child: TextField(
                          controller: budget,
                          keyboardType: TextInputType.number,
                          decoration:
                              const InputDecoration(labelText: 'Budget (RM)'))),
                ],
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: () {
                  if (title.text.trim().isEmpty ||
                      destination.text.trim().isEmpty) return;
                  Navigator.pop(sheetContext, {
                    'title': title.text.trim(),
                    'destinationArea': destination.text.trim(),
                    'startDate': start.text.trim(),
                    'endDate': end.text.trim(),
                    'travellerCount': int.tryParse(travellers.text) ?? 1,
                    'budgetLimit': double.tryParse(budget.text) ?? 0,
                  });
                },
                icon: const Icon(Icons.save_outlined),
                label: const Text('Save trip details'),
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
    try {
      await api.delete(
          '/api/fr5/itineraries/${widget.tripId}/activities/${activity['activityId']}');
      await load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> reorder(int oldIndex, int newIndex) async {
    final list = activities;
    if (newIndex > oldIndex) newIndex -= 1;
    final moved = list.removeAt(oldIndex);
    list.insert(newIndex, moved);
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
    } catch (e) {
      if (mounted) showError(context, e);
      await load();
    }
  }

  Future<void> generate() async {
    final t = trip;
    if (t == null) return;
    setState(() => busy = true);
    try {
      await api.post('/api/fr5/itineraries/${widget.tripId}/generate', {
        'destinationName': t['destinationArea'] ?? '',
      });
      await load();
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Trip days and activity timing updated.')));
    } catch (e) {
      if (mounted) showError(context, e);
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
    };
    try {
      if (id.isNotEmpty) {
        final data =
            await api.get('/api/fr3/destinations/${Uri.encodeComponent(id)}');
        if (data['destination'] is Map)
          initial = Map<String, dynamic>.from(data['destination'] as Map);
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
    Future.microtask(load);
  }

  @override
  Widget build(BuildContext context) {
    final t = trip;
    if (loading && t == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (t == null) {
      return Scaffold(
          appBar: AppBar(title: const Text('Trip details')),
          body: const Center(child: Text('Trip not found.')));
    }
    final list = activities;
    return Scaffold(
      appBar: AppBar(
        title: Text((t['title'] ?? 'Trip').toString()),
        actions: [
          IconButton(
              onPressed: editTrip,
              icon: const Icon(Icons.edit_outlined),
              tooltip: 'Edit trip'),
          IconButton(onPressed: load, icon: const Icon(Icons.refresh_rounded)),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 6, 18, 28),
          children: [
            InkCard(
              color: InkWashColors.cream,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text((t['destinationArea'] ?? '').toString(),
                      style: const TextStyle(
                          fontSize: 20, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 5),
                  Text(_dateRange(t),
                      style: const TextStyle(color: InkWashColors.mutedInk)),
                  const SizedBox(height: 9),
                  Wrap(
                    spacing: 7,
                    runSpacing: 7,
                    children: [
                      TravelStatusPill(
                          text: 'RM ${t['budgetLimit'] ?? 0}',
                          icon: Icons.account_balance_wallet_outlined),
                      TravelStatusPill(
                          text: '${_tripDays(t)} day(s)',
                          icon: Icons.calendar_today_outlined),
                      TravelStatusPill(
                          text: '${list.length} places',
                          icon: Icons.place_outlined),
                      TravelStatusPill(
                          text: '${t['travellerCount'] ?? 1} traveller(s)',
                          icon: Icons.people_outline_rounded),
                      if (t['totalScheduledMinutes'] != null)
                        TravelStatusPill(
                            text: '${t['totalScheduledMinutes']} planned min',
                            icon: Icons.schedule_outlined),
                    ],
                  ),
                  if (_weatherNotes(t).isNotEmpty) ...[
                    const SizedBox(height: 10),
                    ..._weatherNotes(t).map((note) => Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(note,
                              style: const TextStyle(
                                  color: InkWashColors.blueGrey,
                                  fontWeight: FontWeight.w700)),
                        )),
                  ],
                ],
              ),
            ),
            if (_attachedTravelCards(t).isNotEmpty) ...[
              const SizedBox(height: 12),
              ..._attachedTravelCards(t).map((card) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: card,
                  )),
            ],
            const SizedBox(height: 18),
            const TravelSectionHeader(
              title: 'Places & sequence',
              subtitle:
                  'Drag places into the order you want. TravelMate will update the sequence and day grouping.',
            ),
            const SizedBox(height: 10),
            if (list.isEmpty)
              TravelEmptyState(
                icon: Icons.add_location_alt_outlined,
                title: 'No places added yet',
                message:
                    'Search places in TravelMate and add them to this trip instead of typing activities manually.',
                actionLabel: 'Find places',
                onAction: addPlaces,
              )
            else
              ReorderableListView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                buildDefaultDragHandles: false,
                itemCount: list.length,
                onReorder: reorder,
                itemBuilder: (context, index) {
                  final activity = list[index];
                  return Padding(
                    key: ValueKey(activity['activityId'] ??
                        '$index-${activity['activityName']}'),
                    padding: const EdgeInsets.only(bottom: 8),
                    child: InkCard(
                      child: Row(
                        children: [
                          ReorderableDragStartListener(
                            index: index,
                            child: const Padding(
                              padding: EdgeInsets.only(right: 10),
                              child: Icon(Icons.drag_indicator_rounded,
                                  color: InkWashColors.softGrey),
                            ),
                          ),
                          CircleAvatar(
                            radius: 20,
                            backgroundColor: InkWashColors.paleBlue,
                            child: Text('${index + 1}',
                                style: const TextStyle(
                                    fontWeight: FontWeight.w900)),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: InkWell(
                              onTap: () => viewPlace(activity),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                      (activity['activityName'] ?? 'Place')
                                          .toString(),
                                      style: const TextStyle(
                                          fontWeight: FontWeight.w900)),
                                  const SizedBox(height: 2),
                                  Text(
                                      '${_dayText(activity)} • ${_timeText(activity)}',
                                      style: const TextStyle(
                                          fontSize: 12,
                                          color: InkWashColors.mutedInk)),
                                  if (_durationText(activity).isNotEmpty) ...[
                                    const SizedBox(height: 2),
                                    Text(_durationText(activity),
                                        style: const TextStyle(
                                            fontSize: 12,
                                            color: InkWashColors.mutedInk)),
                                  ],
                                  if (_activityNotes(activity).isNotEmpty) ...[
                                    const SizedBox(height: 4),
                                    ..._activityNotes(activity).map((note) =>
                                        Text(note,
                                            maxLines: 2,
                                            overflow: TextOverflow.ellipsis,
                                            style: const TextStyle(
                                                fontSize: 12,
                                                color:
                                                    InkWashColors.blueGrey))),
                                  ],
                                ],
                              ),
                            ),
                          ),
                          IconButton(
                              onPressed: () => viewPlace(activity),
                              icon: const Icon(Icons.info_outline_rounded),
                              tooltip: 'Place details'),
                          IconButton(
                              onPressed: () => removeActivity(activity),
                              icon: const Icon(Icons.close_rounded),
                              tooltip: 'Remove'),
                        ],
                      ),
                    ),
                  );
                },
              ),
            const SizedBox(height: 10),
            FilledButton.icon(
              onPressed: busy ? null : addPlaces,
              icon: const Icon(Icons.add_location_alt_outlined),
              label: const Text('Search and add places'),
            ),
            const SizedBox(height: 18),
            const TravelSectionHeader(
                title: 'Plan tools',
                subtitle:
                    'Generate timing, check the budget and continue booking decisions'),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                    onPressed: busy ? null : generate,
                    icon: const Icon(Icons.auto_fix_high_rounded),
                    label: const Text('Arrange trip days')),
                OutlinedButton.icon(
                    onPressed: showBudget,
                    icon: const Icon(Icons.account_balance_wallet_outlined),
                    label: const Text('Budget')),
                OutlinedButton.icon(
                    onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => WeatherScreen(
                                  initialPlace:
                                      (t['destinationArea'] ?? '').toString(),
                                  tripStartDate:
                                      (t['startDate'] ?? '').toString(),
                                  tripEndDate: (t['endDate'] ?? '').toString(),
                                  tripActivities: list,
                                ))),
                    icon: const Icon(Icons.cloud_outlined),
                    label: const Text('Weather')),
                OutlinedButton.icon(
                    onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => FlightScreen(
                                  initialOutboundDate:
                                      (t['startDate'] ?? '').toString(),
                                  initialReturnDate:
                                      (t['endDate'] ?? '').toString(),
                                ))),
                    icon: const Icon(Icons.flight_takeoff_rounded),
                    label: const Text('Flights')),
                OutlinedButton.icon(
                    onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => HotelScreen(
                                  initialDestination:
                                      (t['destinationArea'] ?? '').toString(),
                                  initialCheckin:
                                      (t['startDate'] ?? '').toString(),
                                  initialCheckout:
                                      (t['endDate'] ?? '').toString(),
                                ))),
                    icon: const Icon(Icons.hotel_rounded),
                    label: const Text('Hotels')),
                OutlinedButton.icon(
                    onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => CarRentalScreen(
                                  initialPickupLocation:
                                      (t['destinationArea'] ?? '').toString(),
                                  initialPickupDate:
                                      (t['startDate'] ?? '').toString(),
                                  initialDropoffDate:
                                      (t['endDate'] ?? '').toString(),
                                ))),
                    icon: const Icon(Icons.directions_car_outlined),
                    label: const Text('Car rentals')),
                OutlinedButton.icon(
                    onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => const PaymentScreen())),
                    icon: const Icon(Icons.credit_card_rounded),
                    label: const Text('Payment')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class TripPlacePickerScreen extends StatefulWidget {
  final String initialLocation;

  const TripPlacePickerScreen({super.key, required this.initialLocation});

  @override
  State<TripPlacePickerScreen> createState() => _TripPlacePickerScreenState();
}

class _TripPlacePickerScreenState extends State<TripPlacePickerScreen> {
  final api = ApiService();
  late final TextEditingController query;
  late final TextEditingController location;
  List<Map<String, dynamic>> results = [];
  final Map<String, Map<String, dynamic>> selected = {};
  bool loading = false;

  @override
  void initState() {
    super.initState();
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
