import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import 'models/budget_model.dart';

/// One presentation for saved trip snapshots and the current budget response.
class BudgetBreakdown extends StatelessWidget {
  final BudgetModel budget;
  final double limit;

  const BudgetBreakdown({super.key, required this.budget, required this.limit});

  String money(double value) => 'RM ${value.toStringAsFixed(2)}';

  @override
  Widget build(BuildContext context) {
    final over = budget.isOverBudget(limit);
    final color = over
        ? AppColors.error
        : budget.isComplete
            ? AppColors.success
            : AppColors.warning;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(budget.statusLabel(limit),
          key: const ValueKey('budget-status'),
          style:
              Theme.of(context).textTheme.titleMedium?.copyWith(color: color)),
      const SizedBox(height: AppSpacing.sm),
      Text('Total group budget: ${money(limit)}'),
      Text('Known estimated subtotal: ${money(budget.knownEstimatedSubtotal)}',
          key: const ValueKey('budget-known-subtotal'),
          style: Theme.of(context).textTheme.titleLarge),
      if (budget.totalCost != budget.knownEstimatedSubtotal)
        Text('Backend estimated total: ${money(budget.totalCost)}'),
      if (over) Text('Known costs exceed the budget.'),
      if (!budget.isComplete)
        const Text(
          'Some expenses or pricing details are unresolved. The subtotal does not establish the full trip cost, and remaining balance cannot be guaranteed.',
        )
      else if (!over)
        Text('Estimated balance: ${money(limit - budget.totalCost)}'),
      const SizedBox(height: AppSpacing.md),
      for (final entry in BudgetModel.categoryLabels.entries)
        Padding(
          key: ValueKey('budget-category-${entry.key}'),
          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                  Text(entry.value),
                  Text(budget.expenseLabel(entry.key),
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(color: AppColors.textSecondary)),
                ])),
            const SizedBox(width: AppSpacing.sm),
            Flexible(
                child: Text(
                    (budget.categoryTotals[entry.key] ?? 0) > 0 ||
                            budget.expenseState(entry.key) == 'priced'
                        ? money(budget.categoryTotals[entry.key] ?? 0)
                        : '—',
                    textAlign: TextAlign.right)),
          ]),
        ),
      if (budget.pendingExpenseCategories.isNotEmpty)
        Text(
            'Pending: ${budget.pendingExpenseCategories.map(BudgetModel.categoryLabel).join(', ')}.'),
      if (budget.excludedExpenseCategories.isNotEmpty)
        Text(
            'Outside this estimate: ${budget.excludedExpenseCategories.map(BudgetModel.categoryLabel).join(', ')}.'),
      if (budget.expenseState('activities') == 'unit_unknown')
        const Text(
            'Activity price units are unknown; amounts have not been scaled per traveller.'),
      if (budget.estimateLimitations.isNotEmpty)
        ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: const Text('Estimate details'),
          children: budget.estimateLimitations
              .map((text) => Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: Align(
                        alignment: Alignment.centerLeft, child: Text(text)),
                  ))
              .toList(),
        ),
      const SizedBox(height: AppSpacing.sm),
      Text('Cost estimates do not confirm payments or reservations.',
          style: Theme.of(context)
              .textTheme
              .bodySmall
              ?.copyWith(color: AppColors.textSecondary)),
    ]);
  }
}
