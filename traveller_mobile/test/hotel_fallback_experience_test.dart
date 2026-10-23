import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockHotelApi extends ApiService {
  final Map<String, dynamic> Function(String path, dynamic body)? postHandler;

  _MockHotelApi({this.postHandler});

  @override
  Future<dynamic> post(String path, [dynamic body]) async {
    if (postHandler != null) {
      return postHandler!(path, body);
    }
    return {'ok': true, 'items': []};
  }

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    return {'ok': true, 'items': []};
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

void main() {
  Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

  testWidgets('opens with prefilled destination when supplied from context',
      (tester) async {
    await tester.pumpWidget(wrap(const HotelScreen(
      initialDestination: 'Melaka City',
      initialCheckin: '2026-11-20',
      initialCheckout: '2026-11-22',
    )));

    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    final dest = fields.firstWhere(
        (f) => f.decoration?.labelText == 'Destination');
    expect(dest.controller?.text, 'Melaka City');
    expect(find.text('George Town, Penang'), findsNothing);
  });

  testWidgets('opens with neutral empty destination when opened without context',
      (tester) async {
    await tester.pumpWidget(wrap(const HotelScreen()));

    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    final dest = fields.firstWhere(
        (f) => f.decoration?.labelText == 'Destination');
    expect(dest.controller?.text, isEmpty);
    expect(dest.decoration?.hintText, 'City or destination in Malaysia');
    expect(find.text('George Town, Penang'), findsNothing);
  });

  testWidgets('tapping a Malaysian hub chip fills the destination field',
      (tester) async {
    await tester.pumpWidget(wrap(const HotelScreen()));

    expect(find.widgetWithText(ActionChip, 'Kuala Lumpur'), findsOneWidget);
    await tester.tap(find.widgetWithText(ActionChip, 'Kuala Lumpur'));
    await tester.pump();

    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    final dest = fields.firstWhere(
        (f) => f.decoration?.labelText == 'Destination');
    expect(dest.controller?.text, 'Kuala Lumpur');
  });

  testWidgets('fallback search outside Penang shows accurate limited sample notice without Penang leakage',
      (tester) async {
    _setViewport(tester);
    final api = _MockHotelApi(postHandler: (path, body) {
      if (path == '/api/fr8/hotels/search') {
        final dest = (body['destination'] ?? '').toString();
        // Backend returns empty items with sampleContentLimited: true for non-Penang fallback
        return {
          'ok': true,
          'items': [],
          'source': 'local',
          'noResults': true,
          'destination': dest,
          'sampleContentLimited': true,
        };
      }
      return {'ok': true};
    });

    await tester.pumpWidget(wrap(HotelScreen(
      api: api,
      initialDestination: 'Kuala Lumpur',
    )));
    await tester.pumpAndSettle();

    // Tap search
    final searchBtn = find.widgetWithText(FilledButton, 'Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    // Verify empty state clearly explains limited local sample content for KL
    expect(find.text('No hotel offers in Kuala Lumpur'), findsOneWidget);
    expect(
        find.textContaining('Local demo content is limited for this location'),
        findsOneWidget);
    expect(find.textContaining('sample properties are available in Penang'),
        findsOneWidget);
    // Crucial: Penang sample hotels must NOT be listed under Kuala Lumpur
    expect(find.text('Ink Wash Heritage Hotel'), findsNothing);
    expect(find.text('Blue Grey City Hotel'), findsNothing);
  });

  testWidgets('fallback search for Penang displays local sample hotels',
      (tester) async {
    _setViewport(tester);
    final api = _MockHotelApi(postHandler: (path, body) {
      if (path == '/api/fr8/hotels/search') {
        return {
          'ok': true,
          'items': [
            {
              'hotelId': 'local_hotel_1',
              'name': 'Ink Wash Heritage Hotel',
              'address': 'George Town, Penang',
              'rating': 8.8,
              'price': 238.0,
              'currency': 'MYR',
              'roomName': 'Deluxe Heritage Room',
              'priceStatus': 'available',
              'offerId': 'local_offer_1',
              'contentSource': 'sample_fixture',
              'rateSource': 'sample_fixture',
            }
          ],
          'source': 'local',
          'noResults': false,
          'sampleContentLimited': false,
        };
      }
      return {'ok': true};
    });

    await tester.pumpWidget(wrap(HotelScreen(
      api: api,
      initialDestination: 'Penang',
    )));
    await tester.pumpAndSettle();

    final searchBtn = find.widgetWithText(FilledButton, 'Search hotels');
    await tester.ensureVisible(searchBtn);
    await tester.tap(searchBtn);
    await tester.pumpAndSettle();

    expect(find.text('Ink Wash Heritage Hotel'), findsOneWidget);
    expect(find.text('Deluxe Heritage Room'), findsOneWidget);
  });
}
