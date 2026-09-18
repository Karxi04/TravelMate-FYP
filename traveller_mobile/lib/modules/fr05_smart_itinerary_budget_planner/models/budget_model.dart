class BudgetModel {

  final double accommodation;
  final double food;
  final double transportation;
  final double activities;

  BudgetModel({
    required this.accommodation,
    required this.food,
    required this.transportation,
    required this.activities,
  });


  double get totalCost {
    return accommodation +
        food +
        transportation +
        activities;
  }


  double difference(double userBudget) {
    return totalCost - userBudget;
  }


  bool isOverBudget(double userBudget) {
    return totalCost > userBudget;
  }
}