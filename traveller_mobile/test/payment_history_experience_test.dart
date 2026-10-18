import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr01_user_management/profile_tab.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_history_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockPaymentApi extends ApiService {
  List<dynamic> paymentItems = [];
  bool shouldThrowError = false;
  bool shouldThrowAuthError = false;
  int getPaymentsCount = 0;
  int postCount = 0;

  _MockPaymentApi({List<dynamic>? items}) : paymentItems = items ?? [];

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr1/me') {
      return {
        'ok': true,
        'profile': {'name': 'Ahmad Traveller', 'email': 'ahmad@example.com'}
      };
    }
    if (path == '/api/fr2/preferences') {
      return {'ok': true, 'preferences': {'interests': ['Culture']}};
    }
    if (path == '/api/fr4/preference-feedback') {
      return {'ok': true, 'learning': {}};
    }
    if (path == '/api/fr9/payments') {
      getPaymentsCount++;
      if (shouldThrowAuthError) {
        throw const ApiException('Missing Firebase ID token', 401, {'ok': false});
      }
      if (shouldThrowError) {
        throw Exception('Network connection timed out');
      }
      return {'ok': true, 'items': paymentItems};
    }
    if (path == '/api/fr9/orders') {
      return {'ok': true, 'items': []};
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postCount++;
    return {'ok': true};
  }
}

void main() {
  Widget buildTestWidget(Widget child, {Size size = const Size(390, 844)}) {
    return MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(size: size),
        child: child,
      ),
    );
  }

  final samplePackagePayment = {
    'id': 'order-pkg-101',
    'orderReference': 'order-pkg-101',
    'bookingType': 'package',
    'productTitle': 'Penang Heritage & Hills Escape',
    'amount': 3346.00,
    'currency': 'MYR',
    'paymentStatus': 'paid',
    'orderStatus': 'paid',
    'testMode': true,
    'paymentProvider': 'stripe',
    'timestamp': '2026-10-18T10:15:00+00:00',
    'source': 'checkout_order',
    'relatedTripId': 'trip-pkg-101',
  };

  final sampleHotelPayment = {
    'id': 'order-htl-202',
    'orderReference': 'order-htl-202',
    'bookingType': 'hotel',
    'productTitle': 'Heritage Hotel Georgetown',
    'amount': 450.00,
    'currency': 'MYR',
    'paymentStatus': 'paid',
    'orderStatus': 'paid',
    'testMode': true,
    'paymentProvider': 'stripe',
    'timestamp': '2026-10-17T14:30:00+00:00',
    'source': 'checkout_order',
  };

  final sampleFlightPayment = {
    'id': 'order-flt-303',
    'orderReference': 'order-flt-303',
    'bookingType': 'flight',
    'productTitle': null,
    'amount': 280.50,
    'currency': 'MYR',
    'paymentStatus': 'paid',
    'orderStatus': 'paid',
    'testMode': true,
    'paymentProvider': 'stripe',
    'timestamp': '2026-10-16T08:00:00+00:00',
    'source': 'checkout_order',
  };

  final sampleLegacyPayment = {
    'id': 'legacy-pay-404',
    'orderReference': 'legacy-pay-404',
    'bookingType': 'legacy_payment',
    'productTitle': null,
    'amount': 80.00,
    'currency': 'MYR',
    'paymentStatus': 'succeeded',
    'testMode': true,
    'paymentProvider': 'travelmate_simulation',
    'cardBrand': 'Visa',
    'cardLast4': '4242',
    'timestamp': '2026-09-01T10:00:00+00:00',
    'source': 'payment_record',
  };

  final samplePendingPayment = {
    'id': 'order-pending-505',
    'orderReference': 'order-pending-505',
    'bookingType': 'package',
    'productTitle': 'Penang Street Food Adventure',
    'amount': 599.00,
    'currency': 'MYR',
    'paymentStatus': 'unpaid',
    'orderStatus': 'checkout_open',
    'testMode': true,
    'timestamp': '2026-10-18T11:00:00+00:00',
    'source': 'checkout_order',
  };

  final sampleFailedPayment = {
    'id': 'order-failed-606',
    'orderReference': 'order-failed-606',
    'bookingType': 'hotel',
    'productTitle': 'Sunset Beach Resort',
    'amount': 890.00,
    'currency': 'MYR',
    'paymentStatus': 'failed',
    'orderStatus': 'payment_failed',
    'testMode': true,
    'timestamp': '2026-10-15T09:00:00+00:00',
    'source': 'checkout_order',
  };

  testWidgets('1. Paid Package Order displayed with title, MYR amount, Paid status, and Test Mode', (tester) async {
    final api = _MockPaymentApi(items: [samplePackagePayment]);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Package — Penang Heritage & Hills Escape'), findsOneWidget);
    expect(find.text('MYR 3346.00'), findsOneWidget);
    expect(find.text('Paid'), findsOneWidget);
    expect(find.text('Test Mode'), findsOneWidget);
  });

  testWidgets('2. Paid Flight and Hotel payments displayed when supported', (tester) async {
    final api = _MockPaymentApi(items: [sampleHotelPayment, sampleFlightPayment]);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Hotel — Heritage Hotel Georgetown'), findsOneWidget);
    expect(find.text('Flight Booking'), findsOneWidget);
    expect(find.text('MYR 450.00'), findsOneWidget);
    expect(find.text('MYR 280.50'), findsOneWidget);
  });

  testWidgets('3. Legacy succeeded payment displayed with honest fallback', (tester) async {
    final api = _MockPaymentApi(items: [sampleLegacyPayment]);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Legacy Payment Booking'), findsOneWidget);
    expect(find.text('MYR 80.00'), findsOneWidget);
    expect(find.text('Paid'), findsOneWidget);
  });

  testWidgets('4. Pending/unpaid payment is marked Pending and NOT marked Paid', (tester) async {
    final api = _MockPaymentApi(items: [samplePendingPayment]);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Package — Penang Street Food Adventure'), findsOneWidget);
    expect(find.text('Pending'), findsOneWidget);
    expect(find.text('Paid'), findsNothing);
  });

  testWidgets('5. Failed payment is labeled correctly', (tester) async {
    final api = _MockPaymentApi(items: [sampleFailedPayment]);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.text('Hotel — Sunset Beach Resort'), findsOneWidget);
    expect(find.text('Failed'), findsOneWidget);
    expect(find.text('Paid'), findsNothing);
  });

  testWidgets('6. Records display sorted newest-first', (tester) async {
    // Pass items in unordered dates
    final api = _MockPaymentApi(items: [
      sampleLegacyPayment, // Sept 1
      samplePackagePayment, // Oct 18 10:15
      samplePendingPayment, // Oct 18 11:00 (newest)
      sampleHotelPayment, // Oct 17
    ]);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    // Verify all 4 cards render
    expect(find.byKey(const ValueKey('payment-item-order-pending-505')), findsOneWidget);
    expect(find.byKey(const ValueKey('payment-item-order-pkg-101')), findsOneWidget);
    expect(find.byKey(const ValueKey('payment-item-order-htl-202')), findsOneWidget);
    expect(find.byKey(const ValueKey('payment-item-legacy-pay-404')), findsOneWidget);

    // Verify vertical order (newest first)
    final pendingY = tester.getTopLeft(find.byKey(const ValueKey('payment-item-order-pending-505'))).dy;
    final packageY = tester.getTopLeft(find.byKey(const ValueKey('payment-item-order-pkg-101'))).dy;
    final hotelY = tester.getTopLeft(find.byKey(const ValueKey('payment-item-order-htl-202'))).dy;
    final legacyY = tester.getTopLeft(find.byKey(const ValueKey('payment-item-legacy-pay-404'))).dy;

    expect(pendingY < packageY, isTrue);
    expect(packageY < hotelY, isTrue);
    expect(hotelY < legacyY, isTrue);
  });

  testWidgets('7. Empty response displays an honest empty state', (tester) async {
    final api = _MockPaymentApi(items: []);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('payment-history-empty')), findsOneWidget);
    expect(find.text('No payment records yet'), findsOneWidget);
    expect(find.text('Completed package bookings and checkout transactions will appear here.'), findsOneWidget);
  });

  testWidgets('8. Backend error displays error state with retry action', (tester) async {
    final api = _MockPaymentApi();
    api.shouldThrowError = true;

    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('payment-history-error')), findsOneWidget);

    // Turn off error and tap retry
    api.shouldThrowError = false;
    api.paymentItems = [samplePackagePayment];
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();

    expect(find.text('Package — Penang Heritage & Hills Escape'), findsOneWidget);
  });

  testWidgets('9. Session expiry (401) is handled safely', (tester) async {
    final api = _MockPaymentApi();
    api.shouldThrowAuthError = true;

    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('payment-history-session-expired')), findsOneWidget);
    expect(find.text('Session Expired'), findsOneWidget);
    expect(find.textContaining('sign in again'), findsOneWidget);
  });

  testWidgets('10. Test Mode clearly disclosed on card and in detail sheet', (tester) async {
    final api = _MockPaymentApi(items: [samplePackagePayment]);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    // On card
    expect(find.text('Test Mode'), findsOneWidget);

    // Tap to open detail bottom sheet
    await tester.tap(find.byKey(const ValueKey('payment-item-order-pkg-101')));
    await tester.pumpAndSettle();

    expect(find.text('Payment Details'), findsOneWidget);
    expect(find.text('Stripe Test Mode'), findsOneWidget);
    expect(find.textContaining('Stripe Test Mode. No real financial transaction'), findsOneWidget);
  });

  testWidgets('11. Long Order Reference does not overflow and can be copied in details', (tester) async {
    final longRefPayment = {
      'id': 'order_cs_test_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0_very_long_reference_string',
      'orderReference': 'order_cs_test_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0_very_long_reference_string',
      'bookingType': 'package',
      'productTitle': 'Penang Heritage Package with a very long descriptive title for responsive overflow testing',
      'amount': 1250.00,
      'currency': 'MYR',
      'paymentStatus': 'paid',
      'testMode': true,
      'timestamp': '2026-10-18T10:00:00+00:00',
    };

    final api = _MockPaymentApi(items: [longRefPayment]);
    // Test on narrow 360px screen
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api), size: const Size(360, 800)));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);

    // Open detail sheet
    await tester.tap(find.textContaining('Penang Heritage Package'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('Payment Details'), findsOneWidget);
    expect(find.byIcon(Icons.copy_rounded), findsOneWidget);
  });

  testWidgets('12. Checkout Test entry is removed from ProfileTab; only Payment history remains', (tester) async {
    final api = _MockPaymentApi();
    await tester.pumpWidget(buildTestWidget(ProfileTab(api: api)));
    await tester.pumpAndSettle();

    // Verify Payment history tile is present
    await tester.scrollUntilVisible(find.text('Payment history'), 300);
    expect(find.text('Payment history'), findsOneWidget);

    // Verify NO Checkout Test button, card or tile exists in Profile
    expect(find.textContaining('Checkout Test'), findsNothing);
    expect(find.textContaining('Secure card payment'), findsNothing);
    expect(find.textContaining('Card number'), findsNothing);
    expect(find.textContaining('Pay RM'), findsNothing);
  });

  testWidgets('13. Existing Stripe Checkout functionality in PaymentScreen remains functional', (tester) async {
    final api = _MockPaymentApi();
    // Hosted checkout mode for package
    await tester.pumpWidget(buildTestWidget(PaymentScreen(
      api: api,
      packageAttemptId: 'attempt-123',
      initialAmount: 799.00,
      initialBookingReference: 'PKG-REF-1',
    )));
    await tester.pumpAndSettle();

    expect(find.text('TravelMate Checkout'), findsOneWidget);
    expect(find.text('Stripe test Checkout'), findsOneWidget);
    expect(find.text('Open Stripe test Checkout'), findsOneWidget);
  });

  testWidgets('14. Refreshing Payment History does not call any POST payment endpoints', (tester) async {
    final api = _MockPaymentApi(items: [samplePackagePayment]);
    await tester.pumpWidget(buildTestWidget(PaymentHistoryScreen(api: api)));
    await tester.pumpAndSettle();

    expect(api.getPaymentsCount, 1);
    expect(api.postCount, 0);

    // Tap refresh button
    await tester.tap(find.byKey(const ValueKey('payment-history-refresh')));
    await tester.pumpAndSettle();

    expect(api.getPaymentsCount, 2);
    expect(api.postCount, 0); // Zero POST calls made!
  });

  testWidgets('15. Tapping Payment history in ProfileTab opens PaymentHistoryScreen', (tester) async {
    final api = _MockPaymentApi(items: [samplePackagePayment]);
    await tester.pumpWidget(buildTestWidget(ProfileTab(api: api)));
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(find.text('Payment history'), 300);
    await tester.tap(find.text('Payment history'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('payment-history-screen')), findsOneWidget);
    expect(find.text('Package — Penang Heritage & Hills Escape'), findsOneWidget);
  });
}
