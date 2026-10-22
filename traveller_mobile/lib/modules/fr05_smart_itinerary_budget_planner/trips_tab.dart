import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../theme/app_theme.dart';
import 'package_trip_details_screen.dart';
import 'personalized_planning_screen.dart';
import 'trip_details_screen.dart';

class TripsTab extends StatefulWidget {
  final ApiService? api;

  const TripsTab({super.key, this.api});

  @override
  State<TripsTab> createState() => _TripsTabState();
}

class _TripsTabState extends State<TripsTab> {
  late final ApiService api;
  List<dynamic> items = [];
  bool busy = false;
  bool loading = true;
  String? loadError;
  int selectedSegment = 0; // 0: My Plans, 1: Package Trips

  static const _months = [
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
    'Dec',
  ];

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
    final start = DateTime.tryParse((trip['startDate'] ?? '').toString());
    final end = DateTime.tryParse((trip['endDate'] ?? '').toString());
    if (start != null && end != null) {
      final startText = '${start.day} ${_months[start.month - 1]}';
      final endText = start.year == end.year
          ? '${end.day} ${_months[end.month - 1]} ${end.year}'
          : '${end.day} ${_months[end.month - 1]} ${end.year}';
      return '$startText–$endText';
    }
    final range = (trip['tripDateRangeLabel'] ?? '').toString().trim();
    if (range.isNotEmpty) return range;
    return 'Dates not set';
  }

  String _budgetText(Map<String, dynamic> trip) {
    final budget = trip['budgetEstimate'];
    if (budget is Map && budget['total'] != null) {
      return 'RM ${budget['total']} estimated';
    }
    final limit = num.tryParse('${trip['budgetLimit'] ?? 0}') ?? 0;
    return limit > 0 ? 'RM $limit budget' : 'Budget not set';
  }

  String _statusText(Map<String, dynamic> trip) {
    return switch ((trip['status'] ?? 'draft').toString().toLowerCase()) {
      'planned' => 'Planned',
      'generating' => 'Preparing',
      'generation_failed' => 'Needs attention',
      _ => 'Draft',
    };
  }

  AppStatusTone _statusTone(Map<String, dynamic> trip) {
    return switch ((trip['status'] ?? 'draft').toString().toLowerCase()) {
      'planned' => AppStatusTone.success,
      'generating' => AppStatusTone.info,
      'generation_failed' => AppStatusTone.warning,
      _ => AppStatusTone.neutral,
    };
  }

  int _activityCount(Map<String, dynamic> trip) {
    // 1. Inspect dailySchedule for genuine scheduled activities
    final daily = trip['dailySchedule'];
    if (daily is List && daily.isNotEmpty) {
      int count = 0;
      for (final day in daily) {
        if (day is Map) {
          final list = day['activities'];
          if (list is List) {
            for (final a in list) {
              if (a is Map) {
                final cat = (a['category'] ?? '').toString().toLowerCase();
                final type = (a['type'] ?? '').toString().toLowerCase();
                if (cat == 'transport' || type == 'placeholder') continue;
                count++;
              }
            }
          }
        }
      }
      if (count > 0) return count;
    }

    // 2. Fall back to top-level activities list
    final activities = trip['activities'];
    if (activities is List && activities.isNotEmpty) {
      int count = 0;
      for (final a in activities) {
        if (a is Map) {
          final cat = (a['category'] ?? '').toString().toLowerCase();
          final type = (a['type'] ?? '').toString().toLowerCase();
          if (cat == 'transport' || type == 'placeholder') continue;
          count++;
        } else if (a != null) {
          count++;
        }
      }
      if (count > 0) return count;
    }

    // 3. Fall back to scheduledActivityCount if positive
    final scheduled = int.tryParse('${trip['scheduledActivityCount'] ?? ''}');
    if (scheduled != null && scheduled > 0) {
      return scheduled;
    }

    return 0;
  }

  Future<void> load() async {
    if (mounted) {
      setState(() {
        loading = true;
        loadError = null;
      });
    }
    try {
      final data = await api.get('/api/fr5/itineraries');
      if (mounted) setState(() => items = data['items'] ?? []);
    } catch (_) {
      if (mounted) {
        setState(() => loadError = 'We couldn’t load your trips. Try again.');
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> planTrip() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => PersonalizedPlanningScreen(api: api)),
    );
    await load();
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
        await Navigator.push(
            context,
            MaterialPageRoute(
                builder: (_) => TripDetailsScreen(
                      key: ValueKey('trip-details-$id'),
                      tripId: id,
                      api: api,
                    )));
        await load();
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> deleteTrip(String id) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.delete_outline_rounded, color: AppColors.error),
        title: const Text('Delete this trip?'),
        content: const Text(
          'This removes the trip and its saved itinerary. This action cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Keep trip'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.error),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Delete trip'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await api.delete('/api/fr5/itineraries/$id');
      await load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Trip deleted.')),
        );
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  bool _isPackage(Map<String, dynamic> trip) =>
      trip['tripType'] == 'package' || trip['packageTrip'] == true;

  List<Map<String, dynamic>> get _plans => items
      .whereType<Map>()
      .map((e) => Map<String, dynamic>.from(e))
      .where((t) => !_isPackage(t))
      .toList();

  List<Map<String, dynamic>> get _packages => items
      .whereType<Map>()
      .map((e) => Map<String, dynamic>.from(e))
      .where(_isPackage)
      .toList();

  Future<void> openTrip(Map<String, dynamic> trip) async {
    if (_isPackage(trip)) {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => PackageTripDetailsScreen(
            key: ValueKey('package-trip-${trip['id']}'),
            tripId: trip['id'].toString(),
            api: api,
            initialTrip: trip,
          ),
        ),
      );
    } else {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => TripDetailsScreen(
            key: ValueKey('trip-details-${trip['id']}'),
            tripId: trip['id'].toString(),
            api: api,
          ),
        ),
      );
    }
    await load();
  }

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(load);
  }

  @override
  Widget build(BuildContext context) {
    final plans = _plans;
    final packages = _packages;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Trips'),
        actions: [
          PopupMenuButton<String>(
            tooltip: 'More trip actions',
            onSelected: (value) {
              if (value == 'manual') createTrip();
              if (value == 'refresh') load();
            },
            itemBuilder: (_) => const [
              PopupMenuItem(
                value: 'manual',
                child: Text('Add trip manually'),
              ),
              PopupMenuItem(value: 'refresh', child: Text('Refresh trips')),
            ],
          ),
        ],
      ),
      floatingActionButton: selectedSegment == 0
          ? FloatingActionButton.extended(
              onPressed: busy ? null : planTrip,
              icon: const Icon(Icons.route_rounded),
              label: const Text('Plan a trip'),
            )
          : null,
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 6, 18, 92),
          children: [
            // Segmented Control: My Plans vs Package Trips
            SegmentedButton<int>(
              segments: [
                ButtonSegment<int>(
                  value: 0,
                  label: Text('My Plans (${plans.length})'),
                  icon: const Icon(Icons.edit_note_rounded),
                ),
                ButtonSegment<int>(
                  value: 1,
                  label: Text('Package Trips (${packages.length})'),
                  icon: const Icon(Icons.verified_rounded),
                ),
              ],
              selected: {selectedSegment},
              onSelectionChanged: (val) {
                setState(() => selectedSegment = val.first);
              },
            ),
            const SizedBox(height: 16),

            if (selectedSegment == 0) ...[
              const TravelSectionHeader(
                title: 'Your travel plans',
                subtitle:
                    'Open a trip when you want to add places, change the sequence or edit details.',
              ),
              const SizedBox(height: 14),
              if (loading)
                const AppLoadingState(message: 'Loading your trips…')
              else if (loadError != null)
                AppErrorState(message: loadError!, onRetry: load)
              else if (plans.isEmpty)
                TravelEmptyState(
                  icon: Icons.luggage_outlined,
                  title: 'No travel plans yet',
                  message: 'Start planning your first personalised trip with custom activities and budget.',
                  actionLabel: 'Plan a trip',
                  onAction: planTrip,
                )
              else
                ...plans.map((trip) {
                  final count = _activityCount(trip);
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(20),
                      onTap: () => openTrip(trip),
                      child: InkCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text((trip['title'] ?? 'Trip').toString(),
                                          maxLines: 2,
                                          overflow: TextOverflow.ellipsis,
                                          style: Theme.of(context)
                                              .textTheme
                                              .titleLarge),
                                      const SizedBox(height: 2),
                                      Text(
                                          (trip['destinationArea'] ?? '')
                                              .toString(),
                                          maxLines: 2,
                                          overflow: TextOverflow.ellipsis,
                                          style: Theme.of(context)
                                              .textTheme
                                              .bodyMedium
                                              ?.copyWith(
                                                color: AppColors.textSecondary,
                                              )),
                                    ],
                                  ),
                                ),
                                PopupMenuButton<String>(
                                  tooltip: 'Trip actions',
                                  onSelected: (value) {
                                    if (value == 'delete') {
                                      deleteTrip(trip['id'].toString());
                                    }
                                  },
                                  itemBuilder: (_) => const [
                                    PopupMenuItem(
                                      value: 'delete',
                                      child: Text('Delete trip'),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                StatusChip(
                                  text: _statusText(trip),
                                  icon: Icons.flag_outlined,
                                  tone: _statusTone(trip),
                                ),
                                TravelStatusPill(
                                  text:
                                      '${_dateRange(trip)} · ${_tripDays(trip)} ${_tripDays(trip) == 1 ? 'day' : 'days'}',
                                  icon: Icons.calendar_month_outlined,
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            Text(
                              '$count ${count == 1 ? 'activity' : 'activities'} · ${_budgetText(trip)}',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodyMedium
                                  ?.copyWith(
                                    color: AppColors.textSecondary,
                                  ),
                            ),
                            const SizedBox(height: 10),
                            Align(
                              alignment: Alignment.centerRight,
                              child: TextButton.icon(
                                onPressed: () => openTrip(trip),
                                icon: const Icon(Icons.arrow_forward_rounded),
                                label: const Text('Continue'),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                }),
            ] else ...[
              const TravelSectionHeader(
                title: 'Purchased Tourism Packages',
                subtitle:
                    'Official read-only itineraries provided by verified tourism operators.',
              ),
              const SizedBox(height: 14),
              if (loading)
                const AppLoadingState(message: 'Loading purchased packages…')
              else if (loadError != null)
                AppErrorState(message: loadError!, onRetry: load)
              else if (packages.isEmpty)
                const TravelEmptyState(
                  icon: Icons.verified_outlined,
                  title: 'No purchased package trips',
                  message: 'When you purchase a tourism package, your confirmed operator itinerary will appear here.',
                )
              else
                ...packages.map((trip) {
                  final snap = trip['packageSnapshot'] is Map
                      ? Map<String, dynamic>.from(trip['packageSnapshot'] as Map)
                      : <String, dynamic>{};
                  final operatorName = (snap['operatorName'] ?? snap['operator'] ?? 'Tourism Operator').toString();
                  final paid = trip['paidTotal'] ?? snap['price'] ?? 0;
                  final currency = (trip['currency'] ?? snap['currency'] ?? 'MYR').toString().toUpperCase();
                  final duration = _tripDays(trip);

                  return Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(20),
                      onTap: () => openTrip(trip),
                      child: InkCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        (snap['title'] ?? trip['title'] ?? 'Tourism Package').toString(),
                                        maxLines: 2,
                                        overflow: TextOverflow.ellipsis,
                                        style: Theme.of(context)
                                            .textTheme
                                            .titleLarge
                                            ?.copyWith(fontWeight: FontWeight.w800),
                                      ),
                                      const SizedBox(height: 2),
                                      Text(
                                        (snap['destination'] ?? trip['destinationArea'] ?? '').toString(),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: Theme.of(context)
                                            .textTheme
                                            .bodyMedium
                                            ?.copyWith(color: AppColors.textSecondary),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 10),
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                  decoration: BoxDecoration(
                                    color: AppColors.successSoft,
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: const Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Icons.verified_rounded, size: 14, color: AppColors.success),
                                      SizedBox(width: 4),
                                      Text(
                                        'Purchased Package',
                                        style: TextStyle(
                                          color: AppColors.success,
                                          fontWeight: FontWeight.w700,
                                          fontSize: 12,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                TravelStatusPill(
                                  text: '${_dateRange(trip)} · $duration ${duration == 1 ? 'day' : 'days'}',
                                  icon: Icons.calendar_month_outlined,
                                ),
                              ],
                            ),
                            const SizedBox(height: 10),
                            Text(
                              'Operator: $operatorName · $currency $paid paid',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodyMedium
                                  ?.copyWith(
                                    color: AppColors.textSecondary,
                                    fontWeight: FontWeight.w600,
                                  ),
                            ),
                            const SizedBox(height: 10),
                            Align(
                              alignment: Alignment.centerRight,
                              child: TextButton.icon(
                                onPressed: () => openTrip(trip),
                                icon: const Icon(Icons.arrow_forward_rounded),
                                label: const Text('View Itinerary'),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                }),
            ],
          ],
        ),
      ),
    );
  }
}
