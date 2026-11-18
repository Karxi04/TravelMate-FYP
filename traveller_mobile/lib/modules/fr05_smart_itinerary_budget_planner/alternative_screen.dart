import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
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
  bool optionsChanged = false;
  String? stateVersion;
  List<Map<String, dynamic>> alternatives = [];
  Map<String, dynamic>? budget;
  Map<String, dynamic>? replanOptions;
  String? activityAdvice;
  String? flightAdvice;
  String? hotelAdvice;
  String? activityAlternativeStatus;
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
      load();
    }
  }

  void _setTripState(Map data) {
    budget = data['budget'] is Map
        ? Map<String, dynamic>.from(data['budget']) : null;
    replanOptions = data['budgetReplanOptions'] is Map
        ? Map<String, dynamic>.from(data['budgetReplanOptions']) : null;
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
        activityAdvice =
            'Draft suggestions are general recommendations. Open a saved trip to review and apply verified options.';
        activityAlternativeStatus = 'priced_replacement_unavailable';
      });
      return;
    }
    final hadPrices = alternatives.isNotEmpty;
    setState(() {
      busy = true;
      checkingPrices = true;
      loadError = null;
      alternatives = [];
      activityAdvice = null;
      flightAdvice = null;
      hotelAdvice = null;
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
    try {
      final data = await api.post(
          '/api/fr5/itineraries/$tripId/lower-cost-alternatives');
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
        activityAdvice = data['activityAdvice']?.toString();
        flightAdvice = data['flightAdvice']?.toString();
        hotelAdvice = data['hotelAdvice']?.toString();
        activityAlternativeStatus =
            data['activityAlternativeStatus']?.toString();
      });
    } catch (e) {
      if (current()) setState(() {
        loadError = userFacingApiError(e);
        if (!loadedTrip) replanOptions = null;
      });
    } finally {
      if (current()) setState(() {
        busy = false;
        checkingPrices = false;
      });
    }
  }

  Future<void> openReplan() async {
    final options = replanOptions;
    final tripId = widget.tripId;
    if (options == null || tripId == null || busy || applying) return;
    final updated = await Navigator.push<Map<String, dynamic>>(context, MaterialPageRoute(
      builder: (context) => BudgetReplanScreen(api: api, tripId: tripId, options: options, stateVersion: stateVersion)));
    if (!mounted || widget.tripId != tripId || updated == null) return;
    if (updated['id'] == tripId) widget.onApplied?.call(updated);
    await load();
  }

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

  String? _comparison(Map<String, dynamic> item) {
    final before = item['currentEstimatedCost'];
    final after = item['replacementEstimatedCost'];
    if (before is! num || after is! num) return null;
    final basis = switch (item['alternativeType']) {
      'flight' => 'Estimated fare',
      'hotel' => 'Estimated stay total',
      _ => 'Estimated admission',
    };
    return '$basis: MYR ${before.toStringAsFixed(2)} → MYR ${after.toStringAsFixed(2)}';
  }

  Future<void> applyAlternative(Map<String, dynamic> item) async {
    if (busy || applying || !_canApplyItem(item)) return;
    final tripId = widget.tripId;
    final version = _loadVersion;
    final savings = _extractSavings(item)!;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text((item['title'] ?? 'Apply alternative?').toString()),
        content: Text("${item['description'] ?? ''}\n\n"
            "${_comparison(item) == null ? '' : '${_comparison(item)}\n'}"
            "Estimated reduction: MYR ${savings.toStringAsFixed(2)}. "
            "This changes your saved trip plan only."),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Confirm change')),
        ],
      ),
    );
    if (!mounted || confirmed != true || busy || version != _loadVersion) return;
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

  Widget _buildAdviceCard() {
    final isUnavailable =
        activityAlternativeStatus == 'priced_replacement_unavailable';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: InkCard(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const CircleAvatar(
              backgroundColor: InkWashColors.paleBlue,
              child: Icon(Icons.lightbulb_outline,
                  color: InkWashColors.blueGrey),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Activity budget guidance',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    activityAdvice!,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: AppColors.textSecondary,
                        ),
                  ),
                  if (isUnavailable) ...[
                    const SizedBox(height: 8),
                    const TravelStatusPill(
                      text: 'Priced replacement unavailable',
                      icon: Icons.info_outline,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final currentTotal = budget?['total'] ?? widget.budget.totalCost;
    final limit = budget?['limit'] ?? widget.userBudget;
    final hasAdvice =
        activityAdvice != null && activityAdvice!.trim().isNotEmpty;
    final supplierAdvice = [flightAdvice, hotelAdvice].whereType<String>();

    return Scaffold(
      appBar: AppBar(title: const Text('Lower-cost alternatives')),
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
          children: [
            TravelSectionHeader(
              title: 'Budget alternatives',
              subtitle: 'Estimated total RM $currentTotal / budget RM $limit',
            ),
            const SizedBox(height: 12),
            if (replanOptions != null) ...[
              const Text('Adjust planned food, local transport or eligible optional visits.'),
              FilledButton(onPressed: busy || applying ? null : openReplan, child: const Text('Review budget options')),
            ],
            if (optionsChanged)
              const Text('Options have been refreshed for this trip. Earlier options may no longer apply.'),
            if (loadError != null)
              AppErrorState(
                title: replanOptions == null ? 'Alternatives unavailable' : 'Could not verify replacement prices',
                message: loadError!,
                onRetry: load,
              )
            else if (checkingPrices)
              const SizedBox(
                  height: 160,
                  child: Center(child: CircularProgressIndicator()))
            else if (alternatives.isEmpty)
              TravelEmptyState(
                icon: Icons.savings_outlined,
                title: replanOptions == null
                    ? 'No priced replacements are available for this itinerary yet.'
                    : 'No comparable replacement prices for the current trip',
                message: [if (hasAdvice) activityAdvice!, ...supplierAdvice].join('\n\n'),
              )
            else ...[
              if (hasAdvice) _buildAdviceCard(),
              for (final advice in supplierAdvice)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: InkCard(child: Text(advice)),
                ),
              ...alternatives.map((item) {
                final savings = _extractSavings(item);
                final canApply = _canApplyItem(item);
                final source = item['source']?.toString().trim();
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: InkCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const CircleAvatar(
                              backgroundColor: InkWashColors.paleBlue,
                              child: Icon(Icons.savings_outlined,
                                  color: InkWashColors.blueGrey),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    (item['title'] ?? 'Lower-cost option')
                                        .toString(),
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w900),
                                  ),
                                  const SizedBox(height: 4),
                                  if (savings != null && canApply)
                                    TravelStatusPill(
                                      text:
                                          'Est. save RM ${savings.toStringAsFixed(2)}',
                                      icon: Icons.payments_outlined,
                                    )
                                  else
                                    const TravelStatusPill(
                                      text: 'Advisory guidance',
                                      icon: Icons.info_outline,
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text((item['description'] ?? item['data'] ?? '')
                            .toString()),
                        if (canApply && _comparison(item) != null)
                          Text(_comparison(item)!),
                        if (source != null && source.isNotEmpty) ...[
                          const SizedBox(height: 4),
                          Text(
                            'Source: $source',
                            style: Theme.of(context)
                                .textTheme
                                .bodySmall
                                ?.copyWith(
                                  color: AppColors.textSecondary,
                                  fontStyle: FontStyle.italic,
                                ),
                          ),
                        ],
                        if (canApply) ...[
                          const SizedBox(height: 10),
                          Align(
                            alignment: Alignment.centerRight,
                            child: FilledButton.tonalIcon(
                              onPressed:
                                  busy || applying ? null : () => applyAlternative(item),
                              icon: const Icon(Icons.check_rounded),
                              label: const Text('Apply'),
                            ),
                          ),
                        ],
                      ],
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
