import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'budget_service.dart';
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
  late final ApiService api;
  List<Map<String, dynamic>> alternatives = [];
  Map<String, dynamic>? budget;
  String? activityAdvice;
  String? activityAlternativeStatus;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(load);
  }

  Future<void> load() async {
    if ((widget.tripId ?? '').isEmpty) {
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
    setState(() => busy = true);
    try {
      final data = await api.post(
          '/api/fr5/itineraries/${widget.tripId}/lower-cost-alternatives');
      if (!mounted) return;
      setState(() {
        alternatives = (data['alternatives'] as List? ?? [])
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
        budget = data['budget'] is Map
            ? Map<String, dynamic>.from(data['budget'] as Map)
            : null;
        activityAdvice = data['activityAdvice']?.toString();
        activityAlternativeStatus =
            data['activityAlternativeStatus']?.toString();
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
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
    return 'Estimated admission: MYR ${before.toStringAsFixed(2)} → MYR ${after.toStringAsFixed(2)}';
  }

  Future<void> applyAlternative(Map<String, dynamic> item) async {
    if (busy || !_canApplyItem(item)) return;
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
    if (!mounted || confirmed != true || busy) return;
    setState(() => busy = true);
    try {
      final data = await api.post(
        '/api/fr5/itineraries/${widget.tripId}/lower-cost-alternatives/apply',
        {'alternative': item},
      );
      if (!mounted) return;
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
      await load();
    } catch (e) {
      if (mounted) showError(context, e);
      if (e is ApiException && e.statusCode == 409 && mounted) await load();
    } finally {
      if (mounted) setState(() => busy = false);
    }
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
            if (hasAdvice) _buildAdviceCard(),
            if (busy && alternatives.isEmpty)
              const SizedBox(
                  height: 160,
                  child: Center(child: CircularProgressIndicator()))
            else if (alternatives.isEmpty)
              TravelEmptyState(
                icon: Icons.savings_outlined,
                title: hasAdvice
                    ? 'No specific alternative options'
                    : 'No alternatives available',
                message: hasAdvice
                    ? 'Follow the guidance above or check other categories to reduce costs.'
                    : 'TravelMate could not build lower-cost options for this trip yet.',
              )
            else
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
                                  busy ? null : () => applyAlternative(item),
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
        ),
      ),
    );
  }
}
