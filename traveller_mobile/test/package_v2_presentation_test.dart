import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';

void main() {
  testWidgets('complete package shows traveller-ready product details',
      (tester) async {
    var added = false;
    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'title': 'Penang Heritage Escape',
          'destination': 'George Town, Penang',
          'fullDescription': 'A guided two-day local experience.',
          'durationDays': 2,
          'durationNights': 1,
          'currency': 'MYR',
          'adultPrice': 320,
          'originalPrice': 380,
          'promotionalPrice': 300,
          'priceBasis': 'per_person',
          'maximumTravellers': 12,
          'highlights': ['Street art', 'Local food'],
          'inclusions': ['Guide', 'Transport'],
          'exclusions': ['Flights'],
          'itineraryDays': [
            {
              'dayNumber': 1,
              'title': 'Heritage quarter',
              'description': 'Walk through George Town.',
              'activities': ['Clan jetty'],
              'meals': ['Lunch'],
              'accommodation': 'Heritage Hotel',
              'transportNotes': 'Private van',
            }
          ],
          'departureDates': ['2026-12-10'],
          'meetingPoint': 'Hotel lobby',
          'cancellationPolicy': 'Cancel seven days before departure.',
          'operatorName': 'Penang Local Tours',
        },
        onAddToTrip: () => added = true,
      ),
    ));

    expect(find.text('Penang Heritage Escape'), findsOneWidget);
    expect(find.text('MYR 300 / person'), findsOneWidget);
    expect(find.text('2 days · 1 night'), findsOneWidget);
    await tester.scrollUntilVisible(
        find.text('Day-by-day itinerary'), 300,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('Day-by-day itinerary'), findsOneWidget);
    expect(find.text('Day 1 · Heritage quarter'), findsOneWidget);
    await tester.tap(find.text('Day 1 · Heritage quarter'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Activities: Clan jetty'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Cancellation policy'), 300,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('Cancellation policy'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Tourism Operator'), 300,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('Tourism Operator'), findsOneWidget);
    await tester.tap(find.text('Add package to trip'));
    expect(added, isTrue);
  });

  testWidgets('legacy package stays readable and omits empty placeholders',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: TourismPackageDetailsScreen(item: {
        'packageTitle': 'Legacy Island Tour',
        'destinationName': 'Penang',
        'description': 'An existing approved package.',
        'durationDays': 1,
        'price': 88,
        'operatorName': 'Legacy Operator',
      }),
    ));

    expect(find.text('Legacy Island Tour'), findsOneWidget);
    expect(find.text('MYR 88 / person'), findsOneWidget);
    expect(find.text('1 day'), findsOneWidget);
    final visibleText = tester
        .widgetList<Text>(find.byType(Text))
        .map((widget) => widget.data ?? '')
        .join(' ');
    expect(visibleText, isNot(contains('null')));
    expect(visibleText, isNot(contains('[]')));
    expect(visibleText, isNot(contains('0 nights')));
  });
}
