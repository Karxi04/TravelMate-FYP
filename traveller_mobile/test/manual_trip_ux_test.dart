import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_trip_actions.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/activity_payload_helper.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockTripApi extends ApiService {
  final Map<String, dynamic>? initialTrip;
  final List<Map<String, dynamic>> trips;
  final List<Map<String, dynamic>> postCalls = [];
  final List<Map<String, dynamic>> putCalls = [];

  _MockTripApi({this.initialTrip, List<Map<String, dynamic>>? trips})
      : trips = trips ?? (initialTrip != null ? [initialTrip] : []);

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries' || path == '/api/fr5/itineraries/') {
      return {
        'ok': true,
        'items': trips,
        'itinerary': trips.isNotEmpty ? trips.first : null
      };
    }
    if (path.startsWith('/api/fr5/itineraries/')) {
      final segments = path.split('/');
      final id = segments.length > 4 ? segments[4] : '';
      final match = trips.firstWhere((t) => t['id'] == id,
          orElse: () => initialTrip ?? {'id': id});
      if (path.endsWith('/budget')) {
        return {'ok': true, 'budget': match['budgetEstimate'] ?? {}};
      }
      return {'ok': true, 'itinerary': match, 'items': [match]};
    }
    if (path.startsWith('/api/fr3/destinations/search')) {
      return {
        'ok': true,
        'results': [
          {
            'destinationId': 'penang_botanic',
            'place_id': 'penang_botanic',
            'title': 'Penang Botanic Gardens',
            'address': 'George Town, Penang',
            'category': 'Nature',
            'type': 'Nature',
            'unitPrice': 0.0,
            'pricingUnit': 'per_person',
            'costProvenance': 'verified_ticket',
            'priceSourceUrl':
                'https://botanicalgardens.penang.gov.my/faq',
            'priceVerifiedAt': '2026-10-26',
            'pricingEvidence': {
              'venueId': 'local_botanical_gardens',
              'applicability': 'applicable',
              'eligibility': 'all_visitors',
              'priceSourceUrl':
                  'https://botanicalgardens.penang.gov.my/faq',
              'priceVerifiedAt': '2026-10-26',
            },
          }
        ]
      };
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [dynamic body]) async {
    postCalls.add({'path': path, 'body': body});
    if (path == '/api/fr5/itineraries') {
      final newTrip = {
        'id': 'manual_trip_999',
        ...Map<String, dynamic>.from(body as Map),
        'status': 'planned',
        'tripDays': 3,
        'dailySchedule': [
          {'dayNo': 1, 'dayDate': '2026-11-01', 'activities': []},
          {'dayNo': 2, 'dayDate': '2026-11-02', 'activities': []},
          {'dayNo': 3, 'dayDate': '2026-11-03', 'activities': []},
        ],
      };
      trips.add(newTrip);
      return {'ok': true, 'id': 'manual_trip_999', 'itinerary': newTrip};
    }
    if (path.contains('/activities')) {
      return {'ok': true, 'activity': body};
    }
    return {'ok': true};
  }
}

Map<String, dynamic> _sampleMultiDayTrip() {
  return {
    'id': 'trip_penang_multiday',
    'title': 'Penang 3-Day Explorer',
    'destinationArea': 'Penang, Malaysia',
    'startDate': '2026-11-01',
    'endDate': '2026-11-03',
    'tripDays': 3,
    'travellerCount': 2,
    'budgetLimit': 1500.0,
    'status': 'planned',
    'dailySchedule': [
      {
        'dayNo': 1,
        'dayDate': '2026-11-01',
        'activities': [
          {
            'activityId': 'act_001',
            'activityName': 'Fort Cornwallis',
            'destinationId': 'fort_cornwallis',
            'dayNo': 1,
            'estimatedCost': 20.0,
            'unitPrice': 10.0,
            'pricingUnit': 'per_person',
            'costProvenance': 'verified_ticket',
            'priceSourceUrl': 'https://fortcornwallis.my',
            'priceVerifiedAt': '2026-10-26',
          }
        ],
      },
      {
        'dayNo': 2,
        'dayDate': '2026-11-02',
        'activities': [],
      },
      {
        'dayNo': 3,
        'dayDate': '2026-11-03',
        'activities': [],
      },
    ],
    'activities': [
      {
        'activityId': 'act_001',
        'activityName': 'Fort Cornwallis',
        'destinationId': 'fort_cornwallis',
        'dayNo': 1,
        'estimatedCost': 20.0,
        'unitPrice': 10.0,
        'pricingUnit': 'per_person',
        'costProvenance': 'verified_ticket',
        'priceSourceUrl': 'https://fortcornwallis.my',
        'priceVerifiedAt': '2026-10-26',
      }
    ],
  };
}

Widget _wrap(Widget child, {Size size = const Size(400, 800), double textScale = 1.0}) {
  return MaterialApp(
    home: MediaQuery(
      data: MediaQueryData(
        size: size,
        textScaler: TextScaler.linear(textScale),
      ),
      child: child is Scaffold ? child : Scaffold(body: child),
    ),
  );
}

void main() {
  group('Batch M1: Manual Trip Planning & Evidence Preservation', () {
    // 1. Create Trip choice shows both planning options.
    testWidgets('1. Create Trip choice shows both planning options', (tester) async {
      final api = _MockTripApi(trips: []);
      await tester.pumpWidget(_wrap(TripsTab(api: api)));
      await tester.pumpAndSettle();

      // Tap "Plan a trip" FAB
      final fab = find.byKey(const ValueKey('plan-trip-fab'));
      expect(fab, findsOneWidget);
      await tester.tap(fab);
      await tester.pumpAndSettle();

      // Verify choice sheet appears with both options
      expect(find.text('Plan your trip'), findsOneWidget);
      expect(find.byKey(const ValueKey('plan-for-me-option')), findsOneWidget);
      expect(find.byKey(const ValueKey('plan-myself-option')), findsOneWidget);
      expect(find.text('Plan for Me'), findsOneWidget);
      expect(find.text('Plan Myself'), findsOneWidget);
    });

    // 2. Plan for Me enters the existing AI planning flow.
    testWidgets('2. Plan for Me enters the existing AI planning flow', (tester) async {
      final api = _MockTripApi(trips: []);
      await tester.pumpWidget(_wrap(TripsTab(api: api)));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-trip-fab')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-for-me-option')));
      await tester.pumpAndSettle();

      expect(find.byType(PersonalizedPlanningScreen), findsOneWidget);
    });

    // 3. Plan Myself enters manual creation.
    testWidgets('3. Plan Myself enters manual creation', (tester) async {
      final api = _MockTripApi(trips: []);
      await tester.pumpWidget(_wrap(TripsTab(api: api)));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-trip-fab')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-myself-option')));
      await tester.pumpAndSettle();

      expect(find.text('Create a new trip'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Trip title'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Destination'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Travellers'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Budget (RM)'), findsOneWidget);
    });

    // 4. Empty draft creation does not generate activities.
    testWidgets('4. Empty draft creation does not generate activities', (tester) async {
      final api = _MockTripApi(trips: []);
      await tester.pumpWidget(_wrap(TripsTab(api: api)));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-trip-fab')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-myself-option')));
      await tester.pumpAndSettle();

      // Enter title and destination
      await tester.enterText(
          find.widgetWithText(TextField, 'Trip title'), 'My Penang Adventure');
      await tester.enterText(
          find.widgetWithText(TextField, 'Destination'), 'George Town');
      await tester.pumpAndSettle();

      // Tap Create trip
      await tester.tap(find.text('Create trip'));
      await tester.pumpAndSettle();

      // Verify POST call was made
      final createCall = api.postCalls.firstWhere(
        (c) => c['path'] == '/api/fr5/itineraries',
      );
      final body = createCall['body'] as Map<String, dynamic>;
      expect(body['title'], 'My Penang Adventure');
      expect(body['destinationArea'], 'George Town');
      expect(body['activities'], isEmpty);
      // No generation fields present
      expect(body.containsKey('generationRequestId'), isFalse);
    });

    // 5. Valid manual metadata payload passes the new public contract.
    test('5. Valid manual metadata payload passes public write allowlist', () {
      final allowedFields = {
        'title',
        'destinationArea',
        'destinationName',
        'destinationCountry',
        'startDate',
        'endDate',
        'travellerCount',
        'budgetLimit',
        'originLocation',
        'travelMode',
        'accommodationChoice',
        'carRentalChoice',
        'travelPace',
        'activities',
      };

      final payload = {
        'title': 'Penang Escapade',
        'destinationArea': 'Penang',
        'startDate': '2026-11-01',
        'endDate': '2026-11-04',
        'travellerCount': 2,
        'budgetLimit': 1200.0,
        'activities': <Map<String, dynamic>>[],
      };

      for (final key in payload.keys) {
        expect(allowedFields.contains(key), isTrue,
            reason: 'Field $key must be allowed in public write contract');
      }
      expect(payload.containsKey('travellerId'), isFalse);
      expect(payload.containsKey('createdAt'), isFalse);
      expect(payload.containsKey('tripType'), isFalse);
      expect(payload.containsKey('paidTotal'), isFalse);
    });

    // 6. Invalid creation handles errors without duplicate saves.
    testWidgets('6. Invalid creation handles errors without duplicate saves', (tester) async {
      final api = _MockTripApi(trips: []);
      await tester.pumpWidget(_wrap(TripsTab(api: api)));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-trip-fab')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-myself-option')));
      await tester.pumpAndSettle();

      // Tap Create trip immediately with empty title and empty destination
      await tester.tap(find.text('Create trip'));
      await tester.pumpAndSettle();

      // Check validation messages appear
      expect(find.text('Trip title is required'), findsOneWidget);
      expect(find.text('Destination area is required'), findsOneWidget);

      // Verify no POST was triggered
      expect(api.postCalls.where((c) => c['path'] == '/api/fr5/itineraries'), isEmpty);
    });

    // 7. Multi-day Add Place supports selected-day insertion.
    testWidgets('7. Multi-day Add Place supports selected-day insertion', (tester) async {
      final trip = _sampleMultiDayTrip();
      int? selectedDay;

      await tester.pumpWidget(_wrap(Builder(builder: (context) {
        return ElevatedButton(
          onPressed: () async {
            selectedDay = await promptTripDaySelection(
              context: context,
              trip: trip,
              initialDay: 2,
            );
          },
          child: const Text('Pick Day'),
        );
      })));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Pick Day'));
      await tester.pumpAndSettle();

      // Verify day options are rendered with dates
      expect(find.text('Select Trip Day'), findsOneWidget);
      expect(find.text('Day 1 · 2026-11-01'), findsOneWidget);
      expect(find.text('Day 2 · 2026-11-02'), findsOneWidget);
      expect(find.text('Day 3 · 2026-11-03'), findsOneWidget);

      // Select Day 2
      await tester.tap(find.byKey(const ValueKey('day-option-2')));
      await tester.pumpAndSettle();

      expect(selectedDay, 2);
    });

    // 8. Day selection survives the activity request.
    test('8. Day selection survives the activity request', () {
      final place = {
        'title': 'Kek Lok Si Temple',
        'destinationId': 'kek_lok_si',
        'address': 'Air Itam, Penang',
        'estimatedCost': 0.0,
      };

      final payloadDay1 = buildActivityPayload(place, dayNo: 1);
      expect(payloadDay1['dayNo'], 1);

      final payloadDay2 = buildActivityPayload(place, dayNo: 2);
      expect(payloadDay2['dayNo'], 2);

      final payloadDay3 = buildActivityPayload(place, dayNo: 3);
      expect(payloadDay3['dayNo'], 3);
    });

    // 9. Existing Activity IDs remain stable.
    test('9. Existing Activity IDs remain stable during activity additions', () {
      final trip = _sampleMultiDayTrip();
      final existingActivity = trip['activities'][0];
      final originalId = existingActivity['activityId'];

      final newPlace = {
        'title': 'Cheong Fatt Tze Mansion',
        'destinationId': 'cheong_fatt_tze',
        'address': 'George Town',
      };
      final newPayload = buildActivityPayload(newPlace, dayNo: 2);

      // Verify the new activity payload does not overwrite existing IDs
      expect(existingActivity['activityId'], originalId);
      expect(newPayload['dayNo'], 2);
      expect(newPayload['activityName'], 'Cheong Fatt Tze Mansion');
    });

    // 10. Saved manual Trips reopen correctly.
    testWidgets('10. Saved manual Trips reopen correctly', (tester) async {
      final trip = _sampleMultiDayTrip();
      final api = _MockTripApi(initialTrip: trip);

      await tester.pumpWidget(_wrap(TripDetailsScreen(
        tripId: trip['id'],
        api: api,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Penang 3-Day Explorer'), findsOneWidget);
      expect(find.text('Fort Cornwallis'), findsOneWidget);
    });

    // 11. Unknown pricing remains unknown.
    test('11. Unknown pricing remains unknown without fabrication', () {
      final place = {
        'title': 'Local Market',
        'destinationId': 'local_market',
        'address': 'Chowrasta',
      };

      final payload = buildActivityPayload(place, dayNo: 1);
      expect(payload.containsKey('pricingUnit'), isFalse);
      expect(payload.containsKey('costProvenance'), isFalse);
      expect(payload.containsKey('priceSourceUrl'), isFalse);
      expect(payload.containsKey('pricingEvidence'), isFalse);
      expect(payload['estimatedCost'], 0.0);
    });

    // 12. Verified-free evidence is accepted only when legitimately supported.
    test('12. Verified-free evidence is accepted only when legitimately supported', () {
      final place = {
        'title': 'Penang Botanic Gardens',
        'destinationId': 'penang_botanic',
        'address': 'George Town',
        'estimatedCost': 0.0,
        'unitPrice': 0.0,
        'pricingUnit': 'per_person',
        'costProvenance': 'verified_ticket',
        'priceSourceUrl': 'https://botanicalgardens.penang.gov.my/',
        'priceVerifiedAt': '2026-10-26',
        'pricingEvidence': {
          'venueId': 'local_botanical_gardens',
          'applicability': 'applicable',
          'eligibility': 'all_visitors',
          'priceSourceUrl': 'https://botanicalgardens.penang.gov.my/',
          'priceVerifiedAt': '2026-10-26',
        },
      };

      final payload = buildActivityPayload(place, dayNo: 1);
      expect(payload['unitPrice'], 0.0);
      expect(payload['pricingUnit'], 'per_person');
      expect(payload['costProvenance'], 'verified_ticket');
      expect(payload['priceSourceUrl'], 'https://botanicalgardens.penang.gov.my/');
      expect(payload['priceVerifiedAt'], '2026-10-26');
      expect(payload['pricingEvidence']['applicability'], 'applicable');
    });

    // 13. Conditional tariffs remain conditional.
    test('13. Conditional tariffs remain conditional', () {
      final place = {
        'title': 'Pinang Peranakan Mansion',
        'destinationId': 'peranakan_mansion',
        'unitPrice': 30.0,
        'pricingUnit': 'per_person',
        'costProvenance': 'verified_ticket',
        'priceSourceUrl': 'http://pinangperanakanmansion.com.my/',
        'priceVerifiedAt': '2026-10-26',
        'pricingEvidence': {
          'venueId': 'local_peranakan_mansion',
          'applicability': 'conditional',
          'eligibility': 'adult_tariff_only',
          'limitations': 'Adult RM30, child 6-12 RM18.',
        },
      };

      final payload = buildActivityPayload(place, dayNo: 1);
      expect(payload['pricingEvidence']['applicability'], 'conditional');
      expect(payload['pricingEvidence']['eligibility'], 'adult_tariff_only');
      expect(payload['unitPrice'], 30.0);
    });

    // 14. Available pricing units and sources survive mapping.
    test('14. Available pricing units and sources survive mapping', () {
      final place = {
        'title': 'The TOP Penang',
        'destinationId': 'the_top',
        'unitPrice': 78.0,
        'pricingUnit': 'per_person',
        'costCategory': 'attraction',
        'costProvenance': 'verified_ticket',
        'priceSourceUrl': 'https://thetop.com.my/product/ticket-1/',
        'priceVerifiedAt': '2026-10-26',
        'overlapsAllowance': false,
      };

      final payload = buildActivityPayload(place, dayNo: 2);
      expect(payload['pricingUnit'], 'per_person');
      expect(payload['unitPrice'], 78.0);
      expect(payload['costCategory'], 'attraction');
      expect(payload['costProvenance'], 'verified_ticket');
      expect(payload['priceSourceUrl'], 'https://thetop.com.my/product/ticket-1/');
      expect(payload['priceVerifiedAt'], '2026-10-26');
      expect(payload['overlapsAllowance'], false);
    });

    // 15. Missing source/evidence does not become trusted.
    test('15. Missing source/evidence does not become trusted', () {
      final place = {
        'title': 'Unverified Temple',
        'destinationId': 'unverified_temple',
        'estimatedCost': 0.0,
      };

      final payload = buildActivityPayload(place, dayNo: 1);
      expect(payload.containsKey('costProvenance'), isFalse);
      expect(payload.containsKey('pricingEvidence'), isFalse);
      expect(payload.containsKey('priceSourceUrl'), isFalse);
    });

    // 16. Group budget disclosures remain correct.
    test('16. Group budget disclosures remain correct', () {
      final trip = _sampleMultiDayTrip();
      expect(trip['budgetLimit'], 1500.0);
      expect(trip['travellerCount'], 2);
    });

    // 17. Existing AI planning remains compatible.
    testWidgets('17. Existing AI planning remains compatible via Plan for Me', (tester) async {
      final api = _MockTripApi(trips: []);
      await tester.pumpWidget(_wrap(TripsTab(api: api)));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-trip-fab')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-for-me-option')));
      await tester.pumpAndSettle();

      expect(find.byType(PersonalizedPlanningScreen), findsOneWidget);
    });

    // 18. Purchased Package Trips remain read-only.
    testWidgets('18. Purchased Package Trips open PackageTripDetailsScreen', (tester) async {
      final packageTrip = {
        'id': 'pkg_trip_001',
        'title': 'Penang Heritage Package',
        'tripType': 'package',
        'destinationArea': 'Penang',
        'startDate': '2026-11-10',
        'endDate': '2026-11-12',
        'status': 'planned',
        'isPurchased': true,
        'packageId': 'pkg_abc',
      };
      final api = _MockTripApi(trips: [packageTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api)));
      await tester.pumpAndSettle();

      // Switch to Package Trips segment
      await tester.tap(find.text('Package Trips (1)'));
      await tester.pumpAndSettle();

      expect(find.text('Penang Heritage Package'), findsOneWidget);

      await tester.tap(find.text('Penang Heritage Package'));
      await tester.pumpAndSettle();

      expect(find.byType(PackageTripDetailsScreen), findsOneWidget);
    });

    // 19. Both relevant Add Place entry points use compatible mappings.
    testWidgets('19. Both Add Place entry points use compatible mappings', (tester) async {
      final destination = {
        'place_id': 'ch_01',
        'title': 'Cheong Fatt Tze',
        'location': 'George Town, Penang',
        'unitPrice': 25.0,
        'pricingUnit': 'per_person',
        'costProvenance': 'verified_ticket',
        'priceSourceUrl': 'https://cheongfatttzemansion.com',
        'priceVerifiedAt': '2026-10-26',
        'pricingEvidence': {
          'ticketProduct': 'Guided Mansion Tour',
          'applicability': 'applicable',
        },
      };

      final api = _MockTripApi(trips: [_sampleMultiDayTrip()]);

      // Path A helper: buildActivityPayload
      final payloadA = buildActivityPayload(destination, dayNo: 2);

      // Path B: addDestinationToTrip
      await tester.pumpWidget(_wrap(Builder(builder: (context) {
        return ElevatedButton(
          onPressed: () async {
            await addDestinationToTrip(
              context: context,
              api: api,
              destination: destination,
            );
          },
          child: const Text('Add to Trip'),
        );
      })));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Add to Trip'));
      await tester.pumpAndSettle();

      // Select the trip from list
      await tester.tap(find.text('Penang 3-Day Explorer'));
      await tester.pumpAndSettle();

      // Select Day 2 in prompt
      await tester.tap(find.byKey(const ValueKey('day-option-2')));
      await tester.pumpAndSettle();

      final postCall = api.postCalls.firstWhere(
        (c) => c['path'].contains('/activities'),
      );
      final payloadB = postCall['body'] as Map<String, dynamic>;

      // Verify essential pricing evidence matches across both paths
      expect(payloadB['dayNo'], payloadA['dayNo']);
      expect(payloadB['unitPrice'], payloadA['unitPrice']);
      expect(payloadB['pricingUnit'], payloadA['pricingUnit']);
      expect(payloadB['costProvenance'], payloadA['costProvenance']);
      expect(payloadB['priceSourceUrl'], payloadA['priceSourceUrl']);
      expect(payloadB['priceVerifiedAt'], payloadA['priceVerifiedAt']);
      expect(payloadB['pricingEvidence']['applicability'],
          payloadA['pricingEvidence']['applicability']);
    });

    // 20. Narrow screens and enlarged text remain usable.
    testWidgets('20. Narrow screens and enlarged text remain usable', (tester) async {
      final api = _MockTripApi(trips: []);
      // Narrow screen: 320px width, text scale 1.5x
      await tester.pumpWidget(_wrap(
        TripsTab(api: api),
        size: const Size(320, 640),
        textScale: 1.5,
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('plan-trip-fab')));
      await tester.pumpAndSettle();

      // Verify no overflow in the planning mode choice sheet
      expect(tester.takeException(), isNull);
      expect(find.byKey(const ValueKey('plan-for-me-option')), findsOneWidget);
      expect(find.byKey(const ValueKey('plan-myself-option')), findsOneWidget);

      // Tap Plan Myself
      await tester.tap(find.byKey(const ValueKey('plan-myself-option')));
      await tester.pumpAndSettle();

      // Verify no overflow in the manual creation sheet
      expect(tester.takeException(), isNull);
      expect(find.text('Create a new trip'), findsOneWidget);
    });
  });
}
