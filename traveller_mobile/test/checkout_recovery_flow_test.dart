import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockCheckoutApi extends ApiService {
  Map<String, dynamic>? sessionPostResponse;
  Map<String, dynamic>? reconcileResponse;
  Map<String, dynamic>? newAttemptResponse;
  bool shouldThrowTimeout = false;
  bool shouldThrowAuthError = false;
  int postCount = 0;
  int getOrdersCount = 0;
  List<dynamic> ordersList = [];
  String? lastPostedPath;

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr9/payments') {
      return {'ok': true, 'items': []};
    }
    if (path == '/api/fr9/orders') {
      getOrdersCount++;
      return {'ok': true, 'items': ordersList};
    }
    if (path.contains('/api/fr9/orders/') && path.endsWith('/reconcile')) {
      if (shouldThrowTimeout) {
        throw TimeoutException('Network timed out');
      }
      return reconcileResponse ?? {'ok': true, 'order': {'checkoutAction': 'check_status'}};
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postCount++;
    lastPostedPath = path;
    if (shouldThrowAuthError) {
      throw const ApiException('Unauthorized traveller', 401, {'ok': false});
    }
    if (shouldThrowTimeout) {
      throw TimeoutException('Network connection timed out');
    }
    if (path.contains('/checkout/session')) {
      return sessionPostResponse ?? {
        'ok': true,
        'order': {
          'id': 'order-test-1',
          'quoteType': 'package',
          'status': 'checkout_open',
          'checkoutAction': 'continue_payment',
          'checkoutUrl': 'https://checkout.stripe.test/cs_test_1',
          'amount': 3596.00,
        }
      };
    }
    if (path == '/api/fr15/package-checkout-attempts') {
      return newAttemptResponse ?? {
        'ok': true,
        'attempt': {
          'id': 'attempt-fresh-999',
          'amount': 3596.00,
          'packageId': 'pkg-penang-1',
        }
      };
    }
    return {'ok': true};
  }
}

Widget buildTestApp(Widget child) {
  return MaterialApp(
    home: child,
  );
}

void main() {
  testWidgets('Package checkout shows package-specific disclaimer, not hotel disclaimer', (tester) async {
    final api = _MockCheckoutApi();
    await tester.pumpWidget(buildTestApp(PaymentScreen(
      api: api,
      packageAttemptId: 'attempt-pkg-100',
      initialAmount: 3596.00,
      initialBookingReference: 'PKG-PENANG-100',
    )));
    await tester.pumpAndSettle();

    expect(find.text('TravelMate Checkout'), findsOneWidget);
    expect(find.text('Authoritative quote: MYR 3596.00'), findsOneWidget);

    // Package-specific disclaimer is shown:
    expect(
      find.textContaining('This is a Stripe test-mode order for an operator tourism package'),
      findsOneWidget,
    );
    expect(
      find.textContaining('Supplier reservations remain managed by the licensed operator'),
      findsOneWidget,
    );
    // Hotel-specific property fees disclaimer is NOT shown:
    expect(
      find.textContaining('The selected hotel quote is a provider sandbox quote and is not live inventory'),
      findsNothing,
    );
  });

  testWidgets('Hotel checkout shows hotel-specific provider sandbox and property fees disclaimer', (tester) async {
    final api = _MockCheckoutApi();
    await tester.pumpWidget(buildTestApp(PaymentScreen(
      api: api,
      quoteType: 'hotel',
      quoteId: 'hotel-quote-1',
      offerId: 'offer-1',
      initialAmount: 450.00,
    )));
    await tester.pumpAndSettle();

    expect(
      find.textContaining('The selected hotel quote is a provider sandbox quote and is not live inventory'),
      findsOneWidget,
    );
    expect(
      find.textContaining('excluded property fees remain due at the property'),
      findsOneWidget,
    );
    expect(
      find.textContaining('operator tourism package'),
      findsNothing,
    );
  });

  testWidgets('HTTP 202 or check_status releases loading and transitions button to Check Payment Status', (tester) async {
    final api = _MockCheckoutApi();
    api.sessionPostResponse = {
      'ok': true,
      'order': {
        'id': 'order-pending-1',
        'quoteType': 'package',
        'status': 'checkout_pending',
        'paymentStatus': 'unpaid',
        'checkoutAction': 'check_status',
        'amount': 3596.00,
      }
    };

    await tester.pumpWidget(buildTestApp(PaymentScreen(
      api: api,
      packageAttemptId: 'attempt-pkg-100',
      initialAmount: 3596.00,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Open Stripe test Checkout'), findsOneWidget);

    // Tap to launch checkout
    await tester.tap(find.text('Open Stripe test Checkout'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 200));

    // Button MUST NOT remain stuck on 'Preparing Checkout…'
    expect(find.text('Preparing Checkout…'), findsNothing);
    // Button transitions to 'Check Payment Status'
    expect(find.text('Check Payment Status'), findsOneWidget);
    // SnackBar informs traveller truthfully
    expect(
      find.text('Payment status is still being verified. No additional payment was opened.'),
      findsOneWidget,
    );
  });

  testWidgets('Network timeout releases loading and shows recoverable error', (tester) async {
    final api = _MockCheckoutApi();
    api.shouldThrowTimeout = true;

    await tester.pumpWidget(buildTestApp(PaymentScreen(
      api: api,
      packageAttemptId: 'attempt-pkg-100',
      initialAmount: 3596.00,
    )));
    await tester.pumpAndSettle();

    expect(find.text('Open Stripe test Checkout'), findsOneWidget);

    await tester.tap(find.text('Open Stripe test Checkout'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 200));

    // Button MUST NOT be stuck on 'Preparing Checkout…'
    expect(find.text('Preparing Checkout…'), findsNothing);
    // Error message appears
    expect(find.textContaining('couldn’t connect to TravelMate'), findsOneWidget);
  });

  testWidgets('Expired Session offers Restart Payment and does not throw raw exception', (tester) async {
    final api = _MockCheckoutApi();
    api.sessionPostResponse = {
      'ok': true,
      'order': {
        'id': 'order-expired-1',
        'quoteType': 'package',
        'packageId': 'pkg-food-1',
        'status': 'expired',
        'paymentStatus': 'unpaid',
        'checkoutAction': 'restart_payment',
        'amount': 3596.00,
      }
    };

    await tester.pumpWidget(buildTestApp(PaymentScreen(
      api: api,
      packageAttemptId: 'attempt-pkg-100',
      initialAmount: 3596.00,
    )));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Open Stripe test Checkout'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 200));

    // Button transitions to Restart Payment
    expect(find.text('Restart Payment'), findsOneWidget);
    expect(find.text('This Checkout Session has ended. You can restart payment.'), findsOneWidget);
  });

  testWidgets('Paid order displays Payment Verified and View Confirmed Booking', (tester) async {
    final api = _MockCheckoutApi();
    api.ordersList = [
      {
        'id': 'order-paid-1',
        'packageAttemptId': 'attempt-pkg-paid',
        'quoteType': 'package',
        'status': 'paid',
        'paymentStatus': 'paid',
        'checkoutAction': 'view_booking',
        'amount': 3596.00,
      }
    ];

    await tester.pumpWidget(buildTestApp(PaymentScreen(
      api: api,
      packageAttemptId: 'attempt-pkg-paid',
      initialAmount: 3596.00,
    )));
    await tester.pumpAndSettle();

    expect(find.text('View Confirmed Booking'), findsOneWidget);
    expect(find.text('Payment Verified · Booking Confirmed'), findsOneWidget);
  });
}
