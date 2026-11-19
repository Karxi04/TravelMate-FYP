import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/alternative_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/budget_service.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/budget_model.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _FakeAlternativeApi extends ApiService {
  final Future<dynamic> Function(String path, [Map<String, dynamic>? body])?
      onPost;
  int postCallCount = 0;
  List<String> postCalls = [];
  List<Map<String, dynamic>?> postBodies = [];

  _FakeAlternativeApi({this.onPost, this.onGet});
  final Future<dynamic> Function(String path)? onGet;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async =>
      onGet == null ? {} : await onGet!(path);

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postCallCount++;
    postCalls.add(path);
    postBodies.add(body);
    if (onPost != null) {
      return await onPost!(path, body);
    }
    return {'ok': true};
  }
}

Widget _buildApp(Widget child, {Size size = const Size(390, 844), double textScale = 1.0}) {
  return MaterialApp(
    home: MediaQuery(
      data: MediaQueryData(
        size: size,
        textScaler: TextScaler.linear(textScale),
      ),
      child: child,
    ),
  );
}

void main() {
  testWidgets('cancel budget replanning retains late verified comparisons without another search', (tester) async {
    final prices = Completer<dynamic>();
    final api = _FakeAlternativeApi(onGet: (_) async => {'ok': true, 'stateVersion': 'revision',
      'budget': {'total': 728, 'limit': 700},
      'budgetReplanOptions': {'allowances': {'foodCost': 360, 'transportCost': 105}}},
      onPost: (path, [body]) => prices.future);
    await tester.pumpWidget(_buildApp(AlternativeScreen(budget: BudgetModel(accommodation: 0,
      food: 360, transportation: 105, activities: 0, flight: 263), userBudget: 700, tripId: 'owned', api: api)));
    await tester.pump(); await tester.pump(const Duration(milliseconds: 100));
    final options = find.text('Review budget options'); await tester.ensureVisible(options);
    await tester.tap(options); await tester.pumpAndSettle();
    prices.complete({'ok': true, 'stateVersion': 'revision', 'budget': {'total': 728, 'limit': 700},
      'alternatives': [{'title': 'Verified lower fare', 'alternativeType': 'flight', 'canApply': true,
      'stateVersion': 'revision', 'estimatedSavings': 40, 'currentEstimatedCost': 263, 'replacementEstimatedCost': 223}]});
    await tester.pumpAndSettle();
    expect(find.text('Budget replanning'), findsOneWidget);
    expect(find.text('Current: RM 360.00'), findsOneWidget);
    await tester.pageBack(); await tester.pumpAndSettle();
    expect(find.text('Verified lower fare'), findsOneWidget);
    expect(api.postCallCount, 1);
    expect(api.postCalls.where((path) => path.endsWith('/apply')), isEmpty);
  });

  testWidgets('budget explanation links Search Flights to the exact current Trip without searching', (tester) async {
    final api = _FakeAlternativeApi(onGet: (path) async {
      if (path.endsWith('/budget-replan')) return {'ok': true, 'stateVersion': 'revision', 'budget': {'total': 728, 'limit': 700},
        'budgetReplanOptions': {'allowances': {'foodCost': 360, 'transportCost': 105}},
        'flightComparison': {'status': 'needs_review', 'reasons': ['Passenger count is missing.']}};
      return {'ok': true, 'itinerary': {'id': 'owned', 'travellerCount': 2, 'startDate': '2028-12-12', 'endDate': '2028-12-14', 'destinationArea': 'Penang'}};
    }, onPost: (path, [body]) async => {'ok': true, 'alternatives': [], 'flightAdvice': 'No comparable fare.'});
    await tester.pumpWidget(_buildApp(AlternativeScreen(budget: BudgetModel(accommodation: 0, food: 360, transportation: 105, activities: 0, flight: 263),
      userBudget: 700, tripId: 'owned', api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Passenger count is missing.'), findsOneWidget);
    final search = find.text('Search Flights'); await tester.ensureVisible(search);
    await tester.tap(search); await tester.pumpAndSettle();
    final target = tester.widget<FlightScreen>(find.byType(FlightScreen));
    expect(target.targetTripId, 'owned');
    expect(target.targetTrip?['travellerCount'], 2);
    expect(target.initialOutboundDate, '2028-12-12');
    expect(api.postCalls.where((path) => path.contains('/fr7/')), isEmpty);
  });

  testWidgets('allowance preview cancel confirm and reopen show known-subtotal reductions', (tester) async {
    var food = 360;
    var applies = 0;
    final api = _FakeAlternativeApi(onGet: (path) async => {'ok': true, 'stateVersion': 'revision',
      'budget': {'total': food + 368, 'limit': 700},
      'budgetReplanOptions': {'allowances': {'foodCost': food, 'transportCost': 105}}},
      onPost: (path, [body]) async {
        if (path.endsWith('/preview')) return {'before': {'total': 728, 'food': 360, 'transport': 105},
          'budget': {'total': 688, 'food': 320, 'transport': 105, 'pendingExpenseCategories': ['hotel', 'activities']},
          'estimatedReduction': 40, 'previewToken': 'confirmed-preview', 'retainedEstimate': 263};
        if (path.endsWith('/apply')) {
          expect(body?['confirmed'], true); expect(body?['previewToken'], 'confirmed-preview');
          applies++; food = 320;
          return {'itinerary': {'id': 'owned'}};
        }
        return {'ok': true, 'alternatives': []};
      });
    await tester.pumpWidget(_buildApp(AlternativeScreen(budget: BudgetModel(accommodation: 0, food: 360, transportation: 105, activities: 0, flight: 263),
      userBudget: 700, tripId: 'owned', api: api)));
    await tester.pumpAndSettle();
    Future<void> open() async {
      final options = find.text('Review budget options'); await tester.ensureVisible(options);
      await tester.tap(options); await tester.pumpAndSettle();
    }
    await open();
    await tester.enterText(find.widgetWithText(TextField, 'Food allowance (MYR)'), '320');
    final preview = find.text('Preview revised budget'); await tester.ensureVisible(preview);
    await tester.tap(preview); await tester.pumpAndSettle();
    expect(find.text('Previous known estimated subtotal: RM 728.00'), findsOneWidget);
    expect(find.text('Proposed known estimated subtotal: RM 688.00'), findsOneWidget);
    expect(find.text('Food allowance reduction: RM 40.00'), findsOneWidget);
    expect(find.textContaining('does not establish full-trip affordability'), findsOneWidget);
    await tester.tap(find.text('Cancel')); await tester.pumpAndSettle();
    expect(applies, 0); expect(food, 360);
    await tester.ensureVisible(preview); await tester.tap(preview); await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm budget changes')); await tester.pumpAndSettle();
    expect(applies, 1); expect(food, 320);
    await open();
    expect(find.text('Current: RM 320.00'), findsOneWidget);
    expect(applies, 1);
  });

  testWidgets('safe budget adjustments remain actionable while provider lookup is delayed', (tester) async {
    final pending = Completer<dynamic>();
    final api = _FakeAlternativeApi(
      onGet: (_) async => {'ok': true, 'stateVersion': 'owned-trip-revision',
        'budget': {'total': 900, 'limit': 800},
        'budgetReplanOptions': {'allowances': {'foodCost': 200, 'transportCost': 100}, 'optionalVisits': []}},
      onPost: (path, [body]) => pending.future,
    );
    await tester.pumpWidget(_buildApp(AlternativeScreen(
      budget: BudgetModel(accommodation: 300, food: 200, transportation: 100, activities: 300),
      userBudget: 800, tripId: 'owned', api: api)));
    await tester.pump(); await tester.pump(const Duration(milliseconds: 100));
    final review = find.widgetWithText(FilledButton, 'Review budget options');
    await tester.ensureVisible(review);
    expect(tester.widget<FilledButton>(review).onPressed, isNotNull);
    await tester.tap(review); await tester.pumpAndSettle();
    expect(find.text('Budget replanning'), findsOneWidget);
    expect(find.text('Food allowance (MYR)'), findsOneWidget);
    expect(api.postCalls, ['/api/fr5/itineraries/owned/lower-cost-alternatives']);
    pending.complete({'ok': true, 'budget': {'total': 1}, 'budgetReplanOptions': {}});
    await tester.pumpAndSettle();
    expect(find.text('Budget replanning'), findsOneWidget);
    expect(find.text('Current: RM 200.00'), findsOneWidget);
    expect(api.postCalls.where((path) => path.endsWith('/apply')), isEmpty);
  });
  final testBudgetModel = BudgetModel(
    accommodation: 300,
    food: 200,
    transportation: 150,
    activities: 250,
  );

  testWidgets('Confirms an applicable activity and displays the saved result', (tester) async {
    const option = {
      'alternativeType': 'activity',
      'title': 'Visit Penang Botanic Gardens instead',
      'description': 'Replace the paid visit on day 1.',
      'stateVersion': 'revision-1',
      'canApply': true,
      'estimatedSavings': 80,
    };
    var applied = false;
    final api = _FakeAlternativeApi(onPost: (path, [body]) async {
      if (path.endsWith('/apply')) {
        expect(body, {'alternative': option});
        applied = true;
        return {'itinerary': {'id': 'trip-123', 'activities': ['gardens']}, 'budget': {'total': 820}};
      }
      return {
        'budget': {'total': applied ? 820 : 900, 'limit': 800},
        'alternatives': applied ? [] : [option],
      };
    });
    Map<String, dynamic>? updated;
    await tester.pumpWidget(_buildApp(AlternativeScreen(
      budget: testBudgetModel,
      userBudget: 800,
      tripId: 'trip-123',
      api: api,
      onApplied: (trip) => updated = trip,
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Apply'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Estimated reduction: MYR 80.00'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(applied, isFalse);
    await tester.tap(find.text('Apply'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm change'));
    await tester.pumpAndSettle();
    expect(updated?['activities'], ['gardens']);
    expect(find.text('Estimated total RM 820 / budget RM 800'), findsOneWidget);
    expect(find.text('Apply'), findsNothing);
  });

  testWidgets('planning options outlast failed price searches, navigation and recreation',
      (tester) async {
    var revision = 'r1';
    var priceCalls = 0;
    var failPrices = true;
    final reads = <String>[];
    final api = _FakeAlternativeApi(
      onGet: (path) async {
        reads.add(path);
        return {
          'ok': true, 'stateVersion': revision,
          'budget': {'total': path.contains('/b/') ? 400 : 285, 'limit': 200},
          'budgetReplanOptions': {
            'allowances': {'foodCost': 100, 'transportCost': 70},
            'optionalVisits': [],
          },
        };
      },
      onPost: (path, [body]) async {
        priceCalls++;
        if (failPrices) throw ApiException('Quote lookup failed.', 503, {});
        return {'ok': true, 'alternatives': []};
      },
    );
    Widget page(String trip) => _buildApp(AlternativeScreen(
        budget: testBudgetModel, userBudget: 200, tripId: trip, api: api));

    await tester.pumpWidget(page('a'));
    await tester.pumpAndSettle();
    expect(find.text('Review budget options'), findsOneWidget);
    expect(find.text('Could not verify replacement prices'), findsOneWidget);

    failPrices = false;
    revision = 'r2';
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.text('Review budget options'), findsOneWidget);
    expect(find.textContaining('Earlier options may no longer apply'), findsOneWidget);
    expect(find.textContaining('No comparable replacement prices'), findsOneWidget);

    await tester.pumpWidget(page('b'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Estimated total RM 400'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await tester.pumpWidget(page('a'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Estimated total RM 285'), findsOneWidget);
    expect(find.text('Review budget options'), findsOneWidget);
    expect(reads, [
      '/api/fr5/itineraries/a/budget-replan', '/api/fr5/itineraries/a/budget-replan',
      '/api/fr5/itineraries/b/budget-replan', '/api/fr5/itineraries/a/budget-replan',
    ]);
    expect(priceCalls, 4);
  });

  group('Batch 21E-F2A-U: Budget Alternatives & Activity Advice Presentation', () {
    testWidgets('1. Backend activityAdvice rendering', (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [],
          'activityAlternativeStatus': 'priced_replacement_unavailable',
          'activityAdvice':
              'Consider a less expensive attraction only after checking its price, pricing unit and suitability. No comparable priced activity replacement is available here; savings cannot be calculated.',
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Activity budget guidance'), findsNothing);
      expect(
        find.textContaining(
            'Consider a less expensive attraction only after checking its price'),
        findsOneWidget,
      );
    });

    testWidgets('2. priced_replacement_unavailable status', (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [],
          'activityAlternativeStatus': 'priced_replacement_unavailable',
          'activityAdvice': 'Guidance available.',
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.text('No priced replacements are available for this itinerary yet.'), findsOneWidget);
    });

    testWidgets('3. Activity advice without numeric savings', (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [],
          'activityAlternativeStatus': 'priced_replacement_unavailable',
          'activityAdvice': 'Check ticket prices before visiting.',
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.textContaining('Save RM'), findsNothing);
      expect(find.textContaining('Est. save RM'), findsNothing);
    });

    testWidgets('4. Unsupported activity Apply absent or disabled',
        (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {
              'alternativeType': 'activity',
              'title': 'Replace one premium activity',
              'description': 'Swap paid attraction for a free walk.',
              'canApply': false,
            }
          ],
          'activityAlternativeStatus': 'priced_replacement_unavailable',
          'activityAdvice': 'No priced replacement available.',
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Replace one premium activity'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Apply'), findsNothing);
    });

    test('5. Draft fallback without invented RM100 savings in BudgetService',
        () {
      final service = BudgetService();
      final alternatives = service.generateAlternatives(testBudgetModel);

      final activityAlt = alternatives.firstWhere(
        (alt) => alt['type'] == 'activity',
        orElse: () => {},
      );

      expect(activityAlt, isNotEmpty);
      expect(activityAlt['saving'], isNull);
      expect(activityAlt['isAdvisory'], isTrue);
      expect(activityAlt['canApply'], isFalse);
    });

    testWidgets('6. Other unsupported draft savings represented as non-numeric advice',
        (tester) async {
      tester.view.physicalSize = const Size(600, 1400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: null, // Draft mode without tripId
      )));
      await tester.pumpAndSettle();

      expect(find.text('Activity budget guidance'), findsOneWidget);
      expect(find.text('Consider Lower-Cost Accommodation'), findsOneWidget);
      expect(find.text('Explore Free or Lower-Cost Attractions'), findsOneWidget);
      expect(find.text('Use Public Transit or Grouped Rides'), findsOneWidget);

      expect(find.textContaining('Save RM 100'), findsNothing);
      expect(find.textContaining('Save RM 150'), findsNothing);
      expect(find.textContaining('Save RM 80'), findsNothing);
      expect(find.widgetWithText(FilledButton, 'Apply'), findsNothing);
      expect(find.text('Advisory guidance'), findsNWidgets(3));
    });

    testWidgets('7. Existing valid flight alternatives', (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        if (path.endsWith('/apply')) {
          return {
            'ok': true,
            'budget': {'total': 750.0, 'limit': 800.0},
            'itinerary': {'id': 'trip-123'},
          };
        }
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {
              'alternativeType': 'flight',
              'title': 'Switch to AirAsia flight',
              'description': 'Replace current flight with AirAsia flight (MYR 120.00).',
              'canApply': true,
              'stateVersion': 'expected-revision',
              'estimatedSavings': 30.0,
              'source': 'fixture_quote',
              'data': {'searchId': 'flight-123', 'optionId': 'flight-option'},
            }
          ],
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Switch to AirAsia flight'), findsOneWidget);
      expect(find.text('Est. save RM 30.00'), findsOneWidget);
      expect(find.text('Source: fixture_quote'), findsOneWidget);

      final applyButton = find.widgetWithText(FilledButton, 'Apply');
      expect(applyButton, findsOneWidget);

      await tester.tap(applyButton);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();

      expect(fakeApi.postCalls, contains('/api/fr5/itineraries/trip-123/lower-cost-alternatives/apply'));
    });

    testWidgets('8. Existing valid hotel alternatives', (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        if (path.endsWith('/apply')) {
          return {
            'ok': true,
            'budget': {'total': 860.0, 'limit': 800.0},
            'itinerary': {'id': 'trip-123'},
          };
        }
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {
              'alternativeType': 'hotel',
              'title': 'Switch to Neo Hotel Penang',
              'description': 'Replace current hotel with Neo Hotel Penang (MYR 200.00).',
              'canApply': true,
              'stateVersion': 'expected-revision',
              'estimatedSavings': 40.0,
              'source': 'liteapi',
              'data': {'hotelBookingId': 'hotel-456'},
            }
          ],
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Switch to Neo Hotel Penang'), findsOneWidget);
      expect(find.text('Est. save RM 40.00'), findsOneWidget);
      expect(find.text('Source: liteapi'), findsOneWidget);

      final applyButton = find.widgetWithText(FilledButton, 'Apply');
      expect(applyButton, findsOneWidget);

      await tester.tap(applyButton);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();

      expect(fakeApi.postCalls, contains('/api/fr5/itineraries/trip-123/lower-cost-alternatives/apply'));
    });

    testWidgets('9. Server-supplied estimated savings are not presented as guaranteed',
        (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {
              'alternativeType': 'flight',
              'title': 'Lower-cost flight',
              'description': 'Same route and dates from a verified planning quote.',
              'canApply': true,
              'stateVersion': 'expected-revision',
              'estimatedSavings': 45.0,
            }
          ],
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      // Must be prefixed with Est. save RM, not a guaranteed Save RM
      expect(find.text('Est. save RM 45.00'), findsOneWidget);
      expect(find.text('Save RM 45'), findsNothing);
    });

    testWidgets('10. HTTP 409 explanation', (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        if (path.endsWith('/apply')) {
          throw const ApiException(
            'No validated priced activity replacement is available. Existing activity prices have not been changed.',
            409,
            {
              'ok': false,
              'error': 'No validated priced activity replacement is available. Existing activity prices have not been changed.',
              'code': 'ACTIVITY_REPLACEMENT_UNAVAILABLE',
              'canApply': false,
            },
          );
        }
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {
              'alternativeType': 'activity',
              'title': 'Test Alternative',
              'canApply': true,
              'stateVersion': 'expected-revision',
              'estimatedSavings': 20.0,
            }
          ],
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      final applyButton = find.widgetWithText(FilledButton, 'Apply');
      await tester.tap(applyButton);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();

      expect(
        find.text(
            'No validated priced activity replacement is available. Existing activity prices have not been changed.'),
        findsOneWidget,
      );
    });

    testWidgets('11. No automatic retry after 409', (tester) async {
      int applyAttempts = 0;
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        if (path.endsWith('/apply')) {
          applyAttempts++;
          throw const ApiException(
            'No validated priced activity replacement is available. Existing activity prices have not been changed.',
            409,
            {'code': 'ACTIVITY_REPLACEMENT_UNAVAILABLE'},
          );
        }
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {'alternativeType': 'activity', 'title': 'Test Option', 'estimatedSavings': 15.0,
             'canApply': true, 'stateVersion': 'expected-revision'}
          ],
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(FilledButton, 'Apply'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();

      // Only one attempt made; no automatic retry
      expect(applyAttempts, 1);
    });

    testWidgets('12. No budget changes after rejected Apply', (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        if (path.endsWith('/apply')) {
          throw const ApiException(
            'No validated priced activity replacement is available.',
            409,
            {'code': 'ACTIVITY_REPLACEMENT_UNAVAILABLE'},
          );
        }
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {'alternativeType': 'activity', 'title': 'Test Option', 'estimatedSavings': 15.0,
             'canApply': true, 'stateVersion': 'expected-revision'}
          ],
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Estimated total RM 900.0 / budget RM 800.0'), findsOneWidget);

      await tester.tap(find.widgetWithText(FilledButton, 'Apply'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();

      // Budget subtitle must remain unchanged
      expect(find.text('Estimated total RM 900.0 / budget RM 800.0'), findsOneWidget);
    });

    testWidgets('13. Legacy responses missing new advice fields',
        (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {
              'alternativeType': 'transport',
              'title': 'Use public transit',
              'estimatedSavings': 30.0,
            }
          ],
          // No activityAdvice or activityAlternativeStatus
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Use public transit'), findsOneWidget);
      expect(find.text('Activity budget guidance'), findsNothing);
      expect(find.text('Priced replacement unavailable'), findsNothing);
    });

    testWidgets('14. Empty alternatives with valid advice', (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [],
          'activityAdvice': 'Review admission tickets directly with venue operators.',
          'activityAlternativeStatus': 'priced_replacement_unavailable',
        };
      });

      await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: testBudgetModel,
        userBudget: 800,
        tripId: 'trip-123',
        api: fakeApi,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Activity budget guidance'), findsNothing);
      expect(
        find.text('Review admission tickets directly with venue operators.'),
        findsOneWidget,
      );
      expect(find.text('No priced replacements are available for this itinerary yet.'), findsOneWidget);
    });

    testWidgets('15. Narrow-screen (320px) and accessibility (1.8x) layouts',
        (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 950.0, 'limit': 800.0},
          'alternatives': [
            {
              'alternativeType': 'hotel',
              'title': 'Switch to Georgetown Heritage Boutique Hotel with Long Title',
              'description': 'Replace current hotel with a heritage boutique property in the central historic precinct.',
              'canApply': true,
              'stateVersion': 'expected-revision',
              'estimatedSavings': 85.0,
              'source': 'liteapi_partner_rates',
            }
          ],
          'activityAdvice': 'Detailed guidance for narrow screen viewports with large accessibility font scaling.',
          'activityAlternativeStatus': 'priced_replacement_unavailable',
        };
      });

      // 320px width narrow screen + 1.8x text scale
      await tester.pumpWidget(_buildApp(
        AlternativeScreen(
          budget: testBudgetModel,
          userBudget: 800,
          tripId: 'trip-123',
          api: fakeApi,
        ),
        size: const Size(320, 600),
        textScale: 1.8,
      ));
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(find.text('Activity budget guidance'), findsOneWidget);
      expect(find.text('Est. save RM 85.00'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Apply'), findsOneWidget);
    });
  });
}
