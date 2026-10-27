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

Map<String, dynamic> _freeActivity({
  String id = 'act_free',
  String name = 'Test Activity',
  String provenance = 'verified_ticket',
  String status = 'verified',
  String applicability = 'applicable',
  String eligibility = 'all_visitors',
  String sourceUrl = 'https://mypenang.gov.my/view_directory.php',
  String date = '2026-10-26T00:00:00Z',
  bool? verified,
  List<dynamic> issues = const [],
  double cost = 0.0,
}) {
  return {
    'activityId': id,
    'destinationId': id,
    'activityName': name,
    'dayNo': 1,
    'timeSlot': '09:00',
    'scheduledStartTime': '09:00',
    'estimatedCost': cost,
    'unitPrice': cost,
    'costProvenance': provenance,
    'selectionPriceStatus': status,
    'pricingEvidence': {
      'applicability': applicability,
      'eligibility': eligibility,
      if (sourceUrl.isNotEmpty) 'priceSourceUrl': sourceUrl,
      if (date.isNotEmpty) 'priceVerifiedAt': date,
      if (verified != null) 'verified': verified,
      if (issues.isNotEmpty) 'pricingIssues': issues,
    },
    'pricingIssues': issues,
    'openingHoursStatus': 'reported',
    'scheduleFeasibility': 'feasible_with_reported_hours',
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
  group('Batch F3-P2V-U: Verified-Free Admission Contract Hardening', () {
    testWidgets(
        '1. Missing verified Boolean and missing verification date -> NOT free',
        (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Missing Boolean and Date',
          date: '',
          verified: null,
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Missing Boolean and Date'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets(
        '2. Missing verified Boolean but complete supported positive evidence -> Free admission',
        (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Complete Positive Evidence',
          date: '2026-10-26T00:00:00Z',
          verified: null,
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Complete Positive Evidence'));
      expect(find.text('Free admission'), findsOneWidget);
      expect(find.text('Admission unverified'), findsNothing);
    });

    testWidgets('3. Explicit verified: false despite valid date -> NOT free',
        (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Explicitly False Verified',
          date: '2026-10-26T00:00:00Z',
          verified: false,
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Explicitly False Verified'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets(
        '4. verified: true but missing required provenance -> NOT free',
        (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Missing Required Provenance',
          provenance: 'unverified',
          date: '2026-10-26T00:00:00Z',
          verified: true,
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Missing Required Provenance'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets('5. Source URL missing -> NOT free', (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Missing Source URL',
          sourceUrl: '',
          date: '2026-10-26T00:00:00Z',
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Missing Source URL'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets('6. Verification date missing -> NOT free', (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Missing Date Field',
          date: '',
          verified: true,
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Missing Date Field'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets('7. Invalid or blank verification date -> NOT free',
        (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Invalid Date Stamp',
          date: 'not-a-valid-iso-date',
          verified: true,
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Invalid Date Stamp'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets('8. Non-empty pricingIssues -> NOT free', (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Conflicting Tram Issues',
          issues: ['Conflicting statements on tram fee'],
          date: '2026-10-26T00:00:00Z',
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Conflicting Tram Issues'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets('9. Conditional admission -> NOT free', (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Penang Hill Funicular',
          status: 'conditional',
          applicability: 'conditional',
          cost: 40,
          date: '2026-10-26T00:00:00Z',
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Penang Hill Funicular'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Tariff conditional'), findsOneWidget);
    });

    testWidgets('10. Unresolved admission -> NOT free', (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          name: 'Unresolved Price Activity',
          status: 'unresolved',
          date: '2026-10-26T00:00:00Z',
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Unresolved Price Activity'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets(
        '11. Legacy numeric zero without trusted evidence -> NOT free',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_leg_0',
          'activityName': 'Legacy Town Stroll',
          'dayNo': 1,
          'timeSlot': '10:00',
          'estimatedCost': 0,
        }
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Legacy Town Stroll'));
      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
    });

    testWidgets(
        '12. Valid Botanic Gardens zero-cost record -> Free admission',
        (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          id: 'local_bot',
          name: 'Penang Botanic Gardens',
          sourceUrl:
              'https://botanicalgardens.penang.gov.my/index.php/hubungi-kami/soalan-lazim-faq',
          date: '2026-10-26T00:00:00Z',
          verified: null, // real backend pricing_registry.py omits verified boolean
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Penang Botanic Gardens'));
      expect(find.text('Free admission'), findsOneWidget);
      expect(find.text('Admission unverified'), findsNothing);
    });

    testWidgets(
        '13. Valid Kek Lok Si main-grounds zero-cost record -> Free admission',
        (tester) async {
      final trip = _buildTrip(activities: [
        _freeActivity(
          id: 'local_kek_lok_si',
          name: 'Kek Lok Si Temple',
          sourceUrl:
              'https://mypenang.gov.my/view_directory.php?id=c2pkMG9tMEw2UUwzUk1hVTNWV3ZXZz09',
          date: '2026-10-26T00:00:00Z',
          verified: null, // real backend pricing_registry.py omits verified boolean
        )
      ]);
      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Kek Lok Si Temple'));
      expect(find.text('Free admission'), findsOneWidget);
      expect(find.text('Admission unverified'), findsNothing);
    });
  });

  group('Batch F3-P2F-R: Real Backend Payload Contract & Transparency', () {

    testWidgets(
        '5. Nested activity title is displayed correctly in unselected activities',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'unselectedActivities': [
            {
              'activity': {
                'activityId': 'act_nested_1',
                'activityName': 'The TOP Rainbow Skywalk',
                'score': 82,
              },
              'reasonCode': 'known_budget_exceeded',
              'explanation':
                  'Exceeds remaining activity budget allowance of RM 50.00.',
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
            'pricingEvidence': {
              'applicability': 'applicable',
              'priceSourceUrl': 'https://cheongfatttze.com',
            },
          }
        ],
      );

      await _pumpTrip(tester, trip);

      final unselectedFinder = find.text('Other places considered (1)');
      await _scrollTarget(tester, unselectedFinder);
      await tester.tap(unselectedFinder);
      await tester.pumpAndSettle();

      expect(find.text('The TOP Rainbow Skywalk'), findsOneWidget);
      expect(find.text('Suggested place'), findsNothing);
    });

    testWidgets(
        '6. Nested reasonCode is converted into user-friendly wording when explanation is absent',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'unselectedActivities': [
            {
              'activity': {
                'activityName': 'ESCAPE Penang Challenge',
              },
              'reasonCode': 'local_quality_replacement',
            }
          ],
        },
        activities: [
          {
            'activityId': 'act_1',
            'activityName': 'Heritage Walk',
            'dayNo': 1,
            'timeSlot': '10:00',
            'estimatedCost': 0,
          }
        ],
      );

      await _pumpTrip(tester, trip);

      final unselectedFinder = find.text('Other places considered (1)');
      await _scrollTarget(tester, unselectedFinder);
      await tester.tap(unselectedFinder);
      await tester.pumpAndSettle();

      expect(find.text('ESCAPE Penang Challenge'), findsOneWidget);
      expect(
          find.text('Replaced by activities with higher travel preference match.'),
          findsOneWidget);
    });

    testWidgets('7. Nested explanation is presented safely', (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'unselectedActivities': [
            {
              'activity': {
                'activityName': 'Wonderfood Museum',
              },
              'reasonCode': 'local_quality_replacement',
              'explanation':
                  'Replaced by two jointly schedulable, budgeted activities with higher aggregate original score.',
            }
          ],
        },
        activities: [
          {
            'activityId': 'act_1',
            'activityName': 'Heritage Walk',
            'dayNo': 1,
            'timeSlot': '10:00',
            'estimatedCost': 0,
          }
        ],
      );

      await _pumpTrip(tester, trip);

      final unselectedFinder = find.text('Other places considered (1)');
      await _scrollTarget(tester, unselectedFinder);
      await tester.tap(unselectedFinder);
      await tester.pumpAndSettle();

      expect(find.text('Wonderfood Museum'), findsOneWidget);
      expect(
          find.text(
              'Replaced by two jointly schedulable, budgeted activities with higher aggregate original score.'),
          findsOneWidget);
    });

    testWidgets('8. Missing nested activity fields do not crash',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'unselectedActivities': [
            {
              'activity': null,
              'reasonCode': null,
              'explanation': null,
            },
            {
              'activity': <String, dynamic>{},
              'reasonCode': 'unknown_code',
            }
          ],
        },
        activities: [
          {
            'activityId': 'act_1',
            'activityName': 'Heritage Walk',
            'dayNo': 1,
            'timeSlot': '10:00',
            'estimatedCost': 0,
          }
        ],
      );

      await _pumpTrip(tester, trip);

      final unselectedFinder = find.text('Other places considered (2)');
      await _scrollTarget(tester, unselectedFinder);
      await tester.tap(unselectedFinder);
      await tester.pumpAndSettle();

      expect(find.text('Suggested place'), findsNWidgets(2));
      expect(tester.takeException(), isNull);
    });

    testWidgets('9. Legacy flat exclusion records remain compatible',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'unselectedActivities': [
            {
              'activityName': 'Old Heritage Gallery',
              'reason': 'known_budget_exceeded',
            }
          ],
        },
        activities: [
          {
            'activityId': 'act_1',
            'activityName': 'Heritage Walk',
            'dayNo': 1,
            'timeSlot': '10:00',
            'estimatedCost': 0,
          }
        ],
      );

      await _pumpTrip(tester, trip);

      final unselectedFinder = find.text('Other places considered (1)');
      await _scrollTarget(tester, unselectedFinder);
      await tester.tap(unselectedFinder);
      await tester.pumpAndSettle();

      expect(find.text('Old Heritage Gallery'), findsOneWidget);
      expect(find.text('Exceeds remaining activity budget allowance.'),
          findsOneWidget);
    });

    testWidgets('10. Structured rationale lists display readable prose',
        (tester) async {
      // Backend budget_aware_selection emits rationale as List of dicts
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'selectionRationale': [
            {
              'activityId': 'act_1',
              'score': 95,
              'explanation':
                  'Accepted in descending original-score order: known group cost fits and all selected visits fit the existing scheduler.',
            },
            {
              'activityId': 'act_2',
              'score': 70,
              'explanation':
                  'Provisional scheduling suggestion only: admission is unresolved and affordability is not established.',
            }
          ],
        },
        activities: [
          {
            'activityId': 'act_1',
            'activityName': 'Kek Lok Si Temple',
            'dayNo': 1,
            'timeSlot': '09:00',
            'estimatedCost': 0,
          }
        ],
      );

      await _pumpTrip(tester, trip);

      expect(
          find.textContaining(
              'Accepted in descending original-score order: known group cost fits'),
          findsOneWidget);
      expect(find.textContaining('{activityId:'), findsNothing);
      expect(find.textContaining('[{'), findsNothing);
    });

    testWidgets('11. Rationale maps are not rendered as raw debug text',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'selectionRationale': {
            'summary':
                'Prioritized cultural heritage sites within available time.',
            'debugInternalTrace': 'opt_step_49',
          },
        },
        activities: [
          {
            'activityId': 'act_1',
            'activityName': 'Kek Lok Si Temple',
            'dayNo': 1,
            'timeSlot': '09:00',
            'estimatedCost': 0,
          }
        ],
      );

      await _pumpTrip(tester, trip);

      expect(
          find.text(
              'Prioritized cultural heritage sites within available time.'),
          findsOneWidget);
      expect(find.textContaining('debugInternalTrace'), findsNothing);
    });

    testWidgets('12. Missing rationale produces a graceful fallback',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'selectionRationale': null,
        },
        activities: [
          {
            'activityId': 'act_1',
            'activityName': 'Kek Lok Si Temple',
            'dayNo': 1,
            'timeSlot': '09:00',
            'estimatedCost': 0,
          }
        ],
      );

      await _pumpTrip(tester, trip);

      expect(find.byKey(const ValueKey('budget-aware-transparency-card')),
          findsOneWidget);
      expect(find.text('null'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        '13. Estimated food and transport allowances are not globally marked verified',
        (tester) async {
      // Itinerary where activity ticket is verified, but food/transport are allowances
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': false,
        },
        activities: [
          {
            'activityId': 'act_v',
            'activityName': 'Kek Lok Si Temple',
            'dayNo': 1,
            'timeSlot': '09:00',
            'estimatedCost': 0,
            'costProvenance': 'verified_ticket',
            'selectionPriceStatus': 'verified',
            'pricingEvidence': {
              'applicability': 'applicable',
              'eligibility': 'all_visitors',
              'priceSourceUrl': 'https://mypenang.gov.my/',
              'priceVerifiedAt': '2026-10-26T00:00:00Z',
              'verified': true,
            },
            'openingHoursStatus': 'reported',
            'scheduleFeasibility': 'feasible_with_reported_hours',
          }
        ],
      );

      await _pumpTrip(tester, trip);

      // Card chip must say 'Admission verified' (specifically for admissions), NOT generic 'Verified'
      expect(find.text('Admission verified'), findsOneWidget);
      expect(find.text('Verified'), findsNothing);
      expect(find.textContaining('Food and transport allowances remain estimated'),
          findsOneWidget);
    });

    testWidgets('14. Incomplete trip costs remain incomplete', (tester) async {
      final budget = BudgetModel.fromJson({
        'budgetLimit': 1500,
        'knownEstimatedSubtotal': 450,
        'totalEstimatedCost': 450,
        'completenessStatus': 'incomplete',
        'affordabilityStatus': 'incomplete',
        'pendingExpenseCategories': ['activities'],
      });

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: BudgetBreakdown(budget: budget, limit: 1500),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Incomplete estimate'), findsOneWidget);
      expect(find.textContaining('remaining balance cannot be guaranteed'),
          findsOneWidget);
      expect(find.textContaining('Estimated balance:'), findsNothing);
    });

    testWidgets(
        '15. Budget-aware metadata absent behaves correctly for legacy Trips',
        (tester) async {
      final trip = {
        'id': 'legacy_trip_15',
        'title': 'Legacy Penang Tour',
        'destinationArea': 'Penang, Malaysia',
        'startDate': '2026-11-20',
        'endDate': '2026-11-20',
        'tripDays': 1,
        'status': 'planned',
        'activities': [
          {
            'activityId': 'act_leg_1',
            'activityName': 'Old Town Stroll',
            'dayNo': 1,
            'timeSlot': '10:00',
            'estimatedCost': 15,
          }
        ],
      };

      await _pumpTrip(tester, trip);

      expect(find.byKey(const ValueKey('budget-aware-transparency-card')),
          findsNothing);
      expect(find.text('Budget-aware itinerary'), findsNothing);
      expect(find.textContaining('Budget Optimized'), findsNothing);
    });

    testWidgets(
        '16. Unknown activity pricing is never presented as confirmed free',
        (tester) async {
      final trip = _buildTrip(activities: [
        {
          'activityId': 'act_unknown_free',
          'activityName': 'Mysterious Night Market',
          'dayNo': 1,
          'timeSlot': '19:00',
          'estimatedCost': 0,
          'costProvenance': 'unverified',
          'selectionPriceStatus': 'unresolved',
        }
      ]);

      await _pumpTrip(tester, trip);
      await _scrollTarget(tester, find.text('Mysterious Night Market'));

      expect(find.text('Free admission'), findsNothing);
      expect(find.text('Admission unverified'), findsOneWidget);
      expect(find.text('Price TBC'), findsOneWidget);
    });

    testWidgets(
        '17. Small screens and long attraction names do not overflow',
        (tester) async {
      final trip = _buildTrip(
        budgetAwareSelection: {
          'applied': true,
          'isProvisional': true,
          'unselectedActivities': [
            {
              'activity': {
                'activityName':
                    'Tropical Spice Garden & Eco-Sanctuary Demonstration Kitchen and Living Plant Museum',
              },
              'reasonCode': 'known_budget_exceeded',
            }
          ],
        },
        activities: [
          {
            'activityId': 'act_long_name',
            'activityName':
                'Pinang Peranakan Mansion Heritage Experience and Antique Jewellery Gallery',
            'dayNo': 1,
            'timeSlot': '10:00',
            'scheduledStartTime': '10:00',
            'estimatedCost': 30,
            'costProvenance': 'verified_ticket',
            'selectionPriceStatus': 'conditional',
            'pricingEvidence': {
              'applicability': 'conditional',
              'priceSourceUrl': 'https://pinangperanakanmansion.com.my/',
            },
          }
        ],
      );

      await _pumpTrip(
        tester,
        trip,
        size: const Size(320, 600),
        textScale: 1.2,
      );

      await _scrollTarget(tester, find.textContaining('Pinang Peranakan Mansion'));
      expect(find.text('Tariff conditional'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        '18. Existing session and historical Trip data contracts remain compatible',
        (tester) async {
      final historicTrip = {
        'id': 'historic_p2f_trip',
        'title': 'Minimal Historical Trip',
        'destinationArea': 'Penang',
        'startDate': '2026-12-01',
        'endDate': '2026-12-02',
        'tripDays': 2,
        'status': 'planned',
        'activities': [
          {
            'activityName': 'Armenian Street Murals',
            'dayNo': 1,
            'timeSlot': '15:00',
            'estimatedCost': 0,
          }
        ],
      };

      await _pumpTrip(tester, historicTrip);

      expect(find.text('Minimal Historical Trip'), findsOneWidget);
      expect(find.text('Armenian Street Murals'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
