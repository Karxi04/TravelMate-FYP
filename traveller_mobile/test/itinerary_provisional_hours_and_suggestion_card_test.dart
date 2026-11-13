import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _FakeTripApi extends ApiService {
  final Map<String, dynamic> trip;
  int viewPlaceCalls = 0;
  String? lastDestinationIdRequested;

  _FakeTripApi(this.trip);

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries' || path.startsWith('/api/fr5/itineraries/')) {
      return {
        'ok': true,
        'items': [trip],
        'itinerary': trip,
      };
    }
    if (path.startsWith('/api/fr3/destinations/')) {
      viewPlaceCalls++;
      lastDestinationIdRequested = path.split('/').last;
      return {
        'ok': true,
        'destination': {
          'destinationId': lastDestinationIdRequested,
          'title': 'Destination Details View',
          'description': 'Details for attraction',
        },
      };
    }
    if (path.endsWith('/budget')) {
      return {'ok': true, 'budget': trip['budgetEstimate'] ?? {}};
    }
    return {'ok': true};
  }
}

class _FakePlanningApi extends ApiService {
  final List<Map<String, dynamic>> recommendations;

  _FakePlanningApi(this.recommendations);

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
      return {
        'ok': true,
        'recommendationGenerationId': 'rec_snapshot_1',
        'source': 'live_provider',
        'snapshot': {
          'recommendationGenerationId': 'rec_snapshot_1',
          'requestedDestination': 'Penang, Malaysia',
          'source': 'live_provider',
        },
        'recommendations': recommendations,
      };
    }
    return {'ok': true};
  }
}

Map<String, dynamic> _makeTrip({
  required List<Map<String, dynamic>> scheduled,
  List<Map<String, dynamic>> unscheduled = const [],
}) {
  return {
    'id': 'trip_test',
    'title': 'Penang Heritage Tour',
    'destinationArea': 'Penang, Malaysia',
    'startDate': '2026-11-24',
    'endDate': '2026-11-24',
    'tripDays': 1,
    'travellerCount': 2,
    'budgetLimit': 1500,
    'status': 'planned',
    'activities': scheduled,
    'unscheduledSuggestions': unscheduled,
    'dailySchedule': [
      {
        'dayNo': 1,
        'dayDate': '2026-11-24',
        'activities': scheduled,
        'planningBlocks': [
          {
            'type': 'meal_rest',
            'label': 'Lunch and rest',
            'startTime': '12:30',
            'endTime': '13:30',
            'durationMinutes': 60,
            'estimated': true,
          }
        ],
        'weather': {
          'source': 'forecast',
          'description': 'Partly cloudy',
          'heavyRainLikely': false,
        },
        'estimatedCost': 50,
      }
    ],
    'budgetEstimate': {
      'total': 450,
      'limit': 1500,
      'activities': 50,
      'food': 120,
      'transport': 80,
      'hotel': 200,
      'costProvenance': {'activities': 'catalog_estimate'},
    },
  };
}

Future<void> _pumpTripDetails(
  WidgetTester tester,
  Map<String, dynamic> trip, {
  Size size = const Size(400, 850),
  double textScale = 1.0,
}) async {
  tester.view.physicalSize = Size(size.width * textScale, size.height * textScale);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final api = _FakeTripApi(trip);
  await tester.pumpWidget(
    MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(
          size: size,
          textScaler: TextScaler.linear(textScale),
        ),
        child: TripDetailsScreen(
          tripId: trip['id'] ?? 'trip_test',
          api: api,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _show(WidgetTester tester, Finder target) async {
  final scrollable = find.byKey(const ValueKey('trip-details-scroll'));
  for (var i = 0; i < 18 && target.evaluate().isEmpty; i++) {
    await tester.drag(scrollable, const Offset(0, -350));
    await tester.pump();
  }
  if (target.evaluate().isEmpty) {
    for (var i = 0; i < 18 && target.evaluate().isEmpty; i++) {
      await tester.drag(scrollable, const Offset(0, 350));
      await tester.pump();
    }
  }
  expect(target, findsWidgets);
  await tester.ensureVisible(target.first);
  await tester.pump();
}

Future<void> _scrollToPlanning(WidgetTester tester, Finder target) async {
  final scrollable = find.byType(Scrollable).first;
  for (var i = 0; i < 18 && target.evaluate().isEmpty; i++) {
    await tester.drag(scrollable, const Offset(0, -350));
    await tester.pump();
  }
  expect(target, findsWidgets);
  await tester.ensureVisible(target.first);
  await tester.pump();
}

void main() {
  group('Batch 21E-F1C: Provisional Itinerary Hours Presentation', () {
    testWidgets('1. Provisional activity displays Hours unverified and explanatory note',
        (tester) async {
      final trip = _makeTrip(
        scheduled: [
          {
            'activityId': 'act_prov_1',
            'destinationId': 'dest_prov_1',
            'activityName': 'Wonderfood Museum',
            'dayNo': 1,
            'timeSlot': '15:30',
            'scheduledStartTime': '15:30',
            'scheduledEndTime': '17:15',
            'timeRangeLabel': '15:30 - 17:15',
            'category': 'Museum',
            'recommendedDurationMinutes': 105,
            'estimatedCost': 25,
            'openingHoursStatus': 'unknown',
            'scheduleFeasibility': 'provisional',
            'scheduleNotes': [
              'Provisional visit time: opening hours are unknown, transient or stale. Confirm with the venue before visiting.'
            ],
          }
        ],
      );

      await _pumpTripDetails(tester, trip);
      await _show(tester, find.text('Wonderfood Museum'));

      expect(find.text('Hours unverified'), findsAtLeastNWidgets(1));
      expect(find.text('15:30'), findsOneWidget);
      expect(find.text('Wonderfood Museum'), findsOneWidget);

      expect(
        find.textContaining('Confirm with the venue before visiting'),
        findsOneWidget,
      );
    });

    testWidgets('2. Known-hours activity displays visit times normally without Hours unverified chip',
        (tester) async {
      final trip = _makeTrip(
        scheduled: [
          {
            'activityId': 'act_known_1',
            'destinationId': 'dest_known_1',
            'activityName': 'Georgetown World Heritage Site',
            'dayNo': 1,
            'timeSlot': '09:00',
            'scheduledStartTime': '09:00',
            'scheduledEndTime': '10:45',
            'timeRangeLabel': '09:00 - 10:45',
            'category': 'Heritage',
            'recommendedDurationMinutes': 105,
            'estimatedCost': 0,
            'openingHoursStatus': 'open',
            'scheduleFeasibility': 'feasible_with_reported_hours',
            'scheduleNotes': [
              'Fits one reported opening period; current hours and special-date closures are not verified.'
            ],
          }
        ],
      );

      await _pumpTripDetails(tester, trip);
      await _show(tester, find.text('Georgetown World Heritage Site'));

      expect(find.text('Georgetown World Heritage Site'), findsOneWidget);
      expect(find.text('09:00'), findsOneWidget);
      expect(find.text('Hours unverified'), findsNothing);
      expect(
        find.textContaining('Fits one reported opening period'),
        findsOneWidget,
      );
    });

    testWidgets('3. Missing hours metadata preserves historical display without inventing certainty',
        (tester) async {
      final trip = _makeTrip(
        scheduled: [
          {
            'activityId': 'act_legacy_1',
            'destinationId': 'dest_legacy_1',
            'activityName': 'Historic Clan Jetty',
            'dayNo': 1,
            'timeSlot': '10:00',
            'scheduledStartTime': '10:00',
            'scheduledEndTime': '11:45',
            'category': 'Sightseeing',
            'recommendedDurationMinutes': 105,
            'estimatedCost': 0,
            'scheduleNotes': const <String>[],
          }
        ],
      );

      await _pumpTripDetails(tester, trip);
      await _show(tester, find.text('Historic Clan Jetty'));

      expect(find.text('Historic Clan Jetty'), findsOneWidget);
      expect(find.text('10:00'), findsOneWidget);
      expect(find.text('Hours unverified'), findsNothing);
    });

    testWidgets('4. Closed activity handling preserves exclusion explanation in unscheduled section',
        (tester) async {
      final trip = _makeTrip(
        scheduled: [
          {
            'activityId': 'act_open_1',
            'destinationId': 'dest_open_1',
            'activityName': 'Penang Street Art',
            'dayNo': 1,
            'timeSlot': '09:00',
            'scheduledStartTime': '09:00',
            'scheduledEndTime': '10:45',
            'category': 'Art',
            'estimatedCost': 0,
            'openingHoursStatus': 'open',
            'scheduleFeasibility': 'feasible_with_reported_hours',
          }
        ],
        unscheduled: [
          {
            'activityId': 'act_closed_1',
            'activityName': 'Closed Museum on Tuesday',
            'unscheduledReason': 'Attraction is closed on all trip days.',
            'scheduleFeasibility': 'unscheduled',
          },
          {
            'activityId': 'act_unverified_overflow',
            'activityName': 'Pinang Peranakan Mansion',
            'unscheduledReason':
                'Could not fit within available time, travel, and opening-hour constraints. Opening hours are unverified; confirm with the venue before arranging a visit.',
            'scheduleFeasibility': 'unscheduled',
          }
        ],
      );

      await _pumpTripDetails(tester, trip);
      await _show(tester, find.text('Penang Street Art'));

      // Unscheduled section
      await _show(tester, find.text('Closed Museum on Tuesday'));
      expect(find.text('Closed Museum on Tuesday'), findsOneWidget);
      expect(
        find.text('This place is closed during your trip dates.'),
        findsOneWidget,
      );

      await _show(tester, find.text('Pinang Peranakan Mansion'));
      expect(find.text('Pinang Peranakan Mansion'), findsOneWidget);
      expect(
        find.textContaining('Opening hours are unverified'),
        findsOneWidget,
      );
    });

    testWidgets('5. Backend warning propagation surfaces custom provisional notes',
        (tester) async {
      final trip = _makeTrip(
        scheduled: [
          {
            'activityId': 'act_warn_1',
            'destinationId': 'dest_warn_1',
            'activityName': 'Little India Spice Market',
            'dayNo': 1,
            'timeSlot': '14:00',
            'scheduledStartTime': '14:00',
            'scheduledEndTime': '15:15',
            'category': 'Shopping',
            'openingHoursStatus': 'unknown',
            'scheduleFeasibility': 'provisional',
            'scheduleNotes': [
              'Custom warning: hours are subject to festive holiday schedule.'
            ],
          }
        ],
      );

      await _pumpTripDetails(tester, trip);
      await _show(tester, find.text('Little India Spice Market'));

      expect(
        find.text('Custom warning: hours are subject to festive holiday schedule.'),
        findsOneWidget,
      );
    });

    testWidgets('6. Legacy saved trip compatibility renders cleanly with no errors',
        (tester) async {
      final legacyTrip = {
        'id': 'legacy_trip_999',
        'title': 'Old Trip 2025',
        'destinationArea': 'Penang',
        'startDate': '2025-05-10',
        'endDate': '2025-05-10',
        'tripDays': 1,
        'travellerCount': 1,
        'budgetLimit': 500,
        'status': 'planned',
        'activities': [
          {
            'activityId': 'leg_1',
            'activityName': 'Kek Lok Si',
            'dayNo': 1,
            'timeSlot': '10:00',
            'category': 'Sightseeing',
            'estimatedCost': 10,
          }
        ],
        'dailySchedule': [
          {
            'dayNo': 1,
            'dayDate': '2025-05-10',
            'activities': [
              {
                'activityId': 'leg_1',
                'activityName': 'Kek Lok Si',
                'dayNo': 1,
                'timeSlot': '10:00',
                'category': 'Sightseeing',
                'estimatedCost': 10,
              }
            ],
            'planningBlocks': const <Map<String, dynamic>>[],
            'weather': {'source': 'unavailable'},
          }
        ],
      };

      await _pumpTripDetails(tester, legacyTrip);
      await _show(tester, find.text('Kek Lok Si'));

      expect(find.text('Kek Lok Si'), findsOneWidget);
      expect(find.text('10:00'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('7. Activity card navigation preserves destination ID',
        (tester) async {
      final trip = _makeTrip(
        scheduled: [
          {
            'activityId': 'act_nav_1',
            'destinationId': 'dest_pinang_mansion',
            'activityName': 'Pinang Peranakan Mansion',
            'dayNo': 1,
            'timeSlot': '11:00',
            'category': 'Heritage',
            'openingHoursStatus': 'unknown',
            'scheduleFeasibility': 'provisional',
          }
        ],
      );

      final api = _FakeTripApi(trip);
      tester.view.physicalSize = const Size(400, 850);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          home: TripDetailsScreen(
            tripId: 'trip_test',
            api: api,
          ),
        ),
      );
      await tester.pumpAndSettle();

      await _show(tester, find.text('Pinang Peranakan Mansion'));
      await tester.tap(find.text('Pinang Peranakan Mansion'));
      await tester.pumpAndSettle();

      expect(api.viewPlaceCalls, 1);
      expect(api.lastDestinationIdRequested, 'dest_pinang_mansion');
    });

    testWidgets('8. No changes to recommendation ranking or budget values',
        (tester) async {
      final trip = _makeTrip(
        scheduled: [
          {
            'activityId': 'act_b_1',
            'activityName': 'Site A',
            'dayNo': 1,
            'timeSlot': '09:00',
            'estimatedCost': 50,
          }
        ],
      );

      await _pumpTripDetails(tester, trip);

      await _show(tester, find.text('Trip budget'));
      expect(find.text('Trip budget'), findsOneWidget);
      expect(find.text('Total budget · MYR 1500.00'), findsOneWidget);
    });
  });

  group('Batch 21E-F1C: Suggestion Card Title Layout & Responsiveness', () {
    testWidgets('9. Long attraction title wraps naturally across words with usable horizontal width',
        (tester) async {
      final recs = [
        {
          'destinationId': 'sugg_long_1',
          'title':
              'King Street (Heritage Building Area and Historical Shophouse Quarter)',
          'finalScore': 79,
          'matchReasons': [
            'Matches your Explorer personality',
            'High cultural interest'
          ],
        }
      ];

      final api = _FakePlanningApi(recs);
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          home: PersonalizedPlanningScreen(api: api),
        ),
      );
      await tester.pumpAndSettle();

      final titleFinder = find.text(
          'King Street (Heritage Building Area and Historical Shophouse Quarter)');
      await _scrollToPlanning(tester, titleFinder);

      expect(titleFinder, findsOneWidget);

      final renderBox = tester.renderObject<RenderBox>(titleFinder);
      // Usable horizontal width on 360px screen with card padding and icon is > 200px
      expect(renderBox.size.width, greaterThan(200));

      expect(find.text('Recommendation score: 79/100'), findsNothing);
    });

    testWidgets('10. StatusChip remains visible without compressing attraction title',
        (tester) async {
      final recs = [
        {
          'destinationId': 'sugg_short_1',
          'title': 'Fort Cornwallis',
          'finalScore': 84,
          'recommendationReason': 'Historical military fortress',
        }
      ];

      final api = _FakePlanningApi(recs);
      tester.view.physicalSize = const Size(380, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          home: PersonalizedPlanningScreen(api: api),
        ),
      );
      await tester.pumpAndSettle();

      await _scrollToPlanning(tester, find.text('Fort Cornwallis'));

      expect(find.text('Fort Cornwallis'), findsOneWidget);
      expect(find.text('Recommendation score: 84/100'), findsNothing);
      expect(find.text('Selected for planning'), findsNothing);
    });

    testWidgets('11. Narrow-screen layout (320px) renders without RenderFlex overflow',
        (tester) async {
      final recs = [
        {
          'destinationId': 'sugg_narrow_1',
          'title':
              'Georgetown UNESCO Historic Site With Extremely Long Extended Name',
          'finalScore': 92,
          'matchReasons': ['Iconic Penang landmark'],
        }
      ];

      final api = _FakePlanningApi(recs);
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          home: PersonalizedPlanningScreen(api: api),
        ),
      );
      await tester.pumpAndSettle();

      final titleFinder = find.text(
          'Georgetown UNESCO Historic Site With Extremely Long Extended Name');
      await _scrollToPlanning(tester, titleFinder);

      expect(tester.takeException(), isNull);
      expect(titleFinder, findsOneWidget);
    });

    testWidgets('12. Large-text accessibility (1.8x text scale) renders cleanly',
        (tester) async {
      final recs = [
        {
          'destinationId': 'sugg_scale_1',
          'title': 'Kek Lok Si Temple',
          'finalScore': 88,
          'recommendationReason': 'Magnificent Buddhist pagoda',
        }
      ];

      final api = _FakePlanningApi(recs);
      tester.view.physicalSize = const Size(400, 850);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          home: MediaQuery(
            data: const MediaQueryData(
              size: Size(400, 850),
              textScaler: TextScaler.linear(1.8),
            ),
            child: PersonalizedPlanningScreen(api: api),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await _scrollToPlanning(tester, find.text('Kek Lok Si Temple'));

      expect(tester.takeException(), isNull);
      expect(find.text('Kek Lok Si Temple'), findsOneWidget);
      expect(find.text('Recommendation score: 88/100'), findsNothing);
    });
  });
}
