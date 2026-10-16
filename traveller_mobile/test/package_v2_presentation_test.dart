import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _PackageDetailsApi extends ApiService {
  String? postedPath;
  Map<String, dynamic>? postedPayload;
  Map<String, dynamic>? mockAttempt;

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
      // Stop before PaymentScreen if empty: this focused widget test has no Firebase app.
      'attempt': mockAttempt ?? <String, dynamic>{},
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

  testWidgets(
      'default participant count is 1 adult 0 children even with minimumTravellers',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-min-4',
          'title': 'Penang Heritage & Hills Escape',
          'priceBasis': 'per_person',
          'adultPrice': 899,
          'minimumTravellers': 4,
          'maximumTravellers': 12,
        },
      ),
    ));

    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('package-group-booking')), 300,
        scrollable: find.byType(Scrollable).first);

    expect(find.text('Adults: 1'), findsOneWidget);
    expect(find.text('Children: 0'), findsOneWidget);
    expect(find.text('Minimum requirement: 4 travellers'), findsOneWidget);
    expect(
        find.textContaining('Minimum group size: 4 travellers required (currently 1)'),
        findsOneWidget);
  });

  testWidgets(
      'Vivo pricing scenario: active promo calculates RM799/adult and RM3196 for 4 adults',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-vivo-active',
          'title': 'Penang Heritage & Hills Escape',
          'priceBasis': 'per_person',
          'adultPrice': 899,
          'originalPrice': 899,
          'promotionalPrice': 799,
          'promotionStart': '2020-01-01',
          'promotionEnd': '2030-12-31',
          'minimumTravellers': 4,
          'maximumTravellers': 12,
        },
      ),
    ));

    expect(find.text('MYR 799 / adult'), findsOneWidget);
    expect(find.text('Special promo rate'), findsOneWidget);

    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('package-group-booking')), 300,
        scrollable: find.byType(Scrollable).first);

    expect(find.text('Group total: MYR 799'), findsOneWidget);
    expect(find.text('Promotional savings: MYR 100'), findsOneWidget);

    // Increase to 4 adults
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();

    expect(find.text('Adults: 4'), findsOneWidget);
    expect(find.text('Group total: MYR 3196'), findsOneWidget);
    expect(find.text('Promotional savings: MYR 400'), findsOneWidget);
    expect(find.text('4 Adults × MYR 799'), findsOneWidget);
  });

  testWidgets(
      'Vivo pricing scenario: future promo uses regular RM899 rate',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-vivo-future',
          'title': 'Penang Heritage & Hills Escape',
          'priceBasis': 'per_person',
          'adultPrice': 899,
          'originalPrice': 899,
          'promotionalPrice': 799,
          'promotionStart': '2030-01-01',
          'promotionEnd': '2030-12-31',
          'minimumTravellers': 4,
          'maximumTravellers': 12,
        },
      ),
    ));

    expect(find.text('MYR 899 / adult'), findsOneWidget);
    expect(find.text('Special promo rate'), findsNothing);

    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('package-group-booking')), 300,
        scrollable: find.byType(Scrollable).first);

    expect(find.text('Group total: MYR 899'), findsOneWidget);
    expect(find.textContaining('Promotional savings'), findsNothing);

    // Increase to 4 adults
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();

    expect(find.text('Adults: 4'), findsOneWidget);
    expect(find.text('Group total: MYR 3596'), findsOneWidget);
    expect(find.text('4 Adults × MYR 899'), findsOneWidget);
  });

  testWidgets(
      'missing child rate displays child rate unavailable and disables child addition',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-no-child',
          'title': 'Penang Island Walk',
          'priceBasis': 'per_person',
          'adultPrice': 150,
        },
      ),
    ));

    expect(find.text('Child rate unavailable'), findsOneWidget);

    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('package-group-booking')), 300,
        scrollable: find.byType(Scrollable).first);

    expect(
        find.text(
            'Child rate unavailable — children cannot be added to this booking.'),
        findsOneWidget);

    final childAddButton = tester.widget<IconButton>(
      find.byKey(const ValueKey('package-children-add')),
    );
    expect(childAddButton.onPressed, isNull);
  });

  testWidgets(
      'equal adult and child rates display both rates distinctly',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-equal-rates',
          'title': 'Penang Island Walk',
          'priceBasis': 'per_person',
          'adultPrice': 200,
          'childPrice': 200,
        },
      ),
    ));

    expect(find.text('MYR 200 / adult'), findsOneWidget);
    expect(find.text('MYR 200 / child'), findsOneWidget);
    expect(find.text('Per person pricing'), findsOneWidget);
  });

  testWidgets(
      'unverified price basis shows unverified status pill and disables checkout',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-unverified',
          'title': 'Legacy Unverified Package',
          'adultPrice': 100,
        },
      ),
    ));

    expect(find.text('Unverified price basis'), findsOneWidget);
    expect(find.text('Price basis unverified'), findsOneWidget);

    final checkoutButton = tester.widget<FilledButton>(
      find.byType(FilledButton),
    );
    expect(checkoutButton.onPressed, isNull);
  });

  testWidgets(
      'fixed group pricing does not multiply total by group count',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-group',
          'title': 'Private Van Tour',
          'priceBasis': 'per_group',
          'adultPrice': 600,
          'maximumTravellers': 6,
        },
      ),
    ));

    expect(find.text('Fixed group pricing'), findsOneWidget);
    expect(find.text('MYR 600 / group'), findsOneWidget);

    await tester.drag(find.byType(ListView), const Offset(0, -350));
    await tester.pump();

    expect(find.text('Group total: MYR 600'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();

    expect(find.text('Adults: 3'), findsOneWidget);
    expect(find.text('Group total: MYR 600'), findsOneWidget);
  });

  testWidgets('checkout blocks on server-client price mismatch', (tester) async {
    final api = _PackageDetailsApi();
    api.mockAttempt = {
      'id': 'attempt-mismatch',
      'amount': 3596, // Server returns 3596 while client estimated 799
    };

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-mismatch',
          'title': 'Penang Heritage & Hills Escape',
          'priceBasis': 'per_person',
          'adultPrice': 899,
          'promotionalPrice': 799,
          'promotionStart': '2020-01-01',
          'promotionEnd': '2030-12-31',
          'minimumTravellers': 1,
        },
        api: api,
      ),
    ));

    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('package-group-booking')), 300,
        scrollable: find.byType(Scrollable).first);

    // Client estimate for 1 adult is 799
    expect(find.text('Group total: MYR 799'), findsOneWidget);

    await tester.tap(find.text('Checkout package'));
    await tester.pumpAndSettle();

    expect(api.postedPath, '/api/fr15/package-checkout-attempts');
    // Error snackbar should be displayed
    expect(find.textContaining('Checkout price mismatch'), findsOneWidget);
  });
}
