import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

const _categories = [
  'Food',
  'Transportation',
  'Accommodation',
  'Activities',
  'Shopping',
  'Other',
];

String _money(num minor) => (minor / 100).toStringAsFixed(2);

class TripExpensesScreen extends StatefulWidget {
  final String tripId;
  final ApiService api;
  final ValueChanged<Map<String, dynamic>>? onChanged;
  final Map<String, dynamic>? initialData;

  const TripExpensesScreen(
      {super.key,
      required this.tripId,
      required this.api,
      this.onChanged,
      this.initialData});

  @override
  State<TripExpensesScreen> createState() => _TripExpensesScreenState();
}

class _TripExpensesScreenState extends State<TripExpensesScreen> {
  Map<String, dynamic>? data;
  String? error;
  bool reading = false, saving = false, unknownOutcome = false;
  int requestVersion = 0;
  bool get busy => reading || saving;

  String get path => '/api/fr5/itineraries/${widget.tripId}/expenses';

  @override
  void initState() {
    super.initState();
    data = widget.initialData;
    load();
  }

  @override
  void didUpdateWidget(covariant TripExpensesScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.tripId != widget.tripId || oldWidget.api != widget.api) {
      requestVersion++;
      data = widget.initialData;
      reading = false;
      saving = false;
      error = null;
      unknownOutcome = false;
      load();
    }
  }

  Future<void> load() async {
    if (reading || saving) return;
    final version = ++requestVersion;
    setState(() {
      reading = true;
      error = null;
    });
    try {
      final response = await widget.api.get(path);
      if (!mounted || version != requestVersion) return;
      if (response is! Map || response['overview'] is! Map)
        throw StateError('Invalid expense response');
      final updated = Map<String, dynamic>.from(response);
      setState(() {
        data = updated;
        unknownOutcome = false;
      });
      widget.onChanged?.call(updated);
    } catch (e) {
      if (mounted && version == requestVersion)
        setState(() => error = userFacingApiError(e));
    } finally {
      if (mounted && version == requestVersion) setState(() => reading = false);
    }
  }

  Future<void> change(Map<String, dynamic> action) async {
    if (busy || unknownOutcome || data == null) return;
    final version = ++requestVersion;
    final revision = data!['revision'];
    final target = path;
    var reload = false;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final response = await widget.api
          .patch(target, {...action, 'expectedRevision': revision});
      if (!mounted || version != requestVersion) return;
      final updated = Map<String, dynamic>.from(response as Map);
      setState(() => data = updated);
      widget.onChanged?.call(updated);
    } catch (e) {
      if (!mounted || version != requestVersion) return;
      reload = e is ApiException && e.statusCode == 409;
      final uncertain = isBackendConnectionFailure(e) ||
          e is ApiException && e.statusCode >= 500;
      setState(() {
        unknownOutcome = uncertain;
        error = uncertain
            ? 'The save result is unconfirmed. Refresh before editing again; the request will not be sent again automatically.'
            : userFacingApiError(e);
      });
    } finally {
      if (mounted && version == requestVersion) setState(() => saving = false);
    }
    if (reload && mounted) {
      await load();
      if (mounted && error == null)
        setState(() => error =
            'These expenses changed. Review the latest records before saving again.');
    }
  }

  Future<void> edit(Map? row) async {
    final expense = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _ExpenseDialog(
        row: row,
        startDate:
            DateTime.tryParse('${data?['startDate'] ?? ''}'.split('T').first),
        endDate:
            DateTime.tryParse('${data?['endDate'] ?? ''}'.split('T').first),
      ),
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
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Delete')),
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
    final unknown =
        (overview?['unknownCategories'] as List? ?? const []).join(', ');
    final balance = overview?['balanceAfterRecordedActualMinor'] as num?;
    return Scaffold(
      appBar: AppBar(title: const Text('Trip expenses'), actions: [
        IconButton(
            tooltip: 'Refresh expenses',
            onPressed: busy ? null : load,
            icon: const Icon(Icons.refresh))
      ]),
      body: overview == null
          ? error != null
              ? AppErrorState(
                  title: 'Budget unavailable', message: error!, onRetry: load)
              : const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: load,
              child: ListView(
                padding: const EdgeInsets.all(AppSpacing.lg),
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  if (busy) const LinearProgressIndicator(),
                  if (error != null || unknownOutcome) ...[
                    Text(error ??
                        'Refresh to confirm the previous save result.'),
                    TextButton(
                        onPressed: busy ? null : load,
                        child: const Text('Retry refresh'))
                  ],
                  InkCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                            'Budget limit · MYR ${_money(overview['budgetLimitMinor'] as num)}'),
                        Text(
                            'System estimate · MYR ${_money(overview['systemEstimateMinor'] as num)}'),
                        Text(
                            'Verified payments · MYR ${_money(overview['verifiedMinor'] as num)}'),
                        if ((overview['committedHotelMinor'] as num? ?? 0) > 0)
                          Text(
                              'Confirmed hotel cost · MYR ${_money(overview['committedHotelMinor'] as num)}'),
                        Text(
                            'Planned expenses · MYR ${_money(overview['plannedMinor'] as num)}'),
                        Text(
                            'Recorded actual expenses · MYR ${_money(overview['actualMinor'] as num)}'),
                        if (balance != null)
                          Text(
                              'Balance after recorded actuals only · MYR ${_money(balance)}'),
                        if (unknown.isNotEmpty)
                          Text('Unpriced or outside the estimate · $unknown'),
                        const SizedBox(height: AppSpacing.xs),
                        const Text(
                            'Your entries are self-reported. Estimates, payments and entries can overlap, so their totals are shown separately.'),
                        TextButton(
                            onPressed:
                                busy || unknownOutcome ? null : editLimit,
                            child: const Text('Edit budget limit')),
                      ],
                    ),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  SecondaryButton(
                    label: 'Add expense',
                    icon: Icons.add,
                    onPressed: busy || unknownOutcome ? null : () => edit(null),
                  ),
                  if (entries.isEmpty) const Text('No expenses recorded.'),
                  for (final row in entries)
                    ListTile(
                      title: Text(
                          '${row['name']} · MYR ${_money(row['amountMinor'] as num)}'),
                      subtitle: Text([
                        '${row['category']} · ${row['type'] == 'actual' ? 'Actual' : 'Planned'}',
                        if (row['date'] != null) '${row['date']}',
                        if ((row['description'] as String? ?? '').isNotEmpty)
                          '${row['description']}',
                      ].join('\n')),
                      onTap: busy || unknownOutcome ? null : () => edit(row),
                      trailing: IconButton(
                        tooltip: 'Delete ${row['name']}',
                        icon: const Icon(Icons.delete_outline),
                        onPressed:
                            busy || unknownOutcome ? null : () => delete(row),
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
  final DateTime? startDate, endDate;

  const _ExpenseDialog({this.row, this.limit, this.startDate, this.endDate});

  @override
  State<_ExpenseDialog> createState() => _ExpenseDialogState();
}

class _ExpenseDialogState extends State<_ExpenseDialog> {
  final form = GlobalKey<FormState>();
  late final TextEditingController name, amount, description, date;
  late String category, type;
  bool get editingLimit => widget.limit != null;
  bool get hasTripDates => widget.startDate != null && widget.endDate != null &&
      !widget.endDate!.isBefore(widget.startDate!);

  Future<void> pickDate() async {
    final first = widget.startDate!;
    final last = widget.endDate!;
    final previous = DateTime.tryParse(date.text);
    final selected = await showDatePicker(
      context: context,
      firstDate: first,
      lastDate: last,
      initialDate: previous != null && !previous.isBefore(first) && !previous.isAfter(last)
          ? previous : first,
    );
    if (!mounted || selected == null) return;
    setState(() => date.text = selected.toIso8601String().split('T').first);
  }

  InputDecoration input({String? hint}) => InputDecoration(hintText: hint, errorMaxLines: 3);

  Widget field(String label, Widget control) => Padding(
    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: AppSpacing.xs),
        control,
      ],
    ),
  );

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
                  field('Expense name', TextFormField(
                    controller: name,
                    decoration: input(),
                    textInputAction: TextInputAction.next,
                    validator: (text) => (text ?? '').trim().isEmpty
                        ? 'Enter a name.'
                        : text!.trim().length > 100 ? 'Use 100 characters or fewer.' : null,
                  )),
                field(editingLimit ? 'Budget limit (MYR)' : 'Amount (MYR)', TextFormField(
                  controller: amount,
                  decoration: input(hint: '0.00'),
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  validator: (text) {
                    final value = (text ?? '').trim();
                    final valid = RegExp(r'^\d+(\.\d{1,2})?$').hasMatch(value);
                    final parsed = double.tryParse(value);
                    if (!valid || parsed == null || parsed > 1000000 || (!editingLimit && parsed == 0)) {
                      return editingLimit ? 'Enter zero or a valid MYR amount.' : 'Enter a positive MYR amount.';
                    }
                    return null;
                  },
                )),
                if (!editingLimit) ...[
                  field('Category', DropdownButtonFormField<String>(
                    initialValue: category,
                    decoration: input(),
                    isExpanded: true,
                    items: _categories.map((value) => DropdownMenuItem(value: value, child: Text(value))).toList(),
                    onChanged: (value) => category = value!,
                  )),
                  field('Expense type', DropdownButtonFormField<String>(
                    initialValue: type,
                    decoration: input(),
                    isExpanded: true,
                    items: const [
                      DropdownMenuItem(value: 'planned', child: Text('Planned')),
                      DropdownMenuItem(value: 'actual', child: Text('Actual')),
                    ],
                    onChanged: (value) => type = value!,
                  )),
                  field('Description (optional)', TextFormField(
                    controller: description,
                    decoration: input(),
                    minLines: 2,
                    maxLines: 4,
                    maxLength: 500,
                  )),
                  field('Trip date (optional)', TextFormField(
                    controller: date,
                    readOnly: true,
                    onTap: hasTripDates ? pickDate : null,
                    decoration: input(hint: hasTripDates ? 'Choose a trip date' : 'Trip dates unavailable').copyWith(
                      suffixIcon: date.text.isNotEmpty
                          ? IconButton(tooltip: 'Clear trip date', onPressed: () => setState(date.clear),
                              icon: const Icon(Icons.close))
                          : const Icon(Icons.calendar_today_outlined),
                    ),
                    validator: (text) {
                      if ((text ?? '').isEmpty || !hasTripDates) return null;
                      final selected = DateTime.tryParse(text!);
                      return selected != null && !selected.isBefore(widget.startDate!) &&
                          !selected.isAfter(widget.endDate!) ? null : 'Choose a date within this trip.';
                    },
                  )),
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
