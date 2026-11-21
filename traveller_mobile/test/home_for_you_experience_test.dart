import 'package:travelmate_traveller/widgets/travel_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/home/home_tab.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/core/navigation/app_shell_navigation.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'fyp_evaluation_journey_test.dart' show evaluationEnvelope;

Map<String, dynamic> _recommendation() => {
      'destinationId': 'kek_lok_si',
      'discoveryEligible': true,
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
  final List<Map<String, dynamic>>? recommendationItems;

  _HomeApi({
    this.failNextRecommendationLoad = false,
    this.recommendationItems,
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
          'recommendationGenerationId': 'rec_hidden_123',
          'stale': staleRecommendations,
          'snapshot': {'requestedDestination': 'Penang'},
          'recommendations':
              emptyQualified ? [] : recommendationItems ?? [_recommendation()],
          'pagination': {'discoveryMode': 'relevant_v1'},
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
        'recommendationGenerationId': 'rec_hidden_123',
        'recommendations': [_recommendation()],
        'pagination': {'discoveryMode': 'relevant_v1'},
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

class _EvidenceHomeApi extends _HomeApi {
  Map updated(Map data) => {...data, 'recommendationGenerationId':'new-evidence-generation',
    'recommendations':[{..._recommendation(),
      'collaborativeRatingCount':0,'collaborativeConfidence':0.0,'rawCollaborativeScore':50.0,
      'popularitySource':'provider_rating_review_count',
      'popularityEvidence':{'source':'provider_rating_review_count','rating':4.5,'reviewCount':9000}}]};
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    final data=await super.get(path,query);
    return path=='/api/fr4/recommendations' && generationCalls>0 ? updated(data as Map):data;
  }
  @override
  Future<dynamic> post(String path,[Map<String,dynamic>? body]) async {
    final data=await super.post(path,body);
    return path=='/api/fr4/recommendations/generate' ? updated(data as Map):data;
  }
}

class _EvaluationHomeApi extends _HomeApi {
  final attached=<Map>[];
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    final data=await super.get(path,query);
    return path=='/api/fr4/recommendations' ? evaluationEnvelope(data as Map):data;
  }
  @override
  Future<dynamic> post(String path,[Map<String,dynamic>? body]) async {
    final data=await super.post(path,body);
    if(path.endsWith('/activities')) attached.add({...?body});
    if(path=='/api/fr4/recommendations/generate') staleRecommendations=false;
    return path=='/api/fr4/recommendations/generate' ? evaluationEnvelope(data as Map):data;
  }
}

Widget _home(_HomeApi api,
    {ValueChanged<AppShellTab>? onSelect, double textScale = 1}) {
  final home = HomeTab(api: api);
  return MaterialApp(
    theme: buildInkWashTheme(),
    builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!),
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
  testWidgets('Home evaluation preference change waits for explicit regeneration',(tester) async {
    final api=_EvaluationHomeApi()..staleRecommendations=true;
    await _settleHome(tester,api);await tester.pumpAndSettle();
    expect(api.generationCalls,0);
    await _showOnHome(tester,find.text(recommendationPreferenceUpdateMessage));
    await tester.tap(find.byKey(const ValueKey('update-recommendation-evidence')));await tester.pumpAndSettle();
    expect(api.generationCalls,1);expect(find.text(recommendationPreferenceUpdateMessage),findsNothing);
    expect(tester.takeException(),isNull);
  });
  testWidgets('integrated Home evaluation retains View and confirmed real destination attachment',(tester) async {
    final api=_EvaluationHomeApi();
    await _settleHome(tester,api);await tester.pumpAndSettle();
    await _showOnHome(tester,find.text('Recommendation data sources'));
    await tester.tap(find.text('Recommendation data sources'));await tester.pumpAndSettle();
    expect(find.text('FYP evaluation configuration'),findsOneWidget);
    await tester.tapAt(const Offset(10,10));await tester.pumpAndSettle();
    await _showOnHome(tester,find.text('View').first);await tester.tap(find.text('View').first);await tester.pumpAndSettle();
    expect(find.byType(DestinationDetailsScreen),findsOneWidget);
    await tester.tap(find.byTooltip('Back'));await tester.pumpAndSettle();
    await _showOnHome(tester,find.text('Add to trip').first);await tester.tap(find.text('Add to trip').first);await tester.pumpAndSettle();
    expect(api.attached,isEmpty); // Destination selection alone does not save anything.
    await tester.tap(find.text('Penang Getaway').last);await tester.pumpAndSettle();
    expect(api.attached.single['destinationId'],'kek_lok_si');
    expect(api.attached.single.keys, isNot(contains('synthetic')));
    expect(api.attached.single.keys, isNot(contains('recommendationEvidenceMode')));
    expect(api.attached.single.keys, isNot(contains('collaborativeScore')));
    expect(api.generationCalls,0);expect(tester.takeException(),isNull);
  });
  testWidgets(
      'carousel lower menu explanation View and Add callbacks remain usable',
      (tester) async {
    var views = 0, adds = 0;
    String? feedback;
    await tester.pumpWidget(MaterialApp(
        theme: buildInkWashTheme(),
        home: Scaffold(
            body: SingleChildScrollView(
                child: SizedBox(
                    width: 280,
                    child: RecommendationCard(
                        carousel: true,
                        discovery: true,
                        recommendation: _recommendation(),
                        onView: () => views++,
                        onAddToTrip: () => adds++,
                        onPreferenceFeedback: (value) => feedback = value))))));
    await tester.pumpAndSettle();
    await tester.ensureVisible(
        find.byKey(const ValueKey('recommendation-feedback-kek_lok_si')));
    await tester
        .tap(find.byKey(const ValueKey('recommendation-feedback-kek_lok_si')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('More like this'));
    await tester.pumpAndSettle();
    expect(feedback, 'more_like_this');
    await tester.ensureVisible(find.text('Why this suggestion'));
    await tester.tap(find.text('Why this suggestion'));
    await tester.pumpAndSettle();
    expect(find.byType(BottomSheet), findsOneWidget);
    Navigator.of(tester.element(find.byType(RecommendationCard))).pop();
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('View'));
    await tester.tap(find.text('View'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Add to trip'));
    await tester.tap(find.text('Add to trip'));
    await tester.pumpAndSettle();
    expect(views, 1);
    expect(adds, 1);
    expect(tester.takeException(), isNull);
  });

  for (final width in [320.0, 360.0, 390.0]) {
    for (final scale in [1.0, 1.8]) {
      testWidgets(
          'Home carousel cards and actions align at width $width scale $scale',
          (tester) async {
        tester.view.physicalSize = Size(width, 1200);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final places = [
          {
            ..._recommendation(),
            'destinationId': 'one',
            'title': 'Short',
            'address': 'Penang',
            'matchReasons': ['One reason'],
            'matchedInterests': [],
            'imageUrl': ''
          },
          {
            ..._recommendation(),
            'destinationId': 'two',
            'title':
                'A much longer Malaysian destination name with several words that cannot fit on one line',
            'address':
                'A very long address in George Town, Penang, Malaysia, with street and locality details',
            'category': 'A long category with detailed cultural information',
            'matchedInterests': ['Photography', 'Food', 'Culture', 'Nature', 'Family',
              'Relaxation', 'History', 'Architecture', 'Outdoor scenery'],
            'matchReasons': [
              'A longer factual reason based on the selected interests and the verified available destination evidence.',
              'Another longer explanation about visiting conditions and travel preferences.'
            ],
            'foodExperienceType': 'food_museum',
            'nearbyDistanceKm': 2.5,
            'city': 'George Town',
            'imageUrl': ''
          },
          {
            ..._recommendation(),
            'destinationId': 'three',
            'title': 'Medium name',
            'address': '',
            'matchReasons': [],
            'imageUrl': ''
          },
        ];
        final api = _HomeApi(recommendationItems: places);
        await tester.pumpWidget(_home(api, textScale: scale));
        await tester.pumpAndSettle();
        for (var step = 0;
            step < 15 && find.byType(RecommendationCard).evaluate().isEmpty;
            step++) {
          await tester.drag(find.byType(ListView).first, const Offset(0, -200));
          await tester.pumpAndSettle();
        }
        expect(find.byType(RecommendationCard), findsNWidgets(3));
        final cards = [
          for (var i = 0; i < 3; i++)
            tester.getRect(find.byType(RecommendationCard).at(i))
        ];
        for (final card in cards.skip(1)) {
          expect(card.height, closeTo(cards.first.height, .1));
          expect(card.top, closeTo(cards.first.top, .1));
        }
        for (final prefix in ['recommendation-view', 'recommendation-add']) {
          final buttons = [
            for (final id in ['one', 'two', 'three'])
              tester.getRect(find.byKey(ValueKey('$prefix-$id')))
          ];
          for (final button in buttons.skip(1))
            expect(button.top, closeTo(buttons.first.top, .1));
        }
        final images = [
          for (var i = 0; i < 3; i++)
            tester.getRect(find.descendant(
                of: find.byType(RecommendationCard).at(i),
                matching: find.byType(TravelPlaceImage)))
        ];
        for (final image in images.skip(1))
          expect(image.height, closeTo(images.first.height, .1));
        expect(
            tester
                .widget<Text>(find.text(places[1]['title'] as String))
                .maxLines,
            isNull);
        expect(
            tester
                .widget<Text>(find.text(places[1]['address'] as String))
                .maxLines,
            isNull);
        for (final id in ['one', 'two', 'three']) {
          final card = find.byKey(ValueKey('recommendation-carousel-$id'));
          final labels =
              tester.getRect(find.byKey(ValueKey('recommendation-labels-$id')));
          final metadata = tester
              .getRect(find.byKey(ValueKey('recommendation-metadata-$id')));
          final title = tester.getRect(
              find.descendant(of: card, matching: find.byType(Text)).first);
          expect(labels.top, greaterThan(title.bottom));
          expect(metadata.top, greaterThanOrEqualTo(labels.bottom));
          final menu = tester
              .getRect(find.byKey(ValueKey('recommendation-feedback-$id')));
          expect(menu.top, greaterThanOrEqualTo(metadata.top));
          expect(title.width,
              closeTo(cards.first.width - AppSpacing.card.horizontal, .1));
        }
        final address =
            tester.getRect(find.text(places[1]['address'] as String));
        expect(
            tester
                .getRect(
                    find.byKey(const ValueKey('recommendation-labels-two')))
                .top,
            greaterThanOrEqualTo(address.bottom));
        expect(tester.takeException(), isNull);
        expect(api.generationCalls, 0);
      });
    }
  }

  testWidgets(
      'stale saved recommendations regenerate in their selected Malaysian scope',
      (tester) async {
    final api = _HomeApi()..staleRecommendations = true;
    await _settleHome(tester, api);
    await tester.pumpAndSettle();
    expect(api.generationCalls, 1);
    expect(api.generatedArea, 'Penang');
  });

  testWidgets('Home explains old evidence without generating until the explicit action', (tester) async {
    final api=_EvidenceHomeApi();
    await _settleHome(tester,api);await tester.pumpAndSettle();
    expect(api.generationCalls,0);
    expect(find.text(recommendationEvidenceUpdateMessage),findsOneWidget);
    final action=find.byKey(const ValueKey('update-recommendation-evidence'));
    await _showOnHome(tester,action);await tester.tap(action);await tester.pumpAndSettle();
    expect(api.generationCalls,1);expect(api.generatedArea,'Penang');
    expect(find.text(recommendationEvidenceUpdateMessage),findsNothing);
    expect(tester.takeException(),isNull);
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
    expect(find.text('Saved destination information'), findsOneWidget);
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

    expect(
        find.text('Something went wrong. Please try again.'), findsOneWidget);
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

  testWidgets(
      'qualified empty snapshot stays empty without repeated generation',
      (tester) async {
    final api = _HomeApi()..emptyQualified = true;
    await _settleHome(tester, api);
    expect(api.generationCalls, 0);
    await _showOnHome(tester, find.text('See all'));
    expect(find.text('No relevant suggestions available yet'), findsOneWidget);
  });
}
