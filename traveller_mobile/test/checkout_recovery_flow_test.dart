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
  for (final kind in ['package', 'hotel', 'flight', 'legacy']) {
    testWidgets('F-F1A $kind payment entry is unavailable and cannot mutate', (tester) async {
      final api = _MockCheckoutApi();
      await tester.pumpWidget(buildTestApp(PaymentScreen(api: api,
        packageAttemptId: kind == 'package' ? 'existing-attempt' : '',
        quoteType: kind == 'legacy' || kind == 'package' ? '' : kind,
        quoteId: 'old-quote', acceptedPrebookSnapshotId: 'old-snapshot')));
      await tester.pumpAndSettle();
      expect(find.text('Payments unavailable'), findsOneWidget);
      expect(find.textContaining('Open Stripe'), findsNothing);
      expect(find.byType(TextField), findsNothing);
      final dynamic state = tester.state(find.byType(PaymentScreen));
      await state.launchCheckout();
      await state.process();
      await state.updatePayment('legacy-record', 'retry');
      await state.reconcileOrder('old-order');
      await tester.pumpAndSettle();
      expect(api.postCount, 0);
      expect(find.textContaining('Payment Successful'), findsNothing);
    });
  }

  for (final status in ['paid', 'checkout_open', 'expired', 'failed']) {
    testWidgets('F-F1A historical $status never re-enables test Checkout', (tester) async {
      final api = _MockCheckoutApi()..ordersList = [{
        'id': 'historical-order', 'packageAttemptId': 'existing-attempt',
        'status': status, 'paymentStatus': status == 'paid' ? 'paid' : 'unpaid',
        'checkoutUrl': 'https://checkout.stripe.test/not-opened', 'testMode': true,
        'checkoutAction': status == 'paid' ? 'view_booking' : 'continue_payment',
      }];
      await tester.pumpWidget(buildTestApp(PaymentScreen(api: api,
        packageAttemptId: 'existing-attempt')));
      await tester.pumpAndSettle();
      expect(find.text('Payments unavailable'), findsOneWidget);
      expect(find.text('Re-open Stripe Checkout'), findsNothing);
      expect(find.text('View Confirmed Booking'), findsNothing);
      expect(api.postCount, 0);
      expect(api.ordersList.single['status'], status);
    });
  }
}
