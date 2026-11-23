import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/planning_settings_sheet.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personal_block_editor.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/budget_model.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/budget_breakdown.dart';

class PlanningApi extends ApiService {
  final posts = <Map<String, dynamic>>[];
  int recommendationReads = 0, creates = 0, applies = 0;
  bool loseFirstCreationResponse = false;
  Map<String, dynamic> trip = {
    'id': 'personal-plan',
    'title': 'A long personal Penang itinerary with heritage and relaxing days',
    'destinationArea': 'Penang, Malaysia',
    'startDate': '2027-12-12',
    'endDate': '2027-12-16',
    'tripDays': 5,
    'travellerCount': 2,
    'budgetLimit': 900,
    'status': 'planned',
    'planningMode': 'assisted',
    'itineraryRevision': 1,
    'activities': <Map<String, dynamic>>[],
    'dailySchedule': [
      for (var n = 1; n <= 5; n++)
        {
          'dayNo': n,
          'dayDate': '2027-12-${11 + n}',
          'activities': <Map<String, dynamic>>[],
          'planningWindow': {'startTime': '09:00', 'endTime': '18:00'},
          'planningBlocks': <Map<String, dynamic>>[]
        }
    ],
    'budgetEstimate': {'total': 400, 'limit': 900, 'personalPlans': 0},
  };
  Map<String, dynamic> changes = {};
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path.startsWith('/api/fr4/')) {
      recommendationReads++;
      return {
        'ok': true,
        'recommendationGenerationId': 'owned-saved-generation',
        'recommendationResults': []
      };
    }
    if (path == '/api/fr2/preferences')
      return {
        'ok': true,
        'preferences': {
          'interests': ['Culture'],
          'travelPace': 'moderate'
        }
      };
    if (path == '/api/fr5/itineraries')
      return {
        'ok': true,
        'items': [trip]
      };
    return {
      'ok': true,
      'itinerary': trip,
      'planning': {
        'availability': {'days': {}, 'confirmationStatus': 'provisional'}
      }
    };
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posts.add({'path': path, 'body': body});
    if (path == '/api/fr5/itineraries') {
      if (creates == 0) {
        creates++;
        trip = {...trip, ...body!};
      }
      if (loseFirstCreationResponse) {
        loseFirstCreationResponse = false;
        throw ApiException('Unknown result', 503, {});
      }
      return {'ok': true, 'id': trip['id'], 'itinerary': trip};
    }
    if (path.endsWith('/preview')) {
      changes = Map<String, dynamic>.from(body?['planningChanges'] ?? {});
      return {
        'ok': true,
        'preview': {
          'previewId': 'owned-preview',
          'kind': 'planning',
          'canApply': true,
          'status': 'ready',
          'before': trip,
          'after': {...trip, ...changes},
          'changes': [],
          'newlyUnscheduled': [],
          'remainingConflicts': [],
          'availability': {'days': {}},
          'boundaries': {},
          'assumptions': {},
          'budgetBefore': {'total': 400},
          'budgetAfter': {'total': 410},
          'scope': body?['scope'] ?? 'full'
        }
      };
    }
    if (path.endsWith('/apply')) {
      applies++;
      trip = {...trip, ...changes};
      return {'ok': true, 'itinerary': trip};
    }
    throw StateError('Unexpected mocked operation: $path');
  }
}

Widget app(Widget child, {double scale = 1}) => MaterialApp(
    theme: buildInkWashTheme(),
    builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(scale)),
        child: child!),
    home: Scaffold(body: child));

Future<void> reveal(WidgetTester tester, String text, {double delta = 180}) async {
  final list = find.byType(PersonalBlockEditor).evaluate().isNotEmpty
      ? find.descendant(of:find.byType(PersonalBlockEditor),matching:find.byType(ListView)).first
      : find.byType(PlanningSettingsSheet).evaluate().isNotEmpty
      ? find
          .descendant(
              of: find.byType(PlanningSettingsSheet),
              matching: find.byType(ListView))
          .first
      : find.byType(ListView).first;
  final scrollable =
      find.descendant(of: list, matching: find.byType(Scrollable)).first;
  await tester.scrollUntilVisible(find.text(text), delta, scrollable: scrollable);
  await tester.pump();
}

void main() {
  for (final mode in ['manual', 'assisted']) {
    testWidgets(
        '$mode creates an empty trip without recommendation or provider dependency',
        (tester) async {
      final api = PlanningApi();
      await tester.pumpWidget(
          app(PersonalizedPlanningScreen(api: api, initialPlanningMode: mode)));
      await tester.pumpAndSettle();
      await reveal(tester, 'Create editable trip');
      await tester.tap(find.text('Create editable trip'));
      await tester.pumpAndSettle();
      expect(api.recommendationReads, 0);
      expect(api.creates, 1);
      final request = api.posts.single['body'] as Map;
      expect(request['planningMode'], mode);
      expect(request['activities'], isEmpty);
      expect(request.containsKey('recommendationGenerationId'), isFalse);
      expect(find.byType(TripDetailsScreen), findsOneWidget);
      expect(api.applies, 0);
    });
  }

  testWidgets('unknown creation result keeps the same intent on explicit retry',
      (tester) async {
    final api = PlanningApi()..loseFirstCreationResponse = true;
    await tester.pumpWidget(app(
        PersonalizedPlanningScreen(api: api, initialPlanningMode: 'manual')));
    await tester.pumpAndSettle();
    await reveal(tester, 'Create editable trip');
    await tester.tap(find.text('Create editable trip'));
    await tester.pumpAndSettle();
    await reveal(tester, 'Retry this trip');
    await tester.tap(find.text('Retry this trip'));
    await tester.pumpAndSettle();
    expect(api.creates, 1);
    final calls = api.posts
        .where((row) => row['path'] == '/api/fr5/itineraries')
        .toList();
    expect(calls.length, 2);
    expect(calls.first['body']['generationRequestId'],
        calls.last['body']['generationRequestId']);
    expect(find.byType(TripDetailsScreen), findsOneWidget);
  });

  testWidgets(
      'Travel Preferences preview never switches planning mode or saves automatically',
      (tester) async {
    final api = PlanningApi();
    await tester
        .pumpWidget(app(PlanningSettingsSheet(trip: api.trip, api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Planning style'), findsNothing);
    await reveal(tester, 'Preview planning changes');
    await tester.tap(find.text('Preview planning changes'));
    await tester.pumpAndSettle();
    expect(api.changes.containsKey('planningMode'), isFalse);
    expect(api.applies, 0);
    expect(find.text('Review planning changes'), findsOneWidget);
    await tester.tap(find.widgetWithIcon(IconButton, Icons.close_rounded));
    await tester.pumpAndSettle();
    expect(api.applies, 0);
    expect(api.trip['planningMode'], 'assisted');
  });

  testWidgets(
      'arrival choice uses a real time picker and survives picker cancellation',
      (tester) async {
    final api = PlanningApi();
    await tester
        .pumpWidget(app(PlanningSettingsSheet(trip: api.trip, api: api)));
    await tester.pumpAndSettle();
    await reveal(tester, 'Arrival day');
    await tester.tap(find
        .ancestor(
            of: find.text('Arrival day'),
            matching: find.byType(DropdownButtonFormField<String>))
        .first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Rest / hotel / luggage first').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sightseeing starts: Choose time'));
    await tester.pumpAndSettle();
    expect(find.byType(TimePickerDialog), findsOneWidget);
    await tester.tap(find.text('Cancel').last);
    await tester.pumpAndSettle();
    expect(find.text('Rest / hotel / luggage first'), findsOneWidget);
    expect(api.posts, isEmpty);
  });

  testWidgets('personal block stays local until preview then explicit apply',
      (tester) async {
    final api = PlanningApi();
    await tester.pumpWidget(app(Builder(builder:(c)=>TextButton(onPressed:()=>PlanningSettingsSheet.show(c,api,api.trip,initialBlockType:'rest',initialDay:3),child:const Text('Open personal planning')))));
    await tester.tap(find.text('Open personal planning'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextFormField, 'Title'),
        'Personal rest before the evening walk');
    await tester.testTextInput.receiveAction(TextInputAction.done);await tester.pumpAndSettle();
    await reveal(tester,'Optional details');await tester.tap(find.text('Optional details'));await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.widgetWithText(TextFormField, 'Estimated cost (RM) — Optional'),180,
      scrollable:find.descendant(of:find.byType(PersonalBlockEditor),matching:find.byType(Scrollable)).first);
    await tester.enterText(
        find.widgetWithText(TextFormField, 'Estimated cost (RM) — Optional'),
        '10');
    await tester.tap(find.text('Add to preview'));
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    await reveal(tester, 'Preview planning changes');
    await tester.tap(find.text('Preview planning changes'));
    await tester.pumpAndSettle();
    final blocks = api.changes['planningBlocks'] as List;
    expect(blocks.single['dayNo'], 3);
    expect(blocks.single['estimatedCost'], 10);
    expect(blocks.single.containsKey('bookingId'), isFalse);
    expect(api.applies, 0);
    await tester.tap(find.byKey(const ValueKey('apply-flight-adjustment-btn')));
    await tester.pumpAndSettle();
    expect(api.applies, 1);
    expect((api.trip['planningBlocks'] as List).length, 1);
  });

  for (final width in [320.0, 360.0, 390.0]) {
    testWidgets('planning controls wrap on ${width}dp with larger text',
        (tester) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = PlanningApi();
      await tester.pumpWidget(
          app(PlanningSettingsSheet(trip: api.trip, api: api), scale: 1.6));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await reveal(tester, 'Daily sightseeing windows');
      await tester.tap(find.text('Daily sightseeing windows'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.textContaining('Day 5 ·'),180,scrollable:find.descendant(of:find.byType(PlanningSettingsSheet),matching:find.byType(Scrollable)).first);
      expect(tester.takeException(), isNull);
      await reveal(tester, 'Preview planning changes');
      expect(find.text('Preview planning changes'), findsOneWidget);
      expect(api.applies, 0);
    });
  }

  testWidgets(
      'personal estimates appear once in the authoritative budget breakdown',
      (tester) async {
    final model = BudgetModel.fromJson({
      'total': 425,
      'knownEstimatedSubtotal': 425,
      'personalPlans': 25,
      'categoryTotals': {'food': 400, 'personalPlans': 25},
      'expenseBreakdown': {
        'personalPlans': {
          'amount': 25,
          'state': 'unverified_estimate',
          'provenance': 'user_estimate'
        }
      }
    });
    await tester.pumpWidget(app(Scaffold(
        body: SingleChildScrollView(
            child: BudgetBreakdown(budget: model, limit: 900)))));
    await tester.pumpAndSettle();
    expect(model.totalCost, 425);
    expect(model.personalPlans, 25);
    expect(find.text('Personal planning estimates'), findsOneWidget);
  });

  for (final width in [320.0, 360.0, 390.0]) {
    testWidgets(
        'ten-day trip and personal planning entry remain usable at ${width}dp',
        (tester) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = PlanningApi();
      api.trip['endDate'] = '2027-12-21';
      api.trip['tripDays'] = 10;
      api.trip['dailySchedule'] = [
        for (var n = 1; n <= 10; n++)
          {
            'dayNo': n,
            'dayDate': '2027-12-${11 + n}',
            'activities': <Map<String, dynamic>>[],
            'planningBlocks': <Map<String, dynamic>>[]
          }
      ];
      await tester.pumpWidget(app(
          TripDetailsScreen(tripId: 'personal-plan', api: api),
          scale: 1.6));
      await tester.pumpAndSettle();
      await reveal(tester, 'Travel Preferences');
      await tester.tap(find.text('Travel Preferences'));
      await tester.pumpAndSettle();
      await reveal(tester, 'Daily sightseeing windows');
      await tester.tap(find.text('Daily sightseeing windows'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.textContaining('Day 10 ·'),180,scrollable:find.descendant(of:find.byType(PlanningSettingsSheet),matching:find.byType(Scrollable)).first);
      expect(tester.takeException(), isNull);
      expect(api.posts, isEmpty);
    });
  }
}
