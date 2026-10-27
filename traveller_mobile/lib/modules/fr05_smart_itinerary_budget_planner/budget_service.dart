import 'models/budget_model.dart';

class BudgetService {
  BudgetModel calculateBudget({
    required double accommodation,
    required double food,
    required double transportation,
    required double activities,
  }) {
    return BudgetModel(
      accommodation: accommodation,
      food: food,
      transportation: transportation,
      activities: activities,
    );
  }

  List<Map<String, dynamic>> generateAlternatives(BudgetModel budget) {
    List<Map<String, dynamic>> alternatives = [];

    if (budget.accommodation > 200) {
      alternatives.add({
        "title": "Consider Lower-Cost Accommodation",
        "description": "Look for budget hotels, guesthouses or homestays to reduce lodging costs.",
        "type": "hotel",
        "isAdvisory": true,
        "canApply": false,
      });
    }

    if (budget.activities > 100) {
      alternatives.add({
        "title": "Explore Free or Lower-Cost Attractions",
        "description": "Consider public parks, heritage walking routes or free beaches without admission fees.",
        "type": "activity",
        "isAdvisory": true,
        "canApply": false,
      });
    }

    if (budget.transportation > 100) {
      alternatives.add({
        "title": "Use Public Transit or Grouped Rides",
        "description": "Replace private e-hailing with buses, trains or grouped transfers.",
        "type": "transport",
        "isAdvisory": true,
        "canApply": false,
      });
    }

    return alternatives;
  }
}
