import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';

class BudgetReplanScreen extends StatefulWidget {
  final ApiService api;
  final String tripId;
  final Map<String, dynamic> options;

  const BudgetReplanScreen({
    super.key,
    required this.api,
    required this.tripId,
    required this.options,
  });

  @override
  State<BudgetReplanScreen> createState() => _BudgetReplanScreenState();
}

class _BudgetReplanScreenState extends State<BudgetReplanScreen> {
  final food = TextEditingController();
  final transport = TextEditingController();
  final removed = <String>{};
  bool busy = false;

  @override
  void dispose() {
    food.dispose();
    transport.dispose();
    super.dispose();
  }

  String _money(Object? value) =>
      value is num ? value.toStringAsFixed(2) : 'Unavailable';

  Future<void> preview() async {
    if (busy) return;
    final changes = <String, dynamic>{};
    for (final entry
        in {'foodCost': food, 'transportCost': transport}.entries) {
      final input = entry.value.text.trim();
      if (input.isEmpty) continue;
      final value = double.tryParse(input);
      if (value == null || !value.isFinite || value < 0) {
        showError(context, 'Enter a non-negative MYR amount.');
        return;
      }
      changes[entry.key] = value;
    }
    if (removed.isNotEmpty) changes['removeActivityIds'] = removed.toList();
    final path = '/api/fr5/itineraries/${widget.tripId}/budget-replan';
    setState(() => busy = true);
    try {
      final data = await widget.api.post('$path/preview', {'changes': changes});
      if (!mounted) return;
      final budget = data['budget'] as Map;
      final before = data['before'] as Map;
      final schedule = (data['dailySchedule'] as List? ?? []).whereType<Map>();
      final pending = (budget['pendingExpenseCategories'] as List? ?? []);
      final reduction = data['estimatedReduction'] as num;
      final approved = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Review revised plan'),
          scrollable: true,
          content:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Previous estimate: RM ${_money(before['total'])}'),
            Text('Revised estimate: RM ${_money(budget['total'])}'),
            Text(reduction < 0
                ? 'Estimated increase: RM ${_money(-reduction)}'
                : 'Estimated planning reduction: RM ${_money(reduction)}'),
            Text('Food allowance: RM ${_money(budget['food'])}'),
            Text(
                'Local transport allowance: RM ${_money(budget['transport'])}'),
            if ((budget['overBy'] as num? ?? 0) > 0)
              Text(
                  'This plan is still RM ${_money(budget['overBy'])} over budget.'),
            if ((budget['limit'] as num? ?? 0) > 0 &&
                (data['retainedEstimate'] as num? ?? 0) >
                    (budget['limit'] as num))
              Text(
                  'The retained costs already total RM ${_money(data['retainedEstimate'])}. '
                  'Changing food and transport allowances alone cannot meet your budget.'),
            if (pending.isNotEmpty)
              const Text(
                  'Some costs are still unpriced. Check the expense breakdown before relying on this estimate.'),
            const Text(
                'Allowances are planning amounts. Verified payments are recorded separately.'),
            if (removed.isNotEmpty)
              for (final day in schedule) ...[
                const SizedBox(height: 8),
                Text('Day ${day['dayNo']}'),
                for (final row
                    in (day['activities'] as List? ?? []).whereType<Map>())
                  Text(
                      '${row['scheduledStartTime'] ?? ''} ${row['activityName']}'),
                if ((day['activities'] as List? ?? []).isEmpty)
                  const Text('No scheduled visits'),
              ],
          ]),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Cancel')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Confirm budget changes')),
          ],
        ),
      );
      if (!mounted || approved != true) return;
      final saved = await widget.api.post('$path/apply', {
        'changes': changes,
        'confirmed': true,
        'previewToken': data['previewToken'],
      });
      if (!mounted) return;
      final trip = saved['itinerary'];
      if (trip is! Map || trip['id'] != widget.tripId) {
        throw StateError('The trip update could not be confirmed.');
      }
      Navigator.pop(context, Map<String, dynamic>.from(trip));
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final allowances = widget.options['allowances'] as Map? ?? {};
    final visits =
        (widget.options['optionalVisits'] as List? ?? []).whereType<Map>();
    return Scaffold(
      appBar: AppBar(title: const Text('Budget replanning')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        const Text(
            'Enter revised total allowances for the trip or remove optional visits.'),
        for (final (label, field, controller) in [
          ('Food allowance', 'foodCost', food),
          ('Local transport allowance', 'transportCost', transport),
        ])
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: TextField(
              controller: controller,
              enabled: !busy,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText: '$label (MYR)',
                helperText: 'Current: RM ${_money(allowances[field])}',
              ),
            ),
          ),
        if (widget.options['visitRemovalLimited'] == true)
          const Padding(
              padding: EdgeInsets.only(top: 12),
              child: Text(
                  'This trip has no visits that can safely be removed here. You can still adjust its allowances.')),
        for (final visit in visits)
          CheckboxListTile(
            value: removed.contains(visit['activityId']),
            title: Text('Remove ${visit['name']}'),
            subtitle: Text(
                'Day ${visit['dayNo'] ?? 'not set'}${visit['priceKnown'] == true ? '' : ' · Price unconfirmed'}'),
            onChanged: busy
                ? null
                : (checked) => setState(() {
                      final id = visit['activityId'].toString();
                      if (checked == true) {
                        removed.add(id);
                      } else {
                        removed.remove(id);
                      }
                    }),
          ),
        const SizedBox(height: 12),
        FilledButton(
            onPressed: busy ? null : preview,
            child: const Text('Preview revised budget')),
      ]),
    );
  }
}
