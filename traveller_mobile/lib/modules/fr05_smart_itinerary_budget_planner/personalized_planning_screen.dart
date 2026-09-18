import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'trips_tab.dart';

class PersonalizedPlanningScreen extends StatefulWidget {
  const PersonalizedPlanningScreen({super.key});

  @override
  State<PersonalizedPlanningScreen> createState() =>
      _PersonalizedPlanningScreenState();
}

class _PersonalizedPlanningScreenState
    extends State<PersonalizedPlanningScreen> {
  final api = ApiService();
  final destination = TextEditingController(text: 'Penang, Malaysia');
  final title = TextEditingController(text: 'My Personalised Penang Trip');
  final travellers = TextEditingController(text: '1');
  final budget = TextEditingController(text: '1200');
  late final TextEditingController startDate;
  late final TextEditingController endDate;
  bool busy = false;
  int step = 0;
  String status = '';
  Map<String, dynamic>? generatedTrip;

  String dateText(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  @override
  void initState() {
    super.initState();
    final start = DateTime.now().add(const Duration(days: 30));
    startDate = TextEditingController(text: dateText(start));
    endDate = TextEditingController(
        text: dateText(start.add(const Duration(days: 2))));
  }

  Future<void> buildPlan() async {
    if (destination.text.trim().isEmpty || title.text.trim().isEmpty) {
      showError(context, 'Enter a destination and trip title.');
      return;
    }
    setState(() {
      busy = true;
      step = 1;
      status = 'Ranking destinations from your travel preferences...';
      generatedTrip = null;
    });

    try {
      // FR4: real hybrid recommendation engine.
      final recommendationData =
          await api.post('/api/fr4/recommendations/generate', {
        'destinationArea': destination.text.trim(),
      });
      final recommendations =
          recommendationData['recommendations'] as List? ?? [];
      if (recommendations.isEmpty) {
        throw Exception('No recommendations were generated.');
      }

      if (mounted)
        setState(() {
          step = 2;
          status = 'Creating itinerary from the top ranked destinations...';
        });

      final days = _dayCount(startDate.text, endDate.text);
      final count = (days * 3).clamp(3, 9).toInt();
      final activities = recommendations.take(count).map((raw) {
        final item = Map<String, dynamic>.from(raw as Map);
        return {
          'activityName': item['title'] ?? item['name'] ?? 'Destination',
          'destinationId': item['destinationId'] ?? item['place_id'] ?? '',
          'address': item['address'] ?? '',
          'estimatedCost': item['estimatedCost'] ?? 0,
          'gps_coordinates':
              item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
          'type': item['type'] ?? item['category'] ?? '',
          'category': item['category'] ?? item['type'] ?? '',
          'description': item['description'] ?? '',
          'openingHours': item['openingHours'] ?? '',
          'indoor': item['indoor'] ?? false,
          'recommendedDurationMinutes':
              item['recommendedDurationMinutes'] ?? 105,
          'recommendationScore': item['score'] ?? 0,
        };
      }).toList();

      final created = await api.post('/api/fr5/itineraries', {
        'title': title.text.trim(),
        'destinationArea': destination.text.trim(),
        'startDate': startDate.text.trim(),
        'endDate': endDate.text.trim(),
        'travellerCount': int.tryParse(travellers.text) ?? 1,
        'budgetLimit': double.tryParse(budget.text) ?? 0,
        'activities': activities,
      });
      final itineraryId = (created['id'] ?? '').toString();
      if (itineraryId.isEmpty)
        throw Exception('Itinerary could not be created.');

      if (mounted)
        setState(() {
          step = 3;
          status = 'Arranging trip days and checking destination weather...';
        });

      // FR5 Smart Itinerary Generator handles grouping, day generation, travel buffers and weather.
      final generated =
          await api.post('/api/fr5/itineraries/$itineraryId/generate', {
        'destinationName': destination.text.trim(),
      });

      if (mounted)
        setState(() {
          step = 4;
          status = 'Calculating and comparing your total trip budget...';
        });

      final budgetData =
          await api.get('/api/fr5/itineraries/$itineraryId/budget');
      await api.post('/api/fr5/itineraries/$itineraryId/save', {});

      final trip = Map<String, dynamic>.from(generated['itinerary'] as Map);
      trip['budgetEstimate'] = budgetData['budget'];
      if (!mounted) return;
      setState(() {
        step = 5;
        status = 'Your personalised trip is ready.';
        generatedTrip = trip;
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  int _dayCount(String start, String end) {
    try {
      final a = DateTime.parse(start);
      final b = DateTime.parse(end);
      return (b.difference(a).inDays + 1).clamp(1, 7).toInt();
    } catch (_) {
      return 3;
    }
  }

  Future<void> _pickDate(TextEditingController controller) async {
    final initial = DateTime.tryParse(controller.text) ??
        DateTime.now().add(const Duration(days: 30));
    final picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime.now().subtract(const Duration(days: 1)),
      lastDate: DateTime.now().add(const Duration(days: 730)),
    );
    if (picked != null) controller.text = dateText(picked);
  }

  List<Map<String, dynamic>> _activityMaps(Map<String, dynamic> trip) {
    return (trip['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
  }

  Map<int, List<Map<String, dynamic>>> _groupByDay(Map<String, dynamic> trip) {
    final grouped = <int, List<Map<String, dynamic>>>{};
    for (final activity in _activityMaps(trip)) {
      final day = int.tryParse('${activity['dayNo'] ?? 1}') ?? 1;
      grouped.putIfAbsent(day, () => []).add(activity);
    }
    return grouped;
  }

  String _dateRange(Map<String, dynamic> trip) {
    final range = (trip['tripDateRangeLabel'] ?? '').toString();
    if (range.isNotEmpty) return range;
    final start = (trip['startDate'] ?? '').toString();
    final end = (trip['endDate'] ?? '').toString();
    return start.isEmpty && end.isEmpty ? 'Dates not set' : '$start to $end';
  }

  String _timeRange(Map<String, dynamic> activity) {
    final range = (activity['timeRangeLabel'] ?? '').toString();
    if (range.isNotEmpty) return range;
    final slot = (activity['timeSlot'] ?? '').toString();
    return slot.isEmpty ? 'Time not arranged' : slot;
  }

  Widget _timelinePreview(Map<String, dynamic> trip) {
    final grouped = _groupByDay(trip);
    if (grouped.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: grouped.entries.map((entry) {
        final first =
            entry.value.isEmpty ? <String, dynamic>{} : entry.value.first;
        final dayLabel = (first['dayLabel'] ?? 'Day ${entry.key}').toString();
        return Padding(
          padding: const EdgeInsets.only(top: 10),
          child: InkCard(
            color: InkWashColors.cream,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(dayLabel,
                    style: const TextStyle(fontWeight: FontWeight.w900)),
                const SizedBox(height: 8),
                ...entry.value.map((activity) {
                  final notes = (activity['scheduleNotes'] as List? ?? [])
                      .map((e) => e.toString())
                      .where((e) => e.trim().isNotEmpty)
                      .take(1)
                      .toList();
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 86,
                          child: Text(_timeRange(activity),
                              style: const TextStyle(
                                  fontWeight: FontWeight.w800,
                                  color: InkWashColors.blueGrey)),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                  (activity['activityName'] ?? 'Place')
                                      .toString(),
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w800)),
                              Text(
                                  '${activity['category'] ?? activity['type'] ?? ''}${activity['recommendedDurationMinutes'] == null ? '' : ' • ${activity['recommendedDurationMinutes']} min'}',
                                  style: const TextStyle(
                                      fontSize: 12,
                                      color: InkWashColors.mutedInk)),
                              if (notes.isNotEmpty)
                                Text(notes.first,
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                        fontSize: 12,
                                        color: InkWashColors.blueGrey)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  );
                }),
              ],
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget processStep(int number, String text) {
    final complete = step > number;
    final active = step == number && busy;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Icon(
            complete
                ? Icons.check_circle_rounded
                : active
                    ? Icons.sync_rounded
                    : Icons.radio_button_unchecked_rounded,
            size: 20,
            color: complete || active
                ? InkWashColors.blueGrey
                : InkWashColors.softGrey,
          ),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final trip = generatedTrip;
    final b = trip?['budgetEstimate'] is Map
        ? Map<String, dynamic>.from(trip!['budgetEstimate'] as Map)
        : <String, dynamic>{};
    final contextData = trip?['generationContext'] is Map
        ? Map<String, dynamic>.from(trip!['generationContext'] as Map)
        : <String, dynamic>{};

    return Scaffold(
      appBar: AppBar(title: const Text('Personalised Plan')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 6, 18, 30),
        children: [
          const TravelSectionHeader(
            title: 'Build the whole trip for me',
            subtitle:
                'Uses your preferences, hybrid ranking, smart itinerary generation, weather and budget analysis.',
          ),
          const SizedBox(height: 14),
          TextField(
              controller: destination,
              decoration: const InputDecoration(
                  labelText: 'Destination area',
                  prefixIcon: Icon(Icons.location_on_outlined))),
          const SizedBox(height: 9),
          TextField(
              controller: title,
              decoration: const InputDecoration(labelText: 'Trip title')),
          const SizedBox(height: 9),
          Row(children: [
            Expanded(
                child: TextField(
                    controller: startDate,
                    readOnly: true,
                    onTap: () => _pickDate(startDate),
                    decoration: const InputDecoration(
                        labelText: 'Start date',
                        prefixIcon: Icon(Icons.calendar_month_outlined)))),
            const SizedBox(width: 8),
            Expanded(
                child: TextField(
                    controller: endDate,
                    readOnly: true,
                    onTap: () => _pickDate(endDate),
                    decoration: const InputDecoration(
                        labelText: 'End date',
                        prefixIcon: Icon(Icons.event_outlined)))),
          ]),
          const SizedBox(height: 9),
          Row(children: [
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
          ]),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: busy ? null : buildPlan,
            icon: const Icon(Icons.auto_fix_high_rounded),
            label: Text(
                busy ? 'Building your plan...' : 'Generate personalised trip'),
          ),
          const SizedBox(height: 18),
          InkCard(
            color: InkWashColors.cream,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('What TravelMate runs',
                    style:
                        TextStyle(fontWeight: FontWeight.w900, fontSize: 17)),
                const SizedBox(height: 7),
                processStep(1, 'Hybrid Recommendation Engine'),
                processStep(2, 'Destination Planning'),
                processStep(3,
                    'Activity Arrangement + Trip Day Generation + Weather Consideration'),
                processStep(4, 'Budget Estimation and Comparison'),
                if (status.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(status,
                      style: const TextStyle(
                          color: InkWashColors.blueGrey,
                          fontWeight: FontWeight.w700)),
                ],
              ],
            ),
          ),
          if (trip != null) ...[
            const SizedBox(height: 16),
            InkCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text((trip['title'] ?? 'Generated trip').toString(),
                      style: const TextStyle(
                          fontWeight: FontWeight.w900, fontSize: 20)),
                  const SizedBox(height: 6),
                  Wrap(spacing: 7, runSpacing: 7, children: [
                    TravelStatusPill(
                        text: '${trip['tripDays'] ?? '-'} days',
                        icon: Icons.calendar_today_outlined),
                    TravelStatusPill(
                        text: _dateRange(trip),
                        icon: Icons.event_available_outlined),
                    TravelStatusPill(
                        text:
                            '${(trip['activities'] as List?)?.length ?? 0} activities',
                        icon: Icons.place_outlined),
                    TravelStatusPill(
                        text: 'RM ${b['total'] ?? 0} / RM ${b['limit'] ?? 0}',
                        icon: Icons.account_balance_wallet_outlined),
                    TravelStatusPill(
                        text: (b['status'] ?? '').toString(),
                        icon: Icons.insights_outlined),
                  ]),
                  const SizedBox(height: 10),
                  Text((b['comparison'] ?? '').toString()),
                  const SizedBox(height: 8),
                  Text(
                      'Weather considered: ${contextData['weatherConsideration'] == true ? 'Yes' : 'No'}'),
                  Text(
                      'Destination source: ${contextData['destinationSource'] ?? 'recommendations'}'),
                  _timelinePreview(trip),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => const TripsTab())),
                    icon: const Icon(Icons.route_rounded),
                    label: const Text('Open generated trip'),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
