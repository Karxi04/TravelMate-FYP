import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_expenses_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _ExpenseApi extends ApiService {
  final List<Map<String, dynamic>> mutations = [];
  Map<String, dynamic>? expense;
  int limit = 30000;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries') {
      return {'items': [
        {'id': 'owned-trip', 'title': 'Penang plan', 'status': 'planned',
         'startDate': '2026-12-10', 'endDate': '2026-12-12', 'destinationArea': 'Penang',
         'budgetLimit': limit / 100, 'activities': <Object>[]},
      ]};
    }
    expect(path, '/api/fr5/itineraries/owned-trip/expenses');
    final actual = expense?['type'] == 'actual' ? expense!['amountMinor'] as int : 0;
    final planned = expense?['type'] == 'planned' ? expense!['amountMinor'] as int : 0;
    return {
      'revision': mutations.length,
      'budgetLimit': limit / 100,
      'startDate': '2026-12-10',
      'endDate': '2026-12-12',
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
  testWidgets('narrow expense form validates with the keyboard open and limits trip dates', (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 1.6;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    addTearDown(tester.view.resetViewInsets);
    final api = _ExpenseApi();
    await tester.pumpWidget(MaterialApp(home: TripExpensesScreen(tripId: 'owned-trip', api: api)));
    await tester.pumpAndSettle();
    final add = find.text('Add expense');
    await tester.scrollUntilVisible(add, 200);
    await tester.ensureVisible(add);
    await tester.tap(add.hitTestable());
    await tester.pumpAndSettle();
    final dialog = find.byType(AlertDialog);
    final fields = find.descendant(of: dialog, matching: find.byType(TextFormField));
    await tester.enterText(fields.at(0), 'Lunch');
    await tester.enterText(fields.at(1), '12.345');
    tester.view.viewInsets = const FakeViewPadding(bottom: 240);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Save').hitTestable());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(api.mutations, isEmpty);
    tester.view.resetViewInsets();
    await tester.pumpAndSettle();
    final date = fields.last;
    await tester.ensureVisible(date);
    await tester.tap(date.hitTestable());
    await tester.pumpAndSettle();
    final picker = tester.widget<DatePickerDialog>(find.byType(DatePickerDialog));
    expect(picker.firstDate, DateTime(2026, 12, 10));
    expect(picker.lastDate, DateTime(2026, 12, 12));
    expect(tester.takeException(), isNull);
  });

  testWidgets('Trip Details displays existing expenses and refreshes after an edit', (tester) async {
    tester.view.physicalSize = const Size(800, 1500);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _ExpenseApi()..expense = {
      'id': 'expense-1', 'name': 'Lunch', 'category': 'Food', 'type': 'planned',
      'amountMinor': 1525,
    };
    await tester.pumpWidget(MaterialApp(home: TripDetailsScreen(tripId: 'owned-trip', api: api)));
    await tester.pumpAndSettle();
    final manage = find.text('Manage trip expenses');
    await tester.scrollUntilVisible(manage, 280, scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(manage);
    expect(find.text('Planned expenses · MYR 15.25'), findsOneWidget);
    expect(find.text('Recorded actual expenses · MYR 0.00'), findsOneWidget);
    expect(find.text('Within recorded budget'), findsNothing);
    await tester.tap(manage.hitTestable());
    await tester.pumpAndSettle();
    await tester.tap(find.text('Lunch · MYR 15.25'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField).at(1), '315.25');
    await tester.tap(find.text('Planned'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Actual').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Recorded actual expenses · MYR 315.25'), findsOneWidget);
    expect(find.text('Planned expenses · MYR 0.00'), findsOneWidget);
    expect(find.text('Lunch · Actual · MYR 315.25'), findsOneWidget);
    expect(find.text('Over budget'), findsOneWidget);
    expect(api.mutations, hasLength(1));
  });

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
