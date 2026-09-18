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

  const AlternativeScreen({
    super.key,
    required this.budget,
    required this.userBudget,
    this.tripId,
  });

  @override
  State<AlternativeScreen> createState() => _AlternativeScreenState();
}

class _AlternativeScreenState extends State<AlternativeScreen> {
  final api = ApiService();
  List<Map<String, dynamic>> alternatives = [];
  Map<String, dynamic>? budget;
  bool busy = false;

  @override
  void initState() {
    super.initState();
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
                  'estimatedSavings': item['saving'],
                  'alternativeType': item['type'] ?? 'activity',
                })
            .toList();
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
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> applyAlternative(Map<String, dynamic> item) async {
    if ((widget.tripId ?? '').isEmpty) {
      showError(context, 'Open this from a saved trip to apply changes.');
      return;
    }
    setState(() => busy = true);
    try {
      final data = await api.post(
        '/api/fr5/itineraries/${widget.tripId}/lower-cost-alternatives/apply',
        {'alternative': item},
      );
      if (!mounted) return;
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
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final currentTotal = budget?['total'] ?? widget.budget.totalCost;
    final limit = budget?['limit'] ?? widget.userBudget;
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
            if (busy && alternatives.isEmpty)
              const SizedBox(
                  height: 160,
                  child: Center(child: CircularProgressIndicator()))
            else if (alternatives.isEmpty)
              const TravelEmptyState(
                icon: Icons.savings_outlined,
                title: 'No alternatives available',
                message:
                    'TravelMate could not build lower-cost options for this trip yet.',
              )
            else
              ...alternatives.map((item) {
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: InkCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          const CircleAvatar(
                            backgroundColor: InkWashColors.paleBlue,
                            child: Icon(Icons.savings_outlined,
                                color: InkWashColors.blueGrey),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              (item['title'] ?? 'Lower-cost option').toString(),
                              style:
                                  const TextStyle(fontWeight: FontWeight.w900),
                            ),
                          ),
                          TravelStatusPill(
                            text:
                                'Save RM ${item['estimatedSavings'] ?? item['saving'] ?? 0}',
                            icon: Icons.payments_outlined,
                          ),
                        ]),
                        const SizedBox(height: 8),
                        Text((item['description'] ?? item['data'] ?? '')
                            .toString()),
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
