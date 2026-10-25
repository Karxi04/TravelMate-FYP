import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _AdjustmentApi extends ApiService {
  final Map<String, dynamic> trip = {
    'id': 'trip_target',
    'title': 'Penang flight trip',
    'destinationArea': 'Penang, Malaysia',
    'startDate': '2026-10-12',
    'endDate': '2026-10-14',
    'tripDays': 3,
    'travellerCount': 1,
    'budgetLimit': 1000,
    'status': 'planned',
    'activities': [
      {
        'activityId': 'a1',
        'activityName': 'George Town walk',
        'dayNo': 1,
        'dayDate': '2026-10-12',
        'scheduledStartTime': '10:00',
        'scheduledEndTime': '11:00',
        'timeRangeLabel': '10:00 - 11:00',
        'category': 'Culture',
        'recommendedDurationMinutes': 60,
        'estimatedCost': 20,
      },
    ],
    'dailySchedule': [
      {
        'dayNo': 1,
        'dayDate': '2026-10-12',
        'activities': <Map<String, dynamic>>[],
        'planningBlocks': <Map<String, dynamic>>[],
        'estimatedCost': 20,
      },
      {
        'dayNo': 2,
        'dayDate': '2026-10-13',
        'activities': <Map<String, dynamic>>[],
        'planningBlocks': <Map<String, dynamic>>[],
        'estimatedCost': 0,
      },
      {
        'dayNo': 3,
        'dayDate': '2026-10-14',
        'activities': <Map<String, dynamic>>[],
        'planningBlocks': <Map<String, dynamic>>[],
        'estimatedCost': 0,
      },
    ],
    'budgetEstimate': {'total': 20, 'limit': 1000},
    'selectedFlight': {
      'flightId': 'f1',
      'airline': 'Demo Air',
      'flightNumber': 'DA101',
      'departureAirport': 'KUL',
      'arrivalAirport': 'PEN',
      'departureTime': '2026-10-12T08:00:00+08:00',
      'arrivalTime': '2026-10-12T09:00:00+08:00',
      'returnSegments': [
        {
          'departureAirport': 'PEN',
          'arrivalAirport': 'KUL',
          'departureTime': '2026-10-14T18:00:00+08:00',
          'arrivalTime': '2026-10-14T19:00:00+08:00',
        },
      ],
    },
  };

  int previewCalls = 0;
  int applyCalls = 0;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries')
      return {
        'ok': true,
        'items': [trip]
      };
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path.endsWith('/flight-adjustment/preview')) {
      previewCalls += 1;
      return {
        'ok': true,
        'preview': {
          'previewId': 'preview-1',
          'canApply': true,
          'availability': {'2026-10-12': 'after 10:30'},
          'changes': [
            {'activityName': 'George Town walk', 'kind': 'rescheduled'},
          ],
          'newlyUnscheduled': [
            {
              'activityName': 'Late market',
              'unscheduledReason': 'Needs manual review',
            },
          ],
          'remainingConflicts': [
            {'message': 'Protected activity needs manual review.'},
          ],
        },
      };
    }
    if (path.endsWith('/flight-adjustment/apply')) {
      applyCalls += 1;
      trip['flightAdjustment'] = {'status': 'applied'};
      return {'ok': true, 'idempotent': false, 'itinerary': trip};
    }
    throw StateError('Unexpected POST $path');
  }
}

Future<void> _pumpAdjustmentTrip(
    WidgetTester tester, _AdjustmentApi api) async {
  tester.view.physicalSize = const Size(430, 1200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(
    home: TripDetailsScreen(tripId: 'trip_target', api: api),
  ));
  await tester.pumpAndSettle();
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  testWidgets('reviews flight adjustment before explicit apply',
      (tester) async {
    final api = _AdjustmentApi();
    await _pumpAdjustmentTrip(tester, api);

    await tester.scrollUntilVisible(find.text('Adjust itinerary'), 250,
        scrollable: find.descendant(
          of: find.byKey(const ValueKey('trip-details-scroll')),
          matching: find.byType(Scrollable),
        ).first);
    await tester.pumpAndSettle();
    final adjust = find.text('Adjust itinerary');
    expect(adjust, findsOneWidget);
    final adjustButton = find.ancestor(
      of: adjust,
      matching: find.byType(OutlinedButton),
    );
    await tester.ensureVisible(adjustButton);
    await tester.tap(adjustButton);
    await tester.pumpAndSettle();
    expect(find.text('Review flight-aware adjustment'), findsOneWidget);
    expect(find.text('Keep current plan'), findsOneWidget);
    expect(find.text('Apply changes'), findsOneWidget);
    expect(find.text('Would become unscheduled'), findsOneWidget);
    expect(find.text('Remaining conflicts'), findsOneWidget);
    expect(api.previewCalls, 1);

    await tester.tap(find.text('Keep current plan'));
    await tester.pumpAndSettle();
    expect(api.applyCalls, 0);

    await tester.ensureVisible(adjustButton);
    await tester.tap(adjustButton);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Apply changes'));
    await tester.pumpAndSettle();
    expect(api.applyCalls, 1);
    expect(api.trip['flightAdjustment']['status'], 'applied');
    expect(
        find.text('Flight-aware itinerary changes applied.'), findsOneWidget);
  });
}
