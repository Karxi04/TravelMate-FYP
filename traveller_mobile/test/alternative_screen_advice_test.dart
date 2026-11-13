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

  _FakeAlternativeApi({this.onPost});

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
