class BudgetModel {
  static const categoryLabels = {
    'activities': 'Activities',
    'food': 'Food allowance',
    'transport': 'Local transport',
    'hotel': 'Hotel',
    'flight': 'Flight',
    'carRental': 'Car rental',
  };
  final double accommodation;
  final double food;
  final double transportation;
  final double activities;
  final double flight;
  final double carRental;
  final double budgetLimit;
  final double? authoritativeTotal;
  final double? knownSubtotal;
  final String completenessStatus;
  final String affordabilityStatus;
  final Map<String, Map<String, dynamic>> expenseBreakdown;
  final Map<String, dynamic> costProvenance;
  final List<String> pendingExpenseCategories;
  final List<String> excludedExpenseCategories;
  final List<String> estimateLimitations;
  final bool invalidAmounts;

  BudgetModel({
    required this.accommodation,
    required this.food,
    required this.transportation,
    required this.activities,
    this.flight = 0,
    this.carRental = 0,
    this.budgetLimit = 0,
    this.authoritativeTotal,
    this.knownSubtotal,
    this.completenessStatus = 'incomplete',
    this.affordabilityStatus = 'incomplete',
    this.expenseBreakdown = const {},
    this.costProvenance = const {},
    this.pendingExpenseCategories = const [],
    this.excludedExpenseCategories = const [],
    this.estimateLimitations = const [],
    this.invalidAmounts = false,
  });

  factory BudgetModel.fromJson(Map<String, dynamic> json,
      {double fallbackLimit = 0}) {
    final totals = _map(json['categoryTotals']);
    final expenses = _map(json['expenseBreakdown']);
    var invalid = false;
    double? read(List<dynamic> values) {
      for (final value in values) {
        if (value == null) continue;
        final parsed = double.tryParse('$value');
        if (parsed != null && parsed.isFinite && parsed >= 0) return parsed;
        invalid = true;
        return 0;
      }
      return null;
    }

    double category(String key) =>
        read([
          totals[key],
          json[key],
          _map(expenses[key])['amount'],
        ]) ??
        0;
    final hotel = category('hotel');
    final food = category('food');
    final transport = category('transport');
    final activities = category('activities');
    final flight = category('flight');
    final rental = category('carRental');
    final total = read([json['totalEstimatedCost'], json['total']]);
    final known = read([json['knownEstimatedSubtotal']]);
    final limit =
        read([json['budgetLimit'], json['limit'], fallbackLimit]) ?? 0;
    return BudgetModel(
      accommodation: hotel,
      food: food,
      transportation: transport,
      activities: activities,
      flight: flight,
      carRental: rental,
      budgetLimit: limit,
      authoritativeTotal: total ?? known,
      knownSubtotal: known,
      invalidAmounts: invalid,
      completenessStatus: '${json['completenessStatus'] ?? 'incomplete'}',
      affordabilityStatus: '${json['affordabilityStatus'] ?? 'incomplete'}',
      expenseBreakdown: {
        for (final entry in expenses.entries) entry.key: _map(entry.value),
      },
      costProvenance: _map(json['costProvenance']),
      pendingExpenseCategories: _strings(json['pendingExpenseCategories']),
      excludedExpenseCategories: _strings(json['excludedExpenseCategories']),
      estimateLimitations: _strings(json['estimateLimitations']),
    );
  }

  static Map<String, dynamic> _map(dynamic value) => value is Map
      ? {for (final entry in value.entries) '${entry.key}': entry.value}
      : {};
  static List<String> _strings(dynamic value) => value is List
      ? value
          .whereType<String>()
          .where((text) => text.trim().isNotEmpty)
          .toSet()
          .toList()
      : [];

  Map<String, double> get categoryTotals => {
        'activities': activities,
        'food': food,
        'transport': transportation,
        'hotel': accommodation,
        'flight': flight,
        'carRental': carRental,
      };
  // Only legacy payloads without a backend total need the six-category fallback.
  double get totalCost =>
      authoritativeTotal ?? categoryTotals.values.fold(0.0, (a, b) => a + b);
  double get knownEstimatedSubtotal => knownSubtotal ?? totalCost;
  double difference(double userBudget) => totalCost - userBudget;
  bool isOverBudget(double userBudget) =>
      affordabilityStatus == 'over_budget' ||
      knownEstimatedSubtotal > userBudget ||
      totalCost > userBudget;

  bool get isComplete =>
      !invalidAmounts &&
      authoritativeTotal != null &&
      completenessStatus == 'complete' &&
      {'within_budget', 'over_budget'}.contains(affordabilityStatus) &&
      pendingExpenseCategories.isEmpty &&
      excludedExpenseCategories.isEmpty &&
      categoryLabels.keys.every((key) =>
          {'priced', 'not_required', 'simulated_estimate'}
              .contains(expenseState(key)) &&
          expenseBreakdown[key]?['overlapsAllowance'] != true);

  String statusLabel(double limit) => isOverBudget(limit)
      ? 'Over budget'
      : isComplete
          ? 'Within budget'
          : 'Incomplete estimate';

  String expenseState(String key) =>
      '${expenseBreakdown[key]?['state'] ?? 'unknown'}';

  String expenseLabel(String key) {
    final state = expenseState(key);
    final source =
        '${expenseBreakdown[key]?['provenance'] ?? costProvenance[key] ?? ''}';
    if (state == 'simulated_estimate' ||
        ({'priced', 'unknown'}.contains(state) &&
            (source.contains('simulated') || source.contains('sandbox')))) {
      return 'Simulated estimate';
    }
    return switch (state) {
      'not_required' => 'Not required',
      'not_selected' => 'Not selected',
      'selected_unpriced' => 'Pending price',
      'undecided' => 'Pending selection',
      'excluded_outside_scope' => 'Outside scope',
      'unit_unknown' => 'Pricing unit unknown',
      'unverified_estimate' => 'Unverified estimate',
      'priced' when key == 'flight' || key == 'hotel' =>
        'Selected cost estimate',
      'priced' when (categoryTotals[key] ?? 0) == 0 => 'Zero cost estimate',
      'priced' => 'Estimate',
      _ => 'Stored estimate · status unknown',
    };
  }

  static String categoryLabel(String key) =>
      categoryLabels[key] ??
      switch (key) {
        'ownVehicleFuelAndTolls' => 'Own-vehicle fuel and tolls',
        'accommodation' => 'Other accommodation',
        'otherTravel' => 'Other travel costs',
        _ => 'Other expenses',
      };
}
