import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/constraint_itinerary_planner.dart';
import 'package:travelmate_traveller/core/utils/itinerary_identity.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/activity_payload_helper.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/alternative_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/budget_model.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';

class _LocalApi extends ApiService {
  final StandaloneApiService service;
  final calls = <String>[];
  final requests = <Map<String, dynamic>>[];
  _LocalApi(this.service);

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) =>
      service.get(path, query);

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    calls.add(path);
    requests.add({...?body});
    return service.post(path, body);
  }
}

Map<String, dynamic> _visit(
        String id, String destination, String name, int day) =>
    {
      'activityId': id,
      'destinationId': destination,
      'activityName': name,
      'dayNo': day,
      'address': 'Air Itam, Penang, Malaysia',
      'estimatedCost': 25,
      'unitPrice': 25,
      'pricingUnit': 'per_person',
      'costProvenance': 'catalog_estimate',
      'recommendedDurationMinutes': 45,
      'gps_coordinates': {'latitude': 5.4244, 'longitude': 100.2684},
    };

_LocalApi _api() {
  final trip = planConstraintAwareItinerary({
    'id': 'f2',
    'travellerId': 'fixture',
    'attractionIdentityPolicy': attractionIdentityPolicy,
    'title': 'Penang visit',
    'destinationArea': 'Penang',
    'status': 'planned',
    'startDate': '2027-01-10',
    'endDate': '2027-01-12',
    'travellerCount': 1,
    'budgetLimit': 200,
    'foodCost': 180,
    'transportCost': 80,
    'paidTotal': 146.18,
    'paymentRecordId': 'existing-payment',
    'activities': [_visit('A1', 'summit', 'Penang Hill', 1)],
  }, preserveOrder: true, respectDayAssignments: true);
  final memory = {
    'travelmate_fixture_itineraries': jsonEncode([trip])
  };
  return _LocalApi(
      StandaloneApiService(uidOverride: 'fixture', memoryStore: memory));
}

const path = '/api/fr5/itineraries/f2';

void main() {
  test('standalone tourism recommendations exclude service buildings before ranking', () async {
    const fixtures = [
      {'destinationId': 'service-office', 'title': 'Pejabat Imigresen', 'type': 'Government office',
       'address': 'George Town, Penang, Malaysia'},
      {'destinationId': 'gallery', 'title': 'City heritage gallery', 'type': 'Gallery',
       'types': ['Gallery', 'government office'], 'address': 'George Town, Penang, Malaysia'},
    ];
    final service = StandaloneApiService(uidOverride: 'fixture', memoryStore: {
      'travelmate_fixture_preferences': jsonEncode({'interests': ['Culture']}),
      'travelmate_fixture_last_search_results': jsonEncode(fixtures),
    });
    final generated = await service.post('/api/fr4/recommendations/generate',
      {'destinationArea': 'Penang', 'limit': 50});
    expect(generated['ok'], true);
    final ids = (generated['recommendations'] as List).cast<Map>()
        .map((row) => row['destinationId']);
    expect(ids, contains('gallery'));
    expect(ids, isNot(contains('service-office')));
  });

  for (final day in [1, 2, 3, 5]) {
    test(
        'trip-wide planner validates Day $day and unscheduled occurrences together',
        () {
      final view = {
        ..._visit('A3', 'view', 'Penang Hill Viewing Area', day),
        'independentSubAttraction': true
      };
      final planner = planConstraintAwareItinerary({
        'attractionIdentityPolicy': attractionIdentityPolicy,
        'travellerCount': 2,
        'startDate': '2027-01-10',
        'endDate': '2027-01-14',
        'activities': [_visit('A1', 'summit', 'Penang Hill', 1)],
        'unscheduledSuggestions': [
          _visit('A2', 'alias', 'Bukit Bendera', day),
          view
        ],
      }, preserveOrder: true, respectDayAssignments: true);
      final activities = (planner['activities'] as List).cast<Map>();
      expect(activities.map((row) => row['activityId']).toSet(), {'A1', 'A3'});
      expect(
          (planner['dailySchedule'] as List)
              .fold<num>(0, (sum, row) => sum + (row['estimatedCost'] as num)),
          100);
      expect(planner['unscheduledSuggestions'], isEmpty);
    });
  }

  testWidgets(
      'manual repeat prompts, cancel writes nothing, then confirmation persists exactly once',
      (tester) async {
    final api = _api();
    final payload = _visit('client-supplied-id', 'alt', 'Bukit Bendera', 3);
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Builder(
      builder: (context) => TextButton(
        onPressed: () async {
          await addTripVisit(context, api, 'f2', payload);
        },
        child: const Text('Add place'),
      ),
    ))));
    await tester.tap(find.text('Add place'));
    await tester.pumpAndSettle();
    expect(find.text('Visit this place again?'), findsOneWidget);
    expect(find.textContaining('already included in your itinerary on Day 1'),
        findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(api.calls.length, 1);
    expect((await api.service.get(path))['itinerary']['activities'].length, 1);
    await tester.tap(find.text('Add place'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Add another visit'));
    await tester.pumpAndSettle();
    final visits =
        ((await api.service.get(path))['itinerary']['activities'] as List)
            .cast<Map>();
    expect(visits.map((row) => row['dayNo']), [1, 3]);
    expect(visits.map((row) => row['activityId']).toSet(), {'A1', 'A2'});
    expect(visits.last['intentionalRepeat'], true);
    expect(visits.last['canonicalAttractionId'], 'summit');
    final savedRequest = api.requests.last;
    expect(savedRequest['clientRequestId'], api.requests[1]['clientRequestId']);
    final retry = await api.service.post('$path/activities', savedRequest);
    expect(retry['alreadyAdded'], true);
    expect((await api.service.get(path))['itinerary']['activities'].length, 2);
  });

  testWidgets('same-day alias add is blocked without a revisit confirmation', (tester) async {
    final api = _api();
    final payload = _visit('not-trusted', 'other-pin', 'Bukit Bendera', 1);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: Builder(
      builder: (context) => TextButton(
        onPressed: () async {
          try {
            await addTripVisit(context, api, 'f2', payload);
          } on ApiException catch (error) {
            expect(error.code, 'duplicate_attraction_day');
            expect(error.message, contains('already included on Day 1'));
          }
        },
        child: const Text('Add place'),
      ),
    ))));
    await tester.tap(find.text('Add place'));
    await tester.pumpAndSettle();
    expect(api.calls.length, 1);
    expect(find.text('Visit this place again?'), findsNothing);
    expect((await api.service.get(path))['itinerary']['activities'].length, 1);
  });

  testWidgets(
      'activity-only overrun has a budget preview, cancel and confirmed save',
      (tester) async {
    final api = _api();
    await tester.pumpWidget(MaterialApp(
        home: AlternativeScreen(
      budget: BudgetModel.fromJson({'total': 285, 'limit': 200}),
      userBudget: 200,
      tripId: 'f2',
      api: api,
    )));
    await tester.pumpAndSettle();
    expect(
        find.textContaining('Choose a lower-cost room option'), findsNothing);
    await tester.tap(find.text('Review budget options'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, '110');
    await tester.enterText(find.byType(TextField).last, '65');
    await tester.tap(find.text('Preview revised budget'));
    await tester.pumpAndSettle();
    expect(find.text('Previous estimate: RM 285.00'), findsOneWidget);
    expect(find.text('Revised estimate: RM 200.00'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(api.calls.where((value) => value.endsWith('/apply')), isEmpty);
    expect((await api.service.get(path))['itinerary']['foodCost'], 180);
    await tester.tap(find.text('Preview revised budget'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm budget changes'));
    await tester.pumpAndSettle();
    final saved = (await api.service.get(path))['itinerary'];
    expect(saved['foodCost'], 110);
    expect(saved['transportCost'], 65);
    expect(saved['paidTotal'], 146.18);
    expect(saved['paymentRecordId'], 'existing-payment');
    expect(saved['budgetEstimate']['total'], 200);
    expect(saved['activities'].length, 1);
  });
}
