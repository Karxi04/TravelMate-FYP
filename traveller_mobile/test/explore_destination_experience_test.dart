import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/navigation/app_shell_navigation.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/explore_tab.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';

Map<String, dynamic> _place({bool personalized = false}) => {
      'destinationId': 'place_1',
      'title': 'Kek Lok Si Temple',
      'address': 'Air Itam, Penang',
      'category': 'Culture',
      'rating': 4.7,
      'reviews': 128,
      'description': 'A hilltop temple complex with heritage architecture.',
      'estimatedCost': 20,
      'recommendedDurationMinutes': 120,
      'imageUrl': 'http://127.0.0.1:9/place.jpg',
      'searchReason': 'Relevant to Penang culture',
      'source': 'local',
      if (personalized) ...{
        'recommendationGenerationId': 'rec_private_1',
        'matchReasons': [
          'Matches your Culture and Heritage interests',
          'Fits your relaxed travel style',
        ],
        'contentScore': 95,
        'collaborativeScore': 80,
        'popularityScore': 90,
        'finalScore': 91,
      },
    };

class _ExploreApi extends ApiService {
  int searchCalls = 0;
  int favouriteCalls = 0;
  int activityCalls = 0;
  bool failSearchOnce = false;
  bool emptySearch = false;
  bool openingAvailable = true;
  bool detailsFallback = false;
  final List<Map<String, String>> searchQueries = [];
  final Map<String, List<Map<String, dynamic>>> resultsByQuery = {};
  final Map<String, Completer<List<Map<String, dynamic>>>> pendingByQuery = {};
  List<Map<String, dynamic>> trips = [
    {
      'id': 'trip_1',
      'title': 'Penang Trip',
      'destinationArea': 'Penang, Malaysia',
    }
  ];

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr3/destinations/search') {
      searchCalls += 1;
      final params = Map<String, String>.from(query ?? const {});
      searchQueries.add(params);
      if (failSearchOnce) {
        failSearchOnce = false;
        throw Exception('provider stack trace');
      }
      final searchText = params['q'] ?? '';
      final pending = pendingByQuery[searchText];
      final configuredResults = pending == null
          ? resultsByQuery[searchText]
          : await pending.future;
      return {
        'ok': true,
        'results': emptySearch
            ? <dynamic>[]
            : configuredResults ?? [_place()],
        'source': 'local',
        'locationUsed': query?['location'] ?? 'Malaysia',
      };
    }
    if (path == '/api/fr5/itineraries') {
      return {'ok': true, 'items': trips};
    }
    if (path == '/api/fr3/destinations/place_1') {
      return {
        'ok': true,
        'destination': {
          ..._place(),
          if (openingAvailable) 'openingHours': '9:00 AM – 5:30 PM',
        },
        'source': detailsFallback ? 'cache' : 'serpapi',
        if (detailsFallback) 'providerWarning': 'secret provider failure',
      };
    }
    if (path == '/api/fr3/destinations/place_1/ratings-reviews') {
      return {
        'ok': true,
        'source': 'travelmate_database',
        'result': {
          'rating': 4.8,
          'reviews': 1,
          'user_reviews': [
            {
              'username': 'Alya',
              'rating': 5,
              'description': 'Beautiful views and a peaceful visit.',
              'date': '2026-09-30',
            }
          ],
        },
      };
    }
    if (path == '/api/fr3/destinations/place_1/nearby') {
      return {
        'ok': true,
        'items': [
          {
            'destinationId': 'nearby_1',
            'title': 'Penang Hill',
            'address': 'Air Itam, Penang',
            'category': 'Nature',
            'rating': 4.5,
            'distanceKm': 2.1,
            'imageUrl': 'http://127.0.0.1:9/nearby.jpg',
          }
        ],
      };
    }
    if (path == '/api/fr3/destinations/nearby_1') {
      return {
        'ok': true,
        'destination': {
          'destinationId': 'nearby_1',
          'title': 'Penang Hill',
        },
        'source': 'cache',
      };
    }
    if (path.endsWith('/nearby') || path.endsWith('/ratings-reviews')) {
      return {'ok': true, 'items': <dynamic>[], 'result': <String, dynamic>{}};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr3/favourites') {
      favouriteCalls += 1;
      return {'ok': true};
    }
    if (path == '/api/fr5/itineraries/trip_1/activities') {
      activityCalls += 1;
      return {'ok': true};
    }
    throw StateError('Unexpected POST $path');
  }
}

Widget _app(Widget home) => MaterialApp(theme: buildInkWashTheme(), home: home);

Future<void> _pumpExplore(WidgetTester tester, _ExploreApi api) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(_app(ExploreTab(api: api)));
  await tester.pump();
}

Future<void> _pumpDetails(
  WidgetTester tester,
  _ExploreApi api, {
  bool personalized = false,
}) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    _app(
      DestinationDetailsScreen(
        initialDestination: _place(personalized: personalized),
        api: api,
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

Finder _verticalScroll() => find.byWidgetPredicate(
      (widget) =>
          widget is Scrollable && widget.axisDirection == AxisDirection.down,
    );

Future<void> _show(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(
    target,
    300,
    scrollable: _verticalScroll().first,
    maxScrolls: 20,
  );
  await tester.pump();
}

Future<void> _search(WidgetTester tester, String value) async {
  await tester.enterText(find.byType(TextField).first, value);
  await tester.tap(find.byKey(const ValueKey('explore-search-button')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  testWidgets('Explore initial state is useful and does not call search',
      (tester) async {
    final api = _ExploreApi();
    await _pumpExplore(tester, api);

    expect(find.text('Explore Penang'), findsOneWidget);
    expect(find.text('Search places, food, attractions…'), findsOneWidget);
    expect(find.text('Interests'), findsOneWidget);
    expect(find.text('Find somewhere memorable'), findsOneWidget);
    expect(api.searchCalls, 0);
  });

  testWidgets('typing is debounced and stale responses are ignored',
      (tester) async {
    final api = _ExploreApi();
    final first = Completer<List<Map<String, dynamic>>>();
    final second = Completer<List<Map<String, dynamic>>>();
    api.pendingByQuery['first'] = first;
    api.pendingByQuery['second'] = second;
    await _pumpExplore(tester, api);

    await tester.enterText(find.byType(TextField).first, 'first');
    await tester.pump(const Duration(milliseconds: 449));
    expect(api.searchCalls, 0);
    await tester.pump(const Duration(milliseconds: 1));
    expect(api.searchCalls, 1);

    await tester.enterText(find.byType(TextField).first, 'second');
    await tester.pump(const Duration(milliseconds: 450));
    expect(api.searchCalls, 2);

    second.complete([
      {..._place(), 'destinationId': 'second', 'title': 'Second result'}
    ]);
    await tester.pump();
    first.complete([
      {..._place(), 'destinationId': 'first', 'title': 'Stale first result'}
    ]);
    await tester.pumpAndSettle();

    expect(find.text('Second result'), findsWidgets);
    expect(find.text('Stale first result'), findsNothing);
  });

  testWidgets('area results lead to area-focused place discovery',
      (tester) async {
    final api = _ExploreApi();
    api.resultsByQuery['George Town'] = [
      {
        'destinationId': 'area_george_town',
        'title': 'George Town',
        'type': 'City',
        'resultKind': 'area',
      }
    ];
    api.resultsByQuery['places to visit'] = [
      {..._place(), 'title': 'Chew Jetty'}
    ];
    await _pumpExplore(tester, api);
    await _search(tester, 'George Town');

    final areaAction =
        find.byKey(const ValueKey('destination-view-area_george_town'));
    await _show(tester, areaAction);
    await tester.tap(areaAction);
    await tester.pumpAndSettle();

    expect(find.text('Chew Jetty'), findsWidgets);
    expect(api.searchQueries.last['location'], 'George Town');
    expect(api.searchQueries.last['q'], 'places to visit');
  });

  testWidgets('search renders a generic destination card and fallback source',
      (tester) async {
    final api = _ExploreApi();
    await _pumpExplore(tester, api);
    await _search(tester, 'Penang culture');

    expect(api.searchCalls, 1);
    expect(find.text('Kek Lok Si Temple'), findsWidgets);
    expect(find.text('Culture'), findsWidgets);
    expect(find.text('Fallback source'), findsWidgets);
    expect(find.textContaining('% match'), findsNothing);
    expect(find.text('contentScore'), findsNothing);
    expect(find.text('provider stack trace'), findsNothing);
  });

  testWidgets('search has no-results and retryable error states',
      (tester) async {
    final api = _ExploreApi()..emptySearch = true;
    await _pumpExplore(tester, api);
    await _search(tester, 'nothing');
    expect(find.text('No places found'), findsOneWidget);

    api
      ..emptySearch = false
      ..failSearchOnce = true;
    await _search(tester, 'culture');
    expect(find.text('Places couldn’t be loaded'), findsOneWidget);
    expect(find.text('provider stack trace'), findsNothing);
    await tester.tap(find.text('Try again'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Kek Lok Si Temple'), findsWidgets);
  });

  testWidgets('destination card pushes details and back returns to one Explore',
      (tester) async {
    final api = _ExploreApi();
    await _pumpExplore(tester, api);
    await _search(tester, 'temple');
    await _show(tester, find.byKey(const ValueKey('destination-view-place_1')));
    await tester.tap(find.byKey(const ValueKey('destination-view-place_1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.byType(DestinationDetailsScreen), findsOneWidget);
    expect(find.byType(ExploreTab), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(ExploreTab), findsOneWidget);
    expect(find.byType(DestinationDetailsScreen), findsNothing);
  });

  testWidgets('Add to trip reuses the existing trip-selection flow',
      (tester) async {
    final api = _ExploreApi();
    await _pumpExplore(tester, api);
    await _search(tester, 'temple');
    await _show(tester, find.byKey(const ValueKey('destination-add-place_1')));
    await tester.tap(find.byKey(const ValueKey('destination-add-place_1')));
    await tester.pumpAndSettle();
    expect(find.text('Add to a trip'), findsOneWidget);
    await tester.tap(find.text('Penang Trip'));
    await tester.pumpAndSettle();
    expect(api.activityCalls, 1);
  });

  testWidgets('Explore save action preserves favourite persistence',
      (tester) async {
    final api = _ExploreApi();
    await _pumpExplore(tester, api);
    await _search(tester, 'temple');
    await _show(
      tester,
      find.byKey(const ValueKey('destination-save-place_1')),
    );
    await tester.tap(
      find.byKey(const ValueKey('destination-save-place_1')),
    );
    await tester.pumpAndSettle();

    expect(api.favouriteCalls, 1);
    expect(find.byIcon(Icons.favorite_rounded), findsOneWidget);
  });

  testWidgets(
      'details shows hero, factual personalised context and safe source',
      (tester) async {
    final api = _ExploreApi()..detailsFallback = true;
    await _pumpDetails(tester, api, personalized: true);

    expect(find.text('Kek Lok Si Temple'), findsWidgets);
    expect(find.text('Air Itam, Penang'), findsWidgets);
    await _show(tester, find.text('Cached source'));
    expect(find.text('Cached source'), findsOneWidget);
    expect(find.text('Why this fits you'), findsOneWidget);
    expect(find.text('Matches your Culture and Heritage interests'),
        findsOneWidget);
    expect(find.text('contentScore'), findsNothing);
    expect(find.text('95'), findsNothing);
    expect(find.text('secret provider failure'), findsNothing);
  });

  testWidgets('ordinary details do not invent personalised reasons',
      (tester) async {
    await _pumpDetails(tester, _ExploreApi());
    expect(find.text('Why this fits you'), findsNothing);
    expect(find.text('Relevant to Penang culture'), findsNothing);
  });

  testWidgets('visit information, reviews and nearby places remain useful',
      (tester) async {
    final api = _ExploreApi()..openingAvailable = false;
    await _pumpDetails(tester, api);
    expect(find.textContaining('External 4.7'), findsNothing);

    await _show(tester, find.text('Visit information'));
    expect(find.text('Opening hours not available'), findsOneWidget);
    expect(find.text('Check with the attraction before visiting.'),
        findsOneWidget);
    expect(find.text('About 120 minutes'), findsOneWidget);
    expect(find.text('About RM 20'), findsOneWidget);

    await _show(tester, find.text('Reviews'));
    expect(find.text('TravelMate 4.8 out of 5 · 1 review'), findsOneWidget);
    expect(find.text('Alya'), findsOneWidget);
    expect(find.text('Beautiful views and a peaceful visit.'), findsOneWidget);

    await _show(tester, find.text('Nearby places'));
    expect(find.text('Penang Hill'), findsWidgets);
  });

  testWidgets('saving updates the accessible visible state', (tester) async {
    final api = _ExploreApi();
    await _pumpDetails(tester, api);

    await tester.tap(find.byKey(const ValueKey('destination-save')));
    await tester.pumpAndSettle();
    expect(api.favouriteCalls, 1);
    expect(find.text('Saved'), findsOneWidget);
    expect(
      tester.getSemantics(find.byKey(const ValueKey('destination-save'))).label,
      contains('Destination saved'),
    );
  });

  testWidgets('empty-trip action selects the existing Trips root tab',
      (tester) async {
    final api = _ExploreApi()..trips = [];
    AppShellTab? selected;
    await tester.pumpWidget(
      _app(
        AppShellNavigation(
          selectedTab: AppShellTab.explore,
          onSelect: (tab) => selected = tab,
          child: DestinationDetailsScreen(
            initialDestination: _place(),
            api: api,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey('destination-primary-add')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Go to Trips'));
    await tester.pumpAndSettle();

    expect(selected, AppShellTab.trips);
    expect(find.byType(ExploreTab), findsNothing);
  });
}
