import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

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

Map<String, dynamic> get _snapshotResponse => {
      'ok': true,
      'recommendationGenerationId': 'rec_widget_1',
      'source': 'cache',
      'snapshot': {
        'recommendationGenerationId': 'rec_widget_1',
        'requestedDestination': 'Penang, Malaysia',
        'source': 'cache',
      },
      'recommendations': [
        {
          'destinationId': 'penang_hill',
          'title': 'Penang Hill',
          'finalScore': 91,
          'matchReasons': ['Matches your nature interests'],
        },
        {
          'destinationId': 'kek_lok_si',
          'title': 'Kek Lok Si Temple',
          'finalScore': 86,
          'recommendationReason': '86% match • Fits your culture profile',
        },
      ],
    };

class _FakeApiService extends ApiService {
  final Completer<dynamic>? generationGate;
  final bool noSavedSnapshot;
  final bool failGenerationOnce;
  final bool snapshotMismatch;
  int recommendationCalls = 0;
  int recommendationReads = 0;
  int generationCalls = 0;
  int regenerationCalls = 0;
  Map<String, dynamic>? lastGenerationBody;
  Map<String, dynamic>? lastRegenerationBody;
  final Map<String, dynamic> trip = _plannedTrip('trip_exact_123');

  _FakeApiService({
    this.generationGate,
    this.noSavedSnapshot = false,
    this.failGenerationOnce = false,
    this.snapshotMismatch = false,
  });

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr4/recommendations/generate') {
      recommendationCalls += 1;
      return _snapshotResponse;
    }
    if (path == '/api/fr5/personalised-trips/generate') {
      generationCalls += 1;
      lastGenerationBody = Map<String, dynamic>.from(body ?? const {});
      if (generationGate != null) await generationGate!.future;
      if (snapshotMismatch) {
        throw const ApiException(
          'Recommendation snapshot destination does not match this trip.',
          409,
          {'stage': 'snapshot_validation'},
        );
      }
      if (failGenerationOnce && generationCalls == 1) {
        return {
          'ok': false,
          'tripId': 'trip_exact_123',
          'status': 'generation_failed',
          'stage': 'budget_calculation',
          'retryable': true,
          'error': 'Raw backend budget exception',
        };
      }
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
    if (path == '/api/fr2/preferences') {
      return {
        'ok': true,
        'preferences': {
          'travelPersonality': 'Explorer',
          'interests': ['Food', 'Culture'],
          'travelPace': 'Relaxed',
          'budgetRange': 'Moderate',
        },
      };
    }
    if (path == '/api/fr4/recommendations') {
      recommendationReads += 1;
      expect(query?['destinationArea'], 'Penang, Malaysia');
      if (noSavedSnapshot) {
        return {
          'ok': true,
          'recommendationGenerationId': '',
          'snapshot': <String, dynamic>{},
          'recommendations': <dynamic>[],
        };
      }
      return _snapshotResponse;
    }
    if (path == '/api/fr5/itineraries') {
      return {
        'ok': true,
        'items': [trip],
      };
    }
    throw StateError('Unexpected GET $path');
  }
}

Future<void> _pumpPlanning(
  WidgetTester tester,
  _FakeApiService api,
) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData(useMaterial3: true),
      home: PersonalizedPlanningScreen(api: api),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _scrollTo(WidgetTester tester, Finder finder) async {
  for (var attempt = 0; attempt < 16 && finder.evaluate().isEmpty; attempt++) {
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -350));
    await tester.pump();
  }
  if (finder.evaluate().isEmpty) {
    for (var attempt = 0;
        attempt < 16 && finder.evaluate().isEmpty;
        attempt++) {
      await tester.drag(find.byType(Scrollable).first, const Offset(0, 350));
      await tester.pump();
    }
  }
  expect(finder, findsWidgets);
  await tester.ensureVisible(finder.first);
  await tester.pump();
}

Finder _textField(String key) => find.descendant(
      of: find.byKey(ValueKey(key)),
      matching: find.byType(TextField),
    );

void main() {
  testWidgets('renders required trip inputs and the saved profile summary',
      (tester) async {
    final api = _FakeApiService();
    await _pumpPlanning(tester, api);

    expect(find.text('Trip basics'), findsOneWidget);
    expect(find.text('Where are you going?'), findsOneWidget);
    expect(find.text('Start date'), findsOneWidget);
    expect(find.text('End date'), findsOneWidget);
    expect(find.text('Travellers'), findsOneWidget);
    expect(find.text('Budget (RM)'), findsOneWidget);

    await _scrollTo(tester, find.text('Your travel style'));
    expect(find.text('Explorer'), findsOneWidget);
    expect(find.text('Food'), findsOneWidget);
    expect(find.text('Culture'), findsOneWidget);
    expect(find.text('Relaxed pace'), findsOneWidget);
    expect(find.text('Moderate budget'), findsOneWidget);
  });

  testWidgets('shows inline validation for an invalid traveller count',
      (tester) async {
    final api = _FakeApiService();
    await _pumpPlanning(tester, api);

    await tester.enterText(_textField('planning-travellers'), '0');
    await tester.pump();

    expect(find.text('Enter at least 1 traveller.'), findsOneWidget);
    await _scrollTo(
      tester,
      find.byKey(const ValueKey('build-itinerary-button')),
    );
    await tester.tap(find.byKey(const ValueKey('build-itinerary-button')));
    await tester.pump();
    expect(api.generationCalls, 0);
  });

  testWidgets('shows inline validation for an invalid date range',
      (tester) async {
    await _pumpPlanning(tester, _FakeApiService());

    final start = tester.widget<TextField>(
      _textField('planning-start-date'),
    );
    final end = tester.widget<TextField>(
      _textField('planning-end-date'),
    );
    end.controller!.text = start.controller!.text;

    await _scrollTo(
      tester,
      find.byKey(const ValueKey('build-itinerary-button')),
    );
    await tester.tap(find.byKey(const ValueKey('build-itinerary-button')));
    await tester.pump();

    await _scrollTo(tester, find.text('End date must be after start date.'));
    expect(find.text('End date must be after start date.'), findsOneWidget);
  });

  testWidgets(
      'shows the returned snapshot and builds with its exact generation ID',
      (tester) async {
    final api = _FakeApiService();
    await _pumpPlanning(tester, api);

    await _scrollTo(tester, find.text('Suggestions for this trip'));
    expect(
      find.byKey(const ValueKey('planning-snapshot-rec_widget_1')),
      findsOneWidget,
    );
    expect(find.text('Penang Hill'), findsOneWidget);
    expect(find.text('91% match'), findsOneWidget);
    expect(find.text('Selected for planning'), findsNWidgets(2));
    expect(api.recommendationReads, 1);
    expect(api.recommendationCalls, 0);

    await _scrollTo(
      tester,
      find.byKey(const ValueKey('build-itinerary-button')),
    );
    await tester.tap(find.byKey(const ValueKey('build-itinerary-button')));
    await tester.pumpAndSettle();

    expect(api.generationCalls, 1);
    expect(
      api.lastGenerationBody?['recommendationGenerationId'],
      'rec_widget_1',
    );
    final details = tester.widget<TripDetailsScreen>(
      find.byType(TripDetailsScreen),
    );
    expect(details.tripId, 'trip_exact_123');
  });

  testWidgets('find suggestions creates a snapshot when none is saved',
      (tester) async {
    final api = _FakeApiService(noSavedSnapshot: true);
    await _pumpPlanning(tester, api);

    await _scrollTo(tester, find.text('Find suggestions'));
    await tester.tap(find.text('Find suggestions'));
    await tester.pumpAndSettle();

    expect(api.recommendationCalls, 1);
    expect(
      find.byKey(const ValueKey('planning-snapshot-rec_widget_1')),
      findsOneWidget,
    );
  });

  testWidgets('generating disables the CTA and repeated taps do not duplicate',
      (tester) async {
    final gate = Completer<dynamic>();
    final api = _FakeApiService(generationGate: gate);
    await _pumpPlanning(tester, api);
    await _scrollTo(
      tester,
      find.byKey(const ValueKey('build-itinerary-button')),
    );

    await tester.tap(find.byKey(const ValueKey('build-itinerary-button')));
    await tester.pump();
    await _scrollTo(
      tester,
      find.byKey(const ValueKey('build-itinerary-button')),
    );
    final button = tester.widget<PrimaryButton>(
      find.byKey(const ValueKey('build-itinerary-button')),
    );
    expect(button.loading, isTrue);
    expect(button.onPressed, isNull);
    expect(api.generationCalls, 1);

    await tester.tap(
      find.byKey(const ValueKey('build-itinerary-button')),
      warnIfMissed: false,
    );
    await tester.pump();
    expect(api.generationCalls, 1);

    gate.complete();
    await tester.pumpAndSettle();
    expect(api.generationCalls, 1);
  });

  testWidgets('retryable failure is safe, understandable and reuses the trip',
      (tester) async {
    final api = _FakeApiService(failGenerationOnce: true);
    await _pumpPlanning(tester, api);
    await _scrollTo(
      tester,
      find.byKey(const ValueKey('build-itinerary-button')),
    );
    await tester.tap(find.byKey(const ValueKey('build-itinerary-button')));
    await tester.pumpAndSettle();

    await _scrollTo(tester, find.text('Retry this trip'));
    expect(find.textContaining('Your trip draft is safe'), findsOneWidget);
    expect(find.text('Raw backend budget exception'), findsNothing);

    final firstRequestId = api.lastGenerationBody?['generationRequestId'];
    await tester.tap(find.text('Retry this trip'));
    await tester.pumpAndSettle();

    expect(api.generationCalls, 2);
    expect(api.lastGenerationBody?['generationRequestId'], firstRequestId);
    expect(
      tester.widget<TripDetailsScreen>(find.byType(TripDetailsScreen)).tripId,
      'trip_exact_123',
    );
  });

  testWidgets('snapshot mismatch shows friendly refresh recovery',
      (tester) async {
    final api = _FakeApiService(snapshotMismatch: true);
    await _pumpPlanning(tester, api);
    await _scrollTo(
      tester,
      find.byKey(const ValueKey('build-itinerary-button')),
    );
    await tester.tap(find.byKey(const ValueKey('build-itinerary-button')));
    await tester.pumpAndSettle();

    await _scrollTo(tester, find.text('Refresh suggestions').last);
    expect(
      find.text('Your recommendations are out of date'),
      findsOneWidget,
    );
    expect(find.textContaining('snapshot destination'), findsNothing);

    await tester.tap(find.text('Refresh suggestions').last);
    await tester.pumpAndSettle();
    expect(api.recommendationCalls, 1);
    expect(find.text('Your recommendations are out of date'), findsNothing);
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
    await tester.pumpWidget(
      MaterialApp(
        home: TripDetailsScreen(tripId: 'trip_exact_123', api: api),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Trip generation did not finish'), findsOneWidget);
    expect(find.textContaining('Your trip draft is safe'), findsOneWidget);
    expect(find.text('Budget calculation failed'), findsNothing);
    await tester.tap(find.text('Retry generation'));
    await tester.pumpAndSettle();

    expect(api.regenerationCalls, 1);
    expect(
      api.lastRegenerationBody?['recommendationGenerationId'],
      'rec_widget_1',
    );
    expect(find.text('generation failed'), findsNothing);
    expect(find.text('Planned'), findsOneWidget);
  });
}
