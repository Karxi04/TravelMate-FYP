import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr01_user_management/profile_tab.dart';
import 'package:travelmate_traveller/modules/fr09_payment/orders_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class OrdersApi extends ApiService {
  final calls = <String>[];
  bool fail = false;
  String status = 'paid';
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    calls.add(path);
    if (path == '/api/fr1/me')
      return {
        'profile': {'name': 'Test traveller', 'email': 'test@example.com'}
      };
    if (path == '/api/fr2/preferences') return {'preferences': {}};
    if (path == '/api/fr4/preference-feedback') return {'learning': {}};
    if (fail) throw const ApiException('Order not found', 404, {});
    final order = {
      'id': 'owned-order',
      'quoteType': 'hotel',
      'amount': 163.89,
      'currency': 'MYR',
      'status': status,
      'paymentStatus': status == 'paid' ? 'paid' : 'unpaid',
      'sandbox': true
    };
    if (path == '/api/fr9/orders')
      return {
        'items': [order]
      };
    if (path.startsWith('/api/fr9/orders/owned-order')) return {'order': order};
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async =>
      throw StateError('Orders must not create payments');
}

void main() {
  testWidgets(
      'Profile exposes Orders separately from legacy records and opens owned details',
      (tester) async {
    final api = OrdersApi();
    await tester.pumpWidget(MaterialApp(home: ProfileTab(api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Payment records'), 400,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('Payment records'), findsOneWidget);
    await tester.ensureVisible(find.text('Orders'));
    await tester.tap(find.text('Orders'));
    await tester.pumpAndSettle();
    expect(find.text('hotel · MYR 163.89'), findsOneWidget);
    await tester.tap(find.text('hotel · MYR 163.89'));
    await tester.pumpAndSettle();
    expect(find.text('Order details'), findsOneWidget);
    expect(find.text('Payment confirmed. No further payment is required.'),
        findsOneWidget);
    expect(find.text('Check payment status'), findsNothing);
    expect(find.textContaining('Pay RM'), findsNothing);
    expect(api.calls, contains('/api/fr9/orders/owned-order'));
    expect(api.calls.where((p) => p.endsWith('/reconcile')), isEmpty);
  });

  testWidgets(
      'Details can reconcile pending orders and preserve paid no-Pay state',
      (tester) async {
    final api = OrdersApi()..status = 'payment_pending';
    await tester.pumpWidget(
        MaterialApp(home: OrdersScreen(api: api, orderId: 'owned-order')));
    await tester.pumpAndSettle();
    api.status = 'paid';
    await tester.tap(find.text('Check payment status'));
    await tester.pumpAndSettle();
    expect(api.calls.last, '/api/fr9/orders/owned-order/reconcile');
    expect(find.text('Check payment status'), findsNothing);
    expect(find.text('Payment confirmed. No further payment is required.'),
        findsOneWidget);
  });

  testWidgets(
      'Denied details show an error rather than stale order data and retry works',
      (tester) async {
    final api = OrdersApi()..fail = true;
    await tester.pumpWidget(
        MaterialApp(home: OrdersScreen(api: api, orderId: 'owned-order')));
    await tester.pumpAndSettle();
    expect(find.text('Order not found'), findsOneWidget);
    expect(find.textContaining('163.89'), findsNothing);
    api.fail = false;
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.text('MYR 163.89'), findsOneWidget);
  });
}
