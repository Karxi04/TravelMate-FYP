import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../widgets/ink_card.dart';
import 'budget_service.dart';
import 'budget_replan_screen.dart';
import 'models/budget_model.dart';

class AlternativeScreen extends StatefulWidget {
  final BudgetModel budget;
  final double userBudget;
  final String? tripId;
  final ApiService? api;
  final ValueChanged<Map<String, dynamic>>? onApplied;

  const AlternativeScreen({
    super.key,
    required this.budget,
    required this.userBudget,
    this.tripId,
    this.api,
    this.onApplied,
  });

  @override
  State<AlternativeScreen> createState() => _AlternativeScreenState();
}

class _AlternativeScreenState extends State<AlternativeScreen> {
  late ApiService api;
  int _loadVersion = 0;
  bool checkingPrices = false;
  bool applying = false;
  String? discovering;
  final searchMessages = <String, String>{};
  List<Map<String, dynamic>> planning = [];
  bool optionsChanged = false;
  String? stateVersion;
  List<Map<String, dynamic>> alternatives = [];
  Map<String, dynamic>? budget;
  Map<String, dynamic>? replanOptions;
  String? loadError;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(load);
  }

  @override
  void didUpdateWidget(covariant AlternativeScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.tripId != widget.tripId || oldWidget.api != widget.api) {
      api = widget.api ?? ApiService();
      stateVersion = null;
      budget = null;
      replanOptions = null;
      optionsChanged = false;
      applying = false;
      discovering = null;
      searchMessages.clear();
      load();
    }
  }

  void _setTripState(Map data) {
    if (data['planningAlternatives'] is List) {
      planning = (data['planningAlternatives'] as List)
          .whereType<Map>()
          .map((row) => Map<String, dynamic>.from(row))
          .toList();
    }
    budget = data['budget'] is Map
        ? Map<String, dynamic>.from(data['budget'])
        : null;
    replanOptions = data['budgetReplanOptions'] is Map
        ? Map<String, dynamic>.from(data['budgetReplanOptions'])
        : null;
    stateVersion = data['stateVersion'] as String?;
  }

  Future<void> load() async {
    if (!mounted || applying) return;
    final version = ++_loadVersion;
    final tripId = widget.tripId;
    bool current() => mounted && version == _loadVersion;
    if ((tripId ?? '').isEmpty) {
      final local = BudgetService().generateAlternatives(widget.budget);
      setState(() {
        alternatives = local
            .map((item) => {
                  'title': item['title'],
                  'description': item['description'],
                  'alternativeType': item['type'] ?? 'strategy',
                  'isAdvisory': item['isAdvisory'] ?? true,
                  'canApply': item['canApply'] ?? false,
                })
            .toList();
      });
      return;
    }
    final hadPrices = alternatives.isNotEmpty;
    setState(() {
      busy = true;
      checkingPrices = true;
      loadError = null;
      alternatives = [];
      planning = [];
    });
    final before = stateVersion;
    var loadedTrip = false;
    try {
      final data = await api.get('/api/fr5/itineraries/$tripId/budget-replan');
      if (!current()) return;
      if (data is Map && data['ok'] == true && data['stateVersion'] is String) {
        loadedTrip = true;
        setState(() {
          _setTripState(data);
          optionsChanged = before != null && before != stateVersion;
          busy = false;
        });
      }
    } catch (_) {
      // An older Backend can still return the complete state from the POST.
    }
    if (!current()) return;
    if (loadedTrip && !_overBudget) {
      setState(() => checkingPrices = false);
      return;
    }
    try {
      final data = await api
          .post('/api/fr5/itineraries/$tripId/lower-cost-alternatives');
      if (!current()) return;
      if (data is! Map || data['ok'] == false) {
        throw StateError('Alternatives could not be refreshed.');
      }
      setState(() {
        alternatives = (data['alternatives'] as List? ?? [])
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
        if (!loadedTrip || data['stateVersion'] is String) {
          _setTripState(data);
          optionsChanged = before != null && before != stateVersion;
        }
        optionsChanged = optionsChanged || (hadPrices && alternatives.isEmpty);
      });
    } catch (e) {
      if (current())
        setState(() {
          loadError = userFacingApiError(e);
          if (!loadedTrip) replanOptions = null;
        });
    } finally {
      if (current())
        setState(() {
          busy = false;
          checkingPrices = false;
        });
    }
  }

  Future<void> openReplan() async {
    final options = replanOptions;
    final tripId = widget.tripId;
    if (options == null || tripId == null || applying) return;
    // The preview owns its options/revision. Keep the existing lookup for returning after Cancel.
    final updated = await Navigator.push<Map<String, dynamic>>(
        context,
        MaterialPageRoute(
            builder: (context) => BudgetReplanScreen(
                api: api,
                tripId: tripId,
                options: options,
                stateVersion: stateVersion)));
    if (!mounted || widget.tripId != tripId || updated == null) return;
    if (updated['id'] == tripId) widget.onApplied?.call(updated);
    await load();
  }

  bool get _overBudget {
    final total = budget?['total'] ?? widget.budget.totalCost;
    final limit = budget?['limit'] ?? widget.userBudget;
    return total is num && limit is num && limit > 0 && total > limit;
  }

  String money(Object? value) =>
      value is num ? value.toStringAsFixed(2) : 'Unavailable';

  Future<void> previewPlanning(Map<String, dynamic> item) async {
    if (applying || discovering != null || widget.tripId == null) return;
    setState(() => applying = true);
    final version = _loadVersion;
    final path = '/api/fr5/itineraries/' + widget.tripId! + '/budget-replan';
    final command = <String, dynamic>{
      'changes': item['changes'],
      'stateVersion': stateVersion
    };
    var refresh = false;
    try {
      final preview = await api.post('$path/preview', command);
      if (!mounted || version != _loadVersion) return;
      final accepted = await confirmPreview(item, preview);
      if (!mounted || accepted != true || version != _loadVersion) return;
      final saved = await api.post('$path/apply', {
        ...command,
        'confirmed': true,
        'previewToken': preview['previewToken']
      });
      if (!mounted || version != _loadVersion) return;
      final trip = saved['itinerary'];
      if (trip is! Map || trip['id'] != widget.tripId)
        throw StateError('The trip update could not be confirmed.');
      if (!mounted) return;
      widget.onApplied?.call(Map<String, dynamic>.from(trip));
      refresh = true;
    } catch (error) {
      if (mounted && version == _loadVersion) showError(context, error);
      refresh = error is ApiException && error.statusCode == 409;
    } finally {
      if (mounted && version == _loadVersion) setState(() => applying = false);
    }
    if (refresh && mounted && version == _loadVersion) await load();
  }

  Future<bool?> confirmPreview(Map<String, dynamic> item, dynamic preview) {
    final before = preview['before'] as Map? ?? {};
    final after = preview['budget'] as Map? ?? {};
    return showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: Text((item['title'] ?? 'Review alternative').toString()),
              scrollable: true,
              content: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text('Original known estimate: RM ' +
                        money(before['total'])),
                    Text(
                        'Proposed known estimate: RM ' + money(after['total'])),
                    Text('Estimated planning reduction: RM ' +
                        money(preview['estimatedReduction'])),
                    Text('Remaining over budget: RM ' +
                        money(after['overBy'] ?? 0)),
                    if ((after['pendingExpenseCategories'] as List? ?? [])
                        .isNotEmpty)
                      const Text(
                          'Important costs remain unpriced; this does not establish full-trip affordability.'),
                    for (final change
                        in (preview['itineraryChanges'] as List? ?? [])
                            .whereType<Map>())
                      Text((change['activityName'] ?? 'Visit').toString() +
                          ' — ' +
                          (change['kind'] ?? 'review').toString() +
                          (change['to'] is Map
                              ? ' ' +
                                  (change['to']['scheduledStartTime'] ?? '')
                                      .toString()
                              : '')),
                    const Text(
                        'This changes your saved plan only. It does not book, cancel or refund a supplier arrangement.'),
                    for (final day in (preview['dailySchedule'] as List? ?? [])
                        .whereType<Map>()) ...[
                      Text('Day ' + day['dayNo'].toString()),
                      for (final row in (day['activities'] as List? ?? [])
                          .whereType<Map>())
                        Text((row['scheduledStartTime'] ?? '').toString() +
                            ' ' +
                            (row['activityName'] ?? '').toString()),
                    ],
                  ]),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('Cancel')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('Confirm change')),
              ],
            ));
  }

  Future<void> discover(String category) async {
    if (discovering != null ||
        applying ||
        widget.tripId == null ||
        stateVersion == null) return;
    final tripId = widget.tripId!;
    final state = stateVersion;
    final version = _loadVersion;
    setState(() => discovering = category);
    try {
      final accepted = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
                title: Text(category == 'flight'
                    ? 'Find cheaper flights?'
                    : 'Find cheaper hotels?'),
                content: Text(category == 'flight'
                    ? 'Search matching fares using up to 2 provider requests. This may use API quota. Quote records may be saved; your trip and bookings stay unchanged until you confirm a replacement.'
                    : 'Search matching stays using 1 provider rates request. This may use API quota. A rate is not a reservation. Your trip stays unchanged until you confirm a replacement.'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Cancel')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Search now')),
                ],
              ));
      if (!mounted ||
          accepted != true ||
          version != _loadVersion ||
          widget.tripId != tripId) return;
      final result = await api.post(
          '/api/fr5/itineraries/$tripId/lower-cost-alternatives/discover', {
        'category': category,
        'providerSearchConfirmed': true,
        'searchRequestId': newTransactionAttemptId('budget_search'),
        'stateVersion': state
      });
      if (!mounted || version != _loadVersion) return;
      final status = result['search']?['status'];
      final message = switch (status) {
        'completed' =>
          'Search complete. Only cheaper compatible offers are shown.',
        'pending' =>
          'Search is still processing. Refresh saved results before trying again.',
        'quota_limited' => 'Search limit reached. Try again next hour.',
        _ =>
          'Provider search is unavailable. Your local planning options remain available.',
      };
      setState(() => searchMessages[category] = message);
      await load();
    } catch (error) {
      if (mounted && version == _loadVersion) {
        setState(() => searchMessages[category] = error is ApiException &&
                error.statusCode == 429
            ? 'Search limit reached. Local planning options remain available.'
            : error is ApiException && error.statusCode == 409
                ? error.message
                : 'Search could not be confirmed. Refresh saved results before trying again.');
      }
    } finally {
      if (mounted && widget.tripId == tripId)
        setState(() => discovering = null);
    }
  }

  Widget discoveryCard(String category) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: InkCard(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(category == 'flight' ? 'Flights' : 'Hotels',
              style: const TextStyle(fontWeight: FontWeight.w700)),
          const Text('Look for a cheaper comparable planning quote.'),
          if (searchMessages[category] != null) Text(searchMessages[category]!),
          OutlinedButton(
              onPressed: discovering != null || applying || stateVersion == null
                  ? null
                  : () => discover(category),
              child: Text(discovering == category
                  ? 'Searching…'
                  : category == 'flight'
                      ? 'Find cheaper flights'
                      : 'Find cheaper hotels')),
        ])),
      );

  double? _extractSavings(Map<String, dynamic> item) {
    final raw = item['estimatedSavings'] ?? item['saving'];
    if (raw == null) return null;
    if (raw is num) return raw > 0 ? raw.toDouble() : null;
    final parsed = double.tryParse(raw.toString());
    return (parsed != null && parsed > 0) ? parsed : null;
  }

  bool _canApplyItem(Map<String, dynamic> item) =>
      (widget.tripId ?? '').isNotEmpty &&
      item['canApply'] == true &&
      item['isAdvisory'] != true &&
      item['stateVersion'] is String &&
      _extractSavings(item) != null;

  Future<void> applyAlternative(Map<String, dynamic> item) async {
    if (busy || applying || discovering != null || !_canApplyItem(item)) return;
    final tripId = widget.tripId;
    final version = _loadVersion;
    setState(() => applying = true);
    dynamic preview;
    try {
      preview = await api.post(
          '/api/fr5/itineraries/$tripId/lower-cost-alternatives/preview',
          {'alternative': item});
    } catch (error) {
      if (mounted) {
        setState(() => applying = false);
        showError(context, error);
      }
      return;
    }
    if (!mounted || version != _loadVersion) return;
    final confirmed = await confirmPreview(item, preview);
    if (mounted) setState(() => applying = false);
    if (!mounted || confirmed != true || busy || version != _loadVersion)
      return;
    setState(() => applying = true);
    var refresh = false;
    try {
      final data = await api.post(
        '/api/fr5/itineraries/$tripId/lower-cost-alternatives/apply',
        {'alternative': item},
      );
      if (!mounted || version != _loadVersion) return;
      final updated = data['itinerary'];
      if (updated is! Map || updated['id'] != widget.tripId) {
        throw StateError('The trip update could not be confirmed.');
      }
      widget.onApplied?.call(Map<String, dynamic>.from(updated));
      setState(() {
        if (data['planningAlternatives'] is List) {
          planning = (data['planningAlternatives'] as List)
              .whereType<Map>()
              .map((row) => Map<String, dynamic>.from(row))
              .toList();
        }
        budget = data['budget'] is Map
            ? Map<String, dynamic>.from(data['budget'] as Map)
            : budget;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Lower-cost alternative applied.')),
      );
      refresh = true;
    } catch (e) {
      if (!mounted || version != _loadVersion) return;
      showError(context, e);
      refresh = e is ApiException && e.statusCode == 409;
    } finally {
      if (mounted && version == _loadVersion) setState(() => applying = false);
    }
    if (refresh && mounted && version == _loadVersion) await load();
  }

  Widget optionCard(Map<String, dynamic> item, {bool local = false}) {
    final canApply = local || _canApplyItem(item);
    final saving = _extractSavings(item);
    final before = item['currentEstimatedCost'];
    final after = item['replacementEstimatedCost'];
    final remaining = item['remainingOverBy'];
    return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: InkCard(
            child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
                (item['category'] ??
                        item['alternativeType'] ??
                        'Planning advice')
                    .toString(),
                style: Theme.of(context).textTheme.labelLarge),
            Text((item['title'] ?? 'Lower-cost option').toString(),
                style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text((item['description'] ?? '').toString()),
            if (item['data'] is Map && item['alternativeType'] == 'hotel')
              Text(((item['data']['roomName'] ?? '')).toString() +
                  ' · ' +
                  ((item['data']['address'] ?? '')).toString()),
            if (item['data'] is Map && item['alternativeType'] == 'flight')
              for (final leg in ['outboundSegments', 'returnSegments'])
                for (final segment
                    in (item['data'][leg] as List? ?? []).whereType<Map>())
                  Text((segment['departureAirportCode'] ?? '').toString() +
                      ' ' +
                      (segment['departureDate'] ?? '').toString() +
                      ' ' +
                      (segment['departureTime'] ?? '').toString() +
                      ' → ' +
                      (segment['arrivalAirportCode'] ?? '').toString() +
                      ' ' +
                      (segment['arrivalTime'] ?? '').toString()),
            if (before is num && after is num)
              Text('RM ' + money(before) + ' → RM ' + money(after)),
            if (saving != null && canApply)
              Text('Estimated reduction: RM ' + money(saving)),
            if (remaining is num)
              Text('Remaining over budget: RM ' + money(remaining)),
            if (item['source'] != null)
              Text('Source: ' + item['source'].toString(),
                  style: Theme.of(context).textTheme.bodySmall),
            if (!canApply) const Text('Advisory guidance'),
            if (canApply)
              Align(
                  alignment: Alignment.centerRight,
                  child: FilledButton.tonal(
                    onPressed: applying || discovering != null
                        ? null
                        : () => local
                            ? previewPlanning(item)
                            : applyAlternative(item),
                    child: const Text('Preview'),
                  )),
          ],
        )));
  }

  @override
  Widget build(BuildContext context) {
    final total = budget?['total'] ?? widget.budget.totalCost;
    final limit = budget?['limit'] ?? widget.userBudget;
    final pending = (budget?['pendingExpenseCategories'] as List? ??
        widget.budget.pendingExpenseCategories);
    return Scaffold(
      appBar: AppBar(title: const Text('Lower-Cost Alternatives')),
      body: RefreshIndicator(
          onRefresh: load,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
            children: [
              InkCard(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    Text('Budget: RM ' + money(limit)),
                    Text('Known estimate: RM ' + money(total)),
                    if (_overBudget)
                      Text('Over budget: RM ' +
                          money((total as num) - (limit as num))),
                    if (!_overBudget && !busy)
                      const Text(
                          'Your known estimate does not exceed the budget.'),
                    if (pending.isNotEmpty)
                      const Text(
                          'Some costs are unpriced. The known subtotal does not establish full-trip affordability.'),
                  ])),
              const SizedBox(height: 16),
              if (_overBudget) ...[
                const Text('Available ways to save',
                    style:
                        TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                const SizedBox(height: 12),
                for (final item in planning) optionCard(item, local: true),
                if (!api.isStandalone &&
                    (widget.tripId ?? '').isNotEmpty &&
                    (budget?['flight'] as num? ?? widget.budget.flight) > 0)
                  discoveryCard('flight'),
                if (!api.isStandalone &&
                    (widget.tripId ?? '').isNotEmpty &&
                    (budget?['hotel'] as num? ?? widget.budget.accommodation) >
                        0)
                  discoveryCard('hotel'),
                for (final item in alternatives) optionCard(item),
                if (replanOptions != null)
                  FilledButton(
                      onPressed: applying ? null : openReplan,
                      child: const Text('Review budget options')),
                if (optionsChanged)
                  const Text(
                      'Options have been refreshed for this trip. Earlier options may no longer apply.'),
                if (checkingPrices)
                  const Padding(
                      padding: EdgeInsets.all(12),
                      child: LinearProgressIndicator()),
                if (loadError != null) ...[
                  const Text(
                      'Replacement prices are unavailable. You can still review available planning changes.'),
                  TextButton(onPressed: load, child: const Text('Try again')),
                ],
                if (!checkingPrices && alternatives.isEmpty)
                  const Text(
                      'No verified cheaper replacement offers are available for this trip.'),
                if (!checkingPrices &&
                    planning.isEmpty &&
                    replanOptions == null)
                  const Text('No eligible planning reductions are available.'),
                if (budget?['hotel'] is num &&
                    (budget!['hotel'] as num) > 0 &&
                    !alternatives
                        .any((item) => item['alternativeType'] == 'hotel'))
                  const Text(
                      'Hotel: no comparable replaceable stay is available.'),
              ],
            ],
          )),
    );
  }
}
