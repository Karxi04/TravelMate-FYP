import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/budget_breakdown.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/budget_model.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockTripApi extends ApiService {
  final Map<String, dynamic> trip;
  _MockTripApi(this.trip);

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries' ||
        path.startsWith('/api/fr5/itineraries/')) {
      return {
        'ok': true,
        'items': [trip],
        'itinerary': trip,
      };
    }
    if (path.startsWith('/api/fr3/destinations/')) {
      return {
        'ok': true,
        'destination': {
          'destinationId': path.split('/').last,
          'title': 'Destination Info',
        },
      };
    }
    if (path.endsWith('/budget')) {
      return {'ok': true, 'budget': trip['budgetEstimate'] ?? {}};
    }
    return {'ok': true};
  }
}

Map<String, dynamic> _buildTrip({
  String id = 'trip_f3_test',
  String title = 'Penang Heritage Tour',
  String destinationArea = 'Penang, Malaysia',
  List<Map<String, dynamic>> activities = const [],
  Map<String, dynamic>? budgetAwareSelection,
  Map<String, dynamic>? generationContext,
  Map<String, dynamic>? budgetEstimate,
  List<Map<String, dynamic>> unscheduledSuggestions = const [],
  double budgetLimit = 1500,
}) {
  return {
    'id': id,
    'title': title,
    'destinationArea': destinationArea,
    'startDate': '2026-11-25',
    'endDate': '2026-11-25',
    'tripDays': 1,
    'travellerCount': 2,
    'budgetLimit': budgetLimit,
    'status': 'planned',
    'activities': activities,
    'unscheduledSuggestions': unscheduledSuggestions,
    if (budgetAwareSelection != null)
      'budgetAwareSelection': budgetAwareSelection,
    if (generationContext != null) 'generationContext': generationContext,
    'dailySchedule': [
      {
        'dayNo': 1,
        'dayDate': '2026-11-25',
        'activities': activities,
        'planningBlocks': const [],
        'weather': {'source': 'forecast', 'description': 'Sunny'},
        'estimatedCost': activities.fold<double>(
          0.0,
          (sum, item) =>
              sum + (double.tryParse('${item['estimatedCost']}') ?? 0.0),
        ),
      }
    ],
    'budgetEstimate': budgetEstimate ??
        {
          'total': 400,
          'limit': budgetLimit,
          'activities': 50,
          'food': 100,
          'transport': 50,
          'hotel': 200,
          'completenessStatus': 'incomplete',
          'affordabilityStatus': 'incomplete',
          'pendingExpenseCategories': ['activities'],
        },
  };
}

Future<void> _pumpTrip(
  WidgetTester tester,
  Map<String, dynamic> trip, {
  Size size = const Size(400, 850),
  double textScale = 1.0,
}) async {
  tester.view.physicalSize =
      Size(size.width * textScale, size.height * textScale);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final api = _MockTripApi(trip);
  await tester.pumpWidget(
    MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(
          size: size,
          textScaler: TextScaler.linear(textScale),
        ),
        child: TripDetailsScreen(
          tripId: trip['id'] ?? 'trip_f3_test',
          api: api,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _scrollTarget(WidgetTester tester, Finder target) async {
  final scrollable = find.byKey(const ValueKey('trip-details-scroll'));
  for (var i = 0; i < 18 && target.evaluate().isEmpty; i++) {
    await tester.drag(scrollable, const Offset(0, -350));
    await tester.pump();
  }
  expect(target, findsWidgets);
  await tester.ensureVisible(target.first);
  await tester.pump();
}

void main() {
  group(
      'Batch F3-P2E: Flutter Budget-Aware Itinerary Transparency & Provisional Pricing UX',
      () {
    testWidgets('1. Verified free attraction renders Free admission chip',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_free_1',
          'activityName': 'Kek Lok Si Temple Grounds',
          'dayNo': 1,
          'timeSlot': '09:00',
          'scheduledStartTime': '09:00',
          'estimatedCost': 0,
          'costProvenance': 'verified_ticket',
          'selectionPriceStatus': 'verified',
          'pricingEvidence': {
            'verified': true,
            'tier': 'free',
            'applicability': 'all',
          },
          'openingHoursStatus': 'reported',
          'scheduleFeasibility': 'feasible_with_reported_hours',
        }
      ]);

      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Kek Lok Si Temple Grounds'));

      expect(find.text('Free admission'), findsOneWidget);
      expect(find.text('RM 0.00'), findsNothing);
      expect(find.text('RM 0'), findsNothing);
      expect(find.text('Hours unverified'), findsNothing);
      expect(find.text('Admission unverified'), findsNothing);
    });

    testWidgets('2. Unknown admission price renders Admission unverified chip',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_unverified_1',
          'activityName': 'Clan Jetties Community Walk',
          'dayNo': 1,
          'timeSlot': '10:00',
          'scheduledStartTime': '10:00',
          'estimatedCost': 0,
          'selectionPriceStatus': 'unresolved',
          'pricingUnit': 'unknown',
          'costProvenance': 'unverified',
          'pricingEvidence': {'verified': false},
          'openingHoursStatus': 'reported',
          'scheduleFeasibility': 'feasible_with_reported_hours',
        }
      ]);

      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Clan Jetties Community Walk'));

      expect(find.text('Admission unverified'), findsOneWidget);
      expect(find.text('Price TBC'), findsOneWidget);
      expect(find.text('Free admission'), findsNothing);
    });

    testWidgets(
        '3. Conditional admission tariff renders Tariff conditional chip',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_conditional_1',
          'activityName': 'Penang Hill Funicular Railway',
          'dayNo': 1,
          'timeSlot': '11:00',
          'scheduledStartTime': '11:00',
          'estimatedCost': 30,
          'selectionPriceStatus': 'conditional',
          'costProvenance': 'verified_ticket',
          'pricingEvidence': {
            'verified': true,
            'applicability': 'conditional',
            'basis': 'per_person',
          },
          'openingHoursStatus': 'reported',
          'scheduleFeasibility': 'feasible_with_reported_hours',
        }
      ]);

      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Penang Hill Funicular Railway'));

      expect(find.text('Tariff conditional'), findsOneWidget);
      expect(find.text('~RM 30 tariff'), findsOneWidget);
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsNothing);
    });

    testWidgets(
        '4. Unverified numeric estimate renders estimate label without verified certainty',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_estimate_1',
          'activityName': 'Pinang Peranakan Mansion',
          'dayNo': 1,
          'timeSlot': '14:00',
          'scheduledStartTime': '14:00',
          'estimatedCost': 25,
          'costProvenance': 'legacy_estimate',
          'selectionPriceStatus': 'unresolved',
          'pricingEvidence': {'verified': false},
          'openingHoursStatus': 'reported',
          'scheduleFeasibility': 'feasible_with_reported_hours',
        }
      ]);

      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Pinang Peranakan Mansion'));

      expect(find.text('Admission unverified'), findsOneWidget);
      expect(find.text('~RM 25 estimate'), findsOneWidget);
      expect(find.text('RM 25 verified'), findsNothing);
    });

    testWidgets(
        '5. Provisional budget status renders Incomplete estimate and warning',
        (tester) async {
      final budget = BudgetModel.fromJson({
        'budgetLimit': 1500,
        'knownEstimatedSubtotal': 450,
        'totalEstimatedCost': 450,
        'completenessStatus': 'incomplete',
        'affordabilityStatus': 'incomplete',
        'pendingExpenseCategories': ['activities'],
        'categoryTotals': {
          'activities': 50,
          'food': 100,
          'transport': 50,
          'hotel': 250,
          'flight': 0,
          'carRental': 0,
        },
        'expenseBreakdown': {
          'activities': {'state': 'unverified_estimate'},
          'food': {'state': 'priced'},
          'transport': {'state': 'priced'},
          'hotel': {'state': 'priced'},
          'flight': {'state': 'not_required'},
          'carRental': {'state': 'not_required'},
        },
      });

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: BudgetBreakdown(budget: budget, limit: 1500),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Incomplete estimate'), findsOneWidget);
      expect(
          find.textContaining(
              'Some expenses or pricing details are unresolved'),
          findsOneWidget);
      expect(find.textContaining('remaining balance cannot be guaranteed'),
          findsOneWidget);
      expect(find.textContaining('Estimated balance:'), findsNothing);
    });

    testWidgets('6. Complete budget status renders Within budget and balance',
        (tester) async {
      final budget = BudgetModel.fromJson({
        'budgetLimit': 1500,
        'knownEstimatedSubtotal': 450,
        'totalEstimatedCost': 450,
        'completenessStatus': 'complete',
        'affordabilityStatus': 'within_budget',
        'pendingExpenseCategories': <String>[],
        'excludedExpenseCategories': <String>[],
        'categoryTotals': {
          'activities': 50,
          'food': 100,
          'transport': 50,
          'hotel': 250,
          'flight': 0,
          'carRental': 0,
        },
        'expenseBreakdown': {
          'activities': {'state': 'priced'},
          'food': {'state': 'priced'},
          'transport': {'state': 'priced'},
          'hotel': {'state': 'priced'},
          'flight': {'state': 'not_required'},
          'carRental': {'state': 'not_required'},
        },
      });

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: BudgetBreakdown(budget: budget, limit: 1500),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Within budget'), findsOneWidget);
      expect(find.text('Estimated balance: RM 1050.00'), findsOneWidget);
    });

    testWidgets(
        '7. Budget-aware selection metadata present renders transparency card',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'selectionMode': 'provisional',
          'isProvisional': true,
          'selectionRationale':
              'Optimized for cultural interest while observing admission limits.',
          'unselectedActivities': [
            {
              'activityName': 'Penang 3D Trick Art Museum',
              'reason': 'known_budget_exceeded',
            }
          ],
        },
        activities: [
          {
            'activityId': 'act_1',
            'activityName': 'Cheong Fatt Tze Mansion',
            'dayNo': 1,
            'timeSlot': '10:00',
            'estimatedCost': 25,
            'costProvenance': 'verified_ticket',
            'selectionPriceStatus': 'verified',
            'openingHoursStatus': 'reported',
          }
        ],
      );

      await _pumpTrip(tester, trip);

      expect(find.byKey(const ValueKey('budget-aware-transparency-card')),
          findsOneWidget);
      expect(find.text('Budget-aware itinerary'), findsOneWidget);
      expect(find.text('Provisional'), findsOneWidget);
      expect(
          find.text(
              'Optimized for cultural interest while observing admission limits.'),
          findsOneWidget);
      expect(find.text('Other places considered (1)'), findsOneWidget);

      await tester.tap(find.text('Other places considered (1)'));
      await tester.pumpAndSettle();

      expect(find.text('Penang 3D Trick Art Museum'), findsOneWidget);
      expect(find.text('Exceeds remaining activity budget allowance.'),
          findsOneWidget);
    });

    testWidgets(
        '8. Budget-aware metadata absent hides transparency card completely',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_standard_1',
          'activityName': 'Fort Cornwallis',
          'dayNo': 1,
          'timeSlot': '09:00',
          'estimatedCost': 20,
          'costProvenance': 'verified_ticket',
          'selectionPriceStatus': 'verified',
          'openingHoursStatus': 'reported',
        }
      ]);

      await _pumpTrip(tester, trip);

      expect(find.byKey(const ValueKey('budget-aware-transparency-card')),
          findsNothing);
      expect(find.text('Budget-aware itinerary'), findsNothing);
    });

    testWidgets('9. Legacy-generated itinerary makes no budget-aware claims',
        (tester) async {
      final trip = {
        'id': 'legacy_trip_99',
        'title': 'Legacy Penang Tour',
        'destinationArea': 'Penang, Malaysia',
        'startDate': '2026-11-20',
        'endDate': '2026-11-20',
        'tripDays': 1,
        'status': 'planned',
        'activities': [
          {
            'activityId': 'act_leg_1',
            'activityName': 'Old Heritage Walk',
            'dayNo': 1,
            'timeSlot': '10:00',
            'estimatedCost': 15,
          }
        ],
      };

      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Old Heritage Walk'));

      expect(find.byKey(const ValueKey('budget-aware-transparency-card')),
          findsNothing);
      expect(find.text('Budget-aware itinerary'), findsNothing);
      expect(find.textContaining('Budget Optimized'), findsNothing);
      expect(find.text('Old Heritage Walk'), findsOneWidget);
    });

    testWidgets(
        '10. Unsupported or missing rationale falls back cleanly without crash',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': false,
          'selectionRationale': null,
          'unselectedActivities': null,
        },
        activities: [
          {
            'activityId': 'act_10',
            'activityName': 'Penang War Museum',
            'dayNo': 1,
            'timeSlot': '11:00',
            'estimatedCost': 35,
            'costProvenance': 'verified_ticket',
            'selectionPriceStatus': 'verified',
            'openingHoursStatus': 'reported',
          }
        ],
      );

      await _pumpTrip(tester, trip);

      expect(find.byKey(const ValueKey('budget-aware-transparency-card')),
          findsOneWidget);
      expect(find.text('Verified'), findsOneWidget);
      expect(find.byKey(const ValueKey('unselected-activities-expansion')),
          findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('11. Empty itinerary day preserves neutral messaging',
        (tester) async {
      final trip = _buildTrip(activities: []);

      await _pumpTrip(tester, trip);

      expect(find.text('No activities for this day'), findsOneWidget);
      expect(
          find.text(
              'Add a place or recalculate the itinerary to build this day.'),
          findsOneWidget);
      expect(find.textContaining('budget limitation'), findsNothing);
      expect(find.textContaining('missing pricing'), findsNothing);
    });

    testWidgets('12. Existing saved Trip compatibility renders with zero errors',
        (tester) async {
      final savedTrip = {
        'id': 'saved_trip_12',
        'title': 'Minimal Historical Trip',
        'destinationArea': 'Penang',
        'startDate': '2026-12-01',
        'endDate': '2026-12-02',
        'tripDays': 2,
        'status': 'planned',
        'activities': [
          {
            'activityName': 'Armenian Street',
            'dayNo': 1,
            'timeSlot': '15:00',
          }
        ],
      };

      await _pumpTrip(tester, savedTrip);

      expect(find.text('Minimal Historical Trip'), findsOneWidget);
      expect(find.text('Armenian Street'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        '13. Hours Unverified and Price Unverified together display combined label',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_both_unverified',
          'activityName': 'Ghost Museum',
          'dayNo': 1,
          'timeSlot': '16:00',
          'scheduledStartTime': '16:00',
          'estimatedCost': 28,
          'costProvenance': 'unverified',
          'selectionPriceStatus': 'unresolved',
          'openingHoursStatus': 'unknown',
          'scheduleFeasibility': 'provisional',
        }
      ]);

      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Ghost Museum'));

      expect(find.text('Hours & price\nunverified'), findsOneWidget);
      expect(find.text('Hours unverified'), findsOneWidget);
      expect(find.text('Admission unverified'), findsOneWidget);
      expect(find.text('~RM 28 estimate'), findsOneWidget);
    });

    testWidgets(
        '14. Long attraction names and small screens render without RenderFlex overflow',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_long_name',
          'activityName':
              'Tropical Spice Garden & Eco-Sanctuary Demonstration Kitchen and Living Plant Museum',
          'dayNo': 1,
          'timeSlot': '10:00',
          'scheduledStartTime': '10:00',
          'estimatedCost': 45,
          'costProvenance': 'verified_ticket',
          'selectionPriceStatus': 'conditional',
          'pricingEvidence': {
            'verified': true,
            'applicability': 'conditional',
          },
          'openingHoursStatus': 'reported',
          'scheduleFeasibility': 'feasible_with_reported_hours',
        }
      ]);

      await _pumpTrip(
        tester,
        trip,
        size: const Size(320, 600),
        textScale: 1.2,
      );
      await _scrollTarget(tester, find.textContaining('Tropical Spice Garden'));

      expect(
          find.text(
              'Tropical Spice Garden & Eco-Sanctuary Demonstration Kitchen and Living Plant Museum'),
          findsOneWidget);
      expect(find.text('Tariff conditional'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('15. Group budget display presents budget and subtotal clearly',
        (tester) async {
      final budget = BudgetModel.fromJson({
        'budgetLimit': 2000,
        'knownEstimatedSubtotal': 650,
        'totalEstimatedCost': 650,
        'completenessStatus': 'incomplete',
        'affordabilityStatus': 'incomplete',
        'pendingExpenseCategories': ['activities'],
        'categoryTotals': {
          'activities': 50,
          'food': 200,
          'transport': 100,
          'hotel': 300,
          'flight': 0,
          'carRental': 0,
        },
      });

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: BudgetBreakdown(budget: budget, limit: 2000),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Total group budget: RM 2000.00'), findsOneWidget);
      expect(find.text('Known estimated subtotal: RM 650.00'), findsOneWidget);
      expect(find.text('Incomplete estimate'), findsOneWidget);
    });

    testWidgets(
        '16. No misleading affordability or discount wording anywhere on the screen',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'selectionRationale': 'Budget-aware selection applied',
        },
        activities: [
          {
            'activityId': 'act_honest_1',
            'activityName': 'Batu Ferringhi Night Market',
            'dayNo': 1,
            'timeSlot': '19:00',
            'estimatedCost': 0,
            'costProvenance': 'unverified',
            'selectionPriceStatus': 'unresolved',
            'openingHoursStatus': 'reported',
          }
        ],
      );

      await _pumpTrip(tester, trip);

      expect(find.textContaining('100% Guaranteed'), findsNothing);
      expect(find.textContaining('Guaranteed Savings'), findsNothing);
      expect(find.textContaining('Discount Guaranteed'), findsNothing);
      expect(find.textContaining('Budget Optimized'), findsNothing);
      expect(
          find.textContaining(
              'Unresolved admission costs are not guaranteed within the initial budget'),
          findsOneWidget);
    });
  });
}
