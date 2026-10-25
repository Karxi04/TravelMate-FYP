import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/budget_comparison_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/budget_model.dart';

Map<String, dynamic> budgetJson() => {
      'totalEstimatedCost': 750,
      'knownEstimatedSubtotal': 750,
      'budgetLimit': 1500,
      'categoryTotals': {
        'activities': 150,
        'food': 360,
        'transport': 90,
        'hotel': 0,
        'flight': 100,
        'carRental': 50,
      },
      'expenseBreakdown': {
        for (final key in BudgetModel.categoryLabels.keys)
          key: {'state': key == 'hotel' ? 'not_required' : 'priced'},
      },
      'completenessStatus': 'complete',
      'affordabilityStatus': 'within_budget',
      'pendingExpenseCategories': <String>[],
      'excludedExpenseCategories': <String>[],
    };

Future<void> pumpBudget(WidgetTester tester, Map<String, dynamic> json) async {
  final model = BudgetModel.fromJson(json);
  await tester.pumpWidget(MaterialApp(
      home: BudgetComparisonScreen(
    budget: model,
    userBudget: model.budgetLimit,
  )));
  await tester.pumpAndSettle();
}

void main() {
  test('all six categories parse and backend total takes precedence', () {
    final json = budgetJson()..['totalEstimatedCost'] = 900;
    final model = BudgetModel.fromJson(json);
    expect(model.flight, 100);
    expect(model.carRental, 50);
    expect(model.accommodation, 0);
    expect(model.food, 360);
    expect(model.transportation, 90);
    expect(model.activities, 150);
    expect(model.totalCost, 900);
    expect(model.knownEstimatedSubtotal, 750);
    expect(model.budgetLimit, 1500);
  });

  test('legacy totals and six-category fallback remain conservative', () {
    final model = BudgetModel.fromJson({
      'total': 1234,
      'limit': 1500,
      'flight': 100,
      'carRental': 50,
      'status': 'within_budget',
    });
    expect(model.totalCost, 1234);
    expect(model.statusLabel(1500), 'Incomplete estimate');
    expect(model.expenseLabel('hotel'), contains('status unknown'));
    final fallback = BudgetModel.fromJson({
      'activities': 150,
      'food': 360,
      'transport': 90,
      'hotel': 0,
      'flight': 100,
      'carRental': 50,
    });
    expect(fallback.totalCost, 750);
    expect(fallback.isComplete, isFalse);
  });

  test(
      'expense applicability takes precedence over stale simulation provenance',
      () {
    final json = budgetJson();
    (json['expenseBreakdown'] as Map)['carRental'] = {
      'state': 'not_required',
      'provenance': 'simulated_local_catalogue',
    };
    var model = BudgetModel.fromJson(json);
    expect(model.expenseLabel('carRental'), 'Not required');
    (json['expenseBreakdown'] as Map)['flight'] = {
      'state': 'selected_unpriced',
      'provenance': 'sandbox_provider_quote',
    };
    model = BudgetModel.fromJson(json);
    expect(model.expenseLabel('flight'), 'Pending price');
    expect(model.isComplete, isFalse);
  });

  test('empty and malformed payloads parse safely without a completeness claim',
      () {
    for (final json in <Map<String, dynamic>>[
      {},
      {
        'totalEstimatedCost': 'NaN',
        'budgetLimit': 'Infinity',
        'categoryTotals': 'invalid'
      },
      {
        'expenseBreakdown': [],
        'pendingExpenseCategories': 3,
        'estimateLimitations': {}
      },
    ]) {
      final model = BudgetModel.fromJson(json);
      expect(model.totalCost.isFinite, isTrue);
      expect(model.totalCost, greaterThanOrEqualTo(0));
      expect(model.isComplete, isFalse);
    }
  });

  for (final category in ['hotel', 'flight']) {
    testWidgets(
        'pending $category remains visible without available-balance claim',
        (tester) async {
      final json = budgetJson();
      (json['expenseBreakdown'] as Map)[category] = {
        'state': 'selected_unpriced'
      };
      (json['categoryTotals'] as Map)[category] = 0;
      json.addAll({
        'totalEstimatedCost': 600,
        'knownEstimatedSubtotal': 600,
        'completenessStatus': 'incomplete',
        'affordabilityStatus': 'incomplete',
        'pendingExpenseCategories': [category],
      });
      await pumpBudget(tester, json);
      expect(find.text('Incomplete estimate'), findsOneWidget);
      expect(find.text('Known estimated subtotal: RM 600.00'), findsOneWidget);
      expect(find.text('Pending price'), findsOneWidget);
      expect(find.byKey(ValueKey('budget-category-$category')), findsOneWidget);
      expect(find.textContaining('Estimated balance'), findsNothing);
      expect(find.textContaining('Within budget'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('known overrun wins while missing expenses remain disclosed',
      (tester) async {
    final json = budgetJson()
      ..addAll({
        'knownEstimatedSubtotal': 1600,
        'totalEstimatedCost': 1600,
        'completenessStatus': 'incomplete',
        'affordabilityStatus': 'incomplete',
        'pendingExpenseCategories': ['hotel'],
      });
    (json['expenseBreakdown'] as Map)['hotel'] = {'state': 'selected_unpriced'};
    await pumpBudget(tester, json);
    expect(find.text('Over budget'), findsOneWidget);
    expect(find.textContaining('Some expenses or pricing details'),
        findsOneWidget);
    expect(find.textContaining('Estimated balance'), findsNothing);
    await tester.scrollUntilVisible(
        find.text('View Lower-Cost Alternatives'), 250);
    expect(find.text('View Lower-Cost Alternatives'), findsOneWidget);
  });

  testWidgets('complete estimate and genuinely not-required category',
      (tester) async {
    await pumpBudget(tester, budgetJson());
    expect(find.text('Within budget'), findsOneWidget);
    expect(find.text('Not required'), findsOneWidget);
    expect(find.text('Estimated balance: RM 750.00'), findsOneWidget);
    expect(find.text('RM 100.00'), findsOneWidget);
    expect(find.text('RM 50.00'), findsOneWidget);
    expect(find.text('Selected cost estimate'), findsOneWidget);
  });

  testWidgets('unknown activity units and simulated rental are explicit',
      (tester) async {
    final json = budgetJson();
    (json['expenseBreakdown'] as Map)['activities'] = {'state': 'unit_unknown'};
    (json['expenseBreakdown'] as Map)['carRental'] = {
      'state': 'simulated_estimate',
      'provenance': 'simulated_local_catalogue',
    };
    json.addAll({
      'completenessStatus': 'incomplete',
      'affordabilityStatus': 'incomplete',
      'pendingExpenseCategories': ['activities'],
    });
    await pumpBudget(tester, json);
    expect(find.text('Pricing unit unknown'), findsOneWidget);
    expect(find.text('Simulated estimate'), findsOneWidget);
    expect(find.textContaining('amounts have not been scaled per traveller'),
        findsOneWidget);
    expect(find.text('Cost estimates do not confirm payments or reservations.'),
        findsOneWidget);
  });

  testWidgets('own-car exclusion and legacy zero do not imply free costs',
      (tester) async {
    final json = budgetJson()
      ..addAll({
        'completenessStatus': 'incomplete',
        'affordabilityStatus': 'incomplete',
        'excludedExpenseCategories': ['ownVehicleFuelAndTolls'],
      });
    await pumpBudget(tester, json);
    expect(find.text('Outside this estimate: Own-vehicle fuel and tolls.'),
        findsOneWidget);
    await pumpBudget(tester, {'total': 0, 'limit': 1500});
    expect(find.text('Incomplete estimate'), findsOneWidget);
    expect(find.text('Not required'), findsNothing);
    expect(find.text('Zero cost estimate'), findsNothing);
  });

  testWidgets('narrow layout with large text stays scrollable', (tester) async {
    tester.view.physicalSize = const Size(320, 760);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final model = BudgetModel.fromJson(budgetJson());
    await tester.pumpWidget(MaterialApp(
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: const TextScaler.linear(1.8)),
        child: child!,
      ),
      home: BudgetComparisonScreen(budget: model, userBudget: 1500),
    ));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('budget-category-carRental')), 300);
    expect(tester.takeException(), isNull);
  });
}
