import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/budget_comparison_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/budget_breakdown.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/budget_model.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personal_block_editor.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/planning_settings_sheet.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_expenses_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/review_contract.dart';
import 'flexible_planning_test.dart' show PlanningApi, app, reveal;

class ReadApi extends PlanningApi {
  final budgets = <Completer<dynamic>>[];
  final expenses = <Completer<dynamic>>[];
  int budgetReads = 0, expenseReads = 0, patches = 0, revision = 0;
  bool loseSave = false;
  final entries = <Map<String, dynamic>>[];
  Map<String, dynamic> get snapshot => {
        'revision': revision,
        'budgetLimit': 900,
        'startDate': '2027-12-12',
        'endDate': '2027-12-16',
        'expenses': [for (final row in entries) Map<String, dynamic>.from(row)],
        'overview': {
          'budgetLimitMinor': 90000,
          'systemEstimateMinor': 10000,
          'verifiedMinor': 0,
          'plannedMinor': entries.fold<int>(
              0, (sum, row) => sum + (row['amountMinor'] as int)),
          'actualMinor': 0,
          'balanceAfterRecordedActualMinor': 90000,
          'unknownCategories': <String>[]
        },
      };
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path.endsWith('/budget')) {
      final n = budgetReads++;
      return budgets[n].future;
    }
    if (path.endsWith('/expenses')) {
      final n = expenseReads++;
      return n < expenses.length ? expenses[n].future : snapshot;
    }
    return super.get(path, query);
  }

  @override
  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) async {
    expect(body!['expectedRevision'], revision);
    patches++;
    revision++;
    entries.add({
      ...Map<String, dynamic>.from(body['expense']),
      'id': 'isolated-expense',
      'amountMinor': 1230
    });
    if (loseSave) throw TimeoutException('Synthetic lost response');
    return snapshot;
  }
}

Map<String, dynamic> quote(num total) => {
      'ok': true,
      'budget': {'total': total, 'limit': 900, 'activities': total}
    };
BudgetModel get cached => BudgetModel.fromJson(quote(100)['budget']);

Future<void> editorReveal(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(target, 180,
      scrollable: find
          .descendant(
              of: find.byType(PersonalBlockEditor),
              matching: find.byType(Scrollable))
          .first);
  await tester.pump();
}

Future<void> openSettings(WidgetTester tester, PlanningApi api) async {
  await tester.pumpWidget(app(Builder(
      builder: (c) => TextButton(
          onPressed: () => PlanningSettingsSheet.show(c, api, api.trip),
          child: const Text('Open settings')))));
  await tester.tap(find.text('Open settings'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('Daily labels follow the actual overnight flight arrival date',
      (tester) async {
    final api = PlanningApi();
    api.trip['selectedFlight'] = {
      'outboundSegments': [
        {'arrivalDate': '2027-12-13'}
      ],
      'returnSegments': [
        {'departureDate': '2027-12-16'}
      ]
    };
    await openSettings(tester, api);
    await reveal(tester, 'Daily sightseeing windows');
    await tester.tap(find.text('Daily sightseeing windows'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
        find.textContaining(RegExp('Day 2 .*Arrival day')), 180,
        scrollable: find
            .descendant(
                of: find.byType(PlanningSettingsSheet),
                matching: find.byType(Scrollable))
            .first);
    expect(find.textContaining(RegExp('Day 2 .*Arrival day')), findsOneWidget);
    expect(api.posts, isEmpty);
  });

  testWidgets(
      'Editing a block retains notes and flexible status through picker cancellation and validates its time range',
      (tester) async {
    Map<String, dynamic>? result;
    await tester.pumpWidget(app(Builder(
        builder: (c) => TextButton(
            onPressed: () async {
              result = await Navigator.push<Map<String, dynamic>>(
                  c,
                  MaterialPageRoute(
                      builder: (_) =>
                          const PersonalBlockEditor(dayCount: 5, initial: {
                            'blockId': 'existing-personal',
                            'type': 'custom',
                            'label': 'Existing plan',
                            'dayNo': 2,
                            'startTime': '10:00',
                            'endTime': '09:00',
                            'notes': 'Keep these notes',
                            'locked': false,
                            'estimatedCost': 25
                          })));
            },
            child: const Text('Edit block')))));
    await tester.tap(find.text('Edit block'));
    await tester.pumpAndSettle();
    await editorReveal(tester, find.text('Start: 10:00'));
    await tester.tap(find.text('Start: 10:00'));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(of:find.byType(TimePickerDialog),matching:find.text('Cancel')));
    await tester.pumpAndSettle();
    expect(find.text('Start: 10:00'), findsOneWidget);
    await tester.tap(find.text('Save changes'));
    await tester.pumpAndSettle();
    expect(find.text('Choose both times, with the end after the start.'),
        findsOneWidget);
    expect(result, isNull);
    await tester.tap(find.text('Leave unscheduled'));
    await tester.pumpAndSettle();
    await editorReveal(tester, find.text('Optional details'));
    await tester.tap(find.text('Optional details'));
    await tester.pumpAndSettle();
    await editorReveal(tester, find.widgetWithText(TextFormField, 'Notes'));
    expect(
        tester
            .widget<TextFormField>(find.widgetWithText(TextFormField, 'Notes'))
            .controller!
            .text,
        'Keep these notes');
    await editorReveal(tester, find.text('Keep this block fixed'));
    expect(tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
        false);
    await tester.tap(find.text('Save changes'));
    await tester.pumpAndSettle();
    expect(result?['notes'], 'Keep these notes');
    expect(result?['locked'], false);
    expect(result?['estimatedCost'], 25);
    expect(result?.containsKey('startTime'), false);
    expect(result?['durationMinutes'], 60);
    expect(tester.takeException(), isNull);
  });

  test(
      'Snapshot-consuming planning requests carry the same local context as FR4 without changing financial requests',
      () {
    for (final path in [
      '/api/fr4/recommendations/generate',
      '/api/fr5/personalised-trips/generate',
      '/api/fr5/itineraries/owned/flight-adjustment/preview',
      '/api/fr5/itineraries/owned/lower-cost-alternatives'
    ]) {
      expect(localReviewContextHeaders('POST', path),
          {'X-TravelMate-Review-Context': 'fyp-v1'});
    }
    for (final path in [
      '/api/fr9/checkout',
      '/api/fr7/flights/search',
      '/api/fr8/hotels/prebook',
      '/api/fr5/itineraries/owned/expenses'
    ]) {
      expect(localReviewContextHeaders('POST', path), isEmpty);
    }
  });
  testWidgets(
      'Two rapid Budget taps open one loading page without reloading the whole Trip on return',
      (tester) async {
    final api = ReadApi()..budgets.add(Completer());
    await tester
        .pumpWidget(app(TripDetailsScreen(tripId: 'personal-plan', api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Budget details'), 200,
        scrollable: find
            .descendant(
                of: find.byKey(const ValueKey('trip-details-scroll')),
                matching: find.byType(Scrollable))
            .first);
    final button = tester.widget<TertiaryButton>(find.ancestor(
        of: find.text('Budget details'),
        matching: find.byType(TertiaryButton)));
    button.onPressed!();
    button.onPressed!();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(BudgetComparisonScreen), findsOneWidget);
    expect(api.budgetReads, 1);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    api.budgets.single.complete(quote(100));
    await tester.pumpAndSettle();
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(TripDetailsScreen), findsOneWidget);
    expect(api.budgetReads, 1);
  });

  testWidgets(
      'Budget immediately shows cache and progress, deduplicates reads and retries without blanking',
      (tester) async {
    final api = ReadApi()..budgets.addAll([Completer(), Completer()]);
    await tester.pumpWidget(app(BudgetComparisonScreen(
        budget: cached,
        userBudget: 900,
        tripId: 'owned',
        api: api,
        refreshOnOpen: true)));
    await tester.pump();
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(
        tester
            .widget<BudgetBreakdown>(find.byType(BudgetBreakdown))
            .budget
            .totalCost,
        100);
    final refresh = tester
        .widget<IconButton>(find.widgetWithIcon(IconButton, Icons.refresh));
    expect(refresh.onPressed, isNull);
    expect(api.budgetReads, 1);
    api.budgets[0].completeError(TimeoutException('Synthetic timeout'));
    await tester.pumpAndSettle();
    expect(find.text(backendConnectionMessage), findsOneWidget);
    expect(
        tester
            .widget<BudgetBreakdown>(find.byType(BudgetBreakdown))
            .budget
            .totalCost,
        100);
    await tester.tap(find.text('Retry budget'));
    await tester.pump();
    api.budgets[1].complete(quote(120));
    await tester.pumpAndSettle();
    expect(api.budgetReads, 2);
    expect(
        tester
            .widget<BudgetBreakdown>(find.byType(BudgetBreakdown))
            .budget
            .totalCost,
        120);
  });

  testWidgets('Budget discards a prior Trip response and tolerates disposal',
      (tester) async {
    final api = ReadApi()..budgets.addAll([Completer(), Completer()]);
    final loaded = <num>[];
    Widget page(String id) => app(BudgetComparisonScreen(
        key: const ValueKey('same-page'),
        budget: cached,
        userBudget: 900,
        tripId: id,
        api: api,
        refreshOnOpen: true,
        onBudgetLoaded: (b) => loaded.add(b['total'])));
    await tester.pumpWidget(page('first'));
    await tester.pump();
    await tester.pumpWidget(page('second'));
    await tester.pump();
    api.budgets[1].complete(quote(222));
    await tester.pumpAndSettle();
    api.budgets[0].complete(quote(111));
    await tester.pumpAndSettle();
    expect(loaded, [222]);
    expect(
        tester
            .widget<BudgetBreakdown>(find.byType(BudgetBreakdown))
            .budget
            .totalCost,
        222);
    await tester.pumpWidget(const MaterialApp(home: Scaffold()));
    expect(tester.takeException(), isNull);
  });

  for (final failure in [
    TimeoutException('Synthetic disconnect'),
    const ApiException('Unavailable', 503, {}),
    const ApiException('Sign in again', 401, {})
  ]) {
    testWidgets(
        'Expenses retains cache and distinguishes ${failure.runtimeType} while explicit retry recovers',
        (tester) async {
      final api = ReadApi()
        ..entries.add({
          'id': 'existing',
          'name': 'Existing lunch',
          'category': 'Food',
          'type': 'planned',
          'amountMinor': 1000
        })
        ..expenses.addAll([Completer(), Completer()]);
      await tester.pumpWidget(app(TripExpensesScreen(
          tripId: 'owned', api: api, initialData: api.snapshot)));
      await tester.pump();
      expect(find.text('Existing lunch · MYR 10.00'), findsOneWidget);
      expect(api.expenseReads, 1);
      expect(
          tester
              .widget<IconButton>(
                  find.widgetWithIcon(IconButton, Icons.refresh))
              .onPressed,
          isNull);
      api.expenses[0].completeError(failure);
      await tester.pumpAndSettle();
      expect(find.text('Existing lunch · MYR 10.00'), findsOneWidget);
      expect(find.text(userFacingApiError(failure)), findsOneWidget);
      await tester.tap(find.text('Retry refresh'));
      await tester.pump();
      api.expenses[1].complete(api.snapshot);
      await tester.pumpAndSettle();
      expect(api.expenseReads, 2);
      expect(find.text(userFacingApiError(failure)), findsNothing);
    });
  }

  testWidgets(
      'Expenses never replays a committed PATCH after its response is lost',
      (tester) async {
    final api = ReadApi()..loseSave = true;
    await tester.pumpWidget(app(TripExpensesScreen(tripId: 'owned', api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Add expense'));
    await tester.pumpAndSettle();
    final fields = find.descendant(
        of: find.byType(AlertDialog), matching: find.byType(TextFormField));
    await tester.enterText(fields.at(0), 'New lunch');
    await tester.enterText(fields.at(1), '12.30');
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();
    expect(api.patches, 1);
    expect(find.textContaining('save result is unconfirmed'), findsOneWidget);
    await tester.pump(const Duration(seconds: 2));
    expect(api.patches, 1);
    await tester.tap(find.text('Retry refresh'));
    await tester.pumpAndSettle();
    expect(find.text('New lunch · MYR 12.30'), findsOneWidget);
    expect(api.patches, 1);
  });

  testWidgets(
      'Bulk hours changes only confirmed selected days and preserves excluded override',
      (tester) async {
    final api = PlanningApi();
    api.trip['travelDayPreferences'] = {
      'days': [
        {'dayNo': 3, 'restDay': true}
      ]
    };
    await openSettings(tester, api);
    await reveal(tester, 'Daily sightseeing windows');
    await tester.tap(find.text('Daily sightseeing windows'));
    await tester.pumpAndSettle();
    await reveal(tester, 'Set hours for multiple days');
    await tester.tap(find.text('Set hours for multiple days'));
    await tester.pumpAndSettle();
    expect(find.text('Apply to middle days'), findsNothing);
    final checkbox = find.ancestor(
        of: find.descendant(
            of: find.byType(AlertDialog),
            matching: find.textContaining('Day 3 ·')),
        matching: find.byType(CheckboxListTile));
    await tester.ensureVisible(checkbox);
    await tester.tap(checkbox);
    await tester.pump();
    await tester.tap(find.text('Apply to draft'));
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    await reveal(tester, 'Preview planning changes');
    await tester.tap(find.text('Preview planning changes'));
    await tester.pumpAndSettle();
    final days = api.changes['travelDayPreferences']['days'] as List;
    expect(days.map((r) => r['dayNo']).toSet(), {2, 3, 4});
    expect(
        days.firstWhere((r) => r['dayNo'] == 3), {'dayNo': 3, 'restDay': true});
    for (final n in [2, 4]) {
      expect(days.firstWhere((r) => r['dayNo'] == n)['startTime'], '09:00');
    }
    expect(api.applies, 0);
    await tester.tap(find.widgetWithIcon(IconButton, Icons.close_rounded));
    await tester.pumpAndSettle();
    expect(api.applies, 0);
  });

  for (final selection in [
    <int>{2},
    <int>{3},
    <int>{2, 3, 4},
    <int>{1, 5}
  ]) {
    testWidgets(
        'Bulk draft ${selection.join(',')} survives explicit apply and reopening',
        (tester) async {
      final api = PlanningApi();
      await openSettings(tester, api);
      await reveal(tester, 'Daily sightseeing windows');
      await tester.tap(find.text('Daily sightseeing windows'));
      await tester.pumpAndSettle();
      await reveal(tester, 'Set hours for multiple days');
      await tester.tap(find.text('Set hours for multiple days'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Clear selection'));
      await tester.pump();
      for (final n in selection) {
        final day = find.ancestor(
            of: find.descendant(
                of: find.byType(AlertDialog),
                matching: find.textContaining('Day $n ·')),
            matching: find.byType(CheckboxListTile));
        await tester.ensureVisible(day);
        await tester.tap(day);
        await tester.pump();
      }
      await tester.tap(find.text('Apply to draft'));
      await tester.pumpAndSettle();
      expect(api.posts, isEmpty);
      await reveal(tester, 'Preview planning changes');
      await tester.tap(find.text('Preview planning changes'));
      await tester.pumpAndSettle();
      expect(
          (api.changes['travelDayPreferences']['days'] as List)
              .map((d) => d['dayNo'])
              .toSet(),
          selection);
      expect(api.applies, 0);
      await tester
          .tap(find.byKey(const ValueKey('apply-flight-adjustment-btn')));
      await tester.pumpAndSettle();
      expect(api.applies, 1);
      await tester.tap(find.text('Open settings'));
      await tester.pumpAndSettle();
      expect(find.byType(PlanningSettingsSheet), findsOneWidget);
      expect(
          (api.trip['travelDayPreferences']['days'] as List)
              .map((d) => d['dayNo'])
              .toSet(),
          selection);
    });
  }

  testWidgets(
      'A rest day can be switched off in the draft without creating or saving activities',
      (tester) async {
    final api = PlanningApi();
    api.trip['travelDayPreferences'] = {
      'days': [
        {'dayNo': 3, 'restDay': true}
      ]
    };
    await openSettings(tester, api);
    await reveal(tester, 'Daily sightseeing windows');
    await tester.tap(find.text('Daily sightseeing windows'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('rest-day-3')), 180,
        scrollable: find
            .descendant(
                of: find.byType(PlanningSettingsSheet),
                matching: find.byType(Scrollable))
            .first);
    await tester.ensureVisible(find.byKey(const ValueKey('rest-day-3')));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<SwitchListTile>(find.byKey(const ValueKey('rest-day-3')))
            .value,
        true);
    await tester.tap(find.byKey(const ValueKey('rest-day-3')).hitTestable());
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    expect(
        tester
            .widget<SwitchListTile>(find.byKey(const ValueKey('rest-day-3')))
            .value,
        false);
    await reveal(tester, 'Preview planning changes');
    await tester.tap(find.text('Preview planning changes'));
    await tester.pumpAndSettle();
    expect(
        (api.changes['travelDayPreferences']['days'] as List).single['restDay'],
        false);
    expect(api.applies, 0);
  });

  for (final width in [320.0, 360.0, 390.0]) {
    testWidgets(
        'Personal editor validates local draft at $width dp with large text and keyboard',
        (tester) async {
      tester.view.physicalSize = Size(width, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetViewInsets);
      Map<String, dynamic>? result;
      await tester.pumpWidget(app(
          Builder(
              builder: (c) => TextButton(
                  onPressed: () async {
                    result = await Navigator.push<Map<String, dynamic>>(
                        c,
                        MaterialPageRoute(
                            builder: (_) => const PersonalBlockEditor(
                                dayCount: 5, initialDay: 3)));
                  },
                  child: const Text('Open editor'))),
          scale: 1.6));
      await tester.tap(find.text('Open editor'));
      await tester.pumpAndSettle();
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Title'), 'Personal rest');
      await editorReveal(tester,
          find.widgetWithText(TextFormField, 'Duration estimate (minutes)'));
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Duration estimate (minutes)'),
          '0');
      tester.view.viewInsets = const FakeViewPadding(bottom: 240);
      await tester.pumpAndSettle();
      expect(find.text('Add to preview').hitTestable(), findsOneWidget);
      await tester.tap(find.text('Add to preview'));
      await tester.pumpAndSettle();
      expect(find.text('Choose 1–1440 minutes.'), findsOneWidget);
      await tester.enterText(
          find.widgetWithText(TextFormField, 'Duration estimate (minutes)'),
          '60');
      await editorReveal(tester, find.text('Optional details'));
      await tester.tap(find.text('Optional details'));
      await tester.pumpAndSettle();
      final cost =
          find.widgetWithText(TextFormField, 'Estimated cost (RM) — Optional');
      await editorReveal(tester, cost);
      await tester.enterText(cost, '-1');
      await tester.tap(find.text('Add to preview'));
      await tester.pumpAndSettle();
      expect(result, isNull);
      expect(
          find.textContaining('Enter a non-negative estimate'), findsOneWidget);
      await tester.enterText(cost, '');
      await tester.tap(find.text('Add to preview'));
      await tester.pumpAndSettle();
      expect(result?['dayNo'], 3);
      expect(result?.containsKey('estimatedCost'), isFalse);
      expect(result?['locked'], true);
      expect(tester.takeException(), isNull);
    });
  }
}
