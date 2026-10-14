import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';

void main() {
  testWidgets('uses explicit Trip guest counts without inferring a total',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: HotelScreen(initialAdults: 3, initialChildren: 1),
    ));

    expect(find.text('Adults'), findsOneWidget);
    expect(find.text('Children'), findsOneWidget);
    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    TextField field(String label) => fields.firstWhere(
        (candidate) => candidate.decoration?.labelText == label);
    expect(field('Adults').controller?.text, '3');
    expect(field('Children').controller?.text, '1');
  });

  testWidgets('requires an adult confirmation when a Trip has no age breakdown',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: HotelScreen(requiresGuestConfirmation: true),
    ));

    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    final adults = fields.firstWhere(
        (candidate) => candidate.decoration?.labelText == 'Adults');
    expect(adults.controller?.text, isEmpty);
    expect(find.textContaining('only stores a total traveller count'), findsOneWidget);
  });
}
