import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/home/home_tab.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _PackageDetailsApi extends ApiService {
  bool checkoutEnabled = false;
  @override
  bool get isStandalone => false;
  String? postedPath;
  Map<String, dynamic>? postedPayload;
  final List<Map<String, dynamic>> postedPayloads = [];
  Map<String, dynamic>? mockAttempt;
  Object? postError;
  final List<dynamic> packages;
  final List<dynamic> orders;

  _PackageDetailsApi({
    List<dynamic>? packages,
    List<dynamic>? orders,
  })  : packages = packages ?? [],
        orders = orders ?? [];

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr9/checkout/capabilities') {
      return {'ok': true, 'mode': 'test', 'hostedCheckout': checkoutEnabled,
        'supportedQuoteTypes': ['hotel', 'package']};
    }
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
    if (path == '/api/fr9/orders') {
      return {'ok': true, 'items': orders};
    }
    return {'ok': true, 'items': []};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path.endsWith('/quote')) return {'ok':true,'quote':{'quoteToken':'test-quote','price':mockAttempt?['amount'] ?? 100,'pricingBreakdown':{'finalPayable':mockAttempt?['amount'] ?? 100}}};
    postedPath = path;
    postedPayload = Map<String, dynamic>.from(body ?? const {});
    postedPayloads.add(postedPayload!);
    if (postError != null) throw postError!;
    return {
      'ok': true,
      // Stop before PaymentScreen if empty: this focused widget test has no Firebase app.
      'attempt': mockAttempt ?? <String, dynamic>{},
    };
  }
}

const _checkoutPackage = <String, dynamic>{
  'id': 'package-repeat',
  'title': 'Penang Heritage & Hills Escape',
  'priceBasis': 'per_person',
  'adultPrice': 100,
  'childPrice': 50,
  'departureDates': ['2027-01-10'],
};

Future<void> _openBookingSheet(WidgetTester tester) async {
  await tester.tap(find.text('Select travellers & date'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('past-only package explains unavailable checkout and never posts', (tester) async {
    tester.view.physicalSize=const Size(1000,2400); tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final api=_PackageDetailsApi()..checkoutEnabled=true;
    await tester.pumpWidget(MaterialApp(home:TourismPackageDetailsScreen(api:api,item:{..._checkoutPackage,'departureDates':['2000-11-07']})));
    await tester.pumpAndSettle(); await _openBookingSheet(tester);
    expect(find.textContaining('No current or upcoming package departures'),findsOneWidget);
    final button=tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn')));
    expect(button.onPressed,isNull);
    expect(api.postedPayloads,isEmpty);
  });

  testWidgets('past departure disabled and explicit valid selection reaches checkout unchanged', (tester) async {
    tester.view.physicalSize=const Size(1000,2400); tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final api=_PackageDetailsApi()..checkoutEnabled=true;
    await tester.pumpWidget(MaterialApp(home:TourismPackageDetailsScreen(api:api,item:{..._checkoutPackage,'departureDates':['2000-11-07','2099-11-10']})));
    await tester.pumpAndSettle(); await _openBookingSheet(tester);
    final dropdown=tester.widget<DropdownButtonFormField<String>>(find.byKey(const ValueKey('package-departure-date')));
    expect(dropdown.initialValue,isNull);
    await tester.tap(find.byKey(const ValueKey('package-departure-date'))); await tester.pumpAndSettle();
    await tester.tap(find.text('2099-11-10').last); await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('package-checkout-btn')));
    await tester.tap(find.byKey(const ValueKey('package-checkout-btn'))); await tester.pumpAndSettle();
    expect(api.postedPayloads.single['departureDate'],'2099-11-10');
  });

  testWidgets('F-F1A-P approved package purchase resumes existing authoritative attempt flow', (tester) async {
    tester.view.physicalSize = const Size(900, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _PackageDetailsApi()..checkoutEnabled = true
      ..mockAttempt = {'id': 'approved-attempt', 'amount': 100};
    await tester.pumpWidget(MaterialApp(home: TourismPackageDetailsScreen(
      item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    expect(find.textContaining('Academic demonstration'), findsNothing);
    expect(find.textContaining('Reviewing this package does not create'),
        findsNothing);
    await tester.tap(find.byKey(const ValueKey('package-checkout-btn')));
    await tester.pumpAndSettle();
    expect(api.postedPath, '/api/fr15/package-checkout-attempts');
    expect(api.postedPayload!['packageId'], 'package-repeat');
    expect(api.postedPayload!['participants'], {'adults': 1, 'children': 0});
    expect(api.postedPayload!.containsKey('price'), isFalse);
    expect(find.text('Review Payment'), findsOneWidget);
    expect(find.textContaining('Academic demonstration'), findsNothing);
    expect(find.text('Continue to Payment'), findsOneWidget);
    expect(api.postedPayloads, hasLength(1));
  });

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
    expect(find.text('MYR 320.00 / person'), findsOneWidget);
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
    expect(find.textContaining('Academic demonstration'), findsOneWidget);

    // Reopen booking sheet and checkout
    await _openBookingSheet(tester);
    expect(find.text('Group total: MYR 800'), findsOneWidget);
    expect(find.text('Purchase unavailable'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn'))).onPressed, isNull);
    expect(api.postedPayloads, isEmpty);
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
    expect(find.text('MYR 88.00 / person'), findsOneWidget);
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
    expect(
      find.text('Minimum 4 travellers required. Currently selected: 1.'),
      findsOneWidget,
    );
    expect(find.text('Minimum requirement: 4 travellers'), findsNothing);
    expect(find.textContaining('Minimum group size:'), findsNothing);
  });

  testWidgets(
      'Legacy manual package promotion is ignored for new bookings',
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

    expect(find.text('MYR 899.00 / person'), findsOneWidget);
    expect(find.text('Automatic campaign offer'), findsNothing);

    await _openBookingSheet(tester);

    expect(find.text('Group total: MYR 899'), findsOneWidget);
    expect(find.textContaining('Promotional savings:'), findsNothing);

    // Increase to 4 adults
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();

    expect(find.text('Adults: 4'), findsOneWidget);
    expect(find.text('Group total: MYR 3596'), findsOneWidget);
    expect(find.textContaining('Promotional savings:'), findsNothing);
    expect(find.text('4 Adults × MYR 899'), findsOneWidget);
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

    expect(find.text('MYR 899.00 / person'), findsOneWidget);
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

    expect(find.text('MYR 200.00 / person'), findsOneWidget);
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
    expect(find.text('MYR 600.00 / group'), findsOneWidget);

    await _openBookingSheet(tester);

    expect(find.text('Group total: MYR 600'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pump();

    expect(find.text('Adults: 3'), findsOneWidget);
    expect(find.text('Group total: MYR 600'), findsOneWidget);
  });

  testWidgets('F-F1A package review cannot start test purchase 0', (tester) async {
    final api = _PackageDetailsApi(orders: [{
      'id': 'historical-order', 'packageId': 'package-repeat',
      'status': 'paid',
      'paymentStatus': 'unpaid', 'testMode': true,
    }]);
    await tester.pumpWidget(MaterialApp(home: TourismPackageDetailsScreen(
      item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    expect(find.text('Purchase unavailable'), findsOneWidget);
    final action = tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn')));
    expect(action.onPressed, isNull);
    expect(api.postedPayloads, isEmpty);
    expect(find.textContaining('Stripe Checkout remains'), findsNothing);
  });

  testWidgets('F-F1A package review cannot start test purchase 1',
      (tester) async {
    final api = _PackageDetailsApi(orders: [{
      'id': 'historical-order', 'packageId': 'package-repeat',
      'status': 'checkout_open',
      'paymentStatus': 'unpaid', 'testMode': true,
    }]);
    await tester.pumpWidget(MaterialApp(home: TourismPackageDetailsScreen(
      item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    expect(find.text('Purchase unavailable'), findsOneWidget);
    final action = tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn')));
    expect(action.onPressed, isNull);
    expect(api.postedPayloads, isEmpty);
    expect(find.textContaining('Stripe Checkout remains'), findsNothing);
  });

  testWidgets('F-F1A package review cannot start test purchase 2',
      (tester) async {
    final api = _PackageDetailsApi(orders: [{
      'id': 'historical-order', 'packageId': 'package-repeat',
      'status': 'expired',
      'paymentStatus': 'unpaid', 'testMode': true,
    }]);
    await tester.pumpWidget(MaterialApp(home: TourismPackageDetailsScreen(
      item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    expect(find.text('Purchase unavailable'), findsOneWidget);
    final action = tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn')));
    expect(action.onPressed, isNull);
    expect(api.postedPayloads, isEmpty);
    expect(find.textContaining('Stripe Checkout remains'), findsNothing);
  });

  testWidgets('F-F1A package review cannot start test purchase 3',
      (tester) async {
    final api = _PackageDetailsApi(orders: [{
      'id': 'historical-order', 'packageId': 'package-repeat',
      'status': 'cancelled',
      'paymentStatus': 'unpaid', 'testMode': true,
    }]);
    await tester.pumpWidget(MaterialApp(home: TourismPackageDetailsScreen(
      item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    expect(find.text('Purchase unavailable'), findsOneWidget);
    final action = tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn')));
    expect(action.onPressed, isNull);
    expect(api.postedPayloads, isEmpty);
    expect(find.textContaining('Stripe Checkout remains'), findsNothing);
  });

  testWidgets('F-F1A package review cannot start test purchase 4',
      (tester) async {
    final api = _PackageDetailsApi(orders: [{
      'id': 'historical-order', 'packageId': 'package-repeat',
      'status': 'payment_failed',
      'paymentStatus': 'unpaid', 'testMode': true,
    }]);
    await tester.pumpWidget(MaterialApp(home: TourismPackageDetailsScreen(
      item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    expect(find.text('Purchase unavailable'), findsOneWidget);
    final action = tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn')));
    expect(action.onPressed, isNull);
    expect(api.postedPayloads, isEmpty);
    expect(find.textContaining('Stripe Checkout remains'), findsNothing);
  });

  testWidgets('F-F1A package review cannot start test purchase 5',
      (tester) async {
    final api = _PackageDetailsApi(orders: [{
      'id': 'historical-order', 'packageId': 'package-repeat',
      'status': 'paid',
      'paymentStatus': 'unpaid', 'testMode': true,
    }]);
    await tester.pumpWidget(MaterialApp(home: TourismPackageDetailsScreen(
      item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    expect(find.text('Purchase unavailable'), findsOneWidget);
    final action = tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn')));
    expect(action.onPressed, isNull);
    expect(api.postedPayloads, isEmpty);
    expect(find.textContaining('Stripe Checkout remains'), findsNothing);
  });

  for (final terminalStatus in ['expired', 'cancelled', 'payment_failed']) {
    testWidgets('F-F1A $terminalStatus history does not enable package purchase',
        (tester) async {
      final api = _PackageDetailsApi(orders: [{
        'id': 'order-$terminalStatus', 'packageId': 'package-repeat',
        'status': terminalStatus, 'testMode': true}]);
      await tester.pumpWidget(MaterialApp(home: TourismPackageDetailsScreen(item: _checkoutPackage, api: api)));
      await _openBookingSheet(tester);
      expect(find.text('Purchase unavailable'), findsOneWidget);
      expect(tester.widget<FilledButton>(find.byKey(const ValueKey('package-checkout-btn'))).onPressed, isNull);
      expect(api.postedPayloads, isEmpty);
  });
  }

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

  testWidgets(
      'Promo code reaches backend and discounted quote is reviewed before payment',
      (tester) async {
    tester.view.physicalSize = const Size(900, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _PackageDetailsApi()
      ..checkoutEnabled = true
      ..mockAttempt = {
        'id': 'promoted',
        'amount': 85,
        'pricingBreakdown': {
          'originalSubtotal': 100,
          'promotionDiscount': 15,
          'finalPayable': 85,
          'currency': 'MYR'
        }
      };
    await tester.pumpWidget(MaterialApp(
        home: TourismPackageDetailsScreen(item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    await tester.enterText(
        find.byKey(const ValueKey('package-promo-code')), 'SAVE15');
    await tester.tap(find.byKey(const ValueKey('package-checkout-btn')));
    await tester.pumpAndSettle();
    expect(api.postedPayload!['promoCode'], 'SAVE15');
    expect(api.postedPayload!.containsKey('amount'), isFalse);
    expect(find.text('Review updated package amount'), findsOneWidget);
    await tester.tap(find.text('Review Checkout'));
    await tester.pumpAndSettle();
    expect(find.text('Original package subtotal: MYR 100.00'), findsOneWidget);
    expect(find.text('Promotion discount: -MYR 15.00'), findsOneWidget);
    expect(find.text('Final payable: MYR 85.00'), findsOneWidget);
    expect(api.postedPayloads, hasLength(1));
  });

  testWidgets('Cancelling updated quote never opens payment', (tester) async {
    tester.view.physicalSize = const Size(900, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = _PackageDetailsApi()
      ..checkoutEnabled = true
      ..mockAttempt = {'id': 'changed', 'amount': 110};
    await tester.pumpWidget(MaterialApp(
        home: TourismPackageDetailsScreen(item: _checkoutPackage, api: api)));
    await tester.pumpAndSettle();
    await _openBookingSheet(tester);
    api.mockAttempt = {'id':'changed-later', 'amount':120};
    await tester.tap(find.byKey(const ValueKey('package-checkout-btn')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel').last);
    await tester.pumpAndSettle();
    expect(find.text('Review Payment'), findsNothing);
    expect(api.postedPayloads, hasLength(1));
  });
}
