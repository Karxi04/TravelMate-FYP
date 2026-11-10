import 'dart:async';
import '../../services/android_push_service.dart';
import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../theme/app_theme.dart';
import 'package_trip_details_screen.dart';
import 'personalized_planning_screen.dart';
import 'trip_details_screen.dart';
import 'trip_status_helper.dart';

class TripsTab extends StatefulWidget {
  final ApiService? api;
  final DateTime? referenceDate;
  final bool selectForActivity;
  final String? initialDestination;

  const TripsTab(
      {super.key,
      this.api,
      this.referenceDate,
      this.selectForActivity = false,
      this.initialDestination});

  @override
  State<TripsTab> createState() => _TripsTabState();
}

class _TripsTabState extends State<TripsTab> with WidgetsBindingObserver {
  late final ApiService api;
  List<dynamic> items = [];
  bool busy = false;
  bool loading = true;
  String? loadError;
  int selectedSegment = 0; // 0: My Plans, 1: Package Trips
  TripFilter selectedFilter = TripFilter.all;
  Timer? _midnightTimer;

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
      AndroidPushService.instance.refreshTripReminders();
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

  Future<void> showPlanningModeSheet(BuildContext context) async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: SingleChildScrollView(
          padding: EdgeInsets.fromLTRB(
            20,
            8,
            20,
            MediaQuery.of(sheetContext).viewInsets.bottom + 24,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Plan your trip',
                style: Theme.of(sheetContext).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.w900,
                        ) ??
                    const TextStyle(fontSize: 22, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 6),
              const Text(
                'Choose how you would like to plan your itinerary.',
                style: TextStyle(color: InkWashColors.mutedInk, fontSize: 14),
              ),
              const SizedBox(height: 20),
              Card(
                elevation: 0,
                color: Theme.of(sheetContext)
                    .colorScheme
                    .primaryContainer
                    .withValues(alpha: 0.4),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                  side: BorderSide(
                    color: Theme.of(sheetContext)
                        .colorScheme
                        .primary
                        .withValues(alpha: 0.3),
                  ),
                ),
                child: ListTile(
                  key: const ValueKey('plan-for-me-option'),
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  leading: CircleAvatar(
                    backgroundColor: Theme.of(sheetContext).colorScheme.primary,
                    foregroundColor:
                        Theme.of(sheetContext).colorScheme.onPrimary,
                    child: const Icon(Icons.auto_awesome_rounded),
                  ),
                  title: const Text(
                    'Plan for Me',
                    style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                  ),
                  subtitle: const Padding(
                    padding: EdgeInsets.only(top: 4.0),
                    child: Text(
                      'Personalized AI recommendations and smart scheduling based on your travel preferences.',
                      style: TextStyle(fontSize: 13),
                    ),
                  ),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: () => Navigator.pop(sheetContext, 'plan_for_me'),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                elevation: 0,
                color: Theme.of(sheetContext)
                    .colorScheme
                    .surfaceContainerHighest
                    .withValues(alpha: 0.4),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                  side: BorderSide(
                    color: Theme.of(sheetContext).colorScheme.outlineVariant,
                  ),
                ),
                child: ListTile(
                  key: const ValueKey('plan-myself-option'),
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  leading: CircleAvatar(
                    backgroundColor:
                        Theme.of(sheetContext).colorScheme.secondary,
                    foregroundColor:
                        Theme.of(sheetContext).colorScheme.onSecondary,
                    child: const Icon(Icons.edit_calendar_rounded),
                  ),
                  title: const Text(
                    'Plan Myself',
                    style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                  ),
                  subtitle: const Padding(
                    padding: EdgeInsets.only(top: 4.0),
                    child: Text(
                      'Create an empty itinerary and handpick places day by day.',
                      style: TextStyle(fontSize: 13),
                    ),
                  ),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: () => Navigator.pop(sheetContext, 'plan_myself'),
                ),
              ),
            ],
          ),
        ),
      ),
    );

    if (choice == 'plan_for_me') {
      await planTrip();
    } else if (choice == 'plan_myself') {
      await createTrip();
    }
  }

  Future<void> createTrip() async {
    final title = TextEditingController();
    final destination = TextEditingController(text: widget.initialDestination);
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

    String? titleError;
    String? destinationError;
    String? dateError;
    String? travellerError;
    String? budgetError;
    bool isSubmitting = false;

    final payload = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (context, setSheetState) => Padding(
          padding: EdgeInsets.fromLTRB(
              18, 0, 18, MediaQuery.of(sheetContext).viewInsets.bottom + 22),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('Create a new trip',
                    style:
                        TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
                const SizedBox(height: 5),
                const Text(
                    'Start with the important trip information. Add real places from search after the trip is created.',
                    style: TextStyle(color: InkWashColors.mutedInk)),
                const SizedBox(height: 14),
                TextField(
                    controller: title,
                    decoration: InputDecoration(
                        labelText: 'Trip title',
                        errorText: titleError,
                        prefixIcon: const Icon(Icons.title_rounded))),
                const SizedBox(height: 9),
                TextField(
                    controller: destination,
                    decoration: InputDecoration(
                        labelText: 'Destination',
                        hintText: 'e.g. Kuala Lumpur',
                        errorText: destinationError,
                        prefixIcon: const Icon(Icons.location_on_outlined))),
                const SizedBox(height: 9),
                TextField(
                  controller: startDate,
                  readOnly: true,
                  onTap: () async {
                    await pickDate(sheetContext, startDate);
                    setSheetState(() => dateError = null);
                  },
                  decoration: const InputDecoration(
                      labelText: 'Start date',
                      prefixIcon: Icon(Icons.calendar_month_outlined)),
                ),
                const SizedBox(height: 9),
                TextField(
                  controller: endDate,
                  readOnly: true,
                  onTap: () async {
                    await pickDate(sheetContext, endDate);
                    setSheetState(() => dateError = null);
                  },
                  decoration: InputDecoration(
                      labelText: 'End date',
                      errorText: dateError,
                      prefixIcon: const Icon(Icons.event_outlined)),
                ),
                const SizedBox(height: 9),
                Row(
                  children: [
                    Expanded(
                        child: TextField(
                            controller: travellers,
                            keyboardType: TextInputType.number,
                            decoration: InputDecoration(
                                labelText: 'Travellers',
                                errorText: travellerError))),
                    const SizedBox(width: 8),
                    Expanded(
                        child: TextField(
                            controller: budget,
                            keyboardType: TextInputType.number,
                            decoration: InputDecoration(
                                labelText: 'Budget (RM)',
                                errorText: budgetError))),
                  ],
                ),
                const SizedBox(height: 14),
                FilledButton.icon(
                  onPressed: isSubmitting
                      ? null
                      : () {
                          final titleText = title.text.trim();
                          final destText = destination.text.trim();
                          final startDt =
                              DateTime.tryParse(startDate.text.trim());
                          final endDt = DateTime.tryParse(endDate.text.trim());
                          final count = int.tryParse(travellers.text.trim());
                          final b = double.tryParse(budget.text.trim());

                          bool hasError = false;
                          setSheetState(() {
                            titleError = null;
                            destinationError = null;
                            dateError = null;
                            travellerError = null;
                            budgetError = null;

                            if (titleText.isEmpty) {
                              titleError = 'Trip title is required';
                              hasError = true;
                            }
                            if (destText.isEmpty) {
                              destinationError = 'Destination area is required';
                              hasError = true;
                            }
                            if (startDt != null &&
                                endDt != null &&
                                endDt.isBefore(startDt)) {
                              dateError =
                                  'End date cannot be earlier than start date';
                              hasError = true;
                            }
                            if (count == null || count < 1) {
                              travellerError = 'At least 1 traveller required';
                              hasError = true;
                            }
                            if (b == null || b < 0) {
                              budgetError = 'Budget cannot be negative';
                              hasError = true;
                            }
                          });

                          if (hasError || isSubmitting) return;

                          setSheetState(() => isSubmitting = true);
                          Navigator.pop(sheetContext, {
                            'title': titleText,
                            'destinationArea': destText,
                            'startDate': startDate.text.trim(),
                            'endDate': endDate.text.trim(),
                            'travellerCount': count ?? 1,
                            'budgetLimit': b ?? 0.0,
                            'activities': <Map<String, dynamic>>[],
                          });
                        },
                  icon: isSubmitting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.add_rounded),
                  label: Text(isSubmitting ? 'Creating trip…' : 'Create trip'),
                ),
              ],
            ),
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
        if (widget.selectForActivity) {
          final trip = rawItinerary is Map
              ? Map<String, dynamic>.from(rawItinerary)
              : <String, dynamic>{...payload};
          Navigator.pop(context, {...trip, 'id': id});
          return;
        }
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

  List<Map<String, dynamic>> get _allPlans => items
      .whereType<Map>()
      .map((e) => Map<String, dynamic>.from(e))
      .where((t) => !_isPackage(t))
      .toList();

  List<Map<String, dynamic>> get _plans => TripStatusHelper.sortAndFilterTrips(
        _allPlans,
        filter: selectedFilter,
        referenceDate: widget.referenceDate,
      );

  List<Map<String, dynamic>> get _allPackages => items
      .whereType<Map>()
      .map((e) => Map<String, dynamic>.from(e))
      .where(_isPackage)
      .toList();

  List<Map<String, dynamic>> get _packages =>
      TripStatusHelper.sortAndFilterTrips(
        _allPackages,
        filter: selectedFilter,
        referenceDate: widget.referenceDate,
      );

  Future<void> openTrip(Map<String, dynamic> trip) async {
    if (widget.selectForActivity) {
      if (trip['tripType'] == 'package' || trip['packageTrip'] == true) return;
      Navigator.pop(context, trip);
      return;
    }
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
            referenceDate: widget.referenceDate,
          ),
        ),
      );
    }
    await load();
  }

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
      // Recalculate temporal classifications when resuming
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

  @override
  Widget build(BuildContext context) {
    final allPlans = _allPlans;
    final plans = _plans;
    final allPackages = _allPackages;
    final packages = _packages;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Trips'),
        actions: [
          PopupMenuButton<String>(
            tooltip: 'More trip actions',
            onSelected: (value) {
              if (value == 'choice') showPlanningModeSheet(context);
              if (value == 'manual') createTrip();
              if (value == 'refresh') load();
            },
            itemBuilder: (_) => const [
              PopupMenuItem(
                value: 'choice',
                child: Text('Plan a trip'),
              ),
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
              key: const ValueKey('plan-trip-fab'),
              onPressed: busy ? null : () => showPlanningModeSheet(context),
              icon: const Icon(Icons.route_rounded),
              label: const Text('Plan a trip'),
            )
          : null,
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 6, 18, 120),
          children: [
            // Segmented Control: My Plans vs Package Trips
            SegmentedButton<int>(
              segments: [
                ButtonSegment<int>(
                  value: 0,
                  label: Text('My Plans (${allPlans.length})'),
                  icon: const Icon(Icons.edit_note_rounded),
                ),
                ButtonSegment<int>(
                  value: 1,
                  enabled: !widget.selectForActivity,
                  label: Text('Package Trips (${allPackages.length})'),
                  icon: const Icon(Icons.verified_rounded),
                ),
              ],
              selected: {selectedSegment},
              onSelectionChanged: (val) {
                setState(() => selectedSegment = val.first);
              },
            ),
            const SizedBox(height: 14),

            // Temporal Filter Chips
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final filter in TripFilter.values) ...[
                    ChoiceChip(
                      key: ValueKey('filter-${filter.name}'),
                      selected: selectedFilter == filter,
                      avatar: Icon(
                        switch (filter) {
                          TripFilter.all => Icons.view_list_rounded,
                          TripFilter.planned => Icons.schedule_rounded,
                          TripFilter.ongoing => Icons.explore_rounded,
                          TripFilter.expired => Icons.history_rounded,
                        },
                        size: 16,
                      ),
                      label: Text(filter.label),
                      onSelected: (selected) {
                        if (selected) {
                          setState(() => selectedFilter = filter);
                        }
                      },
                    ),
                    const SizedBox(width: 8),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 16),

            if (selectedSegment == 0) ...[
              const TravelSectionHeader(
                title: 'Your travel plans',
                subtitle: 'Select a trip to view or edit details.',
              ),
              const SizedBox(height: 14),
              if (loading)
                const AppLoadingState(message: 'Loading your trips…')
              else if (loadError != null)
                AppErrorState(message: loadError!, onRetry: load)
              else if (allPlans.isEmpty)
                TravelEmptyState(
                  icon: Icons.luggage_outlined,
                  title: 'No travel plans yet',
                  message:
                      'Start planning your first personalised trip with custom activities and budget.',
                  actionLabel: 'Plan a trip',
                  onAction: () => showPlanningModeSheet(context),
                )
              else if (plans.isEmpty)
                switch (selectedFilter) {
                  TripFilter.ongoing => const TravelEmptyState(
                      icon: Icons.explore_off_outlined,
                      title: 'No ongoing trips',
                      message:
                          'You have no trips currently in progress. Trips taking place today will appear here automatically.',
                    ),
                  TripFilter.planned => TravelEmptyState(
                      icon: Icons.event_available_outlined,
                      title: 'No upcoming trips planned',
                      message:
                          'You have no upcoming trips scheduled. Plan a new trip to explore Penang.',
                      actionLabel: 'Plan a trip',
                      onAction: () => showPlanningModeSheet(context),
                    ),
                  TripFilter.expired => const TravelEmptyState(
                      icon: Icons.history_toggle_off_rounded,
                      title: 'No expired trips',
                      message:
                          'Completed trips whose travel dates have passed will appear here.',
                    ),
                  TripFilter.all => const TravelEmptyState(
                      icon: Icons.luggage_outlined,
                      title: 'No travel plans',
                      message: 'No travel plans match the current view.',
                    ),
                }
              else
                ...plans.map((trip) {
                  final count = _activityCount(trip);
                  final temporal = TripStatusHelper.resolveStatus(
                    trip,
                    referenceDate: widget.referenceDate,
                  );
                  final lifecycleRaw =
                      (trip['status'] ?? 'draft').toString().toLowerCase();
                  final isDraft = lifecycleRaw == 'draft';
                  final isGenerating = lifecycleRaw == 'generating';
                  final isFailed = lifecycleRaw == 'generation_failed';

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
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
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
                                if (temporal != null)
                                  StatusChip(
                                    key: ValueKey('trip-status-${trip['id']}'),
                                    text: temporal.label,
                                    icon: temporal.icon,
                                    tone: temporal.tone,
                                  ),
                                if (isDraft)
                                  const StatusChip(
                                    text: 'Draft',
                                    icon: Icons.edit_note_rounded,
                                    tone: AppStatusTone.neutral,
                                  ),
                                if (isGenerating)
                                  const StatusChip(
                                    text: 'Preparing',
                                    icon: Icons.hourglass_top_rounded,
                                    tone: AppStatusTone.info,
                                  ),
                                if (isFailed)
                                  const StatusChip(
                                    text: 'Needs attention',
                                    icon: Icons.error_outline_rounded,
                                    tone: AppStatusTone.warning,
                                  ),
                                if (temporal == null &&
                                    !isDraft &&
                                    !isGenerating &&
                                    !isFailed)
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
                    'Package itineraries provided by verified tourism operators.',
              ),
              const SizedBox(height: 14),
              if (loading)
                const AppLoadingState(message: 'Loading purchased packages…')
              else if (loadError != null)
                AppErrorState(message: loadError!, onRetry: load)
              else if (allPackages.isEmpty)
                const TravelEmptyState(
                  icon: Icons.verified_outlined,
                  title: 'No purchased package trips',
                  message:
                      'When you purchase a tourism package, your confirmed operator itinerary will appear here.',
                )
              else if (packages.isEmpty)
                switch (selectedFilter) {
                  TripFilter.ongoing => const TravelEmptyState(
                      icon: Icons.explore_off_outlined,
                      title: 'No ongoing package trips',
                      message: 'You have no package trips taking place today.',
                    ),
                  TripFilter.planned => const TravelEmptyState(
                      icon: Icons.event_available_outlined,
                      title: 'No upcoming package trips',
                      message: 'You have no upcoming package trips scheduled.',
                    ),
                  TripFilter.expired => const TravelEmptyState(
                      icon: Icons.history_toggle_off_rounded,
                      title: 'No expired package trips',
                      message:
                          'Completed package trips whose travel dates have passed will appear here.',
                    ),
                  TripFilter.all => const TravelEmptyState(
                      icon: Icons.verified_outlined,
                      title: 'No purchased package trips',
                      message: 'No package trips found.',
                    ),
                }
              else
                ...packages.map((trip) {
                  final snap = trip['packageSnapshot'] is Map
                      ? Map<String, dynamic>.from(
                          trip['packageSnapshot'] as Map)
                      : <String, dynamic>{};
                  final operatorName = (snap['operatorName'] ??
                          snap['operator'] ??
                          'Tourism Operator')
                      .toString();
                  final paid = trip['paidTotal'] ?? snap['price'] ?? 0;
                  final currency =
                      (trip['currency'] ?? snap['currency'] ?? 'MYR')
                          .toString()
                          .toUpperCase();
                  final duration = _tripDays(trip);
                  final pkgTemporal = TripStatusHelper.resolveStatus(
                    trip,
                    referenceDate: widget.referenceDate,
                  );

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
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        (snap['title'] ??
                                                trip['title'] ??
                                                'Tourism Package')
                                            .toString(),
                                        maxLines: 2,
                                        overflow: TextOverflow.ellipsis,
                                        style: Theme.of(context)
                                            .textTheme
                                            .titleLarge
                                            ?.copyWith(
                                                fontWeight: FontWeight.w800),
                                      ),
                                      const SizedBox(height: 2),
                                      Text(
                                        (snap['destination'] ??
                                                trip['destinationArea'] ??
                                                '')
                                            .toString(),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: Theme.of(context)
                                            .textTheme
                                            .bodyMedium
                                            ?.copyWith(
                                                color: AppColors.textSecondary),
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
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 8, vertical: 4),
                                  decoration: BoxDecoration(
                                    color: AppColors.successSoft,
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: const Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Icons.verified_rounded,
                                          size: 14, color: AppColors.success),
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
                                if (pkgTemporal != null)
                                  StatusChip(
                                    key: ValueKey(
                                        'package-status-${trip['id']}'),
                                    text: pkgTemporal.label,
                                    icon: pkgTemporal.icon,
                                    tone: pkgTemporal.tone,
                                  ),
                                TravelStatusPill(
                                  text:
                                      '${_dateRange(trip)} · $duration ${duration == 1 ? 'day' : 'days'}',
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
            const SizedBox(height: 72),
          ],
        ),
      ),
    );
  }
}
