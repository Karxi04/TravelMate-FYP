import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _Batch18bV1MockApi extends ApiService {
  final List<String> postedPaths = [];
  final List<Map<String, dynamic>?> postedBodies = [];
  int prebookCallCount = 0;
  Map<String, dynamic>? prebookOverride;

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr9/payments' || path == '/api/fr9/orders') {
      return {'ok': true, 'items': []};
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postedPaths.add(path);
    postedBodies.add(body);
    if (path == '/api/fr8/hotels/search') {
      return {
        'ok': true,
        'source': 'liteapi',
        'items': [
          {
            'hotelId': 'hotel-v1-001',
            'offerId': 'offer-v1-001',
            'quoteId': 'quote-v1-001',
            'name': 'Vivo Heritage Suites',
            'roomName': 'Premier Deluxe',
            'price': 336.94,
            'currency': 'MYR',
            'checkin': '2026-11-10',
            'checkout': '2026-11-12',
            'roomQuantity': 1,
          }
        ]
      };
    }
    if (path == '/api/fr8/hotels/prebook') {
      prebookCallCount++;
      if (prebookOverride != null) return prebookOverride!;
      return {
        'ok': true,
        'source': 'liteapi',
        'acceptedPrebook': {
          'id': 'snap-v1-authoritative',
          'amount': 336.94,
          'currency': 'MYR',
          'expiresAt': '2030-01-01T12:00:00Z',
          'checkoutEligible': true,
        },
        'result': {
          'validationId': 'val-v1-001',
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
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({});
  });

  group('Batch 18B-V1 Hotel State & Checkout Verification', () {
    testWidgets('ISS-18B-01: Multi-room renders identical stepper controls for Room 1 and Room 2', (tester) async {
      _setViewport(tester);
      final api = _Batch18bV1MockApi();
      await tester.pumpWidget(_wrap(HotelScreen(
        api: api,
        initialAdults: 2,
        initialChildren: 0,
      )));
      await tester.pumpAndSettle();

      // Initially 1 room
      expect(find.text('1 Room · 2 Adults'), findsOneWidget);

      // Add second room
      final addRoomBtn = find.text('Add Room');
      await tester.ensureVisible(addRoomBtn);
      await tester.tap(addRoomBtn);
      await tester.pumpAndSettle();

      expect(find.text('2 Rooms · 4 Adults'), findsOneWidget);
      expect(find.text('Room 1'), findsOneWidget);
      expect(find.text('Room 2'), findsOneWidget);

      // Both Room 1 and Room 2 should have remove/add icons, not TextFields
      // In multi-room mode, the room cards have IconButtons for minus/plus
      final addIcons = find.byIcon(Icons.add);
      // Room 1 (adults, children) + Room 2 (adults, children) = 4 add icons
      expect(addIcons, findsNWidgets(4));

      // There should be NO TextField with label 'Adults' or 'Children' in multi-room mode
      final textFields = tester.widgetList<TextField>(find.byType(TextField)).toList();
      final hasAdultTextField = textFields.any((f) => f.decoration?.labelText == 'Adults');
      final hasChildTextField = textFields.any((f) => f.decoration?.labelText == 'Children');
      expect(hasAdultTextField, isFalse);
      expect(hasChildTextField, isFalse);
    });

    testWidgets('ISS-18B-02: Changing Room 2 adults does NOT alter Room 1 counts', (tester) async {
      _setViewport(tester);
      final api = _Batch18bV1MockApi();
      await tester.pumpWidget(_wrap(HotelScreen(
        api: api,
        initialAdults: 2,
        initialChildren: 0,
      )));
      await tester.pumpAndSettle();

      // Add Room 2
      final addRoomBtn = find.text('Add Room');
      await tester.ensureVisible(addRoomBtn);
      await tester.tap(addRoomBtn);
      await tester.pumpAndSettle();

      final dynamic state = tester.state(find.byType(HotelScreen));
      expect(state.rooms[0].adults, 2);
      expect(state.rooms[1].adults, 2);

      // Programmatically or via UI increment Room 2 adults
      state.setRoomAdults(1, 3);
      await tester.pumpAndSettle();

      // Invariant: Room 1 adults must STILL be 2, NOT contaminated to 3 or 5!
      expect(state.rooms[0].adults, 2);
      expect(state.rooms[1].adults, 3);

      // Search totals should reflect sum (5 adults across 2 rooms)
      expect(find.text('2 Rooms · 5 Adults'), findsOneWidget);

      // Increment Room 2 children
      state.setRoomChildren(1, 1);
      state.rooms[1].childAges[0] = 7;
      state.syncTotals();
      await tester.pumpAndSettle();

      // Room 1 children must STILL be 0
      expect(state.rooms[0].childAges.length, 0);
      expect(state.rooms[1].childAges.length, 1);
      expect(state.rooms[1].childAges[0], 7);
      expect(find.text('2 Rooms · 5 Adults · 1 Child'), findsOneWidget);
    });

    testWidgets('F-F1A missing accepted price cannot expose payment', (tester) async {
    _setViewport(tester);
    final api = _Batch18bV1MockApi();
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

    testWidgets('ISS-18B-03 B: Hotel prebook outcome sheet prompts re-validation if snapshot ID is missing', (tester) async {
      _setViewport(tester);
      final api = _Batch18bV1MockApi();
      // Configure mock prebook to return validationId but NO acceptedPrebook snapshot ID
      api.prebookOverride = {
        'ok': true,
        'source': 'liteapi',
        'result': {
          'validationId': 'val-legacy-without-snapshot',
        },
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

      // Prebook outcome sheet appears
      expect(find.text('Hotel Offer Validated'), findsOneWidget);

      // Warning card should alert traveller that quote snapshot was not received
      expect(find.textContaining('Please validate this offer again before saving.'), findsOneWidget);

      // Button should offer Re-validate Quote for Checkout, NOT Pay with Card
      final revalidateBtn = find.text('Re-validate Quote');
      expect(revalidateBtn, findsOneWidget);
      expect(find.text('Pay with Card (Stripe Test)'), findsNothing);

      // Tap Re-validate Quote: it re-triggers prebook
      // Now provide a valid snapshot
      api.prebookOverride = {
        'ok': true,
        'source': 'liteapi',
        'acceptedPrebook': {
          'id': 'snap-recovered-authoritative',
          'amount': 336.94,
          'currency': 'MYR',
          'expiresAt': '2030-01-01T12:00:00Z',
          'checkoutEligible': true,
        },
        'result': {
          'validationId': 'val-recovered-001',
        }
      };
      await tester.tap(revalidateBtn);
      await tester.pumpAndSettle();

      // After re-validation, sheet re-opens with valid snapshot
      expect(find.text('Add to Trip'), findsOneWidget);
    });
  });
}
