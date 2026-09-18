import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../theme/app_theme.dart';
import 'trip_details_screen.dart';

class TripsTab extends StatefulWidget {
  const TripsTab({super.key});

  @override
  State<TripsTab> createState() => _TripsTabState();
}

class _TripsTabState extends State<TripsTab> {
  final api = ApiService();
  List<dynamic> items = [];
  bool busy = false;

  String _date(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  int _tripDays(Map<String, dynamic> trip) {
    final start = DateTime.tryParse((trip['startDate'] ?? '').toString());
    final end = DateTime.tryParse((trip['endDate'] ?? '').toString());
    if (start != null && end != null)
      return (end.difference(start).inDays + 1).clamp(1, 14).toInt();
    return int.tryParse('${trip['tripDays'] ?? 1}') ?? 1;
  }

  String _dateRange(Map<String, dynamic> trip) {
    final range = (trip['tripDateRangeLabel'] ?? '').toString();
    if (range.isNotEmpty) return range;
    final start = (trip['startDate'] ?? '').toString();
    final end = (trip['endDate'] ?? '').toString();
    if (start.isNotEmpty && end.isNotEmpty) return '$start to $end';
    return 'Dates not set';
  }

  String _budgetText(Map<String, dynamic> trip) {
    final budget = trip['budgetEstimate'];
    if (budget is Map && budget['total'] != null) {
      return 'RM ${budget['total']} / RM ${budget['limit'] ?? trip['budgetLimit'] ?? 0}';
    }
    return 'RM ${trip['budgetLimit'] ?? 0}';
  }

  String _statusText(Map<String, dynamic> trip) {
    final status = (trip['status'] ?? 'draft').toString().replaceAll('_', ' ');
    return status.isEmpty ? 'draft' : status;
  }

  Future<void> load() async {
    try {
      final data = await api.get('/api/fr5/itineraries');
      if (mounted) setState(() => items = data['items'] ?? []);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> createTrip() async {
    final title = TextEditingController();
    final destination = TextEditingController();
    final firstDay = DateTime.now().add(const Duration(days: 14));
    final startDate = TextEditingController(text: _date(firstDay));
    final endDate = TextEditingController(
        text: _date(firstDay.add(const Duration(days: 2))));
    final travellers = TextEditingController(text: '1');
    final budget = TextEditingController(text: '1200');

    Future<void> pickDate(
        BuildContext c, TextEditingController controller) async {
      final initial = DateTime.tryParse(controller.text) ??
          DateTime.now().add(const Duration(days: 14));
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
              const Text('Create a new trip',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
              const SizedBox(height: 5),
              const Text(
                  'Start with the important trip information. Add real places from search after the trip is created.',
                  style: TextStyle(color: InkWashColors.mutedInk)),
              const SizedBox(height: 14),
              TextField(
                  controller: title,
                  decoration: const InputDecoration(
                      labelText: 'Trip title',
                      prefixIcon: Icon(Icons.title_rounded))),
              const SizedBox(height: 9),
              TextField(
                  controller: destination,
                  decoration: const InputDecoration(
                      labelText: 'Destination',
                      hintText: 'e.g. Kuala Lumpur',
                      prefixIcon: Icon(Icons.location_on_outlined))),
              const SizedBox(height: 9),
              TextField(
                controller: startDate,
                readOnly: true,
                onTap: () => pickDate(sheetContext, startDate),
                decoration: const InputDecoration(
                    labelText: 'Start date',
                    prefixIcon: Icon(Icons.calendar_month_outlined)),
              ),
              const SizedBox(height: 9),
              TextField(
                controller: endDate,
                readOnly: true,
                onTap: () => pickDate(sheetContext, endDate),
                decoration: const InputDecoration(
                    labelText: 'End date',
                    prefixIcon: Icon(Icons.event_outlined)),
              ),
              const SizedBox(height: 9),
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
              const SizedBox(height: 14),
              FilledButton.icon(
                onPressed: () {
                  if (title.text.trim().isEmpty ||
                      destination.text.trim().isEmpty) return;
                  Navigator.pop(sheetContext, {
                    'title': title.text.trim(),
                    'destinationArea': destination.text.trim(),
                    'startDate': startDate.text.trim(),
                    'endDate': endDate.text.trim(),
                    'travellerCount': int.tryParse(travellers.text) ?? 1,
                    'budgetLimit': double.tryParse(budget.text) ?? 0,
                    'activities': <Map<String, dynamic>>[],
                  });
                },
                icon: const Icon(Icons.add_rounded),
                label: const Text('Create trip'),
              ),
            ],
          ),
        ),
      ),
    );

    if (payload == null) return;
    setState(() => busy = true);
    try {
      final data = await api.post('/api/fr5/itineraries', payload);
      await load();
      if (!mounted) return;
      final rawItinerary = data['itinerary'];
      final id = (data['id'] ??
              (rawItinerary is Map ? rawItinerary['id'] : null) ??
              '')
          .toString();
      if (id.isNotEmpty) {
        await Navigator.push(context,
            MaterialPageRoute(builder: (_) => TripDetailsScreen(tripId: id)));
        await load();
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> deleteTrip(String id) async {
    try {
      await api.delete('/api/fr5/itineraries/$id');
      await load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> openTrip(Map<String, dynamic> trip) async {
    await Navigator.push(
      context,
      MaterialPageRoute(
          builder: (_) => TripDetailsScreen(tripId: trip['id'].toString())),
    );
    await load();
  }

  @override
  void initState() {
    super.initState();
    Future.microtask(load);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Trips'),
        actions: [
          IconButton(onPressed: load, icon: const Icon(Icons.refresh_rounded))
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: busy ? null : createTrip,
        icon: const Icon(Icons.add_rounded),
        label: const Text('New trip'),
      ),
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 6, 18, 92),
          children: [
            const TravelSectionHeader(
              title: 'Your travel plans',
              subtitle:
                  'Open a trip when you want to add places, change the sequence or edit details.',
            ),
            const SizedBox(height: 14),
            if (items.isEmpty)
              TravelEmptyState(
                icon: Icons.luggage_outlined,
                title: 'No trip yet',
                message:
                    'Create a trip first. Then search and add places instead of typing activities manually.',
                actionLabel: 'Create first trip',
                onAction: createTrip,
              )
            else
              ...items.map((raw) {
                final trip = Map<String, dynamic>.from(raw as Map);
                final activities = (trip['activities'] as List? ?? []);
                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(20),
                    onTap: () => openTrip(trip),
                    child: InkCard(
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Container(
                            width: 52,
                            height: 52,
                            decoration: BoxDecoration(
                                color: InkWashColors.paleBlue,
                                borderRadius: BorderRadius.circular(15)),
                            child: const Icon(Icons.route_rounded,
                                color: InkWashColors.blueGrey),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text((trip['title'] ?? 'Trip').toString(),
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w900,
                                        fontSize: 18)),
                                const SizedBox(height: 2),
                                Text((trip['destinationArea'] ?? '').toString(),
                                    style: const TextStyle(
                                        color: InkWashColors.mutedInk)),
                                const SizedBox(height: 8),
                                Wrap(
                                  spacing: 7,
                                  runSpacing: 7,
                                  children: [
                                    TravelStatusPill(
                                        text: _dateRange(trip),
                                        icon: Icons.calendar_month_outlined),
                                    TravelStatusPill(
                                        text: '${_tripDays(trip)} day(s)',
                                        icon: Icons.today_outlined),
                                    TravelStatusPill(
                                        text: '${activities.length} places',
                                        icon: Icons.place_outlined),
                                    TravelStatusPill(
                                        text: _budgetText(trip),
                                        icon: Icons
                                            .account_balance_wallet_outlined),
                                    TravelStatusPill(
                                        text: _statusText(trip),
                                        icon: Icons.flag_outlined),
                                  ],
                                ),
                              ],
                            ),
                          ),
                          PopupMenuButton<String>(
                            onSelected: (value) {
                              if (value == 'delete')
                                deleteTrip(trip['id'].toString());
                            },
                            itemBuilder: (_) => const [
                              PopupMenuItem(
                                  value: 'delete', child: Text('Delete trip'))
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              }),
          ],
        ),
      ),
    );
  }
}
