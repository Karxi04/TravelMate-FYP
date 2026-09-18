import 'package:flutter/material.dart';

import 'models/budget_model.dart';
import 'alternative_screen.dart';

class BudgetComparisonScreen extends StatelessWidget {
  final BudgetModel budget;
  final double userBudget;
  final String? tripId;

  const BudgetComparisonScreen({
    super.key,
    required this.budget,
    required this.userBudget,
    this.tripId,
  });

  @override
  Widget build(BuildContext context) {
    bool over = budget.isOverBudget(userBudget);

    return Scaffold(
        appBar: AppBar(
          title: const Text("Budget Comparison"),
        ),
        body: Padding(
            padding: const EdgeInsets.all(20),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text("Estimated Cost",
                  style: Theme.of(context).textTheme.headlineSmall),
              Text("RM ${budget.totalCost.toStringAsFixed(2)}"),
              const SizedBox(height: 20),
              Text("Your Budget"),
              Text("RM ${userBudget.toStringAsFixed(2)}"),
              const SizedBox(height: 20),
              Card(
                  child: ListTile(
                title: const Text("Budget Status"),
                subtitle: Text(over
                    ? "Over Budget RM ${(budget.totalCost - userBudget).toStringAsFixed(2)}"
                    : "Within Budget"),
              )),
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
                                )));
                  },
                )
            ])));
  }
}
