import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_details_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

void _setViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(() => tester.view.resetPhysicalSize());
}

Widget _wrap(Widget child) {
  return MaterialApp(
    home: child,
  );
}

Future<void> _showAttachedFlight(WidgetTester tester) async {
  await tester.scrollUntilVisible(find.text('Attached flight'), 250,
      scrollable: find.descendant(
        of: find.byKey(const ValueKey('trip-details-scroll')),
        matching: find.byType(Scrollable),
      ).first);
  await tester.pumpAndSettle();
}

class _MockFlightApi extends ApiService {
  Map<String, dynamic>? searchResponse;
  Completer<Map<String, dynamic>>? pendingSearch;
  Map<String, dynamic>? returnsResponse;
  Map<String, dynamic>? detailsResponse;
  Completer<Map<String, dynamic>>? pendingDetails;
  Map<String, dynamic>? selectResponse;
  Map<String, dynamic>? tripResponse;
  Map<String, dynamic>? tripsResponse;
  Map<String, dynamic>? paymentsResponse;
  Map<String, dynamic>? ordersResponse;
  Map<String, dynamic>? checkoutSessionResponse;

  bool shouldThrowExpired = false;
  bool shouldThrowTicketingUnavailable = false;
  bool shouldThrowValidation = false;
  bool shouldThrowNetwork = false;

  final List<String> getPaths = [];
  final List<Map<String, String>?> getQueries = [];
  final List<String> postPaths = [];
  final List<Map<String, dynamic>?> postBodies = [];

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    getPaths.add(path);
    getQueries.add(query);

    if (shouldThrowNetwork) {
      throw TimeoutException('Network timed out');
    }

    if (path == '/api/fr7/flights/search') {
      if (pendingSearch != null) return pendingSearch!.future;
      if (shouldThrowValidation) {
        throw const ApiException(
          'Use different 3-letter airports and current or future flight dates',
          400,
          {'ok': false, 'code': 'invalid_flight_search', 'error': 'Invalid search'},
        );
      }
      return searchResponse ?? {
        'ok': true,
        'searchId': 'search_mock_1',
        'source': 'serpapi',
        'sourceLabel': 'Provider search result',
        'retrievedAt': DateTime.now().toUtc().toIso8601String(),
        'expiresAt': DateTime.now().add(const Duration(minutes: 15)).toUtc().toIso8601String(),
        'freshnessStatus': 'provider_cache_possible',
        'planningOnly': true,
        'items': [
          {
            'id': 'flight_out_1',
            'optionId': 'flight_out_1',
            'airline': 'Malaysia Airlines',
            'flightNumber': 'MH1138',
            'departureAirport': 'KUL',
            'arrivalAirport': 'PEN',
            'departureTime': '08:10',
            'arrivalTime': '09:10',
            'durationMinutes': 60,
            'stopText': 'Nonstop',
            'price': 220.0,
            'currency': 'MYR',
            'outboundDate': '2027-02-10',
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
            'id': 'trip_mock_1',
            'title': 'Penang Getaway',
            'budgetLimit': 2500.0,
            'flightCost': 0,
            'selectedFlight': null,
          }
        ],
      };
    }

    if (path.startsWith('/api/fr5/itineraries/')) {
      return tripResponse ?? {
        'ok': true,
        'itinerary': {
          'id': 'trip_mock_1',
          'title': 'Penang Getaway',
          'budgetLimit': 2500.0,
          'flightSearchId': 'search_mock_1',
          'flightOptionId': 'flight_completed_out_ret',
          'flightCost': 550.0,
          'selectedFlight': {
            'airline': 'Malaysia Airlines',
            'flightNumber': 'MH1138',
            'departureAirport': 'KUL',
            'arrivalAirport': 'PEN',
            'departureTime': '08:10',
            'arrivalTime': '09:10',
            'tripType': 'round_trip',
            'roundTripComplete': true,
            'price': 550.0,
            'outboundSegments': [
              {
                'departureAirportCode': 'KUL',
                'arrivalAirportCode': 'PEN',
                'departureTime': '08:10',
                'arrivalTime': '09:10',
                'airline': 'Malaysia Airlines',
                'flightNumber': 'MH1138',
              }
            ],
            'returnSegments': [
              {
                'departureAirportCode': 'PEN',
                'arrivalAirportCode': 'KUL',
                'departureTime': '18:50',
                'arrivalTime': '19:55',
                'airline': 'AirAsia',
                'flightNumber': 'AK6117',
              }
            ],
          },
        },
      };
    }

    if (path == '/api/fr9/payments') {
      return paymentsResponse ?? {'ok': true, 'items': []};
    }

    if (path == '/api/fr9/orders') {
      return ordersResponse ?? {'ok': true, 'items': []};
    }

    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [dynamic body]) async {
    postPaths.add(path);
    postBodies.add(body is Map<String, dynamic> ? body : null);

    if (shouldThrowNetwork) {
      throw TimeoutException('Network timed out');
    }

    if (path == '/api/fr7/flights/returns') {
      if (shouldThrowExpired) {
        throw const ApiException(
          'This flight quote has expired. Search again.',
          409,
          {'ok': false, 'code': 'flight_quote_expired', 'error': 'Quote expired'},
        );
      }
      return returnsResponse ?? {
        'ok': true,
        'searchId': 'search_mock_1',
        'items': [
          {
            'id': 'return_opt_1',
            'optionId': 'return_opt_1',
            'airline': 'Malaysia Airlines',
            'flightNumber': 'MH1145',
            'departureAirport': 'PEN',
            'arrivalAirport': 'KUL',
            'departureTime': '14:20',
            'arrivalTime': '15:25',
            'durationMinutes': 65,
            'stopText': 'Nonstop',
            'price': 420.0,
            'combinedPrice': 420.0,
            'currency': 'MYR',
            'returnSegments': [
              {
                'departureAirportCode': 'PEN',
                'arrivalAirportCode': 'KUL',
                'departureDate': '2027-02-12',
                'departureTime': '14:20',
                'arrivalTime': '15:25',
              }
            ],
          },
          {
            'id': 'return_opt_2',
            'optionId': 'return_opt_2',
            'airline': 'AirAsia',
            'flightNumber': 'AK6117',
            'departureAirport': 'PEN',
            'arrivalAirport': 'KUL',
            'departureTime': '18:50',
            'arrivalTime': '19:55',
            'durationMinutes': 65,
            'stopText': 'Nonstop',
            'price': 550.0,
            'combinedPrice': 550.0,
            'currency': 'MYR',
            'returnSegments': [
              {
                'departureAirportCode': 'PEN',
                'arrivalAirportCode': 'KUL',
                'departureDate': '2027-02-12',
                'departureTime': '18:50',
                'arrivalTime': '19:55',
              }
            ],
          },
        ],
      };
    }

    if (path == '/api/fr7/flights/details') {
      if (pendingDetails != null) return pendingDetails!.future;
      return detailsResponse ?? {
        'ok': true,
        'flight': {
          'id': 'flight_detail_1',
          'airline': 'Malaysia Airlines',
          'flightNumber': 'MH1138',
          'departureAirport': 'KUL',
          'arrivalAirport': 'PEN',
          'departureTime': '08:10',
          'arrivalTime': '09:10',
          'durationMinutes': 60,
          'price': 220.0,
          'currency': 'MYR',
        },
      };
    }

    if (path == '/api/fr7/flights/select') {
      if (shouldThrowExpired) {
        throw const ApiException(
          'This flight quote has expired. Search again.',
          409,
          {'ok': false, 'code': 'flight_quote_expired', 'error': 'Quote expired'},
        );
      }
      return selectResponse ?? {
        'ok': true,
        'itinerary': {
          'id': 'trip_mock_1',
          'flightSearchId': 'search_mock_1',
          'flightOptionId': 'flight_completed_1',
          'flightCost': 550.0,
        },
        'budget': {
          'flight': 550.0,
          'total': 850.0,
        },
      };
    }

    if (path == '/api/fr9/checkout/session') {
      if (shouldThrowTicketingUnavailable || (body is Map && body['quoteType'] == 'flight')) {
        throw const ApiException(
          'TravelMate can save this fare as a planning estimate, but cannot issue or reserve an airline ticket.',
          409,
          {'ok': false, 'code': 'flight_ticketing_unavailable', 'error': 'Ticketing unavailable'},
        );
      }
      return checkoutSessionResponse ?? {
        'ok': true,
        'order': {
          'id': 'order_123',
          'status': 'checkout_open',
          'checkoutUrl': 'https://checkout.stripe.test/123',
          'checkoutAction': 'continue_payment',
        },
      };
    }

    return {'ok': true};
  }
}

void main() {
  testWidgets('F-F1A review shows whole return fare before any Trip mutation', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    final dynamic state = tester.state(find.byType(FlightScreen));
    await state.search();
    final future = state.selectFlight(Map<String, dynamic>.from(state.items.first as Map),
      returnOption: {'optionId': 'return-fixture', 'combinedPrice': 450});
    await tester.pumpAndSettle();
    expect(find.textContaining('Selected offer estimate: MYR 450'), findsOneWidget);
    expect(find.textContaining('not an airline ticket'), findsOneWidget);
    expect(api.postPaths, isEmpty);
    tester.state<NavigatorState>(find.byType(Navigator).first).pop();
    await tester.pumpAndSettle();
    await future;
  });

  testWidgets('F-B2 changed inputs discard in-flight flight details', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi()..pendingDetails = Completer<Map<String, dynamic>>();
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    final dynamic state = tester.state(find.byType(FlightScreen));
    await state.search();
    final flight = Map<String, dynamic>.from(state.items.first as Map);
    final Future<void> request = state.showDetails(flight);
    state.travellers.text = '2';
    api.pendingDetails!.complete({'ok': true, 'flight': flight});
    await tester.pumpAndSettle();
    expect(find.byType(FlightDetailsScreen), findsNothing);
    await request;
  });

  testWidgets('F-B2 blank origin makes no flight request', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    final dynamic state = tester.state(find.byType(FlightScreen));
    state.from.text = '';
    await state.search();
    await tester.pumpAndSettle();
    expect(api.getPaths, isEmpty);
    expect(find.textContaining('Enter 3-letter airport codes'), findsOneWidget);
  });

  testWidgets('F-B2 changed inputs discard an in-flight flight response', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi()..pendingSearch = Completer<Map<String, dynamic>>();
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    final dynamic state = tester.state(find.byType(FlightScreen));
    final Future<void> request = state.search();
    state.travellers.text = '2';
    api.pendingSearch!.complete({'ok': true, 'searchId': 'obsolete', 'items': [
      {'id': 'old', 'airline': 'Obsolete result', 'price': 180, 'currency': 'MYR'}
    ]});
    await request;
    await tester.pumpAndSettle();
    expect(state.items, isEmpty);
    expect(state.searchId, isEmpty);
    expect(api.postPaths, isEmpty);
  });

  testWidgets('F-B2 returning from Flights reloads Trip and keeps injected API', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_mock_1', api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Flights'), 250,
        scrollable: find.descendant(of: find.byKey(const ValueKey('trip-details-scroll')),
            matching: find.byType(Scrollable)).first);
    final reads = api.getPaths.where((path) => path == '/api/fr5/itineraries').length;
    await tester.tap(find.text('Flights'));
    await tester.pumpAndSettle();
    expect(tester.widget<FlightScreen>(find.byType(FlightScreen)).api, same(api));
    tester.state<NavigatorState>(find.byType(Navigator).first).pop();
    await tester.pumpAndSettle();
    expect(api.getPaths.where((path) => path == '/api/fr5/itineraries').length, reads + 1);
  });

  testWidgets('F-B2 saved hotel reopens without inventing cancellation or supplier state', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    api.tripsResponse = {'ok': true, 'items': [{
      'id': 'trip_mock_1', 'title': 'Saved trip', 'activities': [], 'budgetLimit': 2000,
      'hotelCost': 420, 'hotelBookingId': 'synthetic-record',
      'selectedHotel': {'name': 'Saved Property', 'roomName': 'Saved Room', 'price': 420,
        'priceStatus': 'available', 'currency': 'MYR', 'checkin': '2030-01-01', 'checkout': '2030-01-03'},
    }]};
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_mock_1', api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Attached hotel'), 250,
        scrollable: find.descendant(of: find.byKey(const ValueKey('trip-details-scroll')),
            matching: find.byType(Scrollable)).first);
    expect(find.textContaining('Non-refundable'), findsNothing);
    await tester.ensureVisible(find.text('View details').last);
    await tester.tap(find.text('View details').last);
    await tester.pumpAndSettle();
    expect(find.text('Select room'), findsNothing);
    expect(find.textContaining('2030-01-03'), findsWidgets);
    expect(api.postPaths, isEmpty);
  });

  testWidgets('F-B2 changed passenger count invalidates displayed quote', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();
    expect(find.text('Malaysia Airlines MH1138'), findsOneWidget);
    final dynamic state = tester.state(find.byType(FlightScreen));
    state.travellers.text = '2';
    await tester.pumpAndSettle();
    expect(find.text('Malaysia Airlines MH1138'), findsNothing);
    expect(api.postPaths, isEmpty);
  });

  // 1. One-way Flight search results render
  testWidgets('1. One-way Flight search results render', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    expect(find.text('Malaysia Airlines MH1138'), findsOneWidget);
    expect(find.text('MYR 220.0'), findsOneWidget);
    expect(find.text('Select'), findsOneWidget);
  });

  // 2. Round-trip search results render
  testWidgets('2. Round-trip search results render', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api, initialReturnDate: '2027-02-12')));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    expect(find.text('Malaysia Airlines MH1138'), findsOneWidget);
    expect(find.text('From MYR 220.0'), findsOneWidget);
    expect(find.text('Round-trip estimate • Choose return for final fare'), findsOneWidget);
    expect(find.text('Choose return'), findsOneWidget);
  });

  // 3. Outbound selection opens correct return options
  testWidgets('3. Outbound selection opens correct return options', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api, initialReturnDate: '2027-02-12')));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Choose return'));
    await tester.pumpAndSettle();

    expect(api.postPaths, contains('/api/fr7/flights/returns'));
    expect(find.text('Choose your return flight'), findsOneWidget);
    expect(find.text('Malaysia Airlines MH1145'), findsOneWidget);
    expect(find.text('AirAsia AK6117'), findsOneWidget);
  });

  // 4. Different return options display different completed fares
  testWidgets('4. Different return options display different completed fares', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api, initialReturnDate: '2027-02-12')));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Choose return'));
    await tester.pumpAndSettle();

    expect(find.text('RM 420.0'), findsWidgets);
    expect(find.text('RM 550.0'), findsWidgets);
  });

  // 5. Selected completed fare is not double-counted
  testWidgets('5. Selected completed fare is not double-counted', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api, initialReturnDate: '2027-02-12')));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Choose return'));
    await tester.pumpAndSettle();

    // Tap the second return option (RM 550.0)
    await tester.tap(find.text('AirAsia AK6117'));
    await tester.pumpAndSettle();

    // Itinerary sheet opens
    expect(find.text('Attach flight to itinerary'), findsOneWidget);
    await tester.tap(find.text('Penang Getaway'));
    await tester.pumpAndSettle();

    expect(api.postPaths, contains('/api/fr7/flights/select'));
    final selectBody = api.postBodies.firstWhere((b) => b?['returnOptionId'] == 'return_opt_2');
    expect(selectBody?['returnOptionId'], 'return_opt_2');
    expect(find.textContaining('Estimated trip total: RM 850.0'), findsOneWidget);
  });

  // 6. Changing outbound clears incompatible return selection
  testWidgets('6. Changing outbound clears incompatible return selection', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api, initialReturnDate: '2027-02-12')));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    // Trigger another search
    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    // Return loading is reset and clean
    expect(find.text('Choose return'), findsOneWidget);
  });

  // 7. Missing final price is handled safely
  testWidgets('7. Missing final price is handled safely', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    api.returnsResponse = {
      'ok': true,
      'items': [
        {
          'id': 'return_no_price',
          'optionId': 'return_no_price',
          'airline': 'Firefly',
          'flightNumber': 'FY100',
          'departureAirport': 'PEN',
          'arrivalAirport': 'KUL',
          'price': null,
        }
      ]
    };
    await tester.pumpWidget(_wrap(FlightScreen(api: api, initialReturnDate: '2027-02-12')));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Choose return'));
    await tester.pumpAndSettle();

    expect(find.text('Price unavailable'), findsWidgets);
  });

  // 8. Expired quote prevents new selection
  testWidgets('8. Expired quote prevents new selection', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    api.searchResponse = {
      'ok': true,
      'searchId': 'expired_search',
      'source': 'serpapi',
      'retrievedAt': '2026-01-01T00:00:00Z',
      'expiresAt': '2026-01-01T00:15:00Z', // Expired
      'items': [
        {
          'id': 'flight_out_1',
          'optionId': 'flight_out_1',
          'airline': 'Malaysia Airlines',
          'flightNumber': 'MH1138',
          'price': 200.0,
        }
      ]
    };
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    expect(find.text('Flight quote expired. Please search again for current fares.'), findsOneWidget);

    // Tapping select shows expired alert
    await tester.tap(find.widgetWithText(FilledButton, 'Select'));
    await tester.pumpAndSettle();

    expect(find.text('This flight quote has expired. Please search again.'), findsOneWidget);
  });

  // 9. Quote freshness disclosure is displayed
  testWidgets('9. Quote freshness disclosure is displayed', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    expect(find.text('Flight planning estimate — provider caching may apply. Price and availability are not guaranteed.'), findsOneWidget);
  });

  // 10. Provider cached result is not labelled guaranteed live
  testWidgets('10. Provider cached result is not labelled guaranteed live', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Guaranteed Live'), findsNothing);
    expect(find.textContaining('Seat Reserved'), findsNothing);
    expect(find.textContaining('Ticket Confirmed'), findsNothing);
  });

  // 11. Correct Trip identifiers are used
  testWidgets('11. Correct Trip identifiers are used', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    final trip = {
      'id': 'trip_123',
      'title': 'Penang Trip',
      'flightSearchId': 'search_authoritative_top',
      'flightOptionId': 'option_authoritative_top',
      'flightCost': 550.0,
      'selectedFlight': {
        'flightSearchId': 'nested_stale',
        'flightOptionId': 'nested_stale',
        'airline': 'Malaysia Airlines',
        'flightNumber': 'MH1138',
      }
    };
    api.tripsResponse = {'ok': true, 'items': [trip]};
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_123', api: api)));
    await tester.pumpAndSettle();

    await _showAttachedFlight(tester);
    expect(find.text('Attached flight'), findsOneWidget);
    expect(find.text('Flight cost: RM 550.0'), findsOneWidget);
  });

  // 12. Completed Flight selection persists in Trip
  testWidgets('12. Completed Flight selection persists in Trip', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    final trip = {
      'id': 'trip_123',
      'title': 'Penang Trip',
      'flightSearchId': 'search_auth',
      'flightOptionId': 'flight_completed_123',
      'flightCost': 550.0,
      'selectedFlight': {
        'airline': 'Malaysia Airlines',
        'flightNumber': 'MH1138',
        'departureAirport': 'KUL',
        'arrivalAirport': 'PEN',
      }
    };
    api.tripsResponse = {'ok': true, 'items': [trip]};
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_123', api: api)));
    await tester.pumpAndSettle();

    await _showAttachedFlight(tester);
    expect(find.text('Attached flight'), findsOneWidget);
    expect(find.text('Malaysia Airlines MH1138'), findsOneWidget);
  });

  // 13. Saved Trip shows outbound and return details
  testWidgets('13. Saved Trip shows outbound and return details', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    final trip = {
      'id': 'trip_123',
      'title': 'Penang Trip',
      'flightCost': 550.0,
      'selectedFlight': {
        'airline': 'Malaysia Airlines',
        'flightNumber': 'MH1138',
        'departureAirport': 'KUL',
        'arrivalAirport': 'PEN',
        'departureTime': '08:10',
        'arrivalTime': '09:10',
        'tripType': 'round_trip',
        'returnSegments': [
          {
            'departureAirportCode': 'PEN',
            'arrivalAirportCode': 'KUL',
            'departureTime': '18:50',
            'arrivalTime': '19:55',
          }
        ]
      }
    };
    api.tripsResponse = {'ok': true, 'items': [trip]};
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_123', api: api)));
    await tester.pumpAndSettle();

    await _showAttachedFlight(tester);
    expect(find.textContaining('Outbound: KUL to PEN • 08:10 to 09:10'), findsOneWidget);
    expect(find.textContaining('Return: PEN to KUL • 18:50 to 19:55'), findsOneWidget);
  });

  // 14. Budget uses completed fare
  testWidgets('14. Budget uses completed fare', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    final trip = {
      'id': 'trip_123',
      'title': 'Penang Trip',
      'flightCost': 550.0,
      'budgetEstimate': {'flight': 550.0, 'total': 1200.0},
      'selectedFlight': {'airline': 'MH', 'price': 550.0}
    };
    api.tripsResponse = {'ok': true, 'items': [trip]};
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_123', api: api)));
    await tester.pumpAndSettle();

    await _showAttachedFlight(tester);
    expect(find.text('Flight cost: RM 550.0'), findsOneWidget);
  });

  // 15. Repeated application does not duplicate cost
  testWidgets('15. Repeated application does not duplicate cost', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    final trip = {
      'id': 'trip_123',
      'title': 'Penang Trip',
      'flightCost': 550.0,
      'selectedFlight': {'airline': 'MH', 'price': 550.0}
    };
    api.tripsResponse = {'ok': true, 'items': [trip]};
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_123', api: api)));
    await tester.pumpAndSettle();

    await _showAttachedFlight(tester);
    expect(find.text('Flight cost: RM 550.0'), findsOneWidget);
  });

  // 16. Historical Trip remains readable after expiry
  testWidgets('16. Historical Trip remains readable after expiry', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    final trip = {
      'id': 'trip_123',
      'title': 'Penang Trip',
      'flightSearchId': 'ancient_search_from_last_year',
      'flightOptionId': 'ancient_option',
      'flightCost': 420.0,
      'selectedFlight': {
        'airline': 'Batik Air',
        'flightNumber': 'OD2108',
        'departureAirport': 'KUL',
        'arrivalAirport': 'PEN',
      }
    };
    api.tripsResponse = {'ok': true, 'items': [trip]};
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_123', api: api)));
    await tester.pumpAndSettle();

    await _showAttachedFlight(tester);
    expect(find.text('Attached flight'), findsOneWidget);
    expect(find.text('Batik Air OD2108'), findsOneWidget);
    expect(find.text('Flight cost: RM 420.0'), findsOneWidget);
  });

  // 17. Unknown cabin class is not labelled Economy
  testWidgets('17. Unknown cabin class is not labelled Economy', (tester) async {
    _setViewport(tester);
    final flight = {
      'airline': 'Airline X',
      'flightNumber': 'AX100',
      'cabinClass': null,
      'travelClass': null,
      'price': 150.0,
      'currency': 'MYR',
    };
    await tester.pumpWidget(_wrap(FlightDetailsScreen(flight: flight, onSelect: () {})));
    await tester.pumpAndSettle();

    expect(find.text('Economy'), findsNothing);
    expect(find.text('Not provided'), findsWidgets);
  });

  // 18. Unknown baggage is not labelled free
  testWidgets('18. Unknown baggage is not labelled free', (tester) async {
    _setViewport(tester);
    final flight = {
      'airline': 'Airline X',
      'cabinBaggage': null,
      'checkedBaggage': null,
    };
    await tester.pumpWidget(_wrap(FlightDetailsScreen(flight: flight, onSelect: () {})));
    await tester.pumpAndSettle();

    expect(find.textContaining('Free'), findsNothing);
    expect(find.textContaining('Included'), findsNothing);
  });

  // 19. Unknown refund rules are not labelled refundable
  testWidgets('19. Unknown refund rules are not labelled refundable', (tester) async {
    _setViewport(tester);
    final flight = {
      'airline': 'Airline X',
      'refundPolicy': null,
      'changePolicy': null,
    };
    await tester.pumpWidget(_wrap(FlightDetailsScreen(flight: flight, onSelect: () {})));
    await tester.pumpAndSettle();

    expect(find.textContaining('Refundable'), findsNothing);
  });

  // 20. Flight Checkout unavailable state is displayed
  testWidgets('F-F1A legacy booking payment entry 0 remains unavailable', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'flight',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postPaths, isEmpty);
  });

  // 21. No Stripe Checkout is initiated for a new Flight selection
  testWidgets('F-F1A legacy booking payment entry 1 remains unavailable', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'flight',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postPaths, isEmpty);
  });

  // 22. Historical paid Flight Orders remain accessible
  testWidgets('F-F1A legacy booking payment entry 2 remains unavailable', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'flight',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postPaths, isEmpty);
  });

  // 23. Hotel Checkout presentation remains unchanged
  testWidgets('F-F1A legacy booking payment entry 3 remains unavailable', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'hotel',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postPaths, isEmpty);
  });

  // 24. Package Checkout presentation remains unchanged
  testWidgets('F-F1A legacy booking payment entry 4 remains unavailable', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'package',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postPaths, isEmpty);
  });

  // 25. Backend errors are displayed correctly
  testWidgets('25. Backend errors are displayed correctly', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    api.shouldThrowValidation = true;
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    expect(find.text('Use different 3-letter airports and current or future flight dates'), findsOneWidget);
  });

  // 26. Network failures are recoverable
  testWidgets('26. Network failures are recoverable', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    api.shouldThrowNetwork = true;
    await tester.pumpWidget(_wrap(FlightScreen(api: api)));
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    expect(find.textContaining('connect to TravelMate'), findsOneWidget);

    // Turn off network error and retry
    api.shouldThrowNetwork = false;
    await tester.tap(find.widgetWithText(FilledButton, 'Search flights'));
    await tester.pumpAndSettle();

    expect(find.text('Malaysia Airlines MH1138'), findsOneWidget);
  });

  // 27. No sensitive SerpApi tokens are displayed or logged
  testWidgets('27. No sensitive SerpApi tokens are displayed or logged', (tester) async {
    _setViewport(tester);
    final flight = {
      'airline': 'Malaysia Airlines',
      'flightNumber': 'MH1138',
      'price': 220.0,
      'currency': 'MYR',
      '_departureToken': 'private_secret_token_123',
      'departureToken': 'private_secret_token_456',
    };
    await tester.pumpWidget(_wrap(FlightDetailsScreen(flight: flight, onSelect: () {})));
    await tester.pumpAndSettle();

    expect(find.textContaining('private_secret_token'), findsNothing);
  });

  // 28. No fake airline booking is shown
  testWidgets('28. No fake airline booking is shown', (tester) async {
    _setViewport(tester);
    final api = _MockFlightApi();
    final trip = {
      'id': 'trip_123',
      'title': 'Penang Trip',
      'flightCost': 550.0,
      'selectedFlight': {'airline': 'MH', 'price': 550.0}
    };
    api.tripsResponse = {'ok': true, 'items': [trip]};
    await tester.pumpWidget(_wrap(TripDetailsScreen(tripId: 'trip_123', api: api)));
    await tester.pumpAndSettle();

    await _showAttachedFlight(tester);
    expect(find.text('Planning estimate only • No airline ticket issued'), findsOneWidget);
    expect(find.textContaining('PNR'), findsNothing);
    expect(find.textContaining('Ticket Number:'), findsNothing);
  });
}
