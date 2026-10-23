import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/car_rental_screen.dart';

void main() {
  Widget wrap(Widget child) => MaterialApp(home: child);

  testWidgets('opens with prefilled pickup location when supplied from context',
      (tester) async {
    await tester.pumpWidget(wrap(const CarRentalScreen(
      initialPickupLocation: 'Kuala Lumpur City Centre',
      initialPickupDate: '2026-11-20',
      initialDropoffDate: '2026-11-23',
    )));

    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    final pickup = fields.firstWhere(
        (f) => f.decoration?.labelText == 'Pickup location');
    expect(pickup.controller?.text, 'Kuala Lumpur City Centre');
    expect(find.text('George Town, Penang'), findsNothing);
  });

  testWidgets('opens with neutral empty location when opened without context',
      (tester) async {
    await tester.pumpWidget(wrap(const CarRentalScreen()));

    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    final pickup = fields.firstWhere(
        (f) => f.decoration?.labelText == 'Pickup location');
    expect(pickup.controller?.text, isEmpty);
    expect(pickup.decoration?.hintText,
        'City, airport, or destination in Malaysia');
    expect(find.text('George Town, Penang'), findsNothing);
  });

  testWidgets('tapping a Malaysian hub chip fills the pickup location field',
      (tester) async {
    await tester.pumpWidget(wrap(const CarRentalScreen()));

    expect(find.widgetWithText(ActionChip, 'Kota Kinabalu'), findsOneWidget);
    await tester.tap(find.widgetWithText(ActionChip, 'Kota Kinabalu'));
    await tester.pump();

    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    final pickup = fields.firstWhere(
        (f) => f.decoration?.labelText == 'Pickup location');
    expect(pickup.controller?.text, 'Kota Kinabalu');
  });

  testWidgets('user manually editing pickup location preserves their input',
      (tester) async {
    await tester.pumpWidget(wrap(const CarRentalScreen()));

    final pickupFinder = find.widgetWithText(TextField, 'Pickup location');
    await tester.enterText(pickupFinder, 'Kuching Waterfront');
    await tester.pump();

    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    final pickup = fields.firstWhere(
        (f) => f.decoration?.labelText == 'Pickup location');
    expect(pickup.controller?.text, 'Kuching Waterfront');
  });

  testWidgets('validation alerts traveller when searching with empty location',
      (tester) async {
    await tester.pumpWidget(wrap(const CarRentalScreen()));

    await tester.tap(find.widgetWithText(FilledButton, 'Search car rentals'));
    await tester.pump();

    expect(find.text('Enter a pickup location in Malaysia.'), findsOneWidget);
  });
}
