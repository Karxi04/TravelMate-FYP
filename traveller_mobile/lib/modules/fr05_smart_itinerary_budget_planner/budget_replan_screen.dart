import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';

class BudgetReplanScreen extends StatefulWidget {
  final ApiService api;
  final String tripId;
  final Map<String, dynamic> options;
  final String? stateVersion;

  const BudgetReplanScreen({
    super.key,
    required this.api,
    required this.tripId,
    required this.options,
    this.stateVersion,
  });

  @override
  State<BudgetReplanScreen> createState() => _BudgetReplanScreenState();
}

class _BudgetReplanScreenState extends State<BudgetReplanScreen> {
  final food = TextEditingController();
  final transport = TextEditingController();
  final removed = <String>{};
  final detach = <String>{};
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
    for (final field in detach) {
      changes[field] = true;
    }
    if (changes.isEmpty) {
      showError(context, 'Enter a revised allowance or select a planning change to preview.');
      return;
    }
    final path = '/api/fr5/itineraries/${widget.tripId}/budget-replan';
    setState(() => busy = true);
    try {
      final data = await widget.api.post('$path/preview', {
        'changes': changes,
        if (widget.stateVersion != null) 'stateVersion': widget.stateVersion,
      });
      if (!mounted) return;
      final budget = data['budget'] as Map;
      final before = data['before'] as Map;
      final schedule = (data['dailySchedule'] as List? ?? []).whereType<Map>();
      final pending = (budget['pendingExpenseCategories'] as List? ?? []);
      final reduction = data['estimatedReduction'] as num;
      final detached = (data['detachedSelections'] as List? ?? []);
      final approved = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Review revised plan'),
          scrollable: true,
          content:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Previous known estimated subtotal: RM ${_money(before['total'])}'),
            Text('Proposed known estimated subtotal: RM ${_money(budget['total'])}'),
            Text(reduction < 0
                ? 'Estimated increase: RM ${_money(-reduction)}'
                : 'Estimated planning reduction: RM ${_money(reduction)}'),
            if (detached.isNotEmpty)
              Text('Remove unpaid planning selections: ${detached.join(', ')}. Review replacement travel costs before relying on this estimate.'),
            Text('Food allowance: RM ${_money(before['food'])} → RM ${_money(budget['food'])}'),
            Text('Food allowance reduction: RM ${_money((before['food'] as num) - (budget['food'] as num))}'),
            Text(
                'Local transport allowance: RM ${_money(before['transport'])} → RM ${_money(budget['transport'])}'),
            Text('Local transport reduction: RM ${_money((before['transport'] as num) - (budget['transport'] as num))}'),
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
                  'Some costs are still unpriced. This reduction concerns the known subtotal and does not establish full-trip affordability.'),
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
        if (widget.stateVersion != null) 'stateVersion': widget.stateVersion,
        'previewToken': data['previewToken'],
      });
      if (!mounted) return;
      final trip = saved['itinerary'];
      if (trip is! Map || trip['id'] != widget.tripId) {
        throw StateError('The trip update could not be confirmed.');
      }
      Navigator.pop(context, Map<String, dynamic>.from(trip));
    } catch (error) {
      if (!mounted) return;
      if (error is ApiException && error.code == 'STALE_BUDGET_PLAN') {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.message)));
        Navigator.pop(context, <String, dynamic>{});
      } else {
        showError(context, error);
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final allowances = widget.options['allowances'] as Map? ?? {};
    final selections = widget.options['travelSelections'] as Map? ?? {};
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
        for (final (kind, field) in [('flight', 'detachFlight'), ('hotel', 'detachHotel')])
          if (selections[kind] is Map)
            if (selections[kind]['canDetach'] == true)
              CheckboxListTile(
                value: detach.contains(field),
                title: Text('Remove unpaid $kind estimate'),
                subtitle: Text('RM ${_money(selections[kind]['amount'])} · Review alternative travel costs separately'),
                onChanged: busy ? null : (checked) => setState(() {
                  if (checked == true) {
                    detach.add(field);
                  } else {
                    detach.remove(field);
                  }
                }),
              )
            else
              ListTile(title: Text('Retain $kind cost'),
                subtitle: const Text('This selection has a record or cannot be confirmed as planning-only.')),
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
