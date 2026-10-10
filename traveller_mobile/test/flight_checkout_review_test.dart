import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/orders_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class FlightApi extends ApiService {
  bool paid = false;
  bool blocked = false;
  bool changed = false;
  int creations = 0;
  Map<String, dynamic>? confirmed;
  Map<String, dynamic> get snapshot => {
        'price': 120,
        'currency': 'MYR',
        'travellerCount': 1,
        'retrievedAt': '2026-10-10T00:00:00Z',
        'expiresAt': '2026-10-10T01:00:00Z',
        'outboundSegments': [
          {
            'airline': 'Fixture Air',
            'flightNumber': 'FX1',
            'departureAirportCode': 'KUL',
            'arrivalAirportCode': 'PEN',
            'departureDate': '2027-01-01',
            'arrivalDate': '2027-01-01',
            'departureTime': '10:00',
            'arrivalTime': '11:00'
          }
        ],
        'returnSegments': [],
      };
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr9/payments') return {'items': []};
    final order = {
      'id': 'flight_demo',
      'quoteType': 'flight',
      'status': 'paid',
      'paymentStatus': 'paid',
      'amount': 120,
      'currency': 'MYR',
      'provider': 'stripe_checkout_test',
      'quoteFingerprint': 'f3-reviewed',
      'quoteSnapshot': snapshot
    };
    if (path == '/api/fr9/orders')
      return {
        'items': paid ? [order] : []
      };
    if (path == '/api/fr9/orders/flight_demo') return {'order': order};
    throw StateError('Unexpected GET');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr9/checkout/flight-review') {
      if (blocked)
        throw const ApiException(
            'Multi-adult price scope is unresolved.', 409, {});
      return {
        'review': snapshot,
        'fingerprint': changed ? 'fresh-review' : 'f3-reviewed'
      };
    }
    if (path == '/api/fr9/checkout/session') {
      creations++;
      confirmed = body;
      if (changed)
        throw const ApiException('Flight quote changed. Reconfirm.', 409, {});
      return {
        'order': {'id': 'flight_demo', 'checkoutUrl': ''}
      };
    }
    throw StateError('Unexpected POST');
  }
}

Future<void> open(WidgetTester tester, FlightApi api) async {
  await tester.pumpWidget(MaterialApp(
      home: PaymentScreen(
          api: api,
          quoteType: 'flight',
          searchId: 'search',
          optionId: 'option')));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  testWidgets(
      'all segments and demo disclosures are reviewed before explicit confirmation',
      (tester) async {
    final api = FlightApi();
    await open(tester, api);
    expect(find.text('Adults: 1'), findsOneWidget);
    expect(find.text('Fixture Air FX1'), findsOneWidget);
    expect(find.text('Stripe test payment.'), findsOneWidget);
    expect(find.text('TravelMate demo order.'), findsOneWidget);
    expect(find.text('No flight has been booked or ticketed.'), findsOneWidget);
    await tester.ensureVisible(find.text('Open Stripe test Checkout'));
    await tester.tap(find.text('Open Stripe test Checkout'));
    await tester.pumpAndSettle();
    expect(find.text('Confirm flight demo quote'), findsOneWidget);
    expect(api.creations, 0);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(api.creations, 0);
    await tester.tap(find.text('Open Stripe test Checkout'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm this quote'));
    await tester.pumpAndSettle();
    expect(api.creations, 1);
    expect(api.confirmed!['confirmedFlightQuote'], true);
    expect(api.confirmed!['flightQuoteFingerprint'], 'f3-reviewed');
  });
  testWidgets(
      'unsupported price basis blocks launch while explaining the issue',
      (tester) async {
    final api = FlightApi()..blocked = true;
    await open(tester, api);
    expect(find.text('Multi-adult price scope is unresolved.'), findsOneWidget);
    final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Open Stripe test Checkout'));
    expect(button.onPressed, isNull);
    expect(api.creations, 0);
  });
  testWidgets('paid owned flight remains read-only after screen recreation',
      (tester) async {
    final api = FlightApi()..paid = true;
    await tester.pumpWidget(
        MaterialApp(home: OrdersScreen(api: api, orderId: 'flight_demo')));
    await tester.pumpAndSettle();
    expect(find.text('No flight has been booked or ticketed.'), findsOneWidget);
    expect(find.textContaining('Pay RM'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    await tester.pumpWidget(
        MaterialApp(home: OrdersScreen(api: api, orderId: 'flight_demo')));
    await tester.pumpAndSettle();
    expect(find.text('Status: paid'), findsOneWidget);
    expect(find.text('Fixture Air FX1'), findsOneWidget);
    expect(api.creations, 0);
  });
  testWidgets('paid matching snapshot cannot start another Checkout',
      (tester) async {
    final api = FlightApi()..paid = true;
    await open(tester, api);
    final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'This flight demo order is paid'));
    expect(button.onPressed, isNull);
    expect(api.creations, 0);
  });
  testWidgets('material changes require another explicit review confirmation',
      (tester) async {
    final api = FlightApi();
    await open(tester, api);
    await tester.ensureVisible(find.text('Open Stripe test Checkout'));
    await tester.tap(find.text('Open Stripe test Checkout'));
    await tester.pumpAndSettle();
    api.changed = true;
    await tester.tap(find.text('Confirm this quote'));
    await tester.pumpAndSettle();
    expect(api.creations, 1);
    expect(api.confirmed!['flightQuoteFingerprint'], 'f3-reviewed');
    await tester.ensureVisible(find.text('Open Stripe test Checkout'));
    await tester.tap(find.text('Open Stripe test Checkout'));
    await tester.pumpAndSettle();
    expect(find.text('Confirm flight demo quote'), findsOneWidget);
    expect(api.creations, 1);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(api.creations, 1);
  });
}
