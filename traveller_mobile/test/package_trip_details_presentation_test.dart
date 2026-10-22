import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import 'package:travelmate_traveller/services/api_service.dart';

Map<String, dynamic> _mockPackageTrip({bool legacySnapshot = false}) {
  return {
    'id': 'package_trip_001',
    'travellerId': 'traveller_test_uid',
    'title': '4D3N Penang Heritage & Street Food Trail',
    'destinationArea': 'Penang, Malaysia',
    'startDate': '2026-11-01',
    'endDate': '2026-11-04',
    'tripDays': 4,
    'tripType': 'package',
    'packageTrip': true,
    'packageId': 'pkg_penang_001',
    'checkoutOrderId': 'order_stripe_rec_777',
    'paidTotal': 1598.0,
    'currency': 'MYR',
    'supplierReservationStatus': 'not_created',
    'participants': {
      'adults': 2,
      'children': 0,
      'total': 2,
    },
    'budgetEstimate': {
      'total': 1598.0,
      'currency': 'MYR',
      'source': 'verified_package_payment',
    },
    'packageSnapshot': legacySnapshot
        ? <String, dynamic>{}
        : {
            'packageId': 'pkg_penang_001',
            'title': '4D3N Penang Heritage & Street Food Trail',
            'destination': 'Penang, Malaysia',
            'description': 'Experience the rich cultural heritage and legendary hawker fare of George Town.',
            'operatorName': 'Penang Heritage Tours Sdn Bhd',
            'durationDays': 4,
            'durationNights': 3,
            'price': 1598.0,
            'priceBasis': 'per_person',
            'meetingPoint': 'Penang International Airport Arrival Hall (Gate 3)',
            'cancellationPolicy': 'Free cancellation up to 7 days before departure.',
            'importantNotes': [
              'Comfortable walking shoes recommended.',
              'Passport or MyKad required for hotel check-in.',
            ],
            'includedServices': [
              '3 nights boutique heritage hotel accommodation',
              'Daily breakfasts and two guided food trail lunches',
              'Air-conditioned van transfers throughout',
            ],
            'excludedServices': [
              'Flights to/from Penang',
              'Personal travel insurance',
            ],
            'highlights': ['George Town Street Art', 'Kek Lok Si Temple', 'Penang Hill Funicular'],
            'itineraryDays': [
              {
                'dayNumber': 1,
                'title': 'Arrival & George Town Heritage Trail',
                'description': 'Welcome to Penang. Check in and explore Armenian Street murals.',
                'meals': ['Dinner'],
                'accommodation': 'Eastern & Oriental Hotel',
                'transportNotes': 'Airport pickup via private air-conditioned van',
                'activities': [
                  {
                    'activityName': 'Airport Meet & Greet',
                    'scheduledTime': '09:30 AM',
                    'location': 'Penang Airport',
                    'description': 'Meet our licensed guide at Gate 3.',
                  },
                  {
                    'activityName': 'Armenian Street Murals Walk',
                    'scheduledTime': '02:00 PM',
                    'location': 'Armenian Street, George Town',
                    'description': 'Guided walking tour through famous Ernest Zacharevic murals.',
                  },
                  {
                    'activityName': 'Gurney Drive Hawker Welcome Dinner',
                    'scheduledTime': '07:00 PM',
                    'location': 'Gurney Drive',
                    'description': 'Taste Char Kway Teow, Assam Laksa, and Rojak.',
                  },
                ],
              },
              {
                'dayNumber': 2,
                'title': 'Temples & Scenic Hilltop Views',
                'description': 'Ascend Penang Hill and visit Southeast Asia’s grandest Buddhist temple.',
                'meals': ['Breakfast', 'Lunch'],
                'accommodation': 'Eastern & Oriental Hotel',
                'transportNotes': 'Private coach for hilltop and temple transfers',
                'activities': [
                  {
                    'activityName': 'Penang Hill Funicular Ride',
                    'scheduledTime': '09:00 AM',
                    'location': 'Air Itam',
                    'description': 'Fast-track ride to 833m altitude with panoramic island views.',
                  },
                  {
                    'activityName': 'Kek Lok Si Temple Tour',
                    'scheduledTime': '01:30 PM',
                    'location': 'Air Itam',
                    'description': 'Explore Pagoda of Ten Thousand Buddhas and bronze Guanyin statue.',
                  },
                ],
              },
            ],
          },
    'dailySchedule': [
      {
        'dayNo': 1,
        'title': 'Arrival & George Town Heritage Trail',
        'activities': [
          {
            'activityName': 'Airport Meet & Greet',
            'scheduledTime': '09:30 AM',
            'location': 'Penang Airport',
          },
        ],
        'meals': ['Dinner'],
      }
    ],
    'activities': [],
  };
}

Map<String, dynamic> _mockVivoPenangPackageTrip({String supplierStatus = 'not_created'}) {
  return {
    'id': 'package_trip_vivo_penang',
    'travellerId': 'traveller_vivo',
    'title': 'Penang Heritage & Hills Escape — 3D2N',
    'destinationArea': 'Penang, Malaysia',
    'startDate': '2026-11-14',
    'endDate': '2026-11-16',
    'tripDays': 3,
    'tripType': 'package',
    'packageTrip': true,
    'packageId': 'pkg_penang_escape_3d2n',
    'checkoutOrderId': 'package_checkout_order_9c1873a15d5a59a24959f7470b3b7a5278f9e675',
    'paidTotal': 1598.0,
    'currency': 'MYR',
    'supplierReservationStatus': supplierStatus,
    'participants': {
      'adults': 2,
      'children': 0,
      'total': 2,
    },
    'packageSnapshot': {
      'packageId': 'pkg_penang_escape_3d2n',
      'title': 'Penang Heritage & Hills Escape — 3D2N',
      'destination': 'Penang, Malaysia',
      'description': 'Explore George Town UNESCO World Heritage area through a guided cultural walking tour.',
      'operatorName': 'Penang Heritage Tours Sdn Bhd',
      'durationDays': 3,
      'durationNights': 2,
      'price': 1598.0,
      'priceBasis': 'per_person',
      'meetingPoint': 'KOMTAR, George Town',
      'cancellationPolicy': 'Free cancellation up to 7 days before departure.',
      'itineraryDays': [
        {
          'dayNumber': 1,
          'title': 'Discover Historic George Town',
          'description': 'Explore George Town UNESCO World Heritage area.',
          'meals': [
            'Lunch - Local Penang cuisine',
            'Dinner - Penang street food selection',
          ],
          'transportNotes': 'Air-conditioned group vehicle for scheduled transfers.',
          'accommodation': 'George Town 3-Star Hotel (Demo)',
          'activities': [
            '09:00 - Meet at KOMTAR and tour briefing',
            '09:30 - George Town heritage walking tour',
            '10:30 - Armenian Street murals and shophouses',
            '12:00 - Traditional Penang lunch',
            '13:30 - Chew Jetty and Clan Jetties visit',
            '15:30 - Hotel check-in and leisure time',
            '18:30 - Local street food dinner experience',
          ],
        },
        {
          'dayNumber': 2,
          'title': 'Penang Hill & Kek Lok Si Cultural Discovery',
          'description': 'Begin the day with breakfast before visiting Penang Hill.',
          'meals': [
            'Breakfast - Hotel breakfast',
            'Lunch - Local restaurant in Air Itam',
          ],
          'transportNotes': 'Air-conditioned group transfer from hotel to Penang Hill.',
          'accommodation': 'George Town 3-Star Hotel (Demo)',
          'activities': [
            '08:00 - Breakfast at hotel',
            '09:00 - Transfer to Penang Hill Lower Station',
            '09:30 - Penang Hill funicular railway experience',
            '10:00 - Hilltop sightseeing and photography',
            '12:30 - Lunch in Air Itam',
            '14:00 - Visit Kek Lok Si Temple',
            '15:30 - Explore temple grounds and gardens',
            '17:00 - Return to George Town hotel',
            '19:00 - Free evening and own dinner arrangements',
          ],
        },
        {
          'dayNumber': 3,
          'title': 'Penang Nature & Coastal Leisure',
          'description': 'Enjoy breakfast and check out of hotel before visiting Botanic Gardens.',
          'meals': ['Breakfast - Hotel breakfast'],
          'transportNotes': 'Air-conditioned transportation for scheduled sightseeing.',
          'accommodation': 'Not applicable – checkout day',
          'activities': [
            '08:00 - Breakfast at hotel',
            '09:00 - Hotel checkout',
            '09:30 - Penang Botanic Gardens visit',
            '11:30 - Gurney Bay waterfront sightseeing',
            '12:30 - Lunch at own expense',
            '13:30 - Free time for shopping and leisure',
            '15:30 - Return transfer to KOMTAR',
            '16:00 - End of tour',
          ],
        },
      ],
    },
  };
}

Map<String, dynamic> _mockPersonalizedTrip() {
  return {
    'id': 'plan_trip_999',
    'travellerId': 'traveller_test_uid',
    'title': 'My Solo Penang Adventure',
    'destinationArea': 'Penang',
    'startDate': '2026-11-10',
    'endDate': '2026-11-12',
    'tripDays': 3,
    'tripType': 'personalized',
    'packageTrip': false,
    'activities': [
      {
        'activityId': 'p1',
        'activityName': 'Penang National Park',
        'dayNo': 1,
        'timeSlot': '10:00',
        'estimatedCost': 50.0,
      }
    ],
    'budgetEstimate': {'total': 800.0},
  };
}

class _MockApi extends ApiService {
  final Map<String, dynamic> packageTrip;
  final Map<String, dynamic> personalizedTrip;

  _MockApi({
    required this.packageTrip,
    required this.personalizedTrip,
  });

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries') {
      return {
        'ok': true,
        'items': [packageTrip, personalizedTrip],
      };
    }
    if (path == '/api/fr5/itineraries/${packageTrip['id']}') {
      return {'ok': true, 'itinerary': packageTrip};
    }
    if (path == '/api/fr5/itineraries/${personalizedTrip['id']}') {
      return {'ok': true, 'itinerary': personalizedTrip};
    }
    return {'ok': true};
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('PackageTripDetailsScreen Presentation & Integrity Tests', () {
    testWidgets('renders dedicated read-only screen with immutable snapshot and operator schedule', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final trip = _mockPackageTrip();
      final api = _MockApi(packageTrip: trip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: PackageTripDetailsScreen(
            tripId: trip['id'].toString(),
            api: api,
            initialTrip: trip,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Header and Badges
      expect(find.text('Package Trip Details'), findsOneWidget);
      expect(find.text('4D3N Penang Heritage & Street Food Trail'), findsAtLeastNWidgets(1));
      expect(find.text('Purchased Package'), findsAtLeastNWidgets(1));
      expect(find.textContaining('Penang Heritage Tours Sdn Bhd'), findsAtLeastNWidgets(1));

      // Booking Summary
      expect(find.text('Booking & Payment Summary'), findsOneWidget);
      expect(find.text('order_stripe_rec_777'), findsOneWidget);
      expect(find.text('2 Adults'), findsOneWidget);
      expect(find.text('Per Person'), findsOneWidget);
      expect(find.text('MYR 1598.00'), findsOneWidget);
      expect(find.textContaining('Stripe Test Mode'), findsOneWidget);
      expect(find.textContaining('Test payment recorded'), findsOneWidget);

      // Meeting point
      expect(find.textContaining('Arrival Hall (Gate 3)'), findsOneWidget);

      // Day 1 Activities in Exact Original Sequence with exact operator times
      expect(find.text('Airport Meet & Greet'), findsOneWidget);
      expect(find.text('09:30 AM'), findsOneWidget);
      expect(find.text('Armenian Street Murals Walk'), findsOneWidget);
      expect(find.text('02:00 PM'), findsOneWidget);
      expect(find.text('Gurney Drive Hawker Welcome Dinner'), findsOneWidget);
      expect(find.text('07:00 PM'), findsOneWidget);

      // Inclusions and Exclusions
      expect(find.text('What’s Included'), findsOneWidget);
      expect(find.textContaining('3 nights boutique heritage hotel'), findsOneWidget);
      expect(find.text('What’s Not Included'), findsOneWidget);
      expect(find.textContaining('Flights to/from Penang'), findsOneWidget);

      // Read-Only Guarantee: NO recalculate, edit, or unscheduled exclusions
      expect(find.text('Recalculate'), findsNothing);
      expect(find.text('Edit schedule'), findsNothing);
      expect(find.text('Add activity'), findsNothing);
      expect(find.textContaining("Couldn't fit into your schedule"), findsNothing);
      expect(find.textContaining('This purchased tourism package is managed directly by the operator'), findsOneWidget);
    });

    testWidgets('allows switching day tabs and preserves Day 2 sequence', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final trip = _mockPackageTrip();
      final api = _MockApi(packageTrip: trip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: PackageTripDetailsScreen(
            tripId: trip['id'].toString(),
            api: api,
            initialTrip: trip,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Tap Day 2
      final day2Tab = find.text('Day 2');
      expect(day2Tab, findsOneWidget);
      await tester.tap(day2Tab);
      await tester.pumpAndSettle();

      // Day 2 Activities
      expect(find.text('Penang Hill Funicular Ride'), findsOneWidget);
      expect(find.text('09:00 AM'), findsOneWidget);
      expect(find.text('Kek Lok Si Temple Tour'), findsOneWidget);
      expect(find.text('01:30 PM'), findsOneWidget);
      expect(find.text('Meals Included: Breakfast, Lunch'), findsOneWidget);
      expect(find.text('Stay: Eastern & Oriental Hotel'), findsOneWidget);
    });

    testWidgets('legacy package gracefully falls back to dailySchedule', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final legacyTrip = _mockPackageTrip(legacySnapshot: true);
      final api = _MockApi(packageTrip: legacyTrip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: PackageTripDetailsScreen(
            tripId: legacyTrip['id'].toString(),
            api: api,
            initialTrip: legacyTrip,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Package Trip Details'), findsOneWidget);
      expect(find.text('Airport Meet & Greet'), findsOneWidget);
      expect(find.text('09:30 AM'), findsOneWidget);
    });

    testWidgets('TripDetailsScreen delegates immediately to PackageTripDetailsScreen for package trips', (tester) async {
      final trip = _mockPackageTrip();
      final api = _MockApi(packageTrip: trip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: TripDetailsScreen(
            tripId: trip['id'].toString(),
            api: api,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Verify that PackageTripDetailsScreen was instantiated and rendered instead of smart planner
      expect(find.byType(PackageTripDetailsScreen), findsOneWidget);
      expect(find.text('Package Trip Details'), findsOneWidget);
      expect(find.text('Booking & Payment Summary'), findsOneWidget);
      // Ensure Smart Itinerary recalculate button is NOT present
      expect(find.text('Recalculate'), findsNothing);
    });

    testWidgets('TripsTab segments plans and packages, and opens PackageTripDetailsScreen', (tester) async {
      final packageTrip = _mockPackageTrip();
      final planTrip = _mockPersonalizedTrip();
      final api = _MockApi(packageTrip: packageTrip, personalizedTrip: planTrip);

      await tester.pumpWidget(
        MaterialApp(
          home: TripsTab(api: api),
        ),
      );
      await tester.pumpAndSettle();

      // Check segmented control displays counts
      expect(find.text('My Plans (1)'), findsOneWidget);
      expect(find.text('Package Trips (1)'), findsOneWidget);

      // On 'My Plans' tab: planTrip is shown, packageTrip is not
      expect(find.text('My Solo Penang Adventure'), findsOneWidget);
      expect(find.text('4D3N Penang Heritage & Street Food Trail'), findsNothing);

      // Switch to 'Package Trips'
      await tester.tap(find.text('Package Trips (1)'));
      await tester.pumpAndSettle();

      // On 'Package Trips' tab: packageTrip is shown, planTrip is not
      expect(find.text('4D3N Penang Heritage & Street Food Trail'), findsOneWidget);
      expect(find.text('My Solo Penang Adventure'), findsNothing);
      expect(find.text('View Itinerary'), findsOneWidget);

      // Tap 'View Itinerary'
      await tester.tap(find.text('View Itinerary'));
      await tester.pumpAndSettle();

      // Navigated to PackageTripDetailsScreen
      expect(find.byType(PackageTripDetailsScreen), findsOneWidget);
      expect(find.text('Package Trip Details'), findsOneWidget);
    });

    testWidgets('TripsTab calculates activity count from dailySchedule when top-level activities list is empty', (tester) async {
      final tripWithDaily = {
        'id': 'MBdcQ3NF1onYkCXivEaJ',
        'travellerId': 'traveller_test_uid',
        'title': 'My Personalised Penang Trip',
        'destinationArea': 'Penang',
        'startDate': '2026-09-17',
        'endDate': '2026-09-19',
        'tripDays': 3,
        'tripType': 'personalized',
        'packageTrip': false,
        'activities': <Map<String, dynamic>>[],
        'scheduledActivityCount': 0,
        'budgetEstimate': {'total': 1200.0},
        'dailySchedule': [
          {
            'dayNo': 1,
            'activities': [
              {'activityName': 'Chew Jetty', 'timeSlot': '09:00', 'category': 'Heritage'},
              {'activityName': 'George Town Heritage Core', 'timeSlot': '11:00', 'category': 'Heritage'},
              {'activityName': 'Kek Lok Si Temple', 'timeSlot': '14:00', 'category': 'Sightseeing'},
              {'activityName': 'Wonderfood Museum', 'timeSlot': '16:30', 'category': 'Museum'},
            ],
          },
          {
            'dayNo': 2,
            'activities': [
              {'activityName': 'Wonderfood Museum', 'timeSlot': '09:30', 'category': 'Museum'},
              {'activityName': 'George Town Food Trail', 'timeSlot': '12:00', 'category': 'Food'},
              {'activityName': 'Esplanade & Fort Cornwallis Area', 'timeSlot': '15:00', 'category': 'Sightseeing'},
            ],
          },
          {
            'dayNo': 3,
            'activities': [
              {'activityName': 'Pinang Peranakan Mansion', 'timeSlot': '10:00', 'category': 'Heritage'},
              {'activityName': 'Penang Botanic Gardens', 'timeSlot': '13:00', 'category': 'Nature'},
              {'activityName': 'Penang Hill', 'timeSlot': '16:00', 'category': 'Scenic'},
            ],
          },
        ],
      };

      final api = _MockApi(packageTrip: _mockPackageTrip(), personalizedTrip: tripWithDaily);

      await tester.pumpWidget(
        MaterialApp(
          home: TripsTab(api: api),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('My Personalised Penang Trip'), findsOneWidget);
      // Confirms 10 activities are counted and displayed rather than '0 activities'
      expect(find.text('10 activities · RM 1200.0 estimated'), findsOneWidget);
      expect(find.text('0 activities · RM 1200.0 estimated'), findsNothing);
    });

    testWidgets('renders Vivo Penang Heritage package with time-prefixed string activities and accurate day bounds', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final trip = _mockVivoPenangPackageTrip();
      final api = _MockApi(packageTrip: trip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: PackageTripDetailsScreen(
            tripId: trip['id'].toString(),
            api: api,
            initialTrip: trip,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Day 1 Title & Description
      expect(find.text('Discover Historic George Town'), findsOneWidget);
      expect(find.text('No scheduled activities listed for this day.'), findsNothing);

      // Day 1 Operator Activities & Times restored from string format
      expect(find.text('Meet at KOMTAR and tour briefing'), findsOneWidget);
      expect(find.text('09:00'), findsOneWidget);
      expect(find.text('George Town heritage walking tour'), findsOneWidget);
      expect(find.text('09:30'), findsAtLeastNWidgets(1));
      expect(find.text('Armenian Street murals and shophouses'), findsOneWidget);
      expect(find.text('10:30'), findsOneWidget);
      expect(find.text('Traditional Penang lunch'), findsOneWidget);
      expect(find.text('12:00'), findsOneWidget);
      expect(find.text('Chew Jetty and Clan Jetties visit'), findsOneWidget);
      expect(find.text('13:30'), findsOneWidget);
      expect(find.text('Hotel check-in and leisure time'), findsOneWidget);
      expect(find.text('15:30'), findsOneWidget);
      expect(find.text('Local street food dinner experience'), findsOneWidget);
      expect(find.text('18:30'), findsOneWidget);

      // Day 1 Meals and accommodation
      expect(find.textContaining('Local Penang cuisine'), findsOneWidget);
      expect(find.text('Stay: George Town 3-Star Hotel (Demo)'), findsOneWidget);

      // Switch to Day 2
      await tester.tap(find.text('Day 2'));
      await tester.pumpAndSettle();

      // Day 2 Title & Day 2 Breakfast stays within Day 2
      expect(find.text('Penang Hill & Kek Lok Si Cultural Discovery'), findsOneWidget);
      expect(find.text('Breakfast at hotel'), findsOneWidget);
      expect(find.text('08:00'), findsOneWidget);
      expect(find.text('Transfer to Penang Hill Lower Station'), findsOneWidget);
      expect(find.text('Visit Kek Lok Si Temple'), findsOneWidget);
      expect(find.text('14:00'), findsOneWidget);

      // Switch to Day 3
      await tester.tap(find.text('Day 3'));
      await tester.pumpAndSettle();

      // Day 3
      expect(find.text('Penang Nature & Coastal Leisure'), findsOneWidget);
      expect(find.text('Hotel checkout'), findsOneWidget);
      expect(find.text('Penang Botanic Gardens visit'), findsOneWidget);
      expect(find.text('Gurney Bay waterfront sightseeing'), findsOneWidget);
      expect(find.text('11:30'), findsOneWidget);
    });

    testWidgets('responsive layout prevents horizontal overflow at 360px, 390px, 412px, 440px and under 1.5x font scale', (tester) async {
      final trip = _mockVivoPenangPackageTrip();
      final api = _MockApi(packageTrip: trip, personalizedTrip: _mockPersonalizedTrip());

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
              child: PackageTripDetailsScreen(
                key: ValueKey('responsive_$width'),
                tripId: trip['id'].toString(),
                api: api,
                initialTrip: trip,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();

        final error = tester.takeException();
        if (error is FlutterError) {
          debugPrint(error.toStringDeep());
        }
        expect(error, isNull, reason: 'Must not overflow at ${width}px with 1.5x scale');
        expect(find.text('Booking & Payment Summary'), findsOneWidget);
        expect(find.text('package_checkout_order_9c1873a15d5a59a24959f7470b3b7a5278f9e675'), findsOneWidget);
      }
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    testWidgets('supports legacy newline-separated string activities with honest Time not specified', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final legacyTrip = {
        'id': 'package_legacy_text',
        'tripType': 'package',
        'packageTrip': true,
        'packageSnapshot': {
          'title': 'Legacy Package',
          'itineraryDays': [
            {
              'dayNumber': 1,
              'title': 'Heritage Walk',
              'activities': 'Armenian Street Murals\nClan Jetties\nKhoo Kongsi Temple',
              'meals': 'Buffet Breakfast\nNyonya Tasting Lunch',
            },
          ],
        },
      };
      final api = _MockApi(packageTrip: legacyTrip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: PackageTripDetailsScreen(
            tripId: 'package_legacy_text',
            api: api,
            initialTrip: legacyTrip,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Armenian Street Murals'), findsOneWidget);
      expect(find.text('Clan Jetties'), findsOneWidget);
      expect(find.text('Khoo Kongsi Temple'), findsOneWidget);
      // Honest timing status
      expect(find.text('Time not specified'), findsAtLeastNWidgets(3));
      // Multi-line meals joined
      expect(find.textContaining('Meals Included: Buffet Breakfast, Nyonya Tasting Lunch'), findsOneWidget);
    });

    testWidgets('Order Reference copy button triggers clipboard copy and snackbar', (tester) async {
      final trip = _mockVivoPenangPackageTrip();
      final api = _MockApi(packageTrip: trip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: PackageTripDetailsScreen(
              tripId: trip['id'].toString(),
              api: api,
              initialTrip: trip,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      final copyButton = find.text('Copy');
      expect(copyButton, findsOneWidget);

      await tester.tap(copyButton);
      await tester.pump();

      expect(find.text('Order reference copied to clipboard'), findsOneWidget);
    });

    testWidgets('displays accurate supplier disclosure based on supplierReservationStatus', (tester) async {
      tester.view.physicalSize = const Size(800, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      // 1. Unconfirmed / Test Mode
      final unconfirmedTrip = _mockVivoPenangPackageTrip(supplierStatus: 'not_created');
      final api1 = _MockApi(packageTrip: unconfirmedTrip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: PackageTripDetailsScreen(
            key: const ValueKey('unconfirmed'),
            tripId: unconfirmedTrip['id'].toString(),
            api: api1,
            initialTrip: unconfirmedTrip,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        find.textContaining('Test payment recorded. Your Package Trip is available in TravelMate. No external supplier reservation has been created.'),
        findsOneWidget,
      );

      // 2. Confirmed by operator
      final confirmedTrip = _mockVivoPenangPackageTrip(supplierStatus: 'confirmed');
      final api2 = _MockApi(packageTrip: confirmedTrip, personalizedTrip: _mockPersonalizedTrip());

      await tester.pumpWidget(
        MaterialApp(
          home: PackageTripDetailsScreen(
            key: const ValueKey('confirmed'),
            tripId: confirmedTrip['id'].toString(),
            api: api2,
            initialTrip: confirmedTrip,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(
        find.text('Reservation confirmed by operator.'),
        findsOneWidget,
      );
    });
  });
}
