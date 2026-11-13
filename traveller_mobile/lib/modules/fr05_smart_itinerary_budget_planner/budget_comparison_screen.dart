import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import 'alternative_screen.dart';
import 'budget_breakdown.dart';
import 'models/budget_model.dart';

class BudgetComparisonScreen extends StatefulWidget {
  final BudgetModel budget;
  final double userBudget;
  final String? tripId;
  final ApiService? api;
  final ValueChanged<Map<String, dynamic>>? onApplied;

  const BudgetComparisonScreen({
    super.key,
    required this.budget,
    required this.userBudget,
    this.tripId,
    this.api,
    this.onApplied,
  });

  @override
  State<BudgetComparisonScreen> createState() => _BudgetComparisonScreenState();
}

class _BudgetComparisonScreenState extends State<BudgetComparisonScreen> {
  BudgetModel? _appliedBudget;

  BudgetModel get budget => _appliedBudget ?? widget.budget;

  @override
  void didUpdateWidget(covariant BudgetComparisonScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.budget != oldWidget.budget || widget.tripId != oldWidget.tripId) {
      _appliedBudget = null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final canBrowse = (widget.tripId ?? '').isNotEmpty ||
        budget.isOverBudget(widget.userBudget);

    return Scaffold(
        appBar: AppBar(
          title: const Text("Budget Comparison"),
        ),
        body: ListView(padding: const EdgeInsets.all(AppSpacing.lg), children: [
          InkCard(child: BudgetBreakdown(budget: budget, limit: widget.userBudget)),
          if (canBrowse)
            ElevatedButton(
              child: const Text("View Lower-Cost Alternatives"),
              onPressed: () {
                Navigator.push(
                    context,
                    MaterialPageRoute(
                        builder: (context) => AlternativeScreen(
                              budget: budget,
                              userBudget: widget.userBudget,
                              tripId: widget.tripId,
                              api: widget.api,
                              onApplied: (trip) {
                                final estimate = trip['budgetEstimate'];
                                if (mounted && estimate is Map) {
                                  setState(() => _appliedBudget = BudgetModel.fromJson(
                                    Map<String, dynamic>.from(estimate),
                                    fallbackLimit: widget.userBudget,
                                  ));
                                }
                                widget.onApplied?.call(trip);
                              },
                            )));
              },
            )
        ]));
  }
}
