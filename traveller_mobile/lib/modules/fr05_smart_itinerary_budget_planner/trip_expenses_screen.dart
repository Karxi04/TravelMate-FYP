import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

const _categories = [
  'Food', 'Transportation', 'Accommodation', 'Activities', 'Shopping', 'Other',
];

String _money(num minor) => (minor / 100).toStringAsFixed(2);

class TripExpensesScreen extends StatefulWidget {
  final String tripId;
  final ApiService api;

  const TripExpensesScreen({super.key, required this.tripId, required this.api});

  @override
  State<TripExpensesScreen> createState() => _TripExpensesScreenState();
}

class _TripExpensesScreenState extends State<TripExpensesScreen> {
  Map<String, dynamic>? data;
  String? error;
  bool busy = false;

  String get path => '/api/fr5/itineraries/${widget.tripId}/expenses';

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final response = await widget.api.get(path);
      if (mounted) setState(() => data = Map<String, dynamic>.from(response as Map));
    } catch (e) {
      if (mounted) setState(() => error = userFacingApiError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> change(Map<String, dynamic> action) async {
    if (busy || data == null) return;
    final revision = data!['revision'];
    setState(() => busy = true);
    try {
      final response = await widget.api.patch(path, {
        ...action,
        'expectedRevision': revision,
      });
      if (mounted) setState(() => data = Map<String, dynamic>.from(response as Map));
    } catch (e) {
      if (!mounted) return;
      if (e is ApiException && e.statusCode == 409) await load();
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> edit(Map? row) async {
    final expense = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _ExpenseDialog(row: row),
    );
    if (!mounted || expense == null) return;
    await change({
      'action': row == null ? 'add' : 'edit',
      if (row != null) 'expenseId': row['id'],
      'expense': expense,
    });
  }

  Future<void> delete(Map row) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete expense?'),
        content: Text('${row['name']} will be removed from this trip.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (mounted && confirmed == true) {
      await change({'action': 'delete', 'expenseId': row['id']});
    }
  }

  Future<void> editLimit() async {
    final previous = data!['budgetLimit'];
    final limit = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _ExpenseDialog(limit: (previous as num).toDouble()),
    );
    if (!mounted || limit == null) return;
    await change({
      'action': 'limit',
      'budgetLimit': limit['amount'],
      'expectedBudgetLimit': previous,
    });
  }

  @override
  Widget build(BuildContext context) {
    final snapshot = data;
    final overview = snapshot?['overview'] as Map?;
    final entries = (snapshot?['expenses'] as List? ?? []).whereType<Map>();
    final unknown = (overview?['unknownCategories'] as List? ?? const []).join(', ');
    final balance = overview?['balanceAfterRecordedActualMinor'] as num?;
    return Scaffold(
      appBar: AppBar(title: const Text('Trip expenses')),
      body: overview == null
          ? error != null
              ? AppErrorState(title: 'Budget unavailable', message: error!, onRetry: load)
              : const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: load,
              child: ListView(
                padding: const EdgeInsets.all(AppSpacing.lg),
                children: [
                  if (busy) const LinearProgressIndicator(),
                  if (error != null) Text(error!),
                  InkCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Budget limit · MYR ${_money(overview['budgetLimitMinor'] as num)}'),
                        Text('System estimate · MYR ${_money(overview['systemEstimateMinor'] as num)}'),
                        Text('Verified payments · MYR ${_money(overview['verifiedMinor'] as num)}'),
                        if ((overview['committedHotelMinor'] as num? ?? 0) > 0)
                          Text('Confirmed hotel cost · MYR ${_money(overview['committedHotelMinor'] as num)}'),
                        Text('Planned expenses · MYR ${_money(overview['plannedMinor'] as num)}'),
                        Text('Recorded actual expenses · MYR ${_money(overview['actualMinor'] as num)}'),
                        if (balance != null)
                          Text('Balance after recorded actuals only · MYR ${_money(balance)}'),
                        if (unknown.isNotEmpty) Text('Unpriced or outside the estimate · $unknown'),
                        const SizedBox(height: AppSpacing.xs),
                        const Text('Your entries are self-reported. Estimates, payments and entries can overlap, so their totals are shown separately.'),
                        TextButton(onPressed: busy ? null : editLimit, child: const Text('Edit budget limit')),
                      ],
                    ),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  SecondaryButton(
                    label: 'Add expense',
                    icon: Icons.add,
                    onPressed: busy ? null : () => edit(null),
                  ),
                  if (entries.isEmpty) const Text('No expenses recorded.'),
                  for (final row in entries)
                    ListTile(
                      title: Text('${row['name']} · MYR ${_money(row['amountMinor'] as num)}'),
                      subtitle: Text([
                        '${row['category']} · ${row['type'] == 'actual' ? 'Actual' : 'Planned'}',
                        if (row['date'] != null) '${row['date']}',
                        if ((row['description'] as String? ?? '').isNotEmpty) '${row['description']}',
                      ].join('\n')),
                      onTap: busy ? null : () => edit(row),
                      trailing: IconButton(
                        tooltip: 'Delete ${row['name']}',
                        icon: const Icon(Icons.delete_outline),
                        onPressed: busy ? null : () => delete(row),
                      ),
                    ),
                ],
              ),
            ),
    );
  }
}

class _ExpenseDialog extends StatefulWidget {
  final Map? row;
  final double? limit;

  const _ExpenseDialog({this.row, this.limit});

  @override
  State<_ExpenseDialog> createState() => _ExpenseDialogState();
}

class _ExpenseDialogState extends State<_ExpenseDialog> {
  final form = GlobalKey<FormState>();
  late final TextEditingController name, amount, description, date;
  late String category, type;
  bool get editingLimit => widget.limit != null;

  @override
  void initState() {
    super.initState();
    final row = widget.row;
    name = TextEditingController(text: row?['name'] as String?);
    amount = TextEditingController(text: editingLimit
        ? widget.limit!.toStringAsFixed(2)
        : row == null ? '' : _money(row['amountMinor'] as num));
    description = TextEditingController(text: row?['description'] as String?);
    date = TextEditingController(text: row?['date'] as String?);
    category = row?['category'] as String? ?? 'Other';
    type = row?['type'] as String? ?? 'planned';
  }

  @override
  void dispose() {
    name.dispose();
    amount.dispose();
    description.dispose();
    date.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(editingLimit ? 'Edit budget limit' : widget.row == null ? 'Add expense' : 'Edit expense'),
        content: SingleChildScrollView(
          child: Form(
            key: form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (!editingLimit)
                  TextFormField(
                    controller: name,
                    decoration: const InputDecoration(labelText: 'Expense name'),
                    validator: (text) => (text ?? '').trim().isEmpty ? 'Enter a name.' : null,
                  ),
                TextFormField(
                  controller: amount,
                  decoration: InputDecoration(labelText: editingLimit ? 'Budget limit (MYR)' : 'Amount (MYR)'),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: (text) {
                    final value = (text ?? '').trim();
                    final valid = RegExp(r'^\d+(\.\d{1,2})?$').hasMatch(value);
                    if (!valid || (!editingLimit && double.tryParse(value) == 0)) {
                      return editingLimit ? 'Enter zero or a valid MYR amount.' : 'Enter a positive MYR amount.';
                    }
                    return null;
                  },
                ),
                if (!editingLimit) ...[
                  DropdownButtonFormField<String>(
                    initialValue: category,
                    decoration: const InputDecoration(labelText: 'Category'),
                    items: _categories.map((value) => DropdownMenuItem(value: value, child: Text(value))).toList(),
                    onChanged: (value) => category = value!,
                  ),
                  DropdownButtonFormField<String>(
                    initialValue: type,
                    decoration: const InputDecoration(labelText: 'Expense type'),
                    items: const [
                      DropdownMenuItem(value: 'planned', child: Text('Planned')),
                      DropdownMenuItem(value: 'actual', child: Text('Actual')),
                    ],
                    onChanged: (value) => type = value!,
                  ),
                  TextFormField(
                    controller: description,
                    decoration: const InputDecoration(labelText: 'Description (optional)'),
                    maxLength: 500,
                  ),
                  TextFormField(
                    controller: date,
                    decoration: const InputDecoration(labelText: 'Trip date (optional)', hintText: 'YYYY-MM-DD'),
                    validator: (text) {
                      final value = (text ?? '').trim();
                      return value.isEmpty || RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)
                          ? null : 'Enter the date as YYYY-MM-DD.';
                    },
                  ),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
            onPressed: () {
              if (!form.currentState!.validate()) return;
              Navigator.pop(context, {
                'amount': amount.text.trim(),
                if (!editingLimit) ...{
                  'name': name.text.trim(),
                  'description': description.text.trim(),
                  'category': category,
                  'type': type,
                  'date': date.text.trim().isEmpty ? null : date.text.trim(),
                },
              });
            },
            child: const Text('Save'),
          ),
        ],
      );
}
