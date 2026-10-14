import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_description.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_details_screen.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';

void main() {
  test('renders supported hotel markup without raw tags or active links', () {
    final spans = HotelDescription.spans(
      '<p>Welcome <strong>guests</strong>.</p><ul><li>Breakfast</li></ul><a href="https://unsafe.example">Terms</a>',
      bodyStyle: const TextStyle(color: InkWashColors.ink, height: 1.5),
    );
    final text = spans.map((span) => (span as TextSpan).text).join();
    expect(text, contains('Welcome guests.'));
    expect(text, contains('• Breakfast'));
    expect(text, contains('Terms'));
    expect(text, isNot(contains('<')));
    final strong = spans
        .cast<TextSpan>()
        .firstWhere((span) => span.text == 'guests');
    expect(strong.style?.color, InkWashColors.ink);
    expect(strong.style?.fontWeight, FontWeight.w700);
    expect(strong.style?.decoration, TextDecoration.none);
    expect(strong.style?.backgroundColor, Colors.transparent);
  });

  test('handles malformed and unsafe markup as neutral readable text', () {
    final spans = HotelDescription.spans(
      '<script>alert(1)</script><p>First</p><li>Second<strong> bold',
      bodyStyle: const TextStyle(color: InkWashColors.ink),
    );
    final text = spans.map((span) => (span as TextSpan).text).join();
    expect(text, isNot(contains('alert')));
    expect(text, contains('First'));
    expect(text, contains('• Second'));
    expect(text, contains('bold'));
    expect(spans.cast<TextSpan>(), everyElement(predicate<TextSpan>((span) =>
        span.style?.color == InkWashColors.ink &&
        span.style?.decoration == TextDecoration.none &&
        span.style?.backgroundColor == Colors.transparent)));
  });

  testWidgets('shows authoritative stay dates and handles missing dates',
      (tester) async {
    Future<void> pump(Map<String, dynamic> hotel) => tester.pumpWidget(
          MaterialApp(
            theme: buildInkWashTheme(),
            home: HotelDetailsScreen(hotel: hotel, onProceed: () {}),
          ),
        );

    await pump({
      'name': 'Test Hotel',
      'description': '<p>A simple stay.</p>',
      'checkin': '2030-01-01',
      'checkout': '2030-01-03',
      'checkInTime': '15:00',
      'checkOutTime': '11:00',
    });
    expect(find.text('2030-01-01 • 15:00'), findsOneWidget);
    expect(find.text('2030-01-03 • 11:00'), findsOneWidget);
    expect(find.textContaining('<p>'), findsNothing);

    await pump({
      'name': 'Test Hotel',
      'description': 'Plain text remains readable.',
    });
    expect(find.text('Not provided'), findsNWidgets(2));
    expect(find.text('Select room'), findsOneWidget);
  });
}
