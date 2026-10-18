import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/home/home_tab.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _PackageDetailsApi extends ApiService {
  String? postedPath;
  Map<String, dynamic>? postedPayload;
  Map<String, dynamic>? mockAttempt;
  final List<dynamic> packages;

  _PackageDetailsApi({
    List<dynamic>? packages,
  }) : packages = packages ?? [];

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr1/me') {
      return {'ok': true, 'profile': {'name': 'Test Traveller'}};
    }
    if (path == '/api/fr2/preferences') {
      return {'ok': true, 'preferences': {'interests': ['Culture']}};
    }
    if (path == '/api/fr5/itineraries') {
      return {'ok': true, 'items': []};
    }
    if (path == '/api/fr4/recommendations') {
      return {'ok': true, 'recommendations': [], 'source': 'fallback'};
    }
    if (path == '/api/public/tourism-packages') {
      return {'ok': true, 'items': packages};
    }
    if (path == '/api/public/promotional-campaigns') {
      return {'ok': true, 'items': []};
    }
    return {'ok': true, 'items': []};
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

Future<void> _openBookingSheet(WidgetTester tester) async {
  await tester.tap(find.text('Select travellers & date'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('complete package shows traveller-ready product details and clean tabs',
      (tester) async {
    tester.view.physicalSize = const Size(800, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var legacyCallbackCalled = false;
    final api = _PackageDetailsApi();
    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(
        item: {
          'id': 'package-1',
          'title': 'Penang Heritage Escape',
          'destination': 'George Town, Penang',
          'fullDescription':
              'A guided two-day local experience.\n\n**Day 1: Arrival**\nHeritage walk\n**Day 2: Hills**\nFunicular ride',
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
              'activities': ['09:30 - Clan jetty tour'],
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

    // Header product details
    expect(find.text('Penang Heritage Escape'), findsOneWidget);
    expect(find.text('MYR 320 / adult'), findsOneWidget);
    expect(find.text('2 days · 1 night'), findsOneWidget);

    // Overview Tab
    expect(find.text('Package overview'), findsOneWidget);
    expect(find.text('A guided two-day local experience.'), findsOneWidget);
    // Verified: No repeated markdown **Day 1: Arrival** in clean overview
    expect(find.textContaining('**Day 1: Arrival**'), findsNothing);
    expect(find.text('Street art'), findsOneWidget);
    expect(find.text('Local food'), findsOneWidget);
    expect(find.text('Tourism Operator'), findsOneWidget);

    // Open booking sheet via persistent bottom action
    await _openBookingSheet(tester);
    expect(find.byKey(const ValueKey('package-group-booking')), findsOneWidget);
    expect(find.text('Group total: MYR 320'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.tap(find.byKey(const ValueKey('package-children-add')));
    await tester.pump();
    expect(find.text('Group total: MYR 800'), findsOneWidget);

    // Close booking sheet to view other sections
    await tester.tap(find.byIcon(Icons.close_rounded));
    await tester.pumpAndSettle();

    // Check Itinerary Tab
    await tester.tap(find.text('Itinerary'));
    await tester.pumpAndSettle();
    expect(find.text('Day-by-day itinerary'), findsOneWidget);
    expect(find.text('Day 1 · Heritage quarter'), findsOneWidget);
    // Scheduled individual activity row with parsed time and title
    expect(find.text('Clan jetty tour'), findsOneWidget);
    expect(find.text('09:30'), findsOneWidget);

    // Check What's Included Tab
    await tester.tap(find.text("What's Included"));
    await tester.pumpAndSettle();
    expect(find.text('What is included'), findsOneWidget);
    expect(find.text('Guide'), findsOneWidget);
    expect(find.text('Transport'), findsOneWidget);
    expect(find.text('Not included'), findsOneWidget);
    expect(find.text('Flights'), findsOneWidget);

    // Check Policies Tab
    await tester.tap(find.text('Policies'));
    await tester.pumpAndSettle();
    expect(find.text('Cancellation policy'), findsOneWidget);
    expect(find.textContaining('Cancel seven days before departure.'), findsOneWidget);
    expect(find.textContaining('No external supplier reservation has been created.'), findsOneWidget);

    // Reopen booking sheet and checkout
    await _openBookingSheet(tester);
    expect(find.text('Group total: MYR 800'), findsOneWidget);
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

    await _openBookingSheet(tester);

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

    await _openBookingSheet(tester);

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

    await _openBookingSheet(tester);

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

    await _openBookingSheet(tester);

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

    await _openBookingSheet(tester);

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

    await _openBookingSheet(tester);

    // Client estimate for 1 adult is 799
    expect(find.text('Group total: MYR 799'), findsOneWidget);

    await tester.tap(find.text('Checkout package'));
    await tester.pumpAndSettle();

    expect(api.postedPath, '/api/fr15/package-checkout-attempts');
    // Error snackbar should be displayed
    expect(find.textContaining('Checkout price mismatch'), findsOneWidget);
  });

  testWidgets('Home Tourism Package has View Package action and no Add to Trip',
      (tester) async {
    tester.view.physicalSize = const Size(800, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final samplePackage = {
      'id': 'pkg-home-001',
      'title': 'Penang Street Food Adventure',
      'destination': 'Penang, Malaysia',
      'durationDays': 3,
      'durationNights': 2,
      'adultPrice': 450,
      'priceBasis': 'per_person',
      'heroImage': 'http://127.0.0.1:9/food.jpg',
      'operatorName': 'Penang Foodies',
    };

    final api = _PackageDetailsApi(packages: [samplePackage]);

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: HomeTab(api: api),
      ),
    ));
    await tester.pumpAndSettle();

    // Verify package card rendered under inspiration section
    expect(find.text('Penang Street Food Adventure'), findsAtLeastNWidgets(1));
    expect(find.text('View Package'), findsOneWidget);

    // Crucial check: Tourism package must NOT have 'Add to trip'
    // (Note: normal attraction recommendations may have 'Add to trip', but package card only has 'View Package')
    final packageCardFinder = find.ancestor(
      of: find.text('Penang Street Food Adventure').first,
      matching: find.byType(InkWell),
    );
    expect(packageCardFinder, findsAtLeastNWidgets(1));

    final addToTripButtonsUnderPackage = find.descendant(
      of: packageCardFinder.first,
      matching: find.text('Add to trip'),
    );
    expect(addToTripButtonsUnderPackage, findsNothing);

    // Tap View Package
    await tester.tap(find.text('View Package'));
    await tester.pumpAndSettle();

    // Navigated to TourismPackageDetailsScreen
    expect(find.byType(TourismPackageDetailsScreen), findsOneWidget);
    expect(find.text('Penang Street Food Adventure'), findsAtLeastNWidgets(1));
    expect(find.text('Select travellers & date'), findsOneWidget);
  });

  testWidgets('Responsive layout prevents horizontal overflow at 360px, 390px, 412px, 440px and 1.5x font scale',
      (tester) async {
    final item = {
      'id': 'package-responsive',
      'title': 'Penang Island Heritage & Cultural Escape — Long Title Edition',
      'destination': 'George Town, Penang, Malaysia',
      'durationDays': 4,
      'durationNights': 3,
      'adultPrice': 899,
      'childPrice': 499,
      'priceBasis': 'per_person',
      'minimumTravellers': 2,
      'maximumTravellers': 10,
      'highlights': ['Street Art', 'Kek Lok Si Temple', 'Penang Hill Funicular'],
      'inclusions': ['Hotel stay', 'Daily breakfast', 'Transfers'],
      'exclusions': ['Flights', 'Personal expenses'],
      'departureDates': ['2026-11-20'],
      'itineraryDays': [
        {
          'dayNumber': 1,
          'title': 'Historic Heritage Trail',
          'description': 'Walking tour through UNESCO heritage zone.',
          'activities': [
            '09:00 - Meeting at KOMTAR',
            '10:30 - Armenian Street Murals',
            '14:00 - Clan Jetties Exploration',
          ],
          'meals': ['Lunch', 'Dinner'],
        }
      ],
    };

    for (final width in [360.0, 390.0, 412.0, 440.0]) {
      tester.view.physicalSize = Size(width, 2400);
      tester.view.devicePixelRatio = 1.0;

      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(useMaterial3: true),
          home: MediaQuery(
            data: MediaQueryData(
              size: Size(width, 2400),
              textScaler: const TextScaler.linear(1.5),
            ),
            child: TourismPackageDetailsScreen(
              key: ValueKey('responsive_$width'),
              item: item,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      final error = tester.takeException();
      if (error is FlutterError) {
        debugPrint(error.toStringDeep());
      }
      expect(error, isNull, reason: 'Must not overflow at ${width}px under 1.5x font scale');
      expect(find.text('Select travellers & date'), findsOneWidget);
    }

    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
}
