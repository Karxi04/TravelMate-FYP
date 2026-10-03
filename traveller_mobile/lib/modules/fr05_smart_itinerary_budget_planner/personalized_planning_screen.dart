import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'trip_details_screen.dart';

class PersonalizedPlanningScreen extends StatefulWidget {
  final ApiService? api;

  const PersonalizedPlanningScreen({super.key, this.api});

  @override
  State<PersonalizedPlanningScreen> createState() =>
      _PersonalizedPlanningScreenState();
}

class _PersonalizedPlanningScreenState
    extends State<PersonalizedPlanningScreen> {
  late final ApiService api;
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
  String? generationRequestId;
  String? generationSignature;
  String? recommendationGenerationId;
  String? completedTripId;
  String? failedTripId;
  String? failureStage;
  String? failureMessage;
  bool retryable = false;

  String dateText(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    final start = DateTime.now().add(const Duration(days: 30));
    startDate = TextEditingController(text: dateText(start));
    endDate = TextEditingController(
        text: dateText(start.add(const Duration(days: 2))));
  }

  @override
  void dispose() {
    destination.dispose();
    title.dispose();
    travellers.dispose();
    budget.dispose();
    startDate.dispose();
    endDate.dispose();
    super.dispose();
  }

  String? _inputError() {
    if (destination.text.trim().isEmpty || title.text.trim().isEmpty) {
      return 'Enter a destination and trip title.';
    }
    final start = DateTime.tryParse(startDate.text.trim());
    final end = DateTime.tryParse(endDate.text.trim());
    if (start == null || end == null || end.isBefore(start)) {
      return 'Use a valid trip date range.';
    }
    final travellerCount = int.tryParse(travellers.text.trim());
    if (travellerCount == null || travellerCount < 1) {
      return 'Traveller count must be at least 1.';
    }
    final budgetLimit = double.tryParse(budget.text.trim());
    if (budgetLimit == null || budgetLimit < 0) {
      return 'Enter a valid non-negative budget.';
    }
    return null;
  }

  String get _inputSignature => [
        title.text.trim(),
        destination.text.trim().toLowerCase(),
        startDate.text.trim(),
        endDate.text.trim(),
        travellers.text.trim(),
        budget.text.trim(),
      ].join('|');

  Map<String, dynamic> _tripPayload(String snapshotId) => {
        'title': title.text.trim(),
        'destinationArea': destination.text.trim(),
        'destinationName': destination.text.trim(),
        'startDate': startDate.text.trim(),
        'endDate': endDate.text.trim(),
        'travellerCount': int.parse(travellers.text.trim()),
        'budgetLimit': double.parse(budget.text.trim()),
        'recommendationGenerationId': snapshotId,
        'generationRequestId': generationRequestId,
      };

  Future<void> _openTrip(String tripId) async {
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => TripDetailsScreen(tripId: tripId, api: api),
      ),
    );
  }

  void _recordFailure(Map<String, dynamic> data, Object error) {
    failedTripId = (data['tripId'] ?? data['id'] ?? '').toString();
    if (failedTripId!.isEmpty) failedTripId = null;
    failureStage = (data['stage'] ?? 'trip_generation').toString();
    failureMessage = (data['error'] ?? error).toString();
    retryable = data['retryable'] == true;
    status = failureMessage!;
  }

  Future<void> buildPlan({bool retry = false}) async {
    if (busy) return;
    final inputError = _inputError();
    if (inputError != null) {
      showError(context, inputError);
      return;
    }

    final signature = _inputSignature;
    if (generationSignature != signature) {
      generationSignature = signature;
      generationRequestId =
          'personalised_${DateTime.now().microsecondsSinceEpoch}';
      recommendationGenerationId = null;
      completedTripId = null;
      failedTripId = null;
    }
    if (!retry && completedTripId != null) {
      await _openTrip(completedTripId!);
      return;
    }
    setState(() {
      busy = true;
      step = retry ? 2 : 1;
      status = retry
          ? 'Retrying itinerary and budget generation for this trip...'
          : 'Ranking destinations from your travel preferences...';
      generatedTrip = null;
      failureMessage = null;
      failureStage = null;
      retryable = false;
    });

    try {
      if (!retry || recommendationGenerationId == null) {
        final recommendationData =
            await api.post('/api/fr4/recommendations/generate', {
          'destinationArea': destination.text.trim(),
        });
        final recommendations =
            recommendationData['recommendations'] as List? ?? [];
        recommendationGenerationId =
            (recommendationData['recommendationGenerationId'] ?? '').toString();
        if (recommendations.isEmpty) {
          throw Exception('No recommendations were generated.');
        }
        if (recommendationGenerationId!.isEmpty) {
          throw Exception('Recommendation snapshot could not be identified.');
        }
      }

      if (!mounted) return;
      setState(() {
        step = 2;
        status =
            'Generating the itinerary and budget from the selected recommendation snapshot...';
      });

      final generated = await api.post(
        '/api/fr5/personalised-trips/generate',
        _tripPayload(recommendationGenerationId!),
      );
      if (generated is! Map || generated['ok'] != true) {
        final data = generated is Map
            ? Map<String, dynamic>.from(generated)
            : <String, dynamic>{};
        _recordFailure(data, 'Trip generation failed.');
        throw Exception(failureMessage);
      }
      final itineraryId =
          (generated['tripId'] ?? generated['id'] ?? '').toString();
      if (itineraryId.isEmpty) {
        throw Exception('The generated trip ID was not returned.');
      }
      if (generated['status'] != 'planned') {
        _recordFailure(
          {
            ...Map<String, dynamic>.from(generated),
            'stage': 'generation_in_progress',
            'error':
                'Trip generation is still in progress. Please retry shortly.',
            'retryable': true,
          },
          'Trip generation is still in progress.',
        );
        throw Exception(failureMessage);
      }
      final trip = Map<String, dynamic>.from(generated['itinerary'] as Map);
      if (!mounted) return;
      setState(() {
        step = 5;
        status = 'Your personalised trip is ready.';
        generatedTrip = trip;
        completedTripId = itineraryId;
        failedTripId = null;
      });
      await _openTrip(itineraryId);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _recordFailure(e.data, e));
      showError(context, e.message);
    } catch (e) {
      if (mounted) {
        if (failureMessage == null) {
          setState(() {
            failureStage = 'request_transport';
            failureMessage = e.toString().replaceFirst('Exception: ', '');
            retryable = recommendationGenerationId != null &&
                generationRequestId != null;
            status = failureMessage!;
          });
        }
        showError(context, failureMessage ?? e);
      }
    } finally {
      if (mounted) setState(() => busy = false);
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
          if (failureMessage != null) ...[
            const SizedBox(height: 14),
            InkCard(
              color: InkWashColors.cream,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Trip generation did not finish',
                      style:
                          TextStyle(fontWeight: FontWeight.w900, fontSize: 17)),
                  const SizedBox(height: 6),
                  Text(failureMessage!),
                  const SizedBox(height: 5),
                  Text('Stage: ${failureStage ?? 'trip_generation'}',
                      style: const TextStyle(
                          color: InkWashColors.mutedInk, fontSize: 12)),
                  if (failedTripId != null)
                    Text('Recoverable trip: $failedTripId',
                        style: const TextStyle(
                            color: InkWashColors.mutedInk, fontSize: 12)),
                  if (retryable && recommendationGenerationId != null) ...[
                    const SizedBox(height: 10),
                    OutlinedButton.icon(
                      onPressed: busy ? null : () => buildPlan(retry: true),
                      icon: const Icon(Icons.refresh_rounded),
                      label: const Text('Retry this trip'),
                    ),
                  ],
                ],
              ),
            ),
          ],
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
                    onPressed: completedTripId == null
                        ? null
                        : () => _openTrip(completedTripId!),
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
