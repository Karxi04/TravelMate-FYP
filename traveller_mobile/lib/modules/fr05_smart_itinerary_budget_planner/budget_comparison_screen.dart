import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import 'alternative_screen.dart';
import 'budget_breakdown.dart';
import 'models/budget_model.dart';

class BudgetComparisonScreen extends StatelessWidget {
  final BudgetModel budget;
  final double userBudget;
  final String? tripId;
  final ApiService? api;

  const BudgetComparisonScreen({
    super.key,
    required this.budget,
    required this.userBudget,
    this.tripId,
    this.api,
  });

  @override
  Widget build(BuildContext context) {
    bool over = budget.isOverBudget(userBudget);

    return Scaffold(
        appBar: AppBar(
          title: const Text("Budget Comparison"),
        ),
        body: ListView(padding: const EdgeInsets.all(AppSpacing.lg), children: [
          InkCard(child: BudgetBreakdown(budget: budget, limit: userBudget)),
          if (over)
            ElevatedButton(
              child: const Text("View Lower-Cost Alternatives"),
              onPressed: () {
                Navigator.push(
                    context,
                    MaterialPageRoute(
                        builder: (context) => AlternativeScreen(
                              budget: budget,
                              userBudget: userBudget,
                              tripId: tripId,
                              api: api,
                            )));
              },
            )
        ]));
  }
}
