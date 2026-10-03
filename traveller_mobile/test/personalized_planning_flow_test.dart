import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

Map<String, dynamic> _plannedTrip(String id) => {
      'id': id,
      'title': 'My Personalised Penang Trip',
      'destinationArea': 'Penang, Malaysia',
      'startDate': '2026-11-01',
      'endDate': '2026-11-03',
      'tripDays': 3,
      'status': 'planned',
      'recommendationGenerationId': 'rec_widget_1',
      'activities': <Map<String, dynamic>>[],
      'budgetEstimate': {
        'total': 450,
        'limit': 1200,
        'status': 'Within budget',
        'comparison': 'Within budget',
      },
      'generationContext': {
        'recommendationGenerationId': 'rec_widget_1',
        'destinationSource': 'cache',
        'weatherConsideration': true,
      },
    };

class _FakeApiService extends ApiService {
  final Completer<dynamic>? recommendationGate;
  int recommendationCalls = 0;
  int generationCalls = 0;
  int regenerationCalls = 0;
  Map<String, dynamic>? lastRegenerationBody;
  final Map<String, dynamic> trip = _plannedTrip('trip_exact_123');

  _FakeApiService({this.recommendationGate});

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr4/recommendations/generate') {
      recommendationCalls += 1;
      if (recommendationGate != null) await recommendationGate!.future;
      return {
        'ok': true,
        'recommendationGenerationId': 'rec_widget_1',
        'recommendations': [
          {'destinationId': 'penang_hill', 'title': 'Penang Hill'}
        ],
      };
    }
    if (path == '/api/fr5/personalised-trips/generate') {
      generationCalls += 1;
      return {
        'ok': true,
        'id': trip['id'],
        'tripId': trip['id'],
        'status': 'planned',
        'itinerary': trip,
      };
    }
    if (path == '/api/fr5/itineraries/trip_exact_123/generate') {
      regenerationCalls += 1;
      lastRegenerationBody = Map<String, dynamic>.from(body ?? const {});
      trip
        ..['status'] = 'planned'
        ..['retryable'] = false
        ..remove('lastGenerationError')
        ..remove('generationFailureStage');
      return {'ok': true, 'status': 'planned', 'itinerary': trip};
    }
    throw StateError('Unexpected POST $path');
  }

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries') {
      return {
        'ok': true,
        'items': [trip],
      };
    }
    throw StateError('Unexpected GET $path');
  }
}

void main() {
  testWidgets('success opens Trip Details for the exact generated trip ID',
      (tester) async {
    final api = _FakeApiService();
    await tester.pumpWidget(MaterialApp(
      home: PersonalizedPlanningScreen(api: api),
    ));

    await tester.tap(find.text('Generate personalised trip'));
    await tester.pumpAndSettle();

    final details = tester.widget<TripDetailsScreen>(
      find.byType(TripDetailsScreen),
    );
    expect(details.tripId, 'trip_exact_123');
    expect(api.recommendationCalls, 1);
    expect(api.generationCalls, 1);
  });

  testWidgets('repeated Generate taps do not submit duplicate trips',
      (tester) async {
    final gate = Completer<dynamic>();
    final api = _FakeApiService(recommendationGate: gate);
    await tester.pumpWidget(MaterialApp(
      home: PersonalizedPlanningScreen(api: api),
    ));

    await tester.tap(find.text('Generate personalised trip'));
    await tester.pump();
    expect(find.text('Building your plan...'), findsOneWidget);

    await tester.tap(find.text('Building your plan...'), warnIfMissed: false);
    await tester.pump();
    expect(api.recommendationCalls, 1);
    expect(api.generationCalls, 0);

    gate.complete();
    await tester.pumpAndSettle();
    expect(api.recommendationCalls, 1);
    expect(api.generationCalls, 1);
  });

  testWidgets(
      'failed Trip Details is visible and retries with its stored snapshot ID',
      (tester) async {
    final api = _FakeApiService();
    api.trip
      ..['status'] = 'generation_failed'
      ..['retryable'] = true
      ..['generationFailureStage'] = 'budget_calculation'
      ..['lastGenerationError'] = 'Budget calculation failed';
    await tester.pumpWidget(MaterialApp(
      home: TripDetailsScreen(tripId: 'trip_exact_123', api: api),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Trip generation did not finish'), findsOneWidget);
    expect(find.text('Budget calculation failed'), findsOneWidget);
    await tester.tap(find.text('Retry generation'));
    await tester.pumpAndSettle();

    expect(api.regenerationCalls, 1);
    expect(api.lastRegenerationBody?['recommendationGenerationId'],
        'rec_widget_1');
    expect(find.text('generation failed'), findsNothing);
    expect(find.text('planned'), findsOneWidget);
  });
}
