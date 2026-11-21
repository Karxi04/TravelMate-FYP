import 'package:travelmate_traveller/services/transaction_request.dart';
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
    if (path.endsWith('/lower-cost-alternatives/preview')) {
      final option = body!['alternative'] as Map;
      final saving = option['estimatedSavings'] as num;
      return {
        'before': {'total': 900},
        'budget': {'total': 900 - saving, 'overBy': 100 - saving},
        'estimatedReduction': saving
      };
    }
    if (onPost != null) {
      return await onPost!(path, body);
    }
    return {'ok': true};
  }
}

Widget _buildApp(Widget child,
    {Size size = const Size(390, 844), double textScale = 1.0}) {
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
  testWidgets(
      'flight timing preview explains rejected visits without allowing apply',
      (tester) async {
    var applies = 0, searches = 0;
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': 'r',
              'budget': {'total': 900, 'limit': 700, 'flight': 600}
            },
        onPost: (path, [body]) async {
          if (path.endsWith('/apply')) applies++;
          if (path.endsWith('/discover')) searches++;
          return {
            'ok': true,
            'stateVersion': 'r',
            'budget': {'total': 900, 'limit': 700, 'flight': 600},
            'alternatives': [],
            'flightTimingPreviews': [
              {
                'title': 'Flight timing needs review',
                'currentCost': 600,
                'proposedCost': 420,
                'canApply': false,
                'reason': 'The flight cannot retain all planned visits.',
                'itineraryChanges': [
                  {'activityName': 'Long planned visit', 'kind': 'unscheduled'}
                ]
              }
            ]
          };
        });
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 0,
            food: 200,
            transportation: 100,
            activities: 0,
            flight: 600),
        userBudget: 700,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Unavailable options · details'), 200);
    await tester.pump();
    await tester.tap(find.text('Unavailable options · details'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Review timing'), 200);
    await tester.tap(find.text('Review timing'));
    await tester.pumpAndSettle();
    expect(find.text('Long planned visit — unscheduled'), findsOneWidget);
    expect(find.text('Confirm change'), findsNothing);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(applies, 0);
    expect(searches, 0);
  });

  for (final status in ['needs_review', 'unavailable']) {
    testWidgets(
        '$status is not presented as an empty completed provider search',
        (tester) async {
      final api = _FakeAlternativeApi(
          onGet: (_) async => {
                'ok': true,
                'stateVersion': 'r',
                'budget': {'total': 900, 'limit': 700, 'hotel': 400}
              },
          onPost: (path, [body]) async => path.endsWith('/discover')
              ? {
                  'search': {
                    'status': status,
                    'requestsAttempted': status == 'needs_review' ? 0 : 1,
                    'failureCode': 'provider_timeout'
                  }
                }
              : {
                  'ok': true,
                  'stateVersion': 'r',
                  'budget': {'total': 900, 'limit': 700, 'hotel': 400},
                  'alternatives': []
                });
      await tester.pumpWidget(_buildApp(AlternativeScreen(
          budget: BudgetModel(
              accommodation: 400,
              food: 300,
              transportation: 200,
              activities: 0),
          userBudget: 700,
          tripId: 'owned',
          api: api)));
      await tester.pumpAndSettle();
      expect(find.textContaining('No verified cheaper'), findsNothing);
      await tester.scrollUntilVisible(find.text('Find cheaper hotels'), 200);
      await tester.pump();
      await tester.tap(find.text('Find cheaper hotels'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Search now'));
      await tester.pumpAndSettle();
      expect(
          find.textContaining(status == 'needs_review'
              ? 'Hotel search has not run.'
              : 'The provider search timed out.'),
          findsOneWidget);
      expect(find.textContaining('No verified cheaper'), findsNothing);
    });
  }
  testWidgets(
      'genuine search limit shows Malaysia retry time and clears before a fresh search',
      (tester) async {
    var searches = 0;
    final fresh = Completer<dynamic>();
    final retry = DateTime.now().toUtc().add(const Duration(hours: 2));
    final local = retry
        .add(const Duration(hours: 8))
        .toIso8601String()
        .substring(0, 16)
        .replaceFirst('T', ' ');
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': 'r',
              'budget': {
                'total': 900,
                'limit': 700,
                'flight': 300,
                'hotel': 400
              }
            },
        onPost: (path, [body]) async {
          if (path.endsWith('/discover')) {
            searches++;
            if (searches == 1)
              return {
                'search': {
                  'status': 'quota_limited',
                  'retryAt': retry.toIso8601String()
                }
              };
            return fresh.future;
          }
          return {
            'ok': true,
            'stateVersion': 'r',
            'budget': {'total': 900, 'limit': 700, 'flight': 300, 'hotel': 400},
            'alternatives': []
          };
        });
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 400, food: 360, transportation: 140, activities: 0),
        userBudget: 700,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    Future<void> search() async {
      await tester.scrollUntilVisible(find.text('Find cheaper flights'), 200);
      await tester.tap(find.text('Find cheaper flights'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Search now'));
      await tester.pump();
    }

    await search();
    await tester.pumpAndSettle();
    expect(find.text('Flight search limit reached. Try again at $local MYT.'),
        findsOneWidget);
    await search();
    expect(find.textContaining('search limit reached'), findsNothing);
    fresh.complete({
      'search': {'status': 'completed', 'requestsAttempted': 1, 'reasonCode':'no_offers',
        'candidateCount':0,'validQuoteCount':0}
    });
    await tester.pumpAndSettle();
    expect(find.text('Provider search completed with no offers returned.'),
        findsOneWidget);
    expect(searches, 2);
    expect(api.postCalls.where((path) => path.endsWith('/apply')), isEmpty);
  });

  testWidgets(
      'blocked hotel comparison says search has not run and does not apply or retry',
      (tester) async {
    var searches = 0;
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': 'r',
              'budget': {
                'total': 900,
                'limit': 700,
                'flight': 300,
                'hotel': 400
              }
            },
        onPost: (path, [body]) async {
          if (path.endsWith('/discover')) {
            searches++;
            throw ApiException(
                'A comparable unpaid total-stay price including taxes is needed.',
                409, {});
          }
          return {
            'ok': true,
            'stateVersion': 'r',
            'budget': {'total': 900, 'limit': 700, 'flight': 300, 'hotel': 400},
            'alternatives': []
          };
        });
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 400, food: 360, transportation: 140, activities: 0),
        userBudget: 700,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Find cheaper hotels'), 200);
    await tester.pump();
    await tester.tap(find.text('Find cheaper hotels'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Search now'));
    await tester.pumpAndSettle();
    expect(find.textContaining('A comparable unpaid total-stay price including taxes is needed.'), findsOneWidget);
    expect(
        find.text(
            'No verified cheaper hotel is currently available for this stay.'),
        findsNothing);
    expect(find.textContaining('total-stay price'), findsOneWidget);
    expect(searches, 1);
    expect(api.postCalls.where((path) => path.endsWith('/apply')), isEmpty);
  });

  for (final category in ['flight', 'hotel']) {
    testWidgets(
        'discovered $category renders and preview cancel confirm reopens once',
        (tester) async {
      tester.view.physicalSize = const Size(600, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var discovered = false, saved = false, applies = 0;
      final api = _FakeAlternativeApi(
          onGet: (_) async => {
                'ok': true,
                'stateVersion': saved ? 'new' : 'r',
                'budget': {
                  'total': saved ? 750 : 900,
                  'limit': 800,
                  'flight': 300,
                  'hotel': 400
                }
              },
          onPost: (path, [body]) async {
            if (path.endsWith('/discover')) {
              discovered = true;
              return {
                'search': {'status': 'completed', 'requestsAttempted': 1}
              };
            }
            if (path.endsWith('/apply')) {
              applies++;
              saved = true;
              return {
                'ok': true,
                'itinerary': {'id': 'owned'},
                'budget': {'total': 750, 'limit': 800}
              };
            }
            return {
              'ok': true,
              'stateVersion': 'r',
              'budget': {
                'total': 900,
                'limit': 800,
                'flight': 300,
                'hotel': 400
              },
              'alternatives': discovered && !saved
                  ? [
                      {
                        'alternativeType': category,
                        'title': 'Verified cheaper $category',
                        'canApply': true,
                        'stateVersion': 'r',
                        'currentEstimatedCost': 400,
                        'replacementEstimatedCost': 250,
                        'estimatedSavings': 150,
                        'source': 'fixture_quote',
                        'data': category == 'hotel'
                            ? {'roomName': 'Twin', 'address': 'Penang'}
                            : {}
                      }
                    ]
                  : []
            };
          });
      Widget screen() => _buildApp(AlternativeScreen(
          budget: BudgetModel(
              accommodation: 400,
              food: 360,
              transportation: 140,
              activities: 0),
          userBudget: 800,
          tripId: 'owned',
          api: api));
      await tester.pumpWidget(screen());
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
          find.text(
              'Find cheaper ' + (category == 'hotel' ? 'hotels' : 'flights')),
          200);
      await tester.tap(find.text(
          'Find cheaper ' + (category == 'hotel' ? 'hotels' : 'flights')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Search now'));
      await tester.pumpAndSettle();
      expect(find.text('Verified cheaper $category'), findsOneWidget);
      await tester.scrollUntilVisible(
          find.widgetWithText(FilledButton, 'Preview'), 200);
      await tester.ensureVisible(find.text('Preview'));await tester.pump();
    await tester.tap(find.text('Preview'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(saved, false);
      expect(applies, 0);
      await tester.ensureVisible(find.text('Preview'));await tester.pump();
    await tester.tap(find.text('Preview'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();
      expect(saved, true);
      expect(applies, 1);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      await tester.pumpWidget(screen());
      await tester.pumpAndSettle();
      expect(find.text('Verified cheaper $category'), findsNothing);
      expect(
          api.postCalls.where((path) => path.endsWith('/discover')).length, 1);
      expect(applies, 1);
    });
  }

  testWidgets(
      'provider discovery requires confirmation, prevents duplicates and reloads actual quotes',
      (tester) async {
    tester.view.physicalSize = const Size(600, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final response = Completer<dynamic>();
    var found = false;
    var searches = 0;
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': 'revision',
              'budget': {
                'total': 1465,
                'limit': 1000,
                'flight': 600,
                'hotel': 400
              },
              'budgetReplanOptions': {
                'allowances': {'foodCost': 360, 'transportCost': 105}
              }
            },
        onPost: (path, [body]) async {
          if (path.endsWith('/discover')) {
            expect(body?['providerSearchConfirmed'], true);
            expect(body?['stateVersion'], 'revision');
            expect(body?['category'], 'flight');
            expect(body?['searchRequestId'], startsWith('budget_search_'));
            searches++;
            return response.future;
          }
          return {
            'ok': true,
            'stateVersion': 'revision',
            'budget': {
              'total': 1465,
              'limit': 1000,
              'flight': 600,
              'hotel': 400
            },
            'alternatives': found
                ? [
                    {
                      'alternativeType': 'flight',
                      'title': 'Lower-cost flight: Synthetic Air',
                      'stateVersion': 'revision',
                      'canApply': true,
                      'currentEstimatedCost': 600,
                      'replacementEstimatedCost': 420,
                      'estimatedSavings': 180,
                      'data': {
                        'outboundSegments': [
                          {
                            'departureAirportCode': 'KUL',
                            'departureDate': '2027-02-10',
                            'departureTime': '10:40',
                            'arrivalAirportCode': 'PEN',
                            'arrivalTime': '11:40'
                          }
                        ]
                      }
                    }
                  ]
                : []
          };
        });
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 400,
            food: 360,
            transportation: 105,
            activities: 0,
            flight: 600),
        userBudget: 1000,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    expect(searches, 0);
    expect(find.text('Search Flights'), findsNothing);
    await tester.tap(find.text('Find cheaper flights'));
    await tester.pumpAndSettle();
    expect(find.textContaining('up to 2 provider requests'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(searches, 0);
    await tester.tap(find.text('Find cheaper flights'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Search now'));
    await tester.pump(const Duration(milliseconds: 350));
    expect(searches, 1);
    expect(
        tester
            .widget<OutlinedButton>(
                find.widgetWithText(OutlinedButton, 'Searching…'))
            .onPressed,
        isNull);
    expect(
        tester
            .widget<OutlinedButton>(
                find.widgetWithText(OutlinedButton, 'Find cheaper hotels'))
            .onPressed,
        isNull);
    found = true;
    response.complete({
      'ok': true,
      'search': {'status': 'completed', 'requestsAttempted': 2}
    });
    await tester.pumpAndSettle();
    expect(find.text('Lower-cost flight: Synthetic Air'), findsOneWidget);
    await tester.ensureVisible(find.text('Compare flight details'));await tester.pump();
    await tester.tap(find.text('Compare flight details'));await tester.pumpAndSettle();
    expect(find.textContaining('KUL 2027-02-10 10:40 → PEN 11:40'),
        findsOneWidget);
    expect(searches, 1);
    expect(api.postCalls.where((path) => path.endsWith('/apply')), isEmpty);
  });

  testWidgets(
      'hotel search failure is not retried and local planning options remain',
      (tester) async {
    var searches = 0;
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': 'r',
              'budget': {'total': 990, 'limit': 700, 'hotel': 400},
              'budgetReplanOptions': {
                'allowances': {'foodCost': 360, 'transportCost': 105}
              },
              'planningAlternatives': [
                {
                  'title': 'Review food allowance',
                  'category': 'Food',
                  'changes': {'foodCost': 324},
                  'currentEstimatedCost': 360,
                  'replacementEstimatedCost': 324,
                  'estimatedSavings': 36,
                  'remainingOverBy': 254
                }
              ]
            },
        onPost: (path, [body]) async {
          if (path.endsWith('/discover')) {
            searches++;
            throw ApiException('timeout', 503, {});
          }
          return {'ok': true, 'alternatives': []};
        });
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 400, food: 360, transportation: 105, activities: 0),
        userBudget: 700,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Find cheaper hotels'), 200);
    await tester.pump();
    await tester.tap(find.text('Find cheaper hotels'));
    await tester.pumpAndSettle();
    expect(find.textContaining('1 provider rates request'), findsOneWidget);
    await tester.tap(find.text('Search now'));
    await tester.pumpAndSettle();
    expect(searches, 1);
    expect(
        find.textContaining('Search could not be confirmed'), findsOneWidget);
    expect(api.postCalls.where((path) => path.endsWith('/apply')), isEmpty);
    await tester.drag(find.byType(ListView), const Offset(0, 700));
    await tester.pumpAndSettle();
    expect(find.text('Review food allowance'), findsOneWidget);
    expect(
        tester
            .widget<FilledButton>(find.widgetWithText(FilledButton, 'Preview'))
            .onPressed,
        isNotNull);
  });

  test(
      'explicit provider discovery uses bounded provider timeout without changing payment timeout',
      () {
    expect(
        RequestTimeouts.forPost(
            '/api/fr5/itineraries/owned/lower-cost-alternatives/discover'),
        const Duration(seconds: 90));
    expect(RequestTimeouts.forPost('/api/fr9/checkout/session'),
        RequestTimeouts.providerMutation);
    expect(RequestTimeouts.forPost('/ordinary'), RequestTimeouts.ordinaryWrite);
  });

  testWidgets(
      'changing Trip while a local preview is pending cannot confirm or overwrite the new Trip',
      (tester) async {
    final pending = Completer<dynamic>();
    final api = _FakeAlternativeApi(
        onGet: (path) async => {
              'ok': true,
              'stateVersion': path.contains('/first/') ? 'first-r' : 'second-r',
              'budget': {'total': 990, 'limit': 700},
              'planningAlternatives': [
                {
                  'title': 'Review food allowance',
                  'category': 'Food',
                  'changes': {'foodCost': 324},
                  'currentEstimatedCost': 360,
                  'replacementEstimatedCost': 324,
                  'estimatedSavings': 36,
                  'remainingOverBy': 254
                }
              ],
              'budgetReplanOptions': {
                'allowances': {'foodCost': 360, 'transportCost': 105}
              }
            },
        onPost: (path, [body]) async {
          if (path.endsWith('/budget-replan/preview')) return pending.future;
          return {'ok': true, 'alternatives': []};
        });
    Map<String, dynamic>? applied;
    Widget page(String id) => _buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 0,
            food: 360,
            transportation: 105,
            activities: 0,
            flight: 525),
        userBudget: 700,
        tripId: id,
        api: api,
        onApplied: (trip) => applied = trip));
    await tester.pumpWidget(page('first'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Preview'));await tester.pump();
    await tester.tap(find.text('Preview'));
    await tester.pump();
    await tester.pumpWidget(page('second'));
    await tester.pumpAndSettle();
    pending.complete({
      'before': {'total': 990},
      'budget': {'total': 954},
      'estimatedReduction': 36,
      'previewToken': 'first-token'
    });
    await tester.pumpAndSettle();
    expect(find.text('Confirm change'), findsNothing);
    expect(api.postCalls.where((path) => path.endsWith('/apply')), isEmpty);
    expect(applied, isNull);
    expect(find.text('RM 360.00 → RM 324.00'), findsOneWidget);
  });

  testWidgets(
      'RM990 displays local reductions before quotes finish; preview cancel confirm survives reopen',
      (tester) async {
    var food = 360;
    var revision = 'one';
    var writes = 0;
    final pending = Completer<dynamic>();
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': revision,
              'budget': {
                'total': food + 630,
                'limit': 700,
                'pendingExpenseCategories': ['hotel']
              },
              'budgetReplanOptions': {
                'allowances': {'foodCost': food, 'transportCost': 105}
              },
              'planningAlternatives': [
                {
                  'title': 'Review food allowance',
                  'category': 'Food',
                  'changes': {'foodCost': 324},
                  'currentEstimatedCost': food,
                  'replacementEstimatedCost': 324,
                  'estimatedSavings': food - 324,
                  'remainingOverBy': 254,
                  'canApply': true
                }
              ],
            },
        onPost: (path, [body]) async {
          if (path.endsWith('/budget-replan/preview')) {
            expect(body?['stateVersion'], 'one');
            return {
              'before': {'total': 990},
              'budget': {
                'total': 954,
                'overBy': 254,
                'pendingExpenseCategories': ['hotel']
              },
              'estimatedReduction': 36,
              'previewToken': 'bound'
            };
          }
          if (path.endsWith('/budget-replan/apply')) {
            expect(body?['confirmed'], true);
            expect(body?['previewToken'], 'bound');
            writes++;
            food = 324;
            revision = 'two';
            return {
              'itinerary': {'id': 'owned', 'foodCost': 324}
            };
          }
          return pending.future;
        });
    Widget page() => _buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 0,
            food: 360,
            transportation: 105,
            activities: 0,
            flight: 525),
        userBudget: 700,
        tripId: 'owned',
        api: api));
    await tester.pumpWidget(page());
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Known estimate: RM 990.00'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('RM 360.00 → RM 324.00'), 200);
    await tester.pump();
    expect(find.text('RM 360.00 → RM 324.00'), findsOneWidget);
    expect(find.text('Remaining over budget: RM 254.00'), findsOneWidget);
    await tester.ensureVisible(find.text('Preview'));await tester.pump();
    await tester.tap(find.text('Preview'));
    await tester.pump(const Duration(milliseconds: 350));
    expect(find.text('Proposed known estimate: RM 954.00'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pump(const Duration(milliseconds: 350));
    expect(writes, 0);
    expect(food, 360);
    await tester.ensureVisible(find.text('Preview'));await tester.pump();
    await tester.tap(find.text('Preview'));
    await tester.pump(const Duration(milliseconds: 350));
    await tester.tap(find.text('Confirm change'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(writes, 1);
    expect(food, 324);
    pending.complete({
      'ok': true,
      'budget': {'total': 954, 'limit': 700},
      'alternatives': [],
      'stateVersion': 'two'
    });
    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpWidget(page());
    await tester.pump(const Duration(milliseconds: 350));
    expect(find.text('Known estimate: RM 954.00'), findsOneWidget);
    expect(writes, 1);
    expect(find.text('Search Flights'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'within-budget incomplete saved trip skips quote calls and does not claim affordability',
      (tester) async {
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': 'r',
              'budget': {
                'total': 695,
                'limit': 1500,
                'pendingExpenseCategories': ['activities']
              }
            });
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 200, food: 300, transportation: 195, activities: 0),
        userBudget: 1500,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Known estimate: RM 695.00'), findsOneWidget);
    expect(find.textContaining('does not establish full-trip affordability'),
        findsOneWidget);
    expect(find.text('Available ways to save'), findsNothing);
    expect(find.text('Search Flights'), findsNothing);
    expect(api.postCallCount, 0);
  });

  testWidgets(
      'cancel budget replanning retains late verified comparisons without another search',
      (tester) async {
    final prices = Completer<dynamic>();
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': 'revision',
              'budget': {'total': 728, 'limit': 700},
              'budgetReplanOptions': {
                'allowances': {'foodCost': 360, 'transportCost': 105}
              }
            },
        onPost: (path, [body]) => prices.future);
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 0,
            food: 360,
            transportation: 105,
            activities: 0,
            flight: 263),
        userBudget: 700,
        tripId: 'owned',
        api: api)));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    final options = find.text('Review budget options');
    await tester.ensureVisible(options);await tester.pump();
    await tester.tap(options);
    await tester.pumpAndSettle();
    prices.complete({
      'ok': true,
      'stateVersion': 'revision',
      'budget': {'total': 728, 'limit': 700},
      'alternatives': [
        {
          'title': 'Verified lower fare',
          'alternativeType': 'flight',
          'canApply': true,
          'stateVersion': 'revision',
          'estimatedSavings': 40,
          'currentEstimatedCost': 263,
          'replacementEstimatedCost': 223
        }
      ]
    });
    await tester.pumpAndSettle();
    expect(find.text('Budget replanning'), findsOneWidget);
    expect(find.text('Current: RM 360.00'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('Verified lower fare'), findsOneWidget);
    expect(api.postCallCount, 1);
    expect(api.postCalls.where((path) => path.endsWith('/apply')), isEmpty);
  });

  testWidgets(
      'technical flight instructions and navigation are absent from Alternatives',
      (tester) async {
    final api = _FakeAlternativeApi(
        onGet: (_) async => {
              'ok': true,
              'stateVersion': 'revision',
              'budget': {'total': 990, 'limit': 700},
              'budgetReplanOptions': {
                'allowances': {'foodCost': 360, 'transportCost': 105}
              },
              'flightComparison': {
                'status': 'needs_review',
                'reasons': ['Passenger count is missing.']
              }
            },
        onPost: (path, [body]) async => {
              'ok': true,
              'budget': {'total': 990, 'limit': 700},
              'alternatives': [],
              'flightAdvice': 'Comparable fares must retain route and dates.'
            });
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 0,
            food: 360,
            transportation: 105,
            activities: 0,
            flight: 525),
        userBudget: 700,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Search Flights'), findsNothing);
    expect(find.text('Passenger count is missing.'), findsOneWidget);
    expect(find.textContaining('Comparable fares must retain'), findsNothing);
    expect(find.text('Review budget options'), findsOneWidget);
    expect(api.postCalls.where((path) => path.contains('/fr7/')), isEmpty);
  });

  testWidgets(
      'allowance preview cancel confirm and reopen show known-subtotal reductions',
      (tester) async {
    var food = 360;
    var applies = 0;
    final api = _FakeAlternativeApi(
        onGet: (path) async => {
              'ok': true,
              'stateVersion': 'revision',
              'budget': {'total': food + 368, 'limit': 700},
              'budgetReplanOptions': {
                'allowances': {'foodCost': food, 'transportCost': 105}
              }
            },
        onPost: (path, [body]) async {
          if (path.endsWith('/preview'))
            return {
              'before': {'total': 728, 'food': 360, 'transport': 105},
              'budget': {
                'total': 688,
                'food': 320,
                'transport': 105,
                'pendingExpenseCategories': ['hotel', 'activities']
              },
              'estimatedReduction': 40,
              'previewToken': 'confirmed-preview',
              'retainedEstimate': 263
            };
          if (path.endsWith('/apply')) {
            expect(body?['confirmed'], true);
            expect(body?['previewToken'], 'confirmed-preview');
            applies++;
            food = 320;
            return {
              'itinerary': {'id': 'owned'}
            };
          }
          return {'ok': true, 'alternatives': []};
        });
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 0,
            food: 360,
            transportation: 105,
            activities: 0,
            flight: 263),
        userBudget: 700,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    Future<void> open() async {
      final options = find.text('Review budget options');
      await tester.ensureVisible(options);await tester.pump();
      await tester.tap(options);
      await tester.pumpAndSettle();
    }

    await open();
    await tester.enterText(
        find.widgetWithText(TextField, 'Food allowance (MYR)'), '320');
    final preview = find.text('Preview revised budget');
    await tester.ensureVisible(preview);await tester.pump();
    await tester.tap(preview);
    await tester.pumpAndSettle();
    expect(find.text('Previous known estimated subtotal: RM 728.00'),
        findsOneWidget);
    expect(find.text('Proposed known estimated subtotal: RM 688.00'),
        findsOneWidget);
    expect(find.text('Food allowance reduction: RM 40.00'), findsOneWidget);
    expect(find.textContaining('does not establish full-trip affordability'),
        findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(applies, 0);
    expect(food, 360);
    await tester.ensureVisible(preview);await tester.pump();
    await tester.tap(preview);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm budget changes'));
    await tester.pumpAndSettle();
    expect(applies, 1);
    expect(food, 320);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 0,
            food: 320,
            transportation: 105,
            activities: 0,
            flight: 263),
        userBudget: 700,
        tripId: 'owned',
        api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Known estimate: RM 688.00'), findsOneWidget);
    expect(find.text('Review budget options'), findsNothing);
    expect(applies, 1);
  });

  testWidgets(
      'safe budget adjustments remain actionable while provider lookup is delayed',
      (tester) async {
    final pending = Completer<dynamic>();
    final api = _FakeAlternativeApi(
      onGet: (_) async => {
        'ok': true,
        'stateVersion': 'owned-trip-revision',
        'budget': {'total': 900, 'limit': 800},
        'budgetReplanOptions': {
          'allowances': {'foodCost': 200, 'transportCost': 100},
          'optionalVisits': []
        }
      },
      onPost: (path, [body]) => pending.future,
    );
    await tester.pumpWidget(_buildApp(AlternativeScreen(
        budget: BudgetModel(
            accommodation: 300,
            food: 200,
            transportation: 100,
            activities: 300),
        userBudget: 800,
        tripId: 'owned',
        api: api)));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    final review = find.widgetWithText(FilledButton, 'Review budget options');
    await tester.ensureVisible(review);await tester.pump();
    expect(tester.widget<FilledButton>(review).onPressed, isNotNull);
    await tester.tap(review);
    await tester.pumpAndSettle();
    expect(find.text('Budget replanning'), findsOneWidget);
    expect(find.text('Food allowance (MYR)'), findsOneWidget);
    expect(
        api.postCalls, ['/api/fr5/itineraries/owned/lower-cost-alternatives']);
    pending.complete({
      'ok': true,
      'budget': {'total': 1},
      'budgetReplanOptions': {}
    });
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

  testWidgets('Confirms an applicable activity and displays the saved result',
      (tester) async {
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
        return {
          'itinerary': {
            'id': 'trip-123',
            'activities': ['gardens']
          },
          'budget': {'total': 820}
        };
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
    await tester.ensureVisible(find.text('Preview'));await tester.pump();
    await tester.tap(find.text('Preview'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Estimated planning reduction: RM 80.00'),
        findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(applied, isFalse);
    await tester.ensureVisible(find.text('Preview'));await tester.pump();
    await tester.tap(find.text('Preview'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm change'));
    await tester.pumpAndSettle();
    expect(updated?['activities'], ['gardens']);
    expect(find.text('Known estimate: RM 820.00'), findsOneWidget);
    expect(find.text('Preview'), findsNothing);
  });

  testWidgets(
      'planning options outlast failed price searches, navigation and recreation',
      (tester) async {
    var revision = 'r1';
    var priceCalls = 0;
    var failPrices = true;
    final reads = <String>[];
    final api = _FakeAlternativeApi(
      onGet: (path) async {
        reads.add(path);
        return {
          'ok': true,
          'stateVersion': revision,
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
    expect(
        find.text(
            'Replacement prices are unavailable. You can still review available planning changes.'),
        findsOneWidget);

    failPrices = false;
    revision = 'r2';
    await tester.scrollUntilVisible(find.text('Try again'), 200);await tester.pump();
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.text('Review budget options'), findsOneWidget);
    expect(find.textContaining('Earlier options may no longer apply'),
        findsOneWidget);
    expect(find.textContaining('No saved replacement quotes are available to preview.'),
        findsOneWidget);

    await tester.pumpWidget(page('b'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Known estimate: RM 400.00'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    await tester.pumpWidget(page('a'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Known estimate: RM 285.00'), findsOneWidget);
    expect(find.text('Review budget options'), findsOneWidget);
    expect(reads, [
      '/api/fr5/itineraries/a/budget-replan',
      '/api/fr5/itineraries/a/budget-replan',
      '/api/fr5/itineraries/b/budget-replan',
      '/api/fr5/itineraries/a/budget-replan',
    ]);
    expect(priceCalls, 4);
  });

  group('Batch 21E-F2A-U: Budget Alternatives & Activity Advice Presentation',
      () {
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
        find.text(
            'No saved replacement quotes are available to preview. Use the search buttons to check current offers.'),
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

      expect(
          find.text(
              'No saved replacement quotes are available to preview. Use the search buttons to check current offers.'),
          findsOneWidget);
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
      expect(find.widgetWithText(FilledButton, 'Preview'), findsNothing);
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

    testWidgets(
        '6. Other unsupported draft savings represented as non-numeric advice',
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

      expect(find.text('Activity budget guidance'), findsNothing);
      expect(find.text('Consider Lower-Cost Accommodation'), findsOneWidget);
      expect(
          find.text('Explore Free or Lower-Cost Attractions'), findsOneWidget);
      expect(find.text('Use Public Transit or Grouped Rides'), findsOneWidget);

      expect(find.textContaining('Save RM 100'), findsNothing);
      expect(find.textContaining('Save RM 150'), findsNothing);
      expect(find.textContaining('Save RM 80'), findsNothing);
      expect(find.widgetWithText(FilledButton, 'Preview'), findsNothing);
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
              'description':
                  'Replace current flight with AirAsia flight (MYR 120.00).',
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
      expect(find.text('Estimated reduction: RM 30.00'), findsOneWidget);
      expect(find.text('Source: fixture_quote'), findsOneWidget);

      final applyButton = find.widgetWithText(FilledButton, 'Preview');
      expect(applyButton, findsOneWidget);

      await tester.ensureVisible(applyButton);await tester.pump();
    await tester.tap(applyButton);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();

      expect(
          fakeApi.postCalls,
          contains(
              '/api/fr5/itineraries/trip-123/lower-cost-alternatives/apply'));
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
              'description':
                  'Replace current hotel with Neo Hotel Penang (MYR 200.00).',
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
      expect(find.text('Estimated reduction: RM 40.00'), findsOneWidget);
      expect(find.text('Source: liteapi'), findsOneWidget);

      final applyButton = find.widgetWithText(FilledButton, 'Preview');
      expect(applyButton, findsOneWidget);

      await tester.ensureVisible(applyButton);await tester.pump();
    await tester.tap(applyButton);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();

      expect(
          fakeApi.postCalls,
          contains(
              '/api/fr5/itineraries/trip-123/lower-cost-alternatives/apply'));
    });

    testWidgets(
        '9. Server-supplied estimated savings are not presented as guaranteed',
        (tester) async {
      final fakeApi = _FakeAlternativeApi(onPost: (path, [body]) async {
        return {
          'ok': true,
          'budget': {'total': 900.0, 'limit': 800.0},
          'alternatives': [
            {
              'alternativeType': 'flight',
              'title': 'Lower-cost flight',
              'description':
                  'Same route and dates from a verified planning quote.',
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
      expect(find.text('Estimated reduction: RM 45.00'), findsOneWidget);
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
              'error':
                  'No validated priced activity replacement is available. Existing activity prices have not been changed.',
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

      final applyButton = find.widgetWithText(FilledButton, 'Preview');
      await tester.ensureVisible(applyButton);await tester.pump();
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
            {
              'alternativeType': 'activity',
              'title': 'Test Option',
              'estimatedSavings': 15.0,
              'canApply': true,
              'stateVersion': 'expected-revision'
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

      await tester.ensureVisible(find.widgetWithText(FilledButton, 'Preview'));await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Preview'));
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
            {
              'alternativeType': 'activity',
              'title': 'Test Option',
              'estimatedSavings': 15.0,
              'canApply': true,
              'stateVersion': 'expected-revision'
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

      expect(find.text('Known estimate: RM 900.00'), findsOneWidget);

      await tester.ensureVisible(find.widgetWithText(FilledButton, 'Preview'));await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Preview'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm change'));
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(find.text('Known estimate: RM 900.00'), -200);
      await tester.pump();
      // Budget subtitle must remain unchanged
      expect(find.text('Known estimate: RM 900.00'), findsOneWidget);
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
          'activityAdvice':
              'Review admission tickets directly with venue operators.',
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
        findsNothing,
      );
      expect(
          find.text(
              'No saved replacement quotes are available to preview. Use the search buttons to check current offers.'),
          findsOneWidget);
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
              'title':
                  'Switch to Georgetown Heritage Boutique Hotel with Long Title',
              'description':
                  'Replace current hotel with a heritage boutique property in the central historic precinct.',
              'canApply': true,
              'stateVersion': 'expected-revision',
              'estimatedSavings': 85.0,
              'source': 'liteapi_partner_rates',
            }
          ],
          'activityAdvice':
              'Detailed guidance for narrow screen viewports with large accessibility font scaling.',
          'activityAlternativeStatus': 'priced_replacement_unavailable',
        };
      });

      tester.view.physicalSize = const Size(320, 600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
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
      expect(find.text('Activity budget guidance'), findsNothing);
      await tester.scrollUntilVisible(
          find.text('Estimated reduction: RM 85.00'), 200);
      expect(find.text('Estimated reduction: RM 85.00'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Preview'), findsOneWidget);
    });
  });
}
