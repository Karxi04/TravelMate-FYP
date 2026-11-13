import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_expenses_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _ExpenseApi extends ApiService {
  final List<Map<String, dynamic>> mutations = [];
  Map<String, dynamic>? expense;
  int limit = 30000;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    expect(path, '/api/fr5/itineraries/owned-trip/expenses');
    final actual = expense?['type'] == 'actual' ? expense!['amountMinor'] as int : 0;
    final planned = expense?['type'] == 'planned' ? expense!['amountMinor'] as int : 0;
    return {
      'revision': mutations.length,
      'budgetLimit': limit / 100,
      'expenses': [if (expense != null) expense],
      'overview': {
        'budgetLimitMinor': limit, 'verifiedMinor': 4250, 'systemEstimateMinor': 23000,
        'plannedMinor': planned, 'actualMinor': actual, 'balanceAfterRecordedActualMinor': limit - actual,
        'unknownCategories': ['hotel'],
      },
    };
  }

  @override
  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) async {
    final change = body!;
    expect(change['expectedRevision'], mutations.length);
    mutations.add(change);
    if (change['action'] == 'delete') {
      expect(change['expenseId'], 'expense-1');
      expense = null;
    } else if (change['action'] == 'limit') {
      expect(change['expectedBudgetLimit'], 300);
      limit = (double.parse(change['budgetLimit'] as String) * 100).round();
    } else {
      final row = change['expense'] as Map<String, dynamic>;
      expense = {
        ...row, 'id': 'expense-1',
        'amountMinor': (double.parse(row['amount'] as String) * 100).round(),
      };
    }
    return get(path);
  }
}

void main() {
  testWidgets('Add, edit, reopen, update limit and confirm delete', (tester) async {
    final api = _ExpenseApi();
    Future<void> open() async {
      await tester.pumpWidget(MaterialApp(home: TripExpensesScreen(tripId: 'owned-trip', api: api)));
      await tester.pumpAndSettle();
    }

    await open();
    expect(find.text('Verified payments · MYR 42.50'), findsOneWidget);
    await tester.tap(find.text('Add expense'));
    await tester.pumpAndSettle();
    final fields = find.byType(TextFormField);
    await tester.enterText(fields.at(0), 'Lunch');
    await tester.enterText(fields.at(1), '15.25');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Planned expenses · MYR 15.25'), findsOneWidget);
    await tester.tap(find.text('Lunch · MYR 15.25'));
    await tester.pumpAndSettle();
    await tester.enterText(fields.at(1), '12.30');
    await tester.tap(find.text('Planned'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Actual').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Recorded actual expenses · MYR 12.30'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await open();
    expect(find.text('Lunch · MYR 12.30'), findsOneWidget);
    await tester.tap(find.text('Edit budget limit'));
    await tester.pumpAndSettle();
    await tester.enterText(fields, '250.00');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Balance after recorded actuals only · MYR 237.70'), findsOneWidget);
    await tester.tap(find.byTooltip('Delete Lunch'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(api.mutations, hasLength(3));
    await tester.tap(find.byTooltip('Delete Lunch'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(find.text('No expenses recorded.'), findsOneWidget);
    expect(find.text('Recorded actual expenses · MYR 0.00'), findsOneWidget);
  });
}
