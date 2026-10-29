import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_order_details_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/checkout_return_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_history_screen.dart';
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

class _MockBatch18cApi extends ApiService {
  List<dynamic> paymentItems = [];
  List<dynamic> ordersList = [];
  Map<String, dynamic>? singleOrderResponse;
  Map<String, dynamic>? reconcileResponse;
  Map<String, dynamic>? checkoutSessionResponse;

  bool shouldThrow404 = false;
  bool shouldThrowTimeout = false;
  bool shouldThrow500 = false;

  final List<String> getPaths = [];
  final List<String> postPaths = [];
  final List<Map<String, dynamic>?> postBodies = [];

  bool get hasCalledSupplierBooking =>
      getPaths.any((p) => p.contains('/hotels/book') || p.contains('/rates/book')) ||
      postPaths.any((p) => p.contains('/hotels/book') || p.contains('/rates/book'));

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    getPaths.add(path);
    if (shouldThrow404) {
      throw const ApiException('Order not found', 404, {'ok': false, 'error': 'Order not found'});
    }
    if (shouldThrowTimeout) {
      throw TimeoutException('Connection timed out');
    }
    if (shouldThrow500) {
      throw const ApiException('Server error', 500, {'ok': false, 'error': 'Server error'});
    }

    if (path == '/api/fr9/payments') {
      return {'ok': true, 'items': paymentItems};
    }
    if (path == '/api/fr9/orders') {
      return {'ok': true, 'items': ordersList};
    }
    if (path.contains('/api/fr9/orders/') && path.endsWith('/reconcile')) {
      return reconcileResponse ?? {'ok': true, 'order': singleOrderResponse ?? {}};
    }
    if (path.startsWith('/api/fr9/orders/')) {
      return singleOrderResponse != null ? {'ok': true, 'order': singleOrderResponse} : {'ok': true, 'order': {}};
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postPaths.add(path);
    postBodies.add(body);
    if (shouldThrowTimeout) {
      throw TimeoutException('Connection timed out');
    }
    if (path.contains('/checkout/session')) {
      return checkoutSessionResponse ?? {
        'ok': true,
        'order': {
          'id': 'order-test-default',
          'quoteType': 'hotel',
          'status': 'checkout_open',
          'paymentStatus': 'unpaid',
          'checkoutAction': 'continue_payment',
          'checkoutUrl': 'https://checkout.stripe.test/cs_test_default',
        }
      };
    }
    return {'ok': true};
  }
}

void main() {
  final hotelSnapshot = {
    'hotelId': 'lp_hotel_1',
    'name': 'The Waterfront Hotel Kuching',
    'roomName': 'Deluxe River View Suite',
    'checkin': '2026-11-10',
    'checkout': '2026-11-14',
    'roomQuantity': 2,
    'occupancies': [
      {'adults': 2, 'children': []},
      {'adults': 1, 'children': [7]},
    ],
  };

  final samplePaidHotelOrder = {
    'id': 'order-hotel-paid-1',
    'quoteType': 'hotel',
    'quoteId': 'quote-hotel-paid-1',
    'acceptedPrebookSnapshotId': 'snap-1',
    'status': 'paid',
    'paymentStatus': 'paid',
    'amount': 780.0,
    'currency': 'MYR',
    'fulfillmentStatus': 'demo_only',
    'supplierBookingStatus': 'not_created',
    'isSimulated': true,
    'fulfillmentMode': 'demo_only',
    'bookingReference': null,
    'demoDisclosure': 'Demo reservation — no supplier room has been reserved.',
    'quoteSnapshot': hotelSnapshot,
  };

  final sampleUnpaidHotelOrder = {
    'id': 'order-hotel-unpaid-1',
    'quoteType': 'hotel',
    'quoteId': 'lp_hotel_1',
    'acceptedPrebookSnapshotId': 'snap_1',
    'status': 'checkout_open',
    'paymentStatus': 'unpaid',
    'amount': 780.0,
    'currency': 'MYR',
    'fulfillmentStatus': 'not_started',
    'supplierBookingStatus': 'not_created',
    'isSimulated': true,
    'fulfillmentMode': 'demo_only',
    'bookingReference': null,
    'demoDisclosure': 'Demo reservation — no supplier room has been reserved.',
    'quoteSnapshot': hotelSnapshot,
  };

  // 1. Hotel unpaid Order displays pending payment
  testWidgets('1. Hotel unpaid Order displays pending payment', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = sampleUnpaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-unpaid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Payment Pending / Unpaid'), findsOneWidget);
    expect(find.text('Not Started'), findsOneWidget);
  });

  // 2. Hotel paid Order displays Stripe Test payment success
  testWidgets('2. Hotel paid Order displays Stripe Test payment success', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Paid — Stripe Test Mode'), findsOneWidget);
  });

  // 3. Hotel paid Order displays demo_only fulfillment
  testWidgets('3. Hotel paid Order displays demo_only fulfillment', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Test Mode — No Room Reserved'), findsOneWidget);
    expect(find.text('No supplier reservation created'), findsOneWidget);
  });

  // 4. Supplier booking remains not_created
  testWidgets('4. Supplier booking remains not_created', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('No supplier reservation created'), findsOneWidget);
    expect(find.text('Confirmed Hotel Reservation'), findsNothing);
  });

  // 5. No fake confirmation reference is shown
  testWidgets('5. No fake confirmation reference is shown', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('None (No supplier reservation created)'), findsOneWidget);
    expect(find.textContaining('HOTEL-CONF-'), findsNothing);
    expect(find.textContaining('BOOKING-CONF-'), findsNothing);
  });

  // 6. PaymentScreen opens the correct Order details
  testWidgets('F-F1A historical order does not re-enable new payment', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
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

  // 7. Hotel Order details display correct hotel name
  testWidgets('7. Hotel Order details display correct hotel name', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('The Waterfront Hotel Kuching'), findsOneWidget);
  });

  // 8. Stay dates match server response
  testWidgets('8. Stay dates match server response', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('10 Nov 2026'), findsOneWidget);
    expect(find.text('14 Nov 2026'), findsOneWidget);
    expect(find.text('4 Nights'), findsOneWidget);
  });

  // 9. Room and child-age details render correctly
  testWidgets('9. Room and child-age details render correctly', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Deluxe River View Suite'), findsWidgets);
    expect(find.text('2 Rooms'), findsOneWidget);
    expect(find.textContaining('Room 1: 2 Adults'), findsOneWidget);
    expect(find.textContaining('Room 2: 1 Adult, 1 Child (Age 7)'), findsOneWidget);
  });

  // 10. Amount and currency match server values
  testWidgets('10. Amount and currency match server values', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('MYR 780.00'), findsOneWidget);
  });

  // 11. Browser return recovers the current Order
  testWidgets('F-F1A historical browser return is read-only', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi()..singleOrderResponse = {
      'id': 'historical-hotel', 'quoteType': 'hotel', 'status': 'checkout_open',
      'paymentStatus': 'unpaid', 'checkoutSessionId': 'old-session', 'testMode': true};
    await tester.pumpWidget(_wrap(CheckoutReturnScreen(api: api,
      link: const CheckoutReturnLink('historical-hotel', 'processing'))));
    await tester.pumpAndSettle();
    expect(api.getPaths.where((path) => path.endsWith('/reconcile')), isEmpty);
    expect(api.postPaths, isEmpty);
    expect(find.text('Test payment recorded'), findsNothing);
  });

  // 12. App restart recovers paid Order history
  testWidgets('12. App restart recovers paid Order history', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.paymentItems = [
      {
        'id': 'pay-hotel-1',
        'source': 'checkout_order',
        'orderReference': 'order-hotel-paid-1',
        'bookingType': 'hotel',
        'productTitle': 'The Waterfront Hotel Kuching',
        'hotelName': 'The Waterfront Hotel Kuching',
        'roomName': 'Deluxe River View Suite',
        'checkin': '2026-11-10',
        'checkout': '2026-11-14',
        'amount': 780.0,
        'currency': 'MYR',
        'paymentStatus': 'paid',
        'fulfillmentStatus': 'demo_only',
        'supplierBookingStatus': 'not_created',
        'isSimulated': true,
        'bookingReference': null,
      }
    ];

    await tester.pumpWidget(_wrap(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Hotel — The Waterfront Hotel Kuching'), findsOneWidget);
    expect(find.text('Paid (Stripe Test)'), findsOneWidget);
    expect(find.text('Test Mode — No Room Reserved'), findsOneWidget);
  });

  // 13. Missing fulfillmentStatus is handled safely
  testWidgets('13. Missing fulfillmentStatus is handled safely', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    final orderWithoutFulfillment = {
      'id': 'order-missing-fulfillment',
      'quoteType': 'hotel',
      'status': 'paid',
      'paymentStatus': 'paid',
      'amount': 500.0,
      'currency': 'MYR',
      'quoteSnapshot': {'name': 'Legacy Hotel'},
    };
    api.singleOrderResponse = orderWithoutFulfillment;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-missing-fulfillment',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Paid — Stripe Test Mode'), findsOneWidget);
    expect(find.text('Supplier reservation not verified'), findsOneWidget);
  });

  // 14. Legacy paid Hotel Orders do not falsely show confirmed reservations
  testWidgets('14. Legacy paid Hotel Orders do not falsely show confirmed reservations', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.paymentItems = [
      {
        'id': 'legacy-pay-1',
        'source': 'payment_record',
        'orderReference': 'legacy-order-1',
        'bookingType': 'hotel',
        'productTitle': 'Old Hotel Reservation',
        'amount': 300.0,
        'currency': 'MYR',
        'paymentStatus': 'paid',
      }
    ];

    await tester.pumpWidget(_wrap(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Supplier reservation not verified'), findsOneWidget);
    expect(find.text('Confirmed'), findsNothing);
  });

  // 15. Failed payment never shows Paid
  testWidgets('15. Failed payment never shows Paid', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = {
      'id': 'order-failed',
      'quoteType': 'hotel',
      'status': 'payment_failed',
      'paymentStatus': 'failed',
      'amount': 400.0,
      'currency': 'MYR',
      'fulfillmentStatus': 'not_started',
      'quoteSnapshot': {'name': 'Failed Hotel'},
    };

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-failed',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Payment Failed'), findsOneWidget);
    expect(find.text('Paid — Stripe Test Mode'), findsNothing);
    expect(find.text('Paid'), findsNothing);
  });

  // 16. Pending payment never shows Paid
  testWidgets('16. Pending payment never shows Paid', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = sampleUnpaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-unpaid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Payment Pending / Unpaid'), findsOneWidget);
    expect(find.text('Paid — Stripe Test Mode'), findsNothing);
    expect(find.text('Paid'), findsNothing);
  });

  // 17. Expired Checkout displays an appropriate state
  testWidgets('17. Expired Checkout displays an appropriate state', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = {
      'id': 'order-expired',
      'quoteType': 'hotel',
      'status': 'expired',
      'paymentStatus': 'unpaid',
      'amount': 450.0,
      'currency': 'MYR',
      'fulfillmentStatus': 'not_started',
      'quoteSnapshot': {'name': 'Expired Hotel Session'},
    };

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-expired',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Checkout Expired'), findsOneWidget);
    expect(find.text('Paid — Stripe Test Mode'), findsNothing);
  });

  // 18. Backend reconciliation errors are recoverable
  testWidgets('18. Backend reconciliation errors are recoverable', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = sampleUnpaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-unpaid-1',
      initialOrder: sampleUnpaidHotelOrder,
      api: api,
    )));
    await tester.pumpAndSettle();

    api.shouldThrowTimeout = true;

    // Tap refresh / reconcile button
    await tester.tap(find.byKey(const ValueKey('hotel-order-refresh-button')));
    await tester.pumpAndSettle();

    // Verify app recovers gracefully without crashing
    expect(find.byType(HotelOrderDetailsScreen), findsOneWidget);
    expect(find.text('Payment Pending / Unpaid'), findsOneWidget);
  });

  // 19. Cross-user Order access errors do not leak data
  testWidgets('19. Cross-user Order access errors do not leak data', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.shouldThrow404 = true;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'foreign-order-id',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(find.text('This Hotel order is not available for the signed-in Traveller.'), findsOneWidget);
    expect(find.text('The Waterfront Hotel Kuching'), findsNothing);
    expect(find.text('Deluxe River View Suite'), findsNothing);
  });

  // 20. Package Order presentation remains unchanged
  testWidgets('20. Package Order presentation remains unchanged', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.paymentItems = [
      {
        'id': 'pay-package-1',
        'source': 'checkout_order',
        'orderReference': 'order-package-1',
        'bookingType': 'package',
        'productTitle': 'Kinabatangan Wildlife River Cruise',
        'amount': 1800.0,
        'currency': 'MYR',
        'paymentStatus': 'paid',
        'testMode': true,
      }
    ];

    await tester.pumpWidget(_wrap(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Package — Kinabatangan Wildlife River Cruise'), findsOneWidget);
    expect(find.text('Paid (Stripe Test)'), findsOneWidget);
    // Package orders must NOT show hotel demo fulfillment chip
    expect(find.text('Test Mode — No Room Reserved'), findsNothing);
  });

  // 21. Flight Order presentation remains unchanged
  testWidgets('21. Flight Order presentation remains unchanged', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.paymentItems = [
      {
        'id': 'pay-flight-1',
        'source': 'checkout_order',
        'orderReference': 'order-flight-1',
        'bookingType': 'flight',
        'productTitle': 'Kuala Lumpur to Penang Flight',
        'amount': 220.0,
        'currency': 'MYR',
        'paymentStatus': 'paid',
        'testMode': true,
      }
    ];

    await tester.pumpWidget(_wrap(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Flight — Kuala Lumpur to Penang Flight'), findsOneWidget);
    expect(find.text('Paid (Stripe Test)'), findsOneWidget);
    // Flight orders must NOT show hotel demo fulfillment chip
    expect(find.text('Test Mode — No Room Reserved'), findsNothing);
  });

  // 22. No supplier booking endpoint is invoked
  testWidgets('22. No supplier booking endpoint is invoked', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    expect(api.hasCalledSupplierBooking, isFalse);
  });

  // 23. No duplicate Checkout Session is initiated during recovery
  testWidgets('23. No duplicate Checkout Session is initiated during recovery', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.ordersList = [sampleUnpaidHotelOrder];
    api.singleOrderResponse = sampleUnpaidHotelOrder;

    await tester.pumpWidget(_wrap(PaymentScreen(
      quoteType: 'hotel',
      quoteId: 'lp_hotel_1',
      offerId: 'offer_1',
      acceptedPrebookSnapshotId: 'snap_1',
      initialAmount: 780.0,
      api: api,
    )));
    await tester.pumpAndSettle();

    // Check status without paying again
    final checkStatusBtn = find.text('Check Payment Status');
    if (checkStatusBtn.evaluate().isNotEmpty) {
      await tester.tap(checkStatusBtn);
      await tester.pumpAndSettle();
    }

    // Verify no new session was posted during status recovery
    expect(api.postPaths.where((p) => p.contains('/checkout/session')).length, 0);
  });

  // 24. No actual Stripe payment is triggered by automated tests
  testWidgets('24. No actual Stripe payment is triggered by automated tests', (tester) async {
    _setViewport(tester);
    final api = _MockBatch18cApi();
    api.singleOrderResponse = samplePaidHotelOrder;

    await tester.pumpWidget(_wrap(HotelOrderDetailsScreen(
      orderId: 'order-hotel-paid-1',
      api: api,
    )));
    await tester.pumpAndSettle();

    // Confirms tests run completely through mocks and verify mock state only
    expect(api.postPaths.any((p) => p.contains('api.stripe.com')), isFalse);
  });
}
