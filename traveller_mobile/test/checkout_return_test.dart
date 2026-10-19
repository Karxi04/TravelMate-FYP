import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr09_payment/checkout_return_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _ReturnApi extends ApiService {
  _ReturnApi(this.initialOrder, {this.reconciledOrder, this.denied = false});

  final Map<String, dynamic> initialOrder;
  final Map<String, dynamic>? reconciledOrder;
  final bool denied;
  final calls = <String>[];
  var reconcileCalls = 0;
  var postCalls = 0;

  Map<String, dynamic> get current => reconciledOrder ?? initialOrder;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    calls.add(path);
    if (denied && path.contains('/orders/')) {
      throw const ApiException('Order not found', 404, {});
    }
    if (path.endsWith('/reconcile')) {
      reconcileCalls += 1;
      return {'ok': true, 'order': current};
    }
    if (path == '/api/fr9/orders') return {'ok': true, 'items': [current]};
    if (path == '/api/fr9/payments') return {'ok': true, 'items': const []};
    if (path.startsWith('/api/fr9/orders/')) {
      return {'ok': true, 'order': initialOrder};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postCalls += 1;
    throw StateError('Checkout return must not POST to $path');
  }
}

Widget _screen(_ReturnApi api, {String state = 'paid'}) => MaterialApp(
      home: CheckoutReturnScreen(
        link: CheckoutReturnLink('package_checkout_order_12345678', state),
        api: api,
      ),
    );

void main() {
  test('custom checkout scheme is registered only in the debug manifest', () {
    final mainManifest = File('android/app/src/main/AndroidManifest.xml').readAsStringSync();
    final debugManifest = File('android/app/src/debug/AndroidManifest.xml').readAsStringSync();
    expect(mainManifest, isNot(contains('android:scheme="travelmate"')));
    expect(debugManifest, contains('android:scheme="travelmate"'));
    expect(debugManifest, contains('android:host="checkout"'));
    expect(debugManifest, contains('android:path="/return"'));
    expect(debugManifest, contains('android:usesCleartextTraffic="true"'));
  });

  test('accepts only the exact non-secret checkout return URI contract', () {
    final valid = CheckoutReturnLink.parse(
      'travelmate://checkout/return?order_id=package_checkout_order_12345678&state=paid',
    );
    expect(valid?.orderId, 'package_checkout_order_12345678');
    expect(valid?.stateHint, 'paid');

    for (final invalid in [
      'https://checkout/return?order_id=package_checkout_order_12345678&state=paid',
      'travelmate://other/return?order_id=package_checkout_order_12345678&state=paid',
      'travelmate://checkout/other?order_id=package_checkout_order_12345678&state=paid',
      'travelmate://checkout/return?order_id=short&state=paid',
      'travelmate://checkout/return?order_id=package_checkout_order_12345678&state=success',
      'travelmate://checkout/return?order_id=package_checkout_order_12345678&state=paid&token=secret',
      'travelmate://checkout/return?order_id=one_valid_order&order_id=another_valid_order&state=paid',
    ]) {
      expect(CheckoutReturnLink.parse(invalid), isNull, reason: invalid);
    }
  });

  testWidgets('verified paid order refreshes history and exposes its Package Trip', (tester) async {
    final api = _ReturnApi({
      'id': 'package_checkout_order_12345678',
      'status': 'paid',
      'paymentStatus': 'paid',
      'quoteType': 'package',
      'fulfilledTripId': 'package_trip_12345678',
    });
    await tester.pumpWidget(_screen(api));
    await tester.pumpAndSettle();

    expect(find.text('Payment Successful'), findsOneWidget);
    expect(find.text('Open Package Trip'), findsOneWidget);
    expect(find.text('View Payment History'), findsOneWidget);
    expect(api.reconcileCalls, 0);
    expect(api.calls, containsAll(['/api/fr9/orders', '/api/fr9/payments']));
    expect(api.postCalls, 0);
  });

  testWidgets('spoofed paid hint cannot override backend pending state', (tester) async {
    final pending = {
      'id': 'package_checkout_order_12345678',
      'status': 'payment_pending',
      'paymentStatus': 'unpaid',
      'quoteType': 'package',
    };
    final api = _ReturnApi(pending, reconciledOrder: pending);
    await tester.pumpWidget(_screen(api, state: 'paid'));
    await tester.pumpAndSettle();

    expect(find.text('Payment Processing'), findsOneWidget);
    expect(find.text('Payment Successful'), findsNothing);
    expect(find.text('Check payment status'), findsOneWidget);
    expect(api.reconcileCalls, 1);
    expect(api.postCalls, 0);
  });

  testWidgets('cancel hint cannot mark an open backend order paid', (tester) async {
    final open = {
      'id': 'package_checkout_order_12345678',
      'status': 'checkout_open',
      'paymentStatus': 'unpaid',
      'quoteType': 'package',
    };
    final api = _ReturnApi(open, reconciledOrder: open);
    await tester.pumpWidget(_screen(api, state: 'not_completed'));
    await tester.pumpAndSettle();

    expect(find.text('Payment Not Completed'), findsOneWidget);
    expect(find.text('Payment Successful'), findsNothing);
    expect(find.text('Open Package Trip'), findsNothing);
    expect(api.reconcileCalls, 1);
    expect(api.postCalls, 0);
  });

  testWidgets('another Traveller order fails without disclosure', (tester) async {
    final api = _ReturnApi(const {}, denied: true);
    await tester.pumpWidget(_screen(api, state: 'paid'));
    await tester.pumpAndSettle();

    expect(
      find.text('This Checkout order is not available for the signed-in Traveller.'),
      findsOneWidget,
    );
    expect(find.text('Payment Successful'), findsNothing);
    expect(api.reconcileCalls, 0);
    expect(api.postCalls, 0);
  });
}
