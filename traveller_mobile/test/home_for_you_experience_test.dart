import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/home/home_tab.dart';
import 'package:travelmate_traveller/core/navigation/app_shell_navigation.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';

Map<String, dynamic> _recommendation() => {
      'destinationId': 'kek_lok_si',
      'discoveryEligible':true,
      'title': 'Kek Lok Si Temple',
      'address': 'Air Itam, Penang',
      'category': 'Culture',
      'rating': 4.7,
      'finalScore': 92,
      'contentScore': 95,
      'collaborativeScore': 82,
      'popularityScore': 90,
      'recommendationGenerationId': 'rec_hidden_123',
      'matchReasons': [
        'Matches your Culture interests',
        'Fits your relaxed travel pace',
      ],
      'recommendationSource': 'fallback',
      'imageUrl': 'http://127.0.0.1:9/kek-lok-si.jpg',
    };

Map<String, dynamic> _trip() => {
      'id': 'trip_home_123',
      'title': 'Penang Getaway',
      'destinationArea': 'Penang, Malaysia',
      'status': 'planned',
      'tripDays': 3,
      'activities': [
        {'activityId': 'a1'},
        {'activityId': 'a2'},
      ],
      'budgetLimit': 1000,
      'budgetEstimate': {'total': 720, 'limit': 1000},
    };

class _HomeApi extends ApiService {
  bool failNextRecommendationLoad;
  int generationCalls = 0;
  int addedActivities = 0;
  bool emptyQualified = false;
  bool staleRecommendations = false;
  String? generatedArea;
  final List<Map<String, dynamic>> tripItems;

  _HomeApi({
    this.failNextRecommendationLoad = false,
    List<Map<String, dynamic>>? trips,
  }) : tripItems = trips ?? [_trip()];

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    switch (path) {
      case '/api/fr1/me':
        return {
          'ok': true,
          'profile': {'name': 'Alya Traveller'}
        };
      case '/api/fr2/preferences':
        return {
          'ok': true,
          'preferences': {
            'travelPersonality': 'Explorer',
            'travelType': 'Culture',
            'travelPace': 'Relaxed',
            'interests': ['Food', 'Culture'],
          },
        };
      case '/api/fr5/itineraries':
        return {'ok': true, 'items': tripItems};
      case '/api/fr4/recommendations':
        if (failNextRecommendationLoad) {
          failNextRecommendationLoad = false;
          throw Exception('Recommendation service unavailable');
        }
        return {
          'ok': true,
          'recommendationGenerationId':'rec_hidden_123',
          'stale':staleRecommendations,
          'snapshot':{'requestedDestination':'Penang'},
          'recommendations': emptyQualified ? [] : [_recommendation()],
          'pagination':{'discoveryMode':'relevant_v1'},
          'source': 'fallback',
        };
      case '/api/public/tourism-packages':
      case '/api/public/promotional-campaigns':
        return {'ok': true, 'items': <dynamic>[]};
    }
    if (path == '/api/fr3/destinations/kek_lok_si') {
      return {'ok': true, 'destination': _recommendation(), 'source': 'cache'};
    }
    if (path.endsWith('/ratings-reviews')) {
      return {'ok': true, 'result': <String, dynamic>{}, 'source': 'cache'};
    }
    if (path.endsWith('/nearby')) {
      return {'ok': true, 'items': <dynamic>[]};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr4/recommendations/generate') {
      generationCalls += 1;
      generatedArea = body?['destinationArea'];
      return {
        'ok': true,
        'recommendationGenerationId':'rec_hidden_123',
        'recommendations': [_recommendation()],
        'pagination':{'discoveryMode':'relevant_v1'},
        'source': 'fallback',
      };
    }
    if (path.endsWith('/activities')) {
      addedActivities += 1;
      return {'ok': true};
    }
    throw StateError('Unexpected POST $path');
  }
}

Widget _home(_HomeApi api, {ValueChanged<AppShellTab>? onSelect}) {
  final home = HomeTab(api: api);
  return MaterialApp(
    theme: buildInkWashTheme(),
    home: onSelect == null
        ? home
        : AppShellNavigation(
            selectedTab: AppShellTab.home,
            onSelect: onSelect,
            child: home,
          ),
  );
}

Future<void> _settleHome(WidgetTester tester, _HomeApi api,
    {ValueChanged<AppShellTab>? onSelect}) async {
  await tester.pumpWidget(_home(api, onSelect: onSelect));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

Finder _verticalHomeScroll() => find.byWidgetPredicate(
      (widget) =>
          widget is Scrollable && widget.axisDirection == AxisDirection.down,
    );

Future<void> _showOnHome(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(
    target,
    300,
    scrollable: _verticalHomeScroll().first,
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('stale saved recommendations regenerate in their selected Malaysian scope', (tester) async {
    final api = _HomeApi()..staleRecommendations = true;
    await _settleHome(tester, api);
    await tester.pumpAndSettle();
    expect(api.generationCalls, 1);
    expect(api.generatedArea, 'Penang');
  });

  testWidgets('recommendation card shows match and factual reasons only',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildInkWashTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: SizedBox(
              width: 360,
              child: RecommendationCard(
                recommendation: _recommendation(),
                source: 'fallback',
                onView: () {},
                onAddToTrip: () {},
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Recommendation score: 92/100'), findsOneWidget);
    expect(find.textContaining('% match'), findsNothing);
    expect(find.text('Matches your Culture interests'), findsOneWidget);
    expect(find.text('Fits your relaxed travel pace'), findsOneWidget);
    expect(find.text('Fallback source'), findsOneWidget);
    expect(find.text('contentScore'), findsNothing);
    expect(find.text('collaborativeScore'), findsNothing);
    expect(find.text('popularityScore'), findsNothing);
    expect(find.text('rec_hidden_123'), findsNothing);
    expect(find.textContaining('Content 60%'), findsNothing);
  });

  testWidgets('Home renders profile, recommendations and continuation',
      (tester) async {
    final api = _HomeApi();
    await _settleHome(tester, api);

    expect(find.textContaining('Alya'), findsOneWidget);
    expect(find.text('Your travel style'), findsOneWidget);
    expect(find.text('Explorer'), findsOneWidget);
    expect(find.text('Plan a trip'), findsOneWidget);
    expect(find.text('For you'), findsOneWidget);
    expect(find.text('Kek Lok Si Temple'), findsOneWidget);

    await _showOnHome(tester, find.text('Penang Getaway'));
    expect(find.text('Penang Getaway'), findsOneWidget);
    expect(api.generationCalls, 0,
        reason: 'Home must reuse the existing snapshot on initial load.');
  });

  testWidgets('Plan a trip opens the existing personalised planning flow',
      (tester) async {
    final api = _HomeApi();
    await _settleHome(tester, api);

    await tester.tap(find.text('Plan a trip'));
    await tester.pumpAndSettle();

    expect(find.byType(PersonalizedPlanningScreen), findsOneWidget);
  });

  testWidgets('View opens destination details', (tester) async {
    final api = _HomeApi();
    await _settleHome(tester, api);
    await _showOnHome(tester, find.text('View').first);

    await tester
        .tap(find.byKey(const ValueKey('recommendation-view-kek_lok_si')));
    await tester.pumpAndSettle();

    expect(find.byType(DestinationDetailsScreen), findsOneWidget);
  });

  testWidgets('Add to trip retains the existing activity action',
      (tester) async {
    final api = _HomeApi();
    await _settleHome(tester, api);
    await _showOnHome(tester, find.text('Add to trip').first);

    await tester
        .tap(find.byKey(const ValueKey('recommendation-add-kek_lok_si')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Penang Getaway').last);
    await tester.pumpAndSettle();

    expect(api.addedActivities, 1);
  });

  testWidgets('recommendation error offers a working retry', (tester) async {
    final api = _HomeApi(failNextRecommendationLoad: true);
    await _settleHome(tester, api);
    await _showOnHome(tester, find.text('Try again'));

    expect(find.text('Something went wrong. Please try again.'), findsOneWidget);
    await tester.tap(find.text('Try again'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(api.generationCalls, 1);
    expect(find.text('Kek Lok Si Temple'), findsOneWidget);
  });

  testWidgets('Continue planning opens the exact existing trip',
      (tester) async {
    final api = _HomeApi();
    await _settleHome(tester, api);
    await _showOnHome(tester, find.text('Penang Getaway'));

    await tester.tap(find.byKey(const ValueKey('continue-trip-trip_home_123')));
    await tester.pumpAndSettle();

    final details = tester.widget<TripDetailsScreen>(
      find.byType(TripDetailsScreen),
    );
    expect(details.tripId, 'trip_home_123');
  });

  testWidgets('All trips selects the existing root tab', (tester) async {
    final api = _HomeApi();
    AppShellTab? selected;
    await _settleHome(tester, api, onSelect: (tab) => selected = tab);
    await _showOnHome(tester, find.text('All trips'));

    await tester.tap(find.text('All trips'));
    await tester.pump();

    expect(selected, AppShellTab.trips);
    expect(find.byType(HomeTab), findsOneWidget);
  });

  testWidgets('qualified empty snapshot stays empty without repeated generation',(tester) async {
    final api=_HomeApi()..emptyQualified=true;
    await _settleHome(tester,api);
    expect(api.generationCalls,0);
    await _showOnHome(tester,find.text('See all'));
    expect(find.text('No relevant suggestions available yet'),findsOneWidget);
  });
}
