import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _PackageDetailsApi extends ApiService {
  String? postedPath;
  Map<String, dynamic>? postedPayload;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    return {'items': []};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postedPath = path;
    postedPayload = Map<String, dynamic>.from(body ?? const {});
    return {
      'ok': true,
      // Stop before PaymentScreen: this focused widget test has no Firebase app.
      'attempt': <String, dynamic>{},
    };
  }
}

void main() {
  testWidgets('complete package shows traveller-ready product details',
      (tester) async {
    var legacyCallbackCalled = false;
    final api = _PackageDetailsApi();
    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-1',
          'title': 'Penang Heritage Escape',
          'destination': 'George Town, Penang',
          'fullDescription': 'A guided two-day local experience.',
          'durationDays': 2,
          'durationNights': 1,
          'currency': 'MYR',
          'adultPrice': 320,
          'childPrice': 160,
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
        api: api,
        onAddToTrip: () => legacyCallbackCalled = true,
      ),
    ));

    expect(find.text('Penang Heritage Escape'), findsOneWidget);
    expect(find.text('MYR 320 / adult'), findsOneWidget);
    expect(find.text('2 days · 1 night'), findsOneWidget);
    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('package-group-booking')), 300,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('Group total: MYR 320'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.tap(find.byKey(const ValueKey('package-children-add')));
    await tester.pump();
    expect(find.text('Group total: MYR 800'), findsOneWidget);
    await tester.scrollUntilVisible(
        find.text('Day 1 · Heritage quarter'), 300,
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
    await tester.tap(find.text('Checkout package'));
    await tester.pumpAndSettle();
    expect(api.postedPath, '/api/fr15/package-checkout-attempts');
    expect(api.postedPayload?['participants'], {'adults': 2, 'children': 1});
    expect(api.postedPayload?['departureDate'], '2026-12-10');
    expect(api.postedPayload?.containsKey('intendedTripId'), isFalse);
    expect(legacyCallbackCalled, isFalse);
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
    expect(find.text('MYR 88 / adult'), findsOneWidget);
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
