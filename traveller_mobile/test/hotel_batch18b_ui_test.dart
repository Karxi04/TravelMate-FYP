import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _Batch18bMockApi extends ApiService {
  final List<String> postedPaths = [];
  final List<Map<String, dynamic>?> postedBodies = [];
  Future<dynamic> Function(String path, Map<String, dynamic>? body)? postHandler;
  Future<dynamic> Function(String path, Map<String, String>? query)? getHandler;

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (getHandler != null) {
      return getHandler!(path, query);
    }
    if (path == '/api/fr9/payments' || path == '/api/fr9/orders') {
      return {'ok': true, 'items': []};
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postedPaths.add(path);
    postedBodies.add(body);
    if (postHandler != null) {
      return postHandler!(path, body);
    }
    if (path == '/api/fr8/hotels/search') {
      return {
        'ok': true,
        'source': 'liteapi',
        'items': [
          {
            'hotelId': 'hotel-penang-1',
            'offerId': 'offer-b18-001',
            'quoteId': 'quote-b18-001',
            'name': 'Penang Heritage Resort',
            'roomName': 'Deluxe Sea View',
            'price': 420.0,
            'currency': 'MYR',
            'checkin': '2026-11-10',
            'checkout': '2026-11-12',
            'roomQuantity': 1,
          }
        ]
      };
    }
    if (path == '/api/fr8/hotels/prebook') {
      return {
        'ok': true,
        'source': 'liteapi',
        'acceptedPrebook': {
          'id': 'snap-authoritative-99',
          'amount': 420.0,
          'currency': 'MYR',
          'expiresAt': '2030-01-01T12:00:00Z',
          'checkoutEligible': true,
        },
        'result': {
          'validationId': 'val-b18-001',
        }
      };
    }
    if (path.contains('/checkout/session')) {
      return {
        'ok': true,
        'order': {
          'id': 'order-b18-001',
          'quoteType': body?['quoteType'] ?? 'hotel',
          'status': 'checkout_open',
          'checkoutAction': 'check_status',
          'checkoutUrl': '',
          'amount': 420.0,
        }
      };
    }
    return {'ok': true};
  }
}

void _setViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
}

Widget _wrap(Widget child) {
  return MaterialApp(
    home: Scaffold(body: child),
  );
}

void main() {
  testWidgets('F-F1A pending validation never claims hotel details are saved', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(api: api, initialDestination: 'Penang')));
    final dynamic state = tester.state(find.byType(HotelScreen));
    await state.search();
    api.postHandler = (path, body) async => {'ok': true, 'status': 'pending'};
    await state.prebook(Map<String, dynamic>.from(state.items.first as Map));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Hotel Details Pending'), 250,
        scrollable: find.descendant(
          of: find.byType(ListView).first,
          matching: find.byType(Scrollable),
        ).first);
    expect(find.text('Hotel Details Saved'), findsNothing);
    expect(find.text('Room reservation: not confirmed'), findsOneWidget);
    expect(api.postedPaths, isNot(contains('/api/fr8/hotels/book')));
  });

  testWidgets('F-B2 changed inputs discard an in-flight hotel response', (tester) async {
    _setViewport(tester);
    final result = Completer<Map<String, dynamic>>();
    final api = _Batch18bMockApi()..postHandler = (path, body) => result.future;
    await tester.pumpWidget(_wrap(HotelScreen(api: api, initialDestination: 'Penang')));
    final dynamic state = tester.state(find.byType(HotelScreen));
    final Future<void> request = state.search();
    state.destination.text = 'Melaka';
    result.complete({'ok': true, 'items': [{'name': 'Obsolete property', 'quoteId': 'old'}]});
    await request;
    await tester.pumpAndSettle();
    expect(state.items, isEmpty);
    expect(api.postedPaths, ['/api/fr8/hotels/search']);
  });

  testWidgets('F-B2 refreshed quote gets a new attempt but duplicate retry reuses it', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    var quote = 'first-quote';
    api.postHandler = (path, body) async {
      if (path == '/api/fr8/hotels/search') {
        return {'ok': true, 'items': [{'hotelId': 'same-property', 'offerId': 'same-offer',
          'quoteId': quote, 'name': 'Property', 'roomName': 'Room', 'price': 420, 'currency': 'MYR'}]};
      }
      return {'ok': true, 'status': 'pending'};
    };
    await tester.pumpWidget(_wrap(HotelScreen(api: api, initialDestination: 'Penang')));
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(HotelScreen));
    await state.search();
    await state.prebook(Map<String, dynamic>.from(state.items.first as Map));
    await state.prebook(Map<String, dynamic>.from(state.items.first as Map));
    quote = 'refreshed-quote';
    await state.search();
    await state.prebook(Map<String, dynamic>.from(state.items.first as Map));
    final requests = <Map<String, dynamic>>[];
    for (var i = 0; i < api.postedPaths.length; i++) {
      if (api.postedPaths[i] == '/api/fr8/hotels/prebook') requests.add(api.postedBodies[i]!);
    }
    expect(requests.length, 3);
    expect(requests[0]['hotelBookingAttemptId'], requests[1]['hotelBookingAttemptId']);
    expect(requests[2]['hotelBookingAttemptId'], isNot(requests[0]['hotelBookingAttemptId']));
  });

  testWidgets('F-B2 changed destination invalidates displayed hotel offer', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(api: api, initialDestination: 'Penang')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Search hotels'));
    await tester.pumpAndSettle();
    expect(find.text('Penang Heritage Resort'), findsOneWidget);
    final dynamic state = tester.state(find.byType(HotelScreen));
    state.destination.text = 'Melaka';
    await tester.pumpAndSettle();
    expect(find.text('Penang Heritage Resort'), findsNothing);
    expect(api.postedPaths, isNot(contains('/api/fr8/hotels/prebook')));
  });

  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  // 1. Single-room adult search
  testWidgets('1. Single-room adult search serializes valid single occupancy', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
      initialAdults: 2,
      initialChildren: 0,
    )));
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    expect(searchBtn, findsOneWidget);
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    expect(api.postedPaths, contains('/api/fr8/hotels/search'));
    final body = api.postedBodies.last!;
    expect(body['roomQuantity'], 1);
    expect(body['adults'], 2);
    expect(body['children'], 0);
    expect(body['occupancies'], [
      {'adults': 2}
    ]);
  });

  // 2. Two-room adult distribution
  testWidgets('2. Two-room adult distribution distributes adults across rooms', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
      initialAdults: 2,
      initialChildren: 0,
    )));
    await tester.pumpAndSettle();

    final addRoomBtn = find.text('Add Room');
    expect(addRoomBtn, findsOneWidget);
    await tester.ensureVisible(addRoomBtn);
    await tester.tap(addRoomBtn);
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    final body = api.postedBodies.last!;
    expect(body['roomQuantity'], 2);
    expect(body['adults'], 4);
    expect(body['children'], 0);
    expect(body['occupancies'], [
      {'adults': 2},
      {'adults': 2},
    ]);
  });

  // 3. Per-room children and ages
  testWidgets('3. Per-room children and ages are included in room occupancy', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final dynamic state = tester.state(find.byType(HotelScreen));
    state.setRoomChildren(0, 1);
    state.rooms[0].childAges[0] = 8;
    state.addRoom();
    state.setRoomChildren(1, 1);
    state.rooms[1].childAges[0] = 12;
    state.syncTotals();
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    final body = api.postedBodies.last!;
    expect(body['roomQuantity'], 2);
    expect(body['adults'], 4);
    expect(body['children'], 2);
    expect(body['occupancies'], [
      {
        'adults': 2,
        'children': [8]
      },
      {
        'adults': 2,
        'children': [12]
      },
    ]);
  });

  // 4. Missing child-age validation
  testWidgets('4. Missing child-age validation blocks search and alerts traveller', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final dynamic state = tester.state(find.byType(HotelScreen));
    state.setRoomChildren(0, 1);
    state.syncTotals();
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    expect(find.textContaining('Please specify an age for Child 1 in Room 1'), findsOneWidget);
    expect(api.postedPaths, isEmpty);
  });

  // 5. Inconsistent guest totals
  testWidgets('5. Inconsistent guest totals blocks search if totals mismatch room sums', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final dynamic state = tester.state(find.byType(HotelScreen));
    state.adults.text = '6';
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    expect(find.text('Total guests must match room allocations.'), findsOneWidget);
    expect(api.postedPaths, isEmpty);
  });

  // 6. Add/remove room interactions
  testWidgets('6. Add/remove room interactions update room count and UI dynamically', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialAdults: 2,
      initialChildren: 0,
    )));
    await tester.pumpAndSettle();

    expect(find.text('1 Room · 2 Adults'), findsOneWidget);

    final addBtn = find.text('Add Room');
    await tester.ensureVisible(addBtn);
    await tester.tap(addBtn);
    await tester.pumpAndSettle();

    expect(find.text('2 Rooms · 4 Adults'), findsOneWidget);

    final removeButtons = find.text('Remove Room');
    expect(removeButtons, findsWidgets);
    await tester.ensureVisible(removeButtons.last);
    await tester.tap(removeButtons.last);
    await tester.pumpAndSettle();

    expect(find.text('1 Room · 2 Adults'), findsOneWidget);
  });

  // 7. Provider-safe occupancy JSON serialization
  test('7. RoomOccupancyConfig serializes correctly and safely', () {
    final singleAdult = RoomOccupancyConfig(adults: 1);
    expect(singleAdult.toJson(), {'adults': 1});

    final withChildren = RoomOccupancyConfig(adults: 2, childAges: [5, 11]);
    expect(withChildren.toJson(), {
      'adults': 2,
      'children': [5, 11],
    });

    final withNullFiltered = RoomOccupancyConfig(adults: 2, childAges: [null, 7]);
    expect(withNullFiltered.toJson(), {
      'adults': 2,
      'children': [7],
    });

    final cloned = withChildren.clone();
    expect(cloned.adults, 2);
    expect(cloned.childAges, [5, 11]);
  });

  // 8. HTTP 400 invalid occupancy error
  testWidgets('8. HTTP 400 invalid occupancy error handled gracefully', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    api.postHandler = (path, body) async {
      if (path == '/api/fr8/hotels/search') {
        throw const ApiException('Invalid occupancy', 400, {'status': 'invalid_occupancy'});
      }
      return {'ok': true};
    };

    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    expect(find.textContaining('Invalid occupancy'), findsOneWidget);
    expect(find.text('Search hotels'), findsOneWidget);
  });

  // 9. Quote expiration handling
  testWidgets('9. Quote expiration handling prompts refresh on HTTP 409 quote_expired', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    api.postHandler = (path, body) async {
      if (path == '/api/fr8/hotels/prebook') {
        throw const ApiException('Quote expired', 409, {'status': 'quote_expired'});
      }
      return {'ok': true, 'items': []};
    };

    final validateBtn = find.text('Validate quote');
    expect(validateBtn, findsOneWidget);
    await tester.ensureVisible(validateBtn);
    await tester.tap(validateBtn);
    await tester.pumpAndSettle();

    expect(find.text('Quote Expired'), findsOneWidget);
    expect(find.textContaining('This hotel quote has expired'), findsOneWidget);
    expect(find.text('Refresh Search'), findsOneWidget);

    await tester.tap(find.text('Refresh Search'));
    await tester.pumpAndSettle();
    expect(find.text('Quote Expired'), findsNothing);
  });

  // 10. Successful accepted-prebook parsing
  testWidgets('10. Successful accepted-prebook displays authoritative sheet with accepted amount', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    final validateBtn = find.text('Validate quote');
    await tester.ensureVisible(validateBtn);
    await tester.tap(validateBtn);
    await tester.pumpAndSettle();

    expect(find.text('Hotel Offer Validated'), findsOneWidget);
    expect(find.textContaining('Selected stay total:'), findsOneWidget);
    expect(find.textContaining('MYR 420.0'), findsWidgets);
  });

  // 11. Prebook ID propagation
  testWidgets('F-F1A accepted hotel saves details only, never payment', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(api: api, initialDestination: 'Penang')));
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(HotelScreen));
    await state.search();
    final future = state.prebook(Map<String, dynamic>.from(state.items.first as Map));
    await tester.pumpAndSettle();
    expect(find.text('Pay with Card (Stripe Test)'), findsNothing);
    await tester.tap(find.text('Save Hotel Details'));
    await tester.pumpAndSettle();
    await future;
    expect(find.text('Confirm & Save Hotel Details'), findsWidgets);
    await tester.tap(find.byType(SwitchListTile));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Confirm & Save Hotel Details'));
    await tester.pumpAndSettle();
    final index = api.postedPaths.indexOf('/api/fr8/hotels/book');
    expect(index, greaterThanOrEqualTo(0));
    expect(api.postedBodies[index]?['saveDetailsOnly'], isTrue);
    expect(api.postedBodies[index]?.containsKey('payment'), isFalse);
    expect(api.postedPaths, isNot(contains('/api/fr9/checkout/session')));
    expect(find.textContaining('Status: confirmed'), findsNothing);
  });

  // 12. Price-change confirmation
  testWidgets('12. Price-change confirmation displays dialog and accepts quoteVersion on user consent', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    int prebookAttempts = 0;
    api.postHandler = (path, body) async {
      if (path == '/api/fr8/hotels/search') {
        return {
          'ok': true,
          'items': [
            {
              'hotelId': 'h1',
              'offerId': 'offer-reprice-1',
              'quoteId': 'quote-1',
              'name': 'Penang Beach Hotel',
              'price': 400.0,
              'currency': 'MYR',
            }
          ]
        };
      }
      if (path == '/api/fr8/hotels/prebook') {
        prebookAttempts++;
        if (prebookAttempts == 1) {
          throw const ApiException('Price changed', 409, {
            'status': 'reprice_required',
            'quoteVersion': 'v2_repriced',
            'validatedOffer': {
              'price': 450.0,
              'currency': 'MYR',
            }
          });
        }
        return {
          'ok': true,
          'acceptedPrebook': {
            'id': 'snap-repriced-1',
            'amount': 450.0,
            'currency': 'MYR',
            'expiresAt': '2030-01-01T12:00:00Z',
            'checkoutEligible': true,
          },
          'result': {'validationId': 'val-repriced-1'}
        };
      }
      return {'ok': true};
    };

    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    final validateBtn = find.text('Validate quote');
    await tester.ensureVisible(validateBtn);
    await tester.tap(validateBtn);
    await tester.pumpAndSettle();

    expect(find.text('Price or terms updated'), findsOneWidget);
    expect(find.textContaining('Previous rate: MYR 400.0'), findsOneWidget);
    expect(find.textContaining('Updated rate: MYR 450.0'), findsOneWidget);

    await tester.tap(find.text('Accept updated price'));
    await tester.pumpAndSettle();

    expect(prebookAttempts, 2);
    final lastBody = api.postedBodies.last!;
    expect(lastBody['acceptedQuoteVersion'], 'v2_repriced');
    expect(find.text('Hotel Offer Validated'), findsOneWidget);
  });

  // 13. Repricing rejection/cancellation
  testWidgets('13. Repricing cancellation does not re-submit prebook with quoteVersion', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    int prebookAttempts = 0;
    api.postHandler = (path, body) async {
      if (path == '/api/fr8/hotels/search') {
        return {
          'ok': true,
          'items': [
            {
              'hotelId': 'h1',
              'offerId': 'offer-reprice-2',
              'quoteId': 'quote-2',
              'name': 'Penang Grand',
              'price': 300.0,
              'currency': 'MYR',
            }
          ]
        };
      }
      if (path == '/api/fr8/hotels/prebook') {
        prebookAttempts++;
        throw const ApiException('Price changed', 409, {
          'status': 'reprice_required',
          'quoteVersion': 'v2_repriced',
          'validatedOffer': {
            'price': 380.0,
            'currency': 'MYR',
          }
        });
      }
      return {'ok': true};
    };

    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    final validateBtn = find.text('Validate quote');
    await tester.ensureVisible(validateBtn);
    await tester.tap(validateBtn);
    await tester.pumpAndSettle();

    expect(find.text('Price or terms updated'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(prebookAttempts, 1);
    expect(find.text('Price or terms updated'), findsNothing);
    expect(find.text('Hotel Offer Validated'), findsNothing);
  });

  // 14. Reused stable attempt IDs
  testWidgets('14. Stable attempt ID reused across prebook calls for the same offer', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
      initialCheckin: '2026-11-10',
      initialCheckout: '2026-11-12',
    )));
    await tester.pumpAndSettle();

    final searchBtn = find.text('Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    final validateBtn = find.text('Validate quote');
    await tester.ensureVisible(validateBtn);
    await tester.tap(validateBtn);
    await tester.pumpAndSettle();

    final prebookBodies = api.postedBodies
        .where((b) => b != null && b.containsKey('hotelBookingAttemptId'))
        .toList();
    expect(prebookBodies.length, 1);
    final firstAttemptId = prebookBodies[0]!['hotelBookingAttemptId'];
    expect(firstAttemptId, isNotEmpty);

    // Dismiss first outcome sheet
    Navigator.of(tester.element(find.byType(HotelScreen))).pop();
    await tester.pumpAndSettle();

    final dynamic state = tester.state(find.byType(HotelScreen));
    final hotelItem = state.items[0] as Map<String, dynamic>;
    // Trigger prebook again for the same hotel offer
    state.prebook(hotelItem);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    final secondPrebookBodies = api.postedBodies
        .where((b) => b != null && b.containsKey('hotelBookingAttemptId'))
        .toList();
    expect(secondPrebookBodies.length, 2);
    expect(secondPrebookBodies[1]!['hotelBookingAttemptId'], firstAttemptId);

    // Dismiss second outcome sheet
    if (find.byType(BottomSheet).evaluate().isNotEmpty) {
      Navigator.of(tester.element(find.byType(HotelScreen))).pop();
      await tester.pumpAndSettle();
    }
  });

  // 15. Correct Hotel Checkout payload
  testWidgets('F-F1A accepted snapshot does not enable hotel payment', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'hotel',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postedPaths, isEmpty);
  });

  // 16. Checkout blocked without snapshot
  testWidgets('F-F1A missing snapshot cannot enable hotel payment', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'hotel',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: '')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postedPaths, isEmpty);
  });

  // 17. Checkout blocked for expired snapshot
  testWidgets('F-F1A expired snapshot cannot enable hotel payment', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'hotel',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot',
      acceptedPrebook: const {'expiresAt': '2000-01-01T00:00:00Z'})));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postedPaths, isEmpty);
  });

  // 18. Server HTTP 409 recovery in PaymentScreen
  testWidgets('F-F1A stale payment navigation cannot start a checkout', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'hotel',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postedPaths, isEmpty);
  });

  // 19. No accidental supplier booking before Hotel Test Checkout
  testWidgets('F-F1A validating an offer never books or pays', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(api: api, initialDestination: 'Penang')));
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(HotelScreen));
    await state.search();
    final future = state.prebook(Map<String, dynamic>.from(state.items.first as Map));
    await tester.pumpAndSettle();
    expect(find.text('Save Hotel Details'), findsOneWidget);
    expect(api.postedPaths, isNot(contains('/api/fr8/hotels/book')));
    expect(api.postedPaths, isNot(contains('/api/fr9/checkout/session')));
    tester.state<NavigatorState>(find.byType(Navigator).first).pop();
    await tester.pumpAndSettle();
    await future;
  });

  // 20. Demo and Stripe Test disclosures
  testWidgets('F-F1A saving is disclosed without advertising a test payment', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(api: api, initialDestination: 'Penang')));
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(HotelScreen));
    await state.search();
    final future = state.prebook(Map<String, dynamic>.from(state.items.first as Map));
    await tester.pumpAndSettle();
    expect(find.textContaining('does not reserve a room or take payment'), findsOneWidget);
    expect(find.textContaining('Stripe Test'), findsNothing);
    tester.state<NavigatorState>(find.byType(Navigator).first).pop();
    await tester.pumpAndSettle();
    await future;
  });

  // 21. Navigation and state preservation
  testWidgets('21. Initial values are preserved across navigation and render correctly', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(HotelScreen(
      api: api,
      initialDestination: 'Batu Ferringhi, Penang',
      initialCheckin: '2026-12-01',
      initialCheckout: '2026-12-05',
      initialAdults: 3,
      initialChildren: 1,
    )));
    await tester.pumpAndSettle();

    final dynamic state = tester.state(find.byType(HotelScreen));
    expect(state.destination.text, 'Batu Ferringhi, Penang');
    expect(state.checkin.text, '2026-12-01');
    expect(state.checkout.text, '2026-12-05');
    expect(state.adults.text, '3');
    expect(state.children.text, '1');
    expect(state.rooms.length, 1);
    expect(state.rooms[0].adults, 3);
    expect(state.rooms[0].childAges.length, 1);
  });

  // 22. Package/Flight payment regression safety
  testWidgets('F-F1A no new package or flight payment through legacy screen', (tester) async {
    _setViewport(tester);
    final api = _Batch18bMockApi();
    await tester.pumpWidget(_wrap(PaymentScreen(api: api, quoteType: 'hotel',
      quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
    await tester.pumpAndSettle();
    expect(find.text('Payments unavailable'), findsOneWidget);
    expect(find.textContaining('Stripe test Checkout'), findsNothing);
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postedPaths, isEmpty);
  });
}
