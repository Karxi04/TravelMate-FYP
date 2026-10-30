import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/flight_adjustment_preview_sheet.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_details_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_replacement_sheet.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_history_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockLifecycleApi extends ApiService {
  Map<String, dynamic> trip;
  Map<String, dynamic>? searchResponse;
  Map<String, dynamic>? previewResponse;
  Map<String, dynamic>? applyResponse;
  Map<String, dynamic>? removeResponse;
  ApiException? previewException;
  ApiException? applyException;
  ApiException? selectException;

  int previewCalls = 0;
  int applyCalls = 0;
  int removeCalls = 0;
  int selectCalls = 0;
  int searchCalls = 0;

  Completer<dynamic>? delayedSearchCompleter;

  _MockLifecycleApi({required this.trip});

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries') {
      return {
        'ok': true,
        'items': [trip]
      };
    }
    if (path.startsWith('/api/fr5/itineraries/')) {
      return {'ok': true, 'itinerary': trip};
    }
    if (path == '/api/fr8/bookings' || path == '/api/fr8/hotels/bookings') {
      return {'ok': true, 'items': []};
    }
    if (path == '/api/fr7/flights/search') {
      searchCalls += 1;
      if (delayedSearchCompleter != null) {
        return delayedSearchCompleter!.future;
      }
      return searchResponse ??
          {
            'ok': true,
            'source': 'sample_fixture',
            'searchId': 'search-test-1',
            'retrievedAt': DateTime.now().toUtc().toIso8601String(),
            'expiresAt': DateTime.now()
                .add(const Duration(minutes: 30))
                .toUtc()
                .toIso8601String(),
            'items': [
              {
                'id': 'opt-101',
                'optionId': 'opt-101',
                'airline': 'Malaysia Airlines',
                'flightNumber': 'MH1138',
                'departureAirport': 'KUL',
                'arrivalAirport': 'PEN',
                'departureTime': '08:30',
                'arrivalTime': '09:30',
                'price': 180.0,
                'currency': 'MYR',
                'durationMinutes': 60,
                'tripType': 'one_way',
              },
              {
                'id': 'opt-202',
                'optionId': 'opt-202',
                'airline': 'AirAsia',
                'flightNumber': 'AK6112',
                'departureAirport': 'KUL',
                'arrivalAirport': 'PEN',
                'departureTime': '14:00',
                'arrivalTime': '15:00',
                'price': 240.0,
                'currency': 'MYR',
                'durationMinutes': 60,
                'tripType': 'one_way',
              },
            ],
          };
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path.endsWith('/flight-adjustment/preview')) {
      previewCalls += 1;
      if (previewException != null) throw previewException!;
      return previewResponse ??
          {
            'ok': true,
            'preview': {
              'previewId': 'preview-mock-1',
              'canApply': true,
              'availability': {'2026-11-01': 'after 09:30'},
              'changes': [
                {
                  'activityId': 'act-1',
                  'activityName': 'George Town Heritage Walk',
                  'kind': 'moved',
                  'from': {
                    'dayNo': 1,
                    'scheduledStartTime': '09:00',
                    'scheduledEndTime': '11:00'
                  },
                  'to': {
                    'dayNo': 1,
                    'scheduledStartTime': '10:30',
                    'scheduledEndTime': '12:30'
                  },
                  'reason': 'Adjusted for flight arrival',
                  'protected': false,
                },
                {
                  'activityId': 'act-2',
                  'activityName': 'Penang Hill Funicular',
                  'kind': 'retained',
                  'protected': false,
                },
              ],
              'newlyUnscheduled': [
                {
                  'activityId': 'act-3',
                  'activityName': 'Early Morning Dim Sum',
                  'unscheduledReason': 'Arrives after opening hours',
                },
              ],
              'remainingConflicts': [],
              'budgetBefore': {'total': 800, 'transport': 180},
              'budgetAfter': {'total': 800, 'transport': 180},
            },
          };
    }
    if (path.endsWith('/flight-adjustment/apply')) {
      applyCalls += 1;
      if (applyException != null) throw applyException!;
      trip['flightAdjustmentStatus'] = 'applied';
      return applyResponse ??
          {'ok': true, 'idempotent': false, 'itinerary': trip};
    }
    if (path.endsWith('/flight-selection/remove')) {
      removeCalls += 1;
      trip['selectedFlight'] = null;
      trip['flightCost'] = 0;
      final currentBudget =
          trip['budgetEstimate'] as Map<String, dynamic>? ?? {};
      final total =
          (currentBudget['total'] as num? ?? 800).toDouble() - 180.0;
      trip['budgetEstimate'] = {'total': total, 'limit': 1500};
      return removeResponse ??
          {'ok': true, 'itinerary': trip, 'budget': trip['budgetEstimate']};
    }
    if (path == '/api/fr7/flights/select') {
      selectCalls += 1;
      if (selectException != null) throw selectException!;
      final flight = body?['flight'] as Map<String, dynamic>? ?? {};
      trip['selectedFlight'] = flight;
      final fare = (flight['price'] as num? ?? 240).toDouble();
      trip['flightCost'] = fare;
      trip['budgetEstimate'] = {'total': 620.0 + fare, 'limit': 1500};
      return {
        'ok': true,
        'itinerary': trip,
        'budget': trip['budgetEstimate'],
      };
    }
    throw StateError('Unexpected POST $path');
  }
}

Map<String, dynamic> _buildSampleTrip({
  bool withFlight = true,
  bool withHotel = false,
  bool withRental = false,
  bool isOneWay = true,
}) {
  return {
    'id': 'trip-pg-1',
    'title': 'Penang Discovery',
    'destinationArea': 'Penang, Malaysia',
    'startDate': '2026-11-01',
    'endDate': '2026-11-04',
    'tripDays': 4,
    'travellerCount': 1,
    'budgetLimit': 1500,
    'flightCost': withFlight ? 180.0 : 0.0,
    'budgetEstimate': {
      'total': withFlight ? 800.0 : 620.0,
      'limit': 1500,
      'flight': withFlight ? 180.0 : 0.0,
    },
    'activities': [
      {
        'activityId': 'act-1',
        'activityName': 'George Town Heritage Walk',
        'dayNo': 1,
        'dayDate': '2026-11-01',
        'scheduledStartTime': '09:00',
        'scheduledEndTime': '11:00',
        'category': 'Culture',
        'isLocked': false,
      },
      {
        'activityId': 'act-lock',
        'activityName': 'Pre-booked Clan Jetty Dinner',
        'dayNo': 1,
        'dayDate': '2026-11-01',
        'scheduledStartTime': '19:00',
        'scheduledEndTime': '21:00',
        'category': 'Dining',
        'isLocked': true,
        'protected': true,
      },
    ],
    'dailySchedule': [
      {
        'dayNo': 1,
        'dayDate': '2026-11-01',
        'activities': [
          {
            'activityId': 'act-1',
            'activityName': 'George Town Heritage Walk',
            'scheduledStartTime': '09:00',
            'scheduledEndTime': '11:00',
          },
          {
            'activityId': 'act-lock',
            'activityName': 'Pre-booked Clan Jetty Dinner',
            'scheduledStartTime': '19:00',
            'scheduledEndTime': '21:00',
            'isLocked': true,
          },
        ],
      },
    ],
    if (withFlight)
      'selectedFlight': {
        'id': 'opt-101',
        'optionId': 'opt-101',
        'airline': 'Malaysia Airlines',
        'flightNumber': 'MH1138',
        'departureAirport': 'KUL',
        'arrivalAirport': 'PEN',
        'departureTime': '08:30',
        'arrivalTime': '09:30',
        'price': 180.0,
        'currency': 'MYR',
        'tripType': isOneWay ? 'one_way' : 'round_trip',
        if (!isOneWay) 'returnDate': '2026-11-04',
        if (!isOneWay)
          'returnSegments': [
            {
              'departureAirport': 'PEN',
              'arrivalAirport': 'KUL',
              'departureTime': '18:00',
              'arrivalTime': '19:00',
            }
          ],
      },
    if (withHotel)
      'selectedHotel': {
        'hotelId': 'hotel-e-and-o',
        'name': 'Eastern & Oriental Hotel',
        'roomName': 'Deluxe Heritage Suite',
        'price': 450.0,
        'currency': 'MYR',
      },
    if (withRental)
      'selectedCarRental': {
        'rentalId': 'car-myvi',
        'vehicleName': 'Perodua Myvi 1.5 AV',
        'pickupLocation': 'Penang Airport',
        'price': 120.0,
      },
  };
}

Widget _wrap(Widget child, {Size size = const Size(430, 900)}) {
  return MaterialApp(
    home: MediaQuery(
      data: MediaQueryData(size: size),
      child: Scaffold(body: child),
    ),
  );
}

Future<void> _pumpTripDetails(WidgetTester tester, _MockLifecycleApi api) async {
  tester.view.physicalSize = const Size(1080, 5000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: TripDetailsScreen(tripId: 'trip-pg-1', api: api),
    ),
  ));
  await tester.pumpAndSettle();
  await tester.pump(const Duration(milliseconds: 100));
}

Future<void> _pumpFlightScreen(WidgetTester tester, _MockLifecycleApi api,
    {String? targetTripId, Map<String, dynamic>? targetTrip}) async {
  tester.view.physicalSize = const Size(1080, 5000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: FlightScreen(
        api: api,
        targetTripId: targetTripId,
        targetTrip: targetTrip,
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

Future<void> _scrollTo(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(
    finder,
    250,
    scrollable: find
        .descendant(
          of: find.byKey(const ValueKey('trip-details-scroll')),
          matching: find.byType(Scrollable),
        )
        .first,
  );
  await tester.pumpAndSettle();
}

Future<void> _ensureVisibleAndTap(WidgetTester tester, Finder finder) async {
  await _scrollTo(tester, finder);
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // -------------------------------------------------------------
  // FL-UX-01: Flight selected and attached
  // -------------------------------------------------------------
  testWidgets('FL-UX-01: Flight selected and attached to trip', (tester) async {
    final trip = _buildSampleTrip(withFlight: false);
    final api = _MockLifecycleApi(trip: trip);

    await _pumpFlightScreen(tester, api);

    // Tap Search
    await tester.tap(find.text('Search flights'));
    await tester.pumpAndSettle();

    // Find and tap 'Select' on first flight result
    final selectBtn = find.text('Select').first;
    expect(selectBtn, findsOneWidget);
    await tester.tap(selectBtn);
    await tester.pumpAndSettle();

    // Expect modal sheet with trips to attach
    expect(find.text('Attach flight to itinerary'), findsOneWidget);
    expect(find.text('Penang Discovery'), findsOneWidget);

    // Tap trip to attach
    await tester.tap(find.text('Penang Discovery'));
    await tester.pumpAndSettle();

    expect(api.selectCalls, 1);
    expect(find.textContaining('Flight attached to trip plan!'), findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-02: Preview shows affected activities
  // -------------------------------------------------------------
  testWidgets(
      'FL-UX-02: Preview shows affected activities (moved, retained, unscheduled)',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);

    await _pumpTripDetails(tester, api);

    // Tap 'Adjust itinerary'
    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('adjust-flight-itinerary-btn')));

    // Verify preview contents
    expect(find.text('Review flight-aware adjustment'), findsOneWidget);
    expect(
        find.descendant(
          of: find.byType(FlightAdjustmentPreviewSheet),
          matching: find.text('George Town Heritage Walk'),
        ),
        findsOneWidget);
    expect(find.text('Rescheduled'), findsOneWidget);
    expect(find.text('Current'), findsOneWidget);
    expect(find.text('Proposed'), findsOneWidget);
    expect(find.text('09:00 - 11:00'), findsOneWidget);
    expect(find.text('10:30 - 12:30'), findsOneWidget);

    // Retained activity
    expect(find.text('Penang Hill Funicular'), findsOneWidget);
    expect(find.text('Unchanged — fits within flight availability'),
        findsOneWidget);

    // Unscheduled activity
    expect(find.text('Would become unscheduled'), findsWidgets);
    expect(find.textContaining('Early Morning Dim Sum'), findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-03: Apply button requires a valid preview
  // -------------------------------------------------------------
  testWidgets('FL-UX-03: Apply button disabled when canApply is false',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);
    api.previewResponse = {
      'ok': true,
      'preview': {
        'previewId': 'preview-bad-1',
        'canApply': false,
        'reason': 'Flight arrival date is outside trip boundaries.',
        'changes': [],
        'newlyUnscheduled': [],
        'remainingConflicts': [],
      },
    };

    await _pumpTripDetails(tester, api);
    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('adjust-flight-itinerary-btn')));

    expect(find.text('Flight arrival date is outside trip boundaries.'),
        findsOneWidget);
    expect(find.text('Manual review required'), findsOneWidget);

    final applyBtn = tester.widget<FilledButton>(
      find.byKey(const ValueKey('apply-flight-adjustment-btn')),
    );
    expect(applyBtn.onPressed, isNull);
  });

  // -------------------------------------------------------------
  // FL-UX-04: Protected activity conflict displayed
  // -------------------------------------------------------------
  testWidgets('FL-UX-04: Protected activity conflict displayed in preview',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);
    api.previewResponse = {
      'ok': true,
      'preview': {
        'previewId': 'preview-protected',
        'canApply': true,
        'changes': [
          {
            'activityId': 'act-lock',
            'activityName': 'Pre-booked Clan Jetty Dinner',
            'kind': 'moved',
            'from': {
              'scheduledStartTime': '19:00',
              'scheduledEndTime': '21:00'
            },
            'to': {
              'scheduledStartTime': '19:30',
              'scheduledEndTime': '21:30'
            },
            'protected': true,
            'reason': 'Adjusted timing around flight arrival',
          },
        ],
        'newlyUnscheduled': [],
        'remainingConflicts': [
          {
            'message':
                'Protected Activity: Manual review recommended before changing Clan Jetty Dinner.'
          },
        ],
      },
    };

    await _pumpTripDetails(tester, api);
    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('adjust-flight-itinerary-btn')));

    expect(find.text('Protected Activity — Manual review required'),
        findsOneWidget);
    expect(find.text('Remaining conflicts'), findsOneWidget);
    expect(
        find.textContaining('Protected Activity: Manual review recommended'),
        findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-05: Replace Flight review
  // -------------------------------------------------------------
  testWidgets('FL-UX-05: Replace Flight comparison sheet shows current vs new',
      (tester) async {
    final currentFlight = {
      'airline': 'Malaysia Airlines',
      'flightNumber': 'MH1138',
      'departureAirport': 'KUL',
      'arrivalAirport': 'PEN',
      'departureTime': '08:30',
      'arrivalTime': '09:30',
      'price': 180.0,
    };
    final newFlight = {
      'airline': 'AirAsia',
      'flightNumber': 'AK6112',
      'departureAirport': 'KUL',
      'arrivalAirport': 'PEN',
      'departureTime': '14:00',
      'arrivalTime': '15:00',
      'price': 240.0,
    };
    final trip = _buildSampleTrip(withFlight: true);

    await tester.pumpWidget(_wrap(FlightReplacementSheet(
      currentFlight: currentFlight,
      newFlight: newFlight,
      trip: trip,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Replace Flight'), findsOneWidget);
    expect(find.text('CURRENT'), findsOneWidget);
    expect(find.textContaining('MH1138'), findsOneWidget);
    expect(find.text('NEW SELECTION'), findsOneWidget);
    expect(find.textContaining('AK6112'), findsOneWidget);
    expect(find.text('Fare Difference:'), findsOneWidget);
    expect(find.text('+ RM 60.00'), findsOneWidget);
    expect(find.byKey(const ValueKey('flight-replacement-cancel-btn')),
        findsOneWidget);
    expect(find.byKey(const ValueKey('flight-replacement-confirm-btn')),
        findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-06: Replacement success refreshes Trip
  // -------------------------------------------------------------
  testWidgets('FL-UX-06: Replacement success calls select and refreshes flight',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);

    await _pumpFlightScreen(
      tester,
      api,
      targetTripId: 'trip-pg-1',
      targetTrip: trip,
    );

    await tester.tap(find.text('Search flights'));
    await tester.pumpAndSettle();

    // Tap Select on the second flight (AirAsia AK6112)
    final selectBtns = find.text('Select');
    expect(selectBtns, findsNWidgets(2));
    await tester.tap(selectBtns.at(1));
    await tester.pumpAndSettle();

    // FlightReplacementSheet should appear
    expect(find.text('Replace Flight'), findsOneWidget);

    // Confirm replacement
    await tester
        .tap(find.byKey(const ValueKey('flight-replacement-confirm-btn')));
    await tester.pumpAndSettle();

    expect(api.selectCalls, 1);
    expect(find.textContaining('Flight replaced!'), findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-07: Replacement failure preserves old state
  // -------------------------------------------------------------
  testWidgets('FL-UX-07: Replacement cancellation preserves old state',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);

    await _pumpFlightScreen(
      tester,
      api,
      targetTripId: 'trip-pg-1',
      targetTrip: trip,
    );

    await tester.tap(find.text('Search flights'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Select').last);
    await tester.pumpAndSettle();

    // Cancel replacement
    await tester
        .tap(find.byKey(const ValueKey('flight-replacement-cancel-btn')));
    await tester.pumpAndSettle();

    // Select should NOT have been called
    expect(api.selectCalls, 0);
    // Old flight remains
    expect(trip['selectedFlight']['flightNumber'], 'MH1138');
  });

  // -------------------------------------------------------------
  // FL-UX-08: Remove Flight confirmation
  // -------------------------------------------------------------
  testWidgets('FL-UX-08: Remove Flight confirmation dialog details',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);

    await _pumpTripDetails(tester, api);
    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('remove-flight-btn')));

    expect(find.text('Remove flight from trip?'), findsOneWidget);
    expect(find.textContaining('Flight cost (RM 180.0) will be deducted'),
        findsOneWidget);
    expect(find.text('• Hotel and car rental bookings remain unaffected.'),
        findsOneWidget);
    expect(find.text('• Manually protected activities will stay protected.'),
        findsOneWidget);
    expect(find.byKey(const ValueKey('cancel-remove-flight-btn')),
        findsOneWidget);
    expect(find.byKey(const ValueKey('confirm-remove-flight-btn')),
        findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-09: Removal updates Flight card and Budget
  // -------------------------------------------------------------
  testWidgets('FL-UX-09: Removal removes Flight card and decrements budget',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);

    await _pumpTripDetails(tester, api);
    await _scrollTo(tester, find.text('Attached flight'));
    expect(find.text('Attached flight'), findsOneWidget);

    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('remove-flight-btn')));
    await tester.tap(find.byKey(const ValueKey('confirm-remove-flight-btn')));
    await tester.pumpAndSettle();

    expect(api.removeCalls, 1);
    expect(find.text('Attached flight'), findsNothing);
    expect(find.text('Flight removed from trip. Budget updated.'),
        findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-10: Manual activities remain visible
  // -------------------------------------------------------------
  testWidgets('FL-UX-10: Manual/protected activities remain visible',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);

    await _pumpTripDetails(tester, api);

    // Protected activity is visible
    expect(find.text('Pre-booked Clan Jetty Dinner'), findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-11: Expired/stale preview recovery
  // -------------------------------------------------------------
  testWidgets(
      'FL-UX-11: Expired/stale preview (409) recovers via Refresh Preview',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);
    api.applyException = const ApiException(
      'This preview is stale because the trip or selected flight changed. Create a new preview.',
      409,
      {'code': 'stale_preview'},
    );

    await _pumpTripDetails(tester, api);
    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('adjust-flight-itinerary-btn')));

    // Tap Apply changes -> triggers 409
    await tester.tap(find.byKey(const ValueKey('apply-flight-adjustment-btn')));
    await tester.pumpAndSettle();

    // Banner appears
    expect(
        find.text(
            'Your itinerary has changed. Refresh the preview to review the latest schedule.'),
        findsOneWidget);
    expect(find.text('Stale Preview'), findsOneWidget);

    // Now clear the exception and tap Refresh preview
    api.applyException = null;
    await tester.tap(find.byKey(const ValueKey('refresh-preview-btn')));
    await tester.pumpAndSettle();

    expect(api.previewCalls, 2);
    expect(find.text('Ready to apply'), findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-12: Backend restart preview recovery
  // -------------------------------------------------------------
  testWidgets('FL-UX-12: Lost preview on server restart (404) recovers cleanly',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);
    api.applyException = const ApiException(
      'Preview not found',
      404,
      {'code': 'not_found'},
    );

    await _pumpTripDetails(tester, api);
    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('adjust-flight-itinerary-btn')));

    await tester.tap(find.byKey(const ValueKey('apply-flight-adjustment-btn')));
    await tester.pumpAndSettle();

    expect(
        find.text(
            'Preview expired or server restarted. Please refresh the preview.'),
        findsOneWidget);

    api.applyException = null;
    await tester.tap(find.byKey(const ValueKey('refresh-preview-btn')));
    await tester.pumpAndSettle();

    expect(api.previewCalls, 2);
    expect(find.text('Ready to apply'), findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-13: Outdated async response rejected
  // -------------------------------------------------------------
  testWidgets(
      'FL-UX-13: Outdated async search response rejected when criteria changed',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: false);
    final api = _MockLifecycleApi(trip: trip);

    final slowCompleter = Completer<dynamic>();
    api.delayedSearchCompleter = slowCompleter;

    await _pumpFlightScreen(tester, api);

    // Trigger first search (will hang on completer)
    await tester.tap(find.text('Search flights'));
    await tester.pump();

    // Change arrival airport from PEN to LGK
    await tester.enterText(find.widgetWithText(TextField, 'To'), 'LGK');
    await tester.pump();

    // Complete the first search with old results
    slowCompleter.complete({
      'ok': true,
      'searchId': 'old-search',
      'items': [
        {
          'id': 'old-flight',
          'optionId': 'old-flight',
          'airline': 'OldAir',
          'flightNumber': 'OA001',
          'departureAirport': 'KUL',
          'arrivalAirport': 'PEN',
          'price': 100.0,
        }
      ],
    });
    await tester.pumpAndSettle();

    // The old result 'OA001' must NOT be displayed because criteria changed
    expect(find.textContaining('OA001'), findsNothing);
  });

  // -------------------------------------------------------------
  // FL-UX-14: Duplicate Apply prevented
  // -------------------------------------------------------------
  testWidgets('FL-UX-14: Duplicate Apply prevented via applying lock',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);

    await tester.pumpWidget(_wrap(FlightAdjustmentPreviewSheet(
      api: api,
      tripId: 'trip-pg-1',
      trip: trip,
      initialPreview: {
        'previewId': 'prev-lock',
        'canApply': true,
        'changes': [],
        'newlyUnscheduled': [],
        'remainingConflicts': [],
      },
    )));
    await tester.pumpAndSettle();

    final applyFinder =
        find.byKey(const ValueKey('apply-flight-adjustment-btn'));
    expect(applyFinder, findsOneWidget);

    // Tap once
    await tester.tap(applyFinder);
    await tester.pump();

    // Tap second time while applying
    await tester.tap(applyFinder, warnIfMissed: false);
    await tester.pumpAndSettle();

    // Only 1 apply call was dispatched
    expect(api.applyCalls, 1);
  });

  // -------------------------------------------------------------
  // FL-UX-15: One-way Flight rendering
  // -------------------------------------------------------------
  testWidgets('FL-UX-15: One-way Flight does not invent return information',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true, isOneWay: true);
    final api = _MockLifecycleApi(trip: trip);

    await _pumpTripDetails(tester, api);
    await _scrollTo(tester, find.text('Attached flight'));

    expect(find.text('One-way flight'), findsOneWidget);
    expect(find.textContaining('Return:'), findsNothing);
    expect(find.textContaining('Return date:'), findsNothing);
  });

  // -------------------------------------------------------------
  // FL-UX-16: Travel Records synchronization
  // -------------------------------------------------------------
  testWidgets('FL-UX-16: Travel Records synchronizes with flight presence',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);

    await tester.pumpWidget(_wrap(TravelRecordsScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Flight · KUL → PEN'), findsOneWidget);

    // Remove flight from trip and reload
    trip['selectedFlight'] = null;
    await tester.tap(find.byIcon(Icons.refresh));
    await tester.pumpAndSettle();

    expect(find.text('Flight · KUL → PEN'), findsNothing);
  });

  // -------------------------------------------------------------
  // FL-UX-17: Hotel and Rental cards preserved
  // -------------------------------------------------------------
  testWidgets(
      'FL-UX-17: Hotel and Car Rental cards preserved on flight removal',
      (tester) async {
    final trip = _buildSampleTrip(
      withFlight: true,
      withHotel: true,
      withRental: true,
    );
    final api = _MockLifecycleApi(trip: trip);

    await _pumpTripDetails(tester, api);
    await _scrollTo(tester, find.text('Attached flight'));

    expect(find.text('Attached flight'), findsOneWidget);
    expect(find.text('Attached hotel'), findsOneWidget);
    expect(find.text('Eastern & Oriental Hotel'), findsOneWidget);
    expect(find.text('Attached car rental'), findsOneWidget);
    expect(find.text('Perodua Myvi 1.5 AV'), findsOneWidget);

    // Remove flight
    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('remove-flight-btn')));
    await tester.tap(find.byKey(const ValueKey('confirm-remove-flight-btn')));
    await tester.pumpAndSettle();

    // Flight removed, hotel and rental remain intact
    expect(find.text('Attached flight'), findsNothing);
    expect(find.text('Attached hotel'), findsOneWidget);
    expect(find.text('Eastern & Oriental Hotel'), findsOneWidget);
    expect(find.text('Attached car rental'), findsOneWidget);
    expect(find.text('Perodua Myvi 1.5 AV'), findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-18: Network/loading/error states
  // -------------------------------------------------------------
  testWidgets('FL-UX-18: Preview network error displayed gracefully',
      (tester) async {
    final trip = _buildSampleTrip(withFlight: true);
    final api = _MockLifecycleApi(trip: trip);
    api.previewException = const ApiException(
      'Unable to connect to server. Please check your network.',
      503,
      {'code': 'network_error'},
    );

    await _pumpTripDetails(tester, api);
    await _ensureVisibleAndTap(
        tester, find.byKey(const ValueKey('adjust-flight-itinerary-btn')));

    expect(
        find.textContaining('Unable to connect to server'), findsOneWidget);
    expect(find.byKey(const ValueKey('refresh-preview-btn')), findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-19: No unsupported Flight Pay button
  // -------------------------------------------------------------
  testWidgets('FL-UX-19: No fake flight pay or airline checkout button exists',
      (tester) async {
    final flight = {
      'airline': 'Malaysia Airlines',
      'flightNumber': 'MH1138',
      'departureAirport': 'KUL',
      'arrivalAirport': 'PEN',
      'departureTime': '08:30',
      'arrivalTime': '09:30',
      'price': 180.0,
      'currency': 'MYR',
    };

    await tester.pumpWidget(_wrap(FlightDetailsScreen(flight: flight)));
    await tester.pumpAndSettle();

    expect(find.text('Pay for flight'), findsNothing);
    expect(find.text('Flight checkout'), findsNothing);
    expect(find.text('Buy Ticket'), findsNothing);
    expect(
        find.textContaining(
            'TravelMate supports flight planning estimates, but cannot issue airline tickets'),
        findsOneWidget);
  });

  // -------------------------------------------------------------
  // FL-UX-20: Accessibility and layout checks
  // -------------------------------------------------------------
  testWidgets('FL-UX-20: Layout adapts to compact screen without overflow',
      (tester) async {
    final currentFlight = {
      'airline': 'Malaysia Airlines',
      'flightNumber': 'MH1138',
      'departureAirport': 'KUL',
      'arrivalAirport': 'PEN',
      'departureTime': '08:30',
      'arrivalTime': '09:30',
      'price': 180.0,
    };
    final newFlight = {
      'airline': 'AirAsia',
      'flightNumber': 'AK6112',
      'departureAirport': 'KUL',
      'arrivalAirport': 'PEN',
      'departureTime': '14:00',
      'arrivalTime': '15:00',
      'price': 240.0,
    };
    final trip = _buildSampleTrip(withFlight: true);

    // Test compact viewport (360x640)
    await tester.pumpWidget(_wrap(
      FlightReplacementSheet(
        currentFlight: currentFlight,
        newFlight: newFlight,
        trip: trip,
      ),
      size: const Size(360, 640),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Replace Flight'), findsOneWidget);
    expect(find.text('Confirm Replacement'), findsOneWidget);
    // Verify no RenderFlex overflow exception
    expect(tester.takeException(), isNull);
  });
}
