import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockCheckoutApi extends ApiService {
  Map<String, dynamic>? sessionPostResponse;
  Map<String, dynamic>? reconcileResponse;
  Map<String, dynamic>? newAttemptResponse;
  bool checkoutEnabled = false;
  Map<String, dynamic>? lastPostedBody;
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
    if (path == '/api/fr9/checkout/capabilities') {
      return {'ok': true, 'mode': 'test', 'hostedCheckout': checkoutEnabled,
        'supportedQuoteTypes': ['hotel', 'package']};
    }
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
    lastPostedBody = body;
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
  for (final accept in [false, true]) {
    testWidgets('restarting expired package requires explicit fresh quote acceptance $accept', (tester) async {
      SharedPreferences.setMockInitialValues({});
      final api = _MockCheckoutApi()..checkoutEnabled = true
        ..ordersList = [{'id':'old-order','packageAttemptId':'old-attempt','quoteType':'package','packageId':'p1','status':'expired','checkoutAction':'restart_payment','amount':85,
          'packageSnapshot':{'packageId':'p1','participants':{'adults':1,'children':0}}}]
        ..newAttemptResponse = {'ok':true,'attempt':{'id':'fresh-attempt','amount':100,'pricingBreakdown':{'originalSubtotal':100,'promotionDiscount':0,'finalPayable':100,'currency':'MYR'}}}
        ..sessionPostResponse = {'ok':true,'order':{'id':'fresh-order','quoteType':'package','status':'checkout_pending','checkoutAction':'check_status','amount':100}};
      await tester.pumpWidget(buildTestApp(PaymentScreen(api:api,packageAttemptId:'old-attempt',initialAmount:85)));
      await tester.pumpAndSettle();
      final restart = find.text('Restart Payment');
      await tester.ensureVisible(restart);await tester.tap(restart);
      await tester.pump();await tester.pump(const Duration(milliseconds:300));
      expect(find.text('Review refreshed package quote'),findsOneWidget);
      expect(api.postCount,1);expect(api.lastPostedPath,'/api/fr15/package-checkout-attempts');
      await tester.tap(find.text(accept ? 'Accept quote' : 'Cancel'));await tester.pumpAndSettle();
      expect(api.postCount,accept ? 2 : 1);
      if(accept) expect(api.lastPostedPath,'/api/fr9/package-checkout-attempts/fresh-attempt/checkout/session');
    });
  }
  for (final kind in ['hotel', 'package']) {
    testWidgets('F-F1A-P $kind hosted checkout uses authoritative attempt only', (tester) async {
      SharedPreferences.setMockInitialValues({});
      final api = _MockCheckoutApi()..checkoutEnabled = true
        ..sessionPostResponse = {'ok': true, 'order': {
          'id': 'order-restored', 'quoteType': kind,
          'status': 'checkout_pending', 'checkoutAction': 'check_status',
          'paymentStatus': 'unpaid', 'amount': 420, 'currency': 'MYR',
        }};
      await tester.pumpWidget(buildTestApp(PaymentScreen(api: api,
        quoteType: kind, quoteId: 'owned-quote', offerId: 'owned-offer',
        packageAttemptId: kind == 'package' ? 'owned-package-attempt' : '',
        acceptedPrebookSnapshotId: 'accepted-snapshot',
        acceptedPrebook: const {'expiresAt': '2099-01-01T00:00:00Z'})));
      await tester.pumpAndSettle();
      expect(find.text('Review Payment'), findsOneWidget);
      expect(find.textContaining('Academic demonstration'), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      final dynamic state = tester.state(find.byType(PaymentScreen));
      await state.launchCheckout();
      await tester.pumpAndSettle();
      expect(api.postCount, 1);
      expect(api.lastPostedPath, kind == 'package'
        ? '/api/fr9/package-checkout-attempts/owned-package-attempt/checkout/session'
        : '/api/fr9/checkout/session');
      expect(api.lastPostedBody, isNot(contains('amount')));
      if (kind == 'hotel') {
        expect(api.lastPostedBody!['acceptedPrebookSnapshotId'], 'accepted-snapshot');
      }
      await state.process();
      await state.updatePayment('old-record', 'retry');
      expect(api.postCount, 1); // No legacy simulated payment.
    });

    testWidgets('F-F1A-P paid $kind recovers after reopening without checkout creation', (tester) async {
      final api = _MockCheckoutApi()..checkoutEnabled = true..ordersList = [{
        'id': 'paid-order', 'quoteType': kind, 'quoteId': 'owned-quote',
        'packageAttemptId': kind == 'package' ? 'owned-package-attempt' : null,
        'status': 'paid', 'paymentStatus': 'paid', 'checkoutAction': 'view_booking',
        'amount': 420, 'currency': 'MYR', 'supplierBookingStatus': 'not_created',
      }];
      for (var reopen = 0; reopen < 2; reopen++) {
        await tester.pumpWidget(buildTestApp(PaymentScreen(key: ValueKey(reopen), api: api,
          quoteType: kind, quoteId: 'owned-quote',
          packageAttemptId: kind == 'package' ? 'owned-package-attempt' : '',
          acceptedPrebookSnapshotId: 'accepted-snapshot')));
        await tester.pumpAndSettle();
        final dynamic state = tester.state(find.byType(PaymentScreen));
        expect(state.checkoutAction, 'view_booking');
        expect(find.text('Continue to Payment'), findsNothing);
      }
      expect(api.postCount, 0);
    });
  }

  testWidgets('F-F1A-P authorized hosted URL opens without app card entry', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final launches = <MethodCall>[];
    const channel = MethodChannel('plugins.flutter.io/url_launcher');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
      launches.add(call);
      return true;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, null));
    final api = _MockCheckoutApi()..checkoutEnabled = true..sessionPostResponse = {
      'ok': true, 'order': {'id': 'hosted-order', 'quoteType': 'package',
        'status': 'checkout_open', 'checkoutAction': 'continue_payment',
        'checkoutUrl': 'https://checkout.stripe.com/pay/synthetic-fixture',
        'amount': 100, 'currency': 'MYR'}};
    await tester.pumpWidget(buildTestApp(PaymentScreen(api: api, packageAttemptId: 'approved-attempt')));
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(PaymentScreen));
    await state.launchCheckout();
    await tester.pumpAndSettle();
    expect(api.postCount, 1);
    expect(launches.any((call) => call.arguments.toString().contains('https://checkout.stripe.com/pay/synthetic-fixture')), isTrue);
  });

  for (final missing in [true, false]) {
    testWidgets('F-F1A-P ${missing ? "missing" : "expired"} accepted snapshot cannot pay', (tester) async {
      final api = _MockCheckoutApi()..checkoutEnabled = true;
      await tester.pumpWidget(buildTestApp(PaymentScreen(api: api,
        quoteType: 'hotel', quoteId: 'owned-quote', offerId: 'owned-offer',
        acceptedPrebookSnapshotId: missing ? '' : 'expired-snapshot',
        acceptedPrebook: const {'expiresAt': '2000-01-01T00:00:00Z'})));
      await tester.pumpAndSettle();
      final dynamic state = tester.state(find.byType(PaymentScreen));
      await state.launchCheckout();
      expect(api.postCount, 0);
    });
  }

  for (final kind in ['flight', 'rental', 'legacy']) {
    testWidgets('F-F1A-P configured checkout never enables $kind', (tester) async {
      final api = _MockCheckoutApi()..checkoutEnabled = true;
      await tester.pumpWidget(buildTestApp(PaymentScreen(api: api,
        quoteType: kind == 'legacy' ? '' : kind)));
      await tester.pumpAndSettle();
      expect(find.text('Payments unavailable'), findsOneWidget);
      final dynamic state = tester.state(find.byType(PaymentScreen));
      await state.launchCheckout();
      expect(api.postCount, 0);
    });
  }

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
