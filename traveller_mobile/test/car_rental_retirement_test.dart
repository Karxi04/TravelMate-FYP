import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/home/home_tab.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _FakeRetirementApi extends ApiService {
  final List<dynamic>? tripsData;

  _FakeRetirementApi({this.tripsData});

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr1/profile' || path == '/api/fr1/me' || path == '/profile' || path == '/me') {
      return {
        'ok': true,
        'profile': {
          'name': 'Test Traveller',
          'firstName': 'Test',
          'travelPersonality': 'Cultural Explorer',
        },
      };
    }
    if (path.contains('/preferences')) {
      return {
        'ok': true,
        'preferences': {
          'interests': ['Culture', 'Food'],
          'pace': 'moderate',
        },
      };
    }
    if (path == '/api/fr5/itineraries' || path.startsWith('/trips')) {
      return {
        'ok': true,
        'items': tripsData ?? [],
      };
    }
    if (path.endsWith('/budget')) {
      return {
        'ok': true,
        'budget': {
          'currency': 'MYR',
          'totalEstimatedCost': 500,
          'targetBudget': 1500,
        },
      };
    }
    if (path.contains('/recommendations')) {
      return {'recommendations': []};
    }
    if (path.contains('/promotions') || path.contains('/packages')) {
      return {'ok': true, 'items': []};
    }
    return {'ok': true};
  }
}

Future<void> _scrollUntilFound(WidgetTester tester, Finder target) async {
  final scrollables = find.byType(Scrollable);
  if (scrollables.evaluate().isNotEmpty) {
    for (var i = 0; i < 20 && target.evaluate().isEmpty; i++) {
      await tester.drag(scrollables.first, const Offset(0, -300));
      await tester.pumpAndSettle();
    }
  }
}

void main() {
  Widget wrap(Widget child) => MaterialApp(
        home: Scaffold(body: child),
      );

  group('Car Rental UI Retirement & Preservation', () {
    testWidgets('Home tab features Packing tool and retires Car rentals shortcut',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);

      final fakeApi = _FakeRetirementApi();
      await tester.pumpWidget(wrap(HomeTab(api: fakeApi)));
      await tester.pumpAndSettle();

      await _scrollUntilFound(tester, find.text('Packing'));

      // Verify Packing is present
      expect(find.text('Packing'), findsOneWidget);
      expect(find.byIcon(Icons.checklist_rounded), findsOneWidget);

      // Verify Car rentals is absent from tools
      expect(find.text('Car rentals'), findsNothing);
      expect(find.text('Car rental'), findsNothing);
    });

    testWidgets('Trip details essentials displays Packing checklist instead of Car rental',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);

      final trip = {
        'id': 'trip_test_101',
        'title': 'Penang Heritage Weekend',
        'destination': 'Penang',
        'destinationCity': 'George Town',
        'destinationArea': 'Penang',
        'status': 'planned',
        'startDate': '2026-11-20',
        'endDate': '2026-11-23',
        'budget': 1500,
        'dailySchedule': [
          {
            'dayNo': 1,
            'dayDate': '2026-11-20',
            'activities': [
              {
                'activityId': 'act_1',
                'activityName': 'Kek Lok Si Temple',
                'timeSlot': '09:00',
                'scheduledStartTime': '09:00',
                'scheduledEndTime': '11:00',
                'estimatedCost': 20,
              }
            ],
          }
        ],
        'activities': [
          {
            'activityId': 'act_1',
            'activityName': 'Kek Lok Si Temple',
            'dayNo': 1,
            'timeSlot': '09:00',
            'scheduledStartTime': '09:00',
            'scheduledEndTime': '11:00',
            'estimatedCost': 20,
          }
        ],
      };

      final api = _FakeRetirementApi(tripsData: [trip]);

      await tester.pumpWidget(wrap(TripDetailsScreen(tripId: 'trip_test_101', api: api)));
      await tester.pumpAndSettle();

      await _scrollUntilFound(tester, find.text('Packing checklist'));

      // Trip essentials section should offer Packing checklist
      expect(find.text('Packing checklist'), findsOneWidget);

      // Should NOT have active Car rental button in essentials
      expect(find.widgetWithText(OutlinedButton, 'Car rental'), findsNothing);
      expect(find.widgetWithText(FilledButton, 'Car rental'), findsNothing);
    });

    testWidgets('Trip details preserves historical car rental attached cards',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);

      final historicalTrip = {
        'id': 'trip_hist_202',
        'title': 'Historical Langkawi Holiday',
        'destination': 'Langkawi',
        'destinationCity': 'Kuah',
        'destinationArea': 'Langkawi',
        'status': 'planned',
        'startDate': '2026-11-20',
        'endDate': '2026-11-23',
        'budget': 2000,
        'selectedCarRental': {
          'vehicleName': 'Toyota Vios Sedan',
          'supplierName': 'Langkawi Drive Easy',
          'pickupLocation': 'Langkawi International Airport',
          'dropoffLocation': 'Langkawi International Airport',
          'totalPrice': 240.0,
          'currency': 'MYR',
          'confirmationNumber': 'LGK-CR-9921',
        },
        'carRentalCost': 240.0,
        'dailySchedule': [
          {
            'dayNo': 1,
            'dayDate': '2026-11-20',
            'activities': [],
          }
        ],
        'activities': [],
      };

      final api = _FakeRetirementApi(tripsData: [historicalTrip]);

      await tester.pumpWidget(wrap(TripDetailsScreen(tripId: 'trip_hist_202', api: api)));
      await tester.pumpAndSettle();

      await _scrollUntilFound(tester, find.text('Toyota Vios Sedan'));

      // Attached rental card must still render historical data
      expect(find.text('Attached car rental'), findsOneWidget);
      expect(find.text('Toyota Vios Sedan'), findsOneWidget);
      expect(find.textContaining('Car rental cost: MYR 240'), findsOneWidget);
    });

    testWidgets('Personalized planning screen retires active car rental selection and defaults to not_required',
        (tester) async {
      await tester.pumpWidget(wrap(const PersonalizedPlanningScreen()));
      await tester.pumpAndSettle();

      // In arrangement choices, there should be no car rental choice selector
      expect(find.text('Need a rental car?'), findsNothing);
      expect(find.text('Car rental option'), findsNothing);
      expect(find.text('Compact sedan'), findsNothing);
      expect(find.text('SUV / Van'), findsNothing);

      // State default check: create state and verify carRentalChoice is 'not_required'
      final state = tester.state(find.byType(PersonalizedPlanningScreen)) as dynamic;
      expect(state.carRentalChoice, 'not_required');
    });
  });
}
