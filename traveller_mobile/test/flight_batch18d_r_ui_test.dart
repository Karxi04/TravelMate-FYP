import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_details_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

void _setViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 5000);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(() => tester.view.resetPhysicalSize());
}

Widget _wrap(Widget child) {
  return MaterialApp(
    home: child,
  );
}

class _Mock18DRApi extends ApiService {
  Map<String, dynamic>? searchResponse;
  Map<String, dynamic>? returnsResponse;
  Map<String, dynamic>? selectResponse;
  Map<String, dynamic>? tripsResponse;

  ApiException? selectException;
  bool acknowledgeRequired = false;
  int selectCallCount = 0;

  final List<String> getPaths = [];
  final List<String> postPaths = [];
  final List<Map<String, dynamic>?> postBodies = [];

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    getPaths.add(path);
    if (path == '/api/fr7/flights/search') {
      return searchResponse ?? {
        'ok': true,
        'searchId': 'search_mock_18dr',
        'source': 'serpapi',
        'sourceLabel': 'Provider search result',
        'retrievedAt': DateTime.now().toUtc().toIso8601String(),
        'expiresAt': DateTime.now().add(const Duration(minutes: 15)).toUtc().toIso8601String(),
        'freshnessStatus': 'provider_cache_possible',
        'planningOnly': true,
        'items': [
          {
            'id': 'flight_out_18dr',
            'optionId': 'flight_out_18dr',
            'airline': 'Malaysia Airlines',
            'flightNumber': 'MH1138',
            'departureAirport': 'KUL',
            'arrivalAirport': 'PEN',
            'departureTime': '08:10',
            'arrivalTime': '09:10',
            'durationMinutes': 60,
            'stopText': 'Nonstop',
            'price': 256.0,
            'currency': 'MYR',
            'outboundDate': '2026-11-20',
            'roundTripComplete': false,
            'quoteCompleteness': 'return_selection_pending',
          }
        ],
      };
    }

    if (path == '/api/fr5/itineraries') {
      return tripsResponse ?? {
        'ok': true,
        'items': [
          {
            'id': 'trip_penang_oct',
            'title': 'My Personalised Penang Trip',
            'startDate': '2026-10-31',
            'endDate': '2026-11-03',
            'budgetLimit': 2500.0,
            'flightCost': 0,
            'selectedFlight': null,
          },
          {
            'id': 'trip_penang_nov',
            'title': 'Penang Late November Trip',
            'startDate': '2026-11-19',
            'endDate': '2026-11-25',
            'budgetLimit': 3000.0,
            'flightCost': 0,
            'selectedFlight': null,
          },
        ],
      };
    }

    if (path == '/api/fr9/payments') {
      return {'ok': true, 'items': []};
    }

    if (path == '/api/fr9/orders') {
      return {'ok': true, 'items': []};
    }

    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [dynamic body]) async {
    postPaths.add(path);
    postBodies.add(body is Map<String, dynamic> ? body : null);

    if (path == '/api/fr7/flights/select') {
      selectCallCount++;
      if (selectException != null) {
        throw selectException!;
      }
      if (acknowledgeRequired) {
        if (body is Map && body['acknowledgeConflicts'] == true) {
          return selectResponse ?? {
            'ok': true,
            'itinerary': {'id': 'trip_penang_nov', 'flightConflictStatus': 'acknowledged'},
            'budget': {'total': 850.0},
          };
        }
        throw const ApiException(
          'Flight conflicts require acknowledgement',
          409,
          {
            'ok': false,
            'error': 'Flight conflicts require acknowledgement',
            'status': 'conflicts_require_acknowledgement',
            'conflicts': [
              {
                'type': 'activity_overlap',
                'message': 'Flight overlaps with planned activity at 09:00',
              }
            ],
          },
        );
      }
      return selectResponse ?? {
        'ok': true,
        'itinerary': {
          'id': 'trip_penang_nov',
          'flightOptionId': 'flight_completed_18dr_valid',
        },
        'budget': {'total': 850.0},
      };
    }

    return {'ok': true};
  }
}

Future<void> _searchAndSelect(WidgetTester tester, {String tripName = 'My Personalised Penang Trip'}) async {
  await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
  await tester.pumpAndSettle();
  await tester.tap(find.widgetWithText(FilledButton, 'Select'));
  await tester.pumpAndSettle();
  await tester.tap(find.text(tripName));
  await tester.pumpAndSettle();
}

Map<String, dynamic> _makeTrip({
  required String id,
  required String title,
  required String startDate,
  required String endDate,
  String flightOptionId = 'flight_completed_mh1138_ak6117',
  double flightCost = 256.0,
  String outboundDate = '2026-11-20',
  String returnDate = '2026-11-23',
  String costProvenanceFlight = 'confirmed_total',
  String costProvenanceHotel = 'confirmed_total',
}) {
  return {
    'id': id,
    'title': title,
    'startDate': startDate,
    'endDate': endDate,
    'budgetLimit': 2500.0,
    'flightSearchId': 'search_mock_18dr',
    'flightOptionId': flightOptionId,
    'flightCost': flightCost,
    'budgetEstimate': {
      'total': 556.0,
      'limit': 2500.0,
      'hotel': 300.0,
      'flight': flightCost,
      'costProvenance': {
        'hotel': costProvenanceHotel,
        'flight': costProvenanceFlight,
        'food': 'estimated_daily_allowance',
        'transport': 'estimated_daily_allowance',
      },
    },
    'selectedFlight': {
      'airline': 'Malaysia Airlines',
      'flightNumber': 'MH1138',
      'departureAirport': 'KUL',
      'arrivalAirport': 'PEN',
      'departureTime': '08:10',
      'arrivalTime': '09:10',
      'outboundDate': outboundDate,
      'returnDate': returnDate,
      'price': flightCost,
      'tripType': 'round_trip',
      'roundTripComplete': true,
      'outboundSegments': [
        {
          'departureAirportCode': 'KUL',
          'arrivalAirportCode': 'PEN',
          'departureDate': outboundDate,
          'arrivalDate': outboundDate,
          'departureTime': '08:10',
          'arrivalTime': '09:10',
        }
      ],
      'returnSegments': [
        {
          'departureAirportCode': 'PEN',
          'arrivalAirportCode': 'KUL',
          'departureDate': returnDate,
          'arrivalDate': returnDate,
          'departureTime': '18:50',
          'arrivalTime': '19:55',
        }
      ],
    },
  };
}

Future<void> _pumpTripDetails(WidgetTester tester, Map<String, dynamic> trip, _Mock18DRApi api) async {
  api.tripsResponse = {'ok': true, 'items': [trip]};
  await tester.pumpWidget(_wrap(TripDetailsScreen(
    key: ValueKey('trip-${trip['id']}-${trip['startDate']}'),
    tripId: trip['id'] as String,
    api: api,
  )));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Batch 18D-R-UI Regression Tests', () {
    testWidgets('1. HTTP 409 flight_trip_date_mismatch dialog renders with title and explanation', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {
          'ok': false,
          'code': 'flight_trip_date_mismatch',
          'error': 'Selected flight dates must fall within the Trip dates.',
          'status': 'hard_conflict',
          'tripDates': {'startDate': '2026-10-31', 'endDate': '2026-11-03'},
          'flightDates': ['2026-11-20', '2026-11-23'],
          'conflicts': [
            {
              'type': 'flight_dates',
              'segmentType': 'outbound',
              'flightDate': '2026-11-20',
              'tripStartDate': '2026-10-31',
              'tripEndDate': '2026-11-03',
              'message': 'Selected flight dates must fall within the Trip dates.',
            }
          ],
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(find.byKey(const ValueKey('flight-date-conflict-dialog')), findsOneWidget);
      expect(find.text('Flight Dates Mismatch'), findsOneWidget);
      expect(find.textContaining('These flights fall outside your selected Trip dates'), findsOneWidget);
    });

    testWidgets('2. Correct display of Trip dates', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {
          'ok': false,
          'code': 'flight_trip_date_mismatch',
          'error': 'Selected flight dates must fall within the Trip dates.',
          'status': 'hard_conflict',
          'tripDates': {'startDate': '2026-10-31', 'endDate': '2026-11-03'},
          'flightDates': ['2026-11-20', '2026-11-23'],
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(find.text('Trip Dates'), findsOneWidget);
      expect(find.text('2026-10-31 to 2026-11-03'), findsOneWidget);
    });

    testWidgets('3. Correct display of Flight dates', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {
          'ok': false,
          'code': 'flight_trip_date_mismatch',
          'error': 'Selected flight dates must fall within the Trip dates.',
          'status': 'hard_conflict',
          'tripDates': {'startDate': '2026-10-31', 'endDate': '2026-11-03'},
          'flightDates': ['2026-11-20', '2026-11-23'],
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(find.text('Flight Dates'), findsOneWidget);
      expect(find.text('2026-11-20, 2026-11-23'), findsOneWidget);
    });

    testWidgets('4. Hard conflict rejects attachment', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {
          'ok': false,
          'code': 'flight_trip_date_mismatch',
          'status': 'hard_conflict',
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(api.selectCallCount, equals(1));
    });

    testWidgets('5. Hard conflict cannot be acknowledged away', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {
          'ok': false,
          'code': 'flight_trip_date_mismatch',
          'status': 'hard_conflict',
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(find.text('Keep flight'), findsNothing);
      expect(find.byKey(const ValueKey('back-to-flight-results-button')), findsOneWidget);
      expect(find.byKey(const ValueKey('choose-another-trip-button')), findsOneWidget);
    });

    testWidgets('6. No successful attachment message on rejection', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {
          'ok': false,
          'code': 'flight_trip_date_mismatch',
          'status': 'hard_conflict',
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(find.byType(SnackBar), findsNothing);
      expect(find.textContaining('Flight attached'), findsNothing);
    });

    testWidgets('7. Choose Another Trip action works', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {
          'ok': false,
          'code': 'flight_trip_date_mismatch',
          'status': 'hard_conflict',
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      await tester.tap(find.byKey(const ValueKey('choose-another-trip-button')));
      await tester.pumpAndSettle();

      expect(find.text('Attach flight to itinerary'), findsOneWidget);
      expect(find.text('Penang Late November Trip'), findsOneWidget);
    });

    testWidgets('8. Back to Flight Results action works', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {
          'ok': false,
          'code': 'flight_trip_date_mismatch',
          'status': 'hard_conflict',
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      await tester.tap(find.byKey(const ValueKey('back-to-flight-results-button')));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('flight-date-conflict-dialog')), findsNothing);
      expect(find.text('Malaysia Airlines MH1138'), findsOneWidget);
    });

    testWidgets('9. invalid_trip_dates handled', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'The target Trip must have a valid startDate and endDate before attaching a flight.',
        409,
        {
          'ok': false,
          'code': 'invalid_trip_dates',
          'error': 'The target Trip must have a valid startDate and endDate before attaching a flight.',
          'status': 'hard_conflict',
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(find.byKey(const ValueKey('flight-date-conflict-dialog')), findsOneWidget);
      expect(find.textContaining('valid startDate and endDate'), findsOneWidget);
    });

    testWidgets('10. invalid_flight_dates handled', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'The selected flight has incomplete segment date information.',
        409,
        {
          'ok': false,
          'code': 'invalid_flight_dates',
          'error': 'The selected flight has incomplete segment date information.',
          'status': 'hard_conflict',
        },
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(find.byKey(const ValueKey('flight-date-conflict-dialog')), findsOneWidget);
      expect(find.textContaining('incomplete segment date information'), findsOneWidget);
    });

    testWidgets('11. Existing acknowledgeable activity warning continues working', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.acknowledgeRequired = true;

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester, tripName: 'Penang Late November Trip');

      expect(find.text('Review itinerary timing'), findsOneWidget);
      expect(find.text('Keep flight'), findsOneWidget);

      await tester.tap(find.text('Keep flight'));
      await tester.pumpAndSettle();

      expect(api.selectCallCount, equals(2));
      expect(api.postBodies.last?['acknowledgeConflicts'], isTrue);
      expect(find.byType(SnackBar), findsOneWidget);
    });

    testWidgets('12. Successful valid Flight selection remains working', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester, tripName: 'Penang Late November Trip');

      expect(find.byType(SnackBar), findsOneWidget);
      expect(find.textContaining('Flight attached to trip plan! Estimated trip total: RM 850'), findsOneWidget);
    });

    testWidgets('13. Completed round-trip ID propagated correctly', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      final trip = _makeTrip(
        id: 'trip_penang_nov',
        title: 'Penang Late November Trip',
        startDate: '2026-11-19',
        endDate: '2026-11-25',
        flightOptionId: 'flight_completed_mh1138_ak6117',
        flightCost: 550.0,
      );

      await _pumpTripDetails(tester, trip, api);

      expect(find.text('Malaysia Airlines MH1138'), findsOneWidget);
      expect(find.text('Flight cost: RM 550.0'), findsOneWidget);
    });

    testWidgets('14. Historical outbound-style ID remains readable', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      final trip = _makeTrip(
        id: 'trip_penang_oct',
        title: 'My Personalised Penang Trip',
        startDate: '2026-11-20',
        endDate: '2026-11-25',
        flightOptionId: 'AirAsia-AK_6114-2026-11-20_08_05-0',
        flightCost: 256.0,
      );

      await _pumpTripDetails(tester, trip, api);

      expect(find.text('Malaysia Airlines MH1138'), findsOneWidget);
      expect(find.text('Flight cost: RM 256.0'), findsOneWidget);
    });

    testWidgets('15. Existing mismatched saved Trip remains readable', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      final trip = _makeTrip(
        id: 'trip_penang_oct',
        title: 'My Personalised Penang Trip',
        startDate: '2026-10-31',
        endDate: '2026-11-03',
        outboundDate: '2026-11-20',
        returnDate: '2026-11-23',
      );

      await _pumpTripDetails(tester, trip, api);

      expect(find.text('My Personalised Penang Trip'), findsOneWidget);
      expect(find.text('Attached flight'), findsOneWidget);
    });

    testWidgets('16. Historical mismatch warning is accurate', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();

      // Trip dates: 2026-10-31 to 2026-11-03, Flight dates: 2026-11-20 to 2026-11-23 -> Mismatch!
      final mismatchedTrip = _makeTrip(
        id: 'trip_penang_oct',
        title: 'My Personalised Penang Trip',
        startDate: '2026-10-31',
        endDate: '2026-11-03',
        outboundDate: '2026-11-20',
        returnDate: '2026-11-23',
      );

      await _pumpTripDetails(tester, mismatchedTrip, api);

      expect(find.byKey(const ValueKey('flight-date-mismatch-warning')), findsOneWidget);
      expect(find.text("Flight dates do not match this Trip's dates. Review your travel plan before relying on this itinerary."), findsOneWidget);

      // Now test matching trip: warning should NOT appear
      final matchingTrip = _makeTrip(
        id: 'trip_penang_matching',
        title: 'Matching Trip',
        startDate: '2026-11-19',
        endDate: '2026-11-25',
        outboundDate: '2026-11-20',
        returnDate: '2026-11-23',
      );

      await _pumpTripDetails(tester, matchingTrip, api);

      expect(find.byKey(const ValueKey('flight-date-mismatch-warning')), findsNothing);
    });

    testWidgets('17. No existing Trip data is overwritten by error handling', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      api.selectException = const ApiException(
        'Selected flight dates must fall within the Trip dates.',
        409,
        {'ok': false, 'code': 'flight_trip_date_mismatch', 'status': 'hard_conflict'},
      );

      await tester.pumpWidget(_wrap(FlightScreen(api: api)));
      await tester.pumpAndSettle();

      await _searchAndSelect(tester);

      expect(api.postPaths.where((p) => p.startsWith('/api/fr5/itineraries')), isEmpty);
    });

    testWidgets('18. Budget shows planning estimate instead of confirmed booking', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      final trip = _makeTrip(
        id: 'trip_penang_oct',
        title: 'My Personalised Penang Trip',
        startDate: '2026-10-31',
        endDate: '2026-11-03',
        costProvenanceFlight: 'confirmed_total',
      );

      await _pumpTripDetails(tester, trip, api);

      expect(find.text('RM 256.00'), findsOneWidget);
      expect(find.text('Incomplete estimate'), findsOneWidget);
      expect(find.text('confirmed · RM 256'), findsNothing);
    });

    testWidgets('19. Budget amount remains server-authoritative', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      final trip = _makeTrip(
        id: 'trip_penang_oct',
        title: 'My Personalised Penang Trip',
        startDate: '2026-10-31',
        endDate: '2026-11-03',
      );

      await _pumpTripDetails(tester, trip, api);

      expect(find.text('Known estimated subtotal: RM 556.00'), findsOneWidget);
    });

    testWidgets('20. Hotel and Package budget labels are unaffected', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      final trip = _makeTrip(
        id: 'trip_penang_oct',
        title: 'My Personalised Penang Trip',
        startDate: '2026-10-31',
        endDate: '2026-11-03',
        costProvenanceHotel: 'confirmed_total',
      );

      await _pumpTripDetails(tester, trip, api);

      expect(find.text('Hotel'), findsOneWidget);
      expect(find.text('RM 300.00'), findsOneWidget);
      expect(find.text('confirmed · RM 300'), findsNothing);
    });

    testWidgets('21. Flight Checkout remains unavailable', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();

      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'flight',
        searchId: 'search_mock_18dr',
        optionId: 'flight_completed_18dr',
        initialAmount: 256.0,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Payments unavailable'), findsOneWidget);
      expect(find.textContaining('Checkout is unavailable for this selection'), findsOneWidget);
      expect(find.text('Continue to Payment'), findsNothing);
      expect(find.text('View Travel Records'), findsOneWidget);
    });

    testWidgets('22. No fake airline ticket or PNR is displayed', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      final trip = _makeTrip(
        id: 'trip_penang_oct',
        title: 'My Personalised Penang Trip',
        startDate: '2026-10-31',
        endDate: '2026-11-03',
      );

      await _pumpTripDetails(tester, trip, api);

      expect(find.textContaining('PNR'), findsNothing);
      expect(find.textContaining('Booking Reference:'), findsNothing);
      expect(find.textContaining('Ticket Number:'), findsNothing);
      expect(find.text('Planning estimate only • No airline ticket issued'), findsOneWidget);
    });

    testWidgets('23. No duplicate Flight cost', (tester) async {
      _setViewport(tester);
      final api = _Mock18DRApi();
      final trip = _makeTrip(
        id: 'trip_penang_oct',
        title: 'My Personalised Penang Trip',
        startDate: '2026-10-31',
        endDate: '2026-11-03',
        flightCost: 256.0,
      );

      await _pumpTripDetails(tester, trip, api);

      expect(find.text('Flight cost: RM 256.0'), findsOneWidget);
    });

    testWidgets('24. No sensitive provider tokens are exposed', (tester) async {
      _setViewport(tester);

      await tester.pumpWidget(_wrap(FlightDetailsScreen(
        onSelect: () {},
        flight: {
          'airline': 'Malaysia Airlines',
          'flightNumber': 'MH1138',
          'departureAirport': 'KUL',
          'arrivalAirport': 'PEN',
          'departureTime': '08:10',
          'arrivalTime': '09:10',
          'durationMinutes': 60,
          'price': 256.0,
          'currency': 'MYR',
          'departureToken': 'SECRET_PROVIDER_DEPARTURE_TOKEN_XYZ',
          'bookingToken': 'SECRET_PROVIDER_BOOKING_TOKEN_123',
        },
      )));
      await tester.pumpAndSettle();

      expect(find.textContaining('SECRET_PROVIDER'), findsNothing);
      expect(find.textContaining('departureToken'), findsNothing);
      expect(find.textContaining('bookingToken'), findsNothing);
    });
  });
}
