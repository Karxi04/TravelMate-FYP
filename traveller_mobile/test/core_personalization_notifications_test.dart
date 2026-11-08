import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/core/utils/traveller_notifications.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/modules/traveller_notifications/notification_center.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_history_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/packing_checklist_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';

class RecsApi extends ApiService {
  double minimum = 70;
  int generations = 0;
  final feedback = <Map>[];
  final reads = <Map>[];
  Completer<dynamic>? heldPage;
  bool failGeneration = false;
  final pool = List.generate(
      40,
      (i) => <String, dynamic>{
            'destinationId': 'fixture_$i',
            'title': 'Fixture place $i',
            'finalScore': 95 - i,
            'destinationConcepts': ['culture'],
            'type': 'Culture'
          });
  Map response(Map options) {
    final page = recommendationPage({
      'recommendationGenerationId': 'generation_$generations',
      'requestedDestination': 'Penang',
      'recommendationResults': pool
    }, options);
    return {
      'ok': true,
      'snapshot': page,
      'recommendations': page['recommendationResults'],
      'recommendationGenerationId': 'generation_$generations',
      'pagination': page['pagination'],
      'source': 'cache'
    };
  }

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr4/settings') return {'minimumMatchScore': minimum};
    if (path == '/api/fr4/recommendations') {
      reads.add({...?query});
      if (heldPage != null && query?['offset'] == '12') return heldPage!.future;
      return response(query ?? {});
    }
    if (path == '/api/fr2/preferences')
      return {
        'preferences': {
          'interests': ['Culture']
        }
      };
    if (path == '/api/fr4/preference-feedback')
      return {
        'learning': {'currentFeedback': {}}
      };
    return {'ok': true, 'items': []};
  }

  @override
  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    minimum = (body!['minimumMatchScore'] as num).toDouble();
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr4/preference-feedback') {
      feedback.add({...body!});
      return {'ok': true};
    }
    if (path == '/api/fr4/recommendations/generate') {
      if (failGeneration) throw StateError('Provider unavailable');
      generations++;
      return response(body ?? {});
    }
    throw StateError(path);
  }
}

class NoticesApi extends ApiService {
  final items = <Map<String, dynamic>>[
    {
      'id': 'event1',
      'category': 'payment',
      'title': 'Payment status updated',
      'message': 'Your recorded payment status is paid.',
      'target': {'screen': 'payments', 'orderId': 'order1'},
      'createdAt': '2026-11-08T10:00:00Z',
      'read': false
    }
  ];
  bool fail = false;
  final updates = <Map>[];
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == notificationPath) {
      if (fail) throw StateError('Retry later');
      return {
        'items': items,
        'unreadCount': items.where((e) => e['read'] != true).length
      };
    }
    return {'ok': true, 'items': []};
  }

  @override
  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) async {
    if (fail) throw StateError('Retry later');
    updates.add({'path': path, ...body!});
    items[0]['read'] = body['read'];
    return {'ok': true};
  }
}

void main() {
  test(
      'filter actual scores before paging, keep global order and reject bad boundaries',
      () {
    final api = RecsApi();
    final first = api.response({'minimumMatchScore': 70});
    final second = api.response({'minimumMatchScore': 70, 'offset': 12});
    expect(first['pagination']['qualifiedCount'], 26);
    expect((first['recommendations'] as List).first['finalScore'], 95);
    final ids = [...first['recommendations'], ...second['recommendations']]
        .map((e) => e['destinationId'])
        .toList();
    expect(ids.toSet().length, 24);
    expect(
        api.response({'minimumMatchScore': 100})['recommendations'], isEmpty);
    expect(() => api.response({'minimumMatchScore': double.nan}),
        throwsArgumentError);
    expect(() => api.response({'offset': -1}), throwsArgumentError);
  });

  testWidgets(
      'threshold slider filters correctly, persists and Load More keeps unique qualified results',
      (tester) async {
    final api = RecsApi();
    await tester.pumpWidget(MaterialApp(
        theme: buildInkWashTheme(), home: RecommendationScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Minimum match: 70/100'), findsOneWidget);
    expect(find.text('Fixture place 0'), findsOneWidget);
    expect(find.text('Fixture place 12'), findsNothing);
    await tester.scrollUntilVisible(find.text('Load more matching places'), 600,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Load more matching places'));
    await tester.pumpAndSettle();
    expect(find.text('Fixture place 12'), findsOneWidget);
    expect(api.reads.last['offset'], '12');
    await tester.scrollUntilVisible(find.byType(Slider), -600,
        scrollable: find.byType(Scrollable).first);
    await tester.drag(find.byType(Slider), const Offset(500, 0));
    await tester.pumpAndSettle();
    expect(api.minimum, 90);
    await tester.scrollUntilVisible(find.text('Minimum match: 90/100'), -400,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('Minimum match: 90/100'), findsOneWidget);
    expect(find.text('Fixture place 10'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(MaterialApp(home: RecommendationScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Minimum match: 90/100'), findsOneWidget);
  });

  testWidgets('old page cannot overwrite a changed threshold', (tester) async {
    final api = RecsApi()..heldPage = Completer();
    await tester.pumpWidget(MaterialApp(home: RecommendationScreen(api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Load more matching places'), 600,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Load more matching places'));
    await tester.pump();
    await tester.scrollUntilVisible(find.byType(Slider), -600,
        scrollable: find.byType(Scrollable).first);
    await tester.drag(find.byType(Slider), const Offset(500, 0));
    await tester.pumpAndSettle();
    api.heldPage!
        .complete(api.response({'minimumMatchScore': 40, 'offset': 12}));
    await tester.pumpAndSettle();
    expect(api.minimum, 90);
    await tester.scrollUntilVisible(find.text('Minimum match: 90/100'), -400,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('Minimum match: 90/100'), findsOneWidget);
    expect(find.text('Fixture place 12'), findsNothing);
  });

  testWidgets(
      'More Like This saves stable identity then generates a fresh ranked list',
      (tester) async {
    final api = RecsApi();
    await tester.pumpWidget(MaterialApp(home: RecommendationScreen(api: api)));
    await tester.pumpAndSettle();
    final action =
        find.byKey(const ValueKey('recommendation-feedback-fixture_0'));
    await tester.scrollUntilVisible(action.hitTestable(), 400,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(action);
    await tester.pumpAndSettle();
    await tester.tap(find.text('More like this'));
    await tester.pumpAndSettle();
    expect(api.feedback.single['destinationId'], 'fixture_0');
    expect(api.feedback.single['recommendationGenerationId'], 'generation_0');
    expect(api.generations, 1);
  });

  testWidgets('provider refresh failure retains the loaded qualified places',
      (tester) async {
    final api = RecsApi()..failGeneration = true;
    await tester.pumpWidget(MaterialApp(home: RecommendationScreen(api: api)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
        find.text('Refresh for you').hitTestable(), 200,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Refresh for you'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Provider unavailable'), findsOneWidget);
    expect(find.text('Fixture place 0'), findsOneWidget);
    expect(api.generations, 0);
  });

  test('notification targets keep the exact existing route and stable ID', () {
    final api = NoticesApi();
    expect(notificationDestination({'screen': 'payments', 'orderId': 'o'}, api),
        isA<PaymentHistoryScreen>());
    expect(
        (notificationDestination({'screen': 'trip', 'tripId': 't1'}, api)
                as TripDetailsScreen)
            .tripId,
        't1');
    expect(
        (notificationDestination(
                    {'screen': 'package_trip', 'tripId': 'p1'}, api)
                as PackageTripDetailsScreen)
            .tripId,
        'p1');
    expect(
        (notificationDestination({'screen': 'packing', 'tripId': 't2'}, api)
                as PackingChecklistScreen)
            .tripId,
        't2');
    expect(
        notificationDestination(
            {'screen': 'https://external', 'tripId': 'x'}, api),
        isNull);
    expect(notificationDestination({'screen': 'trip', 'tripId': 'bad/id'}, api),
        isNull);
  });

  testWidgets(
      'bell opens center, read/unread changes persist, tap opens payment history',
      (tester) async {
    final api = NoticesApi();
    await tester.pumpWidget(MaterialApp(
        theme: buildInkWashTheme(),
        home: Scaffold(body: NotificationBell(api: api))));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Notifications, 1 unread'));
    await tester.pumpAndSettle();
    expect(find.text('Payment status updated'), findsOneWidget);
    await tester.tap(find.byTooltip('Mark read'));
    await tester.pumpAndSettle();
    expect(api.items.single['read'], true);
    await tester.tap(find.byTooltip('Mark unread'));
    await tester.pumpAndSettle();
    expect(api.items.single['read'], false);
    await tester.tap(find.text('Payment status updated'));
    await tester.pumpAndSettle();
    expect(find.byType(PaymentHistoryScreen), findsOneWidget);
    expect(api.updates.last['path'], '$notificationPath/event1');
  });

  testWidgets(
      'notification refresh errors retry without inventing an empty success',
      (tester) async {
    final api = NoticesApi()..fail = true;
    await tester
        .pumpWidget(MaterialApp(home: NotificationCenterScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('Retry later'), findsOneWidget);
    api.fail = false;
    await tester.tap(find.text('Try again'));
    await tester.pumpAndSettle();
    expect(find.text('Payment status updated'), findsOneWidget);
  });

  test('local dates, real forecast concerns, cancellation and user isolation',
      () {
    final now = DateTime.utc(2026, 11, 8, 15);
    final trip = <String, dynamic>{
      'id': 't',
      'travellerId': 'a',
      'title': 'Penang',
      'startDate': '2026-11-11'
    };
    final weather = <String, Map<String, dynamic>>{
      't': {
        'daily': {
          'time': ['2026-11-11'],
          'weather_code': [95],
          'precipitation_probability_max': [90]
        }
      }
    };
    final events = localTripNotifications('a', [trip], weather, now);
    expect(
        events.map((e) => e['category']).toSet(), {'upcoming_trip', 'weather'});
    expect(localTripNotifications('b', [trip], weather, now), isEmpty);
    expect(
        localTripNotifications(
            'a',
            [
              {...trip, 'status': 'cancelled'}
            ],
            weather,
            now),
        isEmpty);
    expect(
        localTripNotifications(
            'a',
            [
              {...trip, 'startDate': '2026-02-30'}
            ],
            weather,
            now),
        isEmpty);
    expect(
        localTripNotifications('a', [trip], {}, now).map((e) => e['category']),
        ['upcoming_trip']);
    expect(
        localTripNotifications(
            'a',
            [
              {...trip, 'endDate': '2026-11-10'}
            ],
            weather,
            now),
        isEmpty);
    expect(
        localTripNotifications('a', [trip], {}, DateTime.utc(2026, 11, 8, 16)),
        isEmpty);
    final later = localTripNotifications(
        'a',
        [
          {...trip, 'endDate': '2026-11-13'}
        ],
        {
          't': {
            'daily': {
              'time': ['2026-11-12'],
              'weather_code': [95]
            }
          }
        },
        now);
    expect(
        later.any((e) =>
            e['category'] == 'weather' && e['message'].contains('2026-11-12')),
        true);
  });

  test(
      'standalone notifications deduplicate and persist read state per account',
      () async {
    final now = DateTime.now().toUtc().add(const Duration(hours: 8, days: 3));
    final start = now.toIso8601String().substring(0, 10);
    final memory = <String, String>{
      'travelmate_a_itineraries': jsonEncode([
        {'id': 't', 'travellerId': 'a', 'startDate': start}
      ])
    };
    final api = StandaloneApiService(uidOverride: 'a', memoryStore: memory);
    final first = await api.get(notificationPath);
    expect(first['items'].length, 1);
    final id = first['items'][0]['id'];
    await api
        .put('$notificationPath/${Uri.encodeComponent(id)}', {'read': true});
    expect((await api.get(notificationPath))['unreadCount'], 0);
    final other = StandaloneApiService(uidOverride: 'b', memoryStore: memory);
    expect((await other.get(notificationPath))['items'], isEmpty);
    expect(
        () => other.put(
            '$notificationPath/${Uri.encodeComponent(id)}', {'read': true}),
        throwsStateError);
  });

  test('standalone concurrent feedback is serialized, repeat-safe and isolated',
      () async {
    final memory = <String, String>{};
    final a = StandaloneApiService(uidOverride: 'owner', memoryStore: memory);
    final b = StandaloneApiService(uidOverride: 'owner', memoryStore: memory);
    await Future.wait([
      a.post('/api/fr4/preference-feedback', {
        'destinationId': 'museum',
        'destinationConcepts': ['culture'],
        'feedbackType': 'more_like_this'
      }),
      b.post('/api/fr4/preference-feedback', {
        'destinationId': 'cafe',
        'destinationConcepts': ['food'],
        'feedbackType': 'more_like_this'
      }),
    ]);
    final profile =
        jsonDecode(memory['travelmate_owner_learned_preference_profile']!);
    expect(profile['affinities'], {'culture': .15, 'food': .15});
    final repeated = await a.post('/api/fr4/preference-feedback', {
      'destinationId': 'museum',
      'destinationConcepts': ['culture'],
      'feedbackType': 'more_like_this'
    });
    expect(repeated['changed'], false);
    await a.post('/api/fr4/preference-feedback', {
      'destinationId': 'unknown',
      'destinationConcepts': [],
      'feedbackType': 'not_for_me'
    });
    expect(
        jsonDecode(memory['travelmate_owner_learned_preference_profile']!)[
            'affinities'],
        {'culture': .15, 'food': .15});
    final other =
        StandaloneApiService(uidOverride: 'other', memoryStore: memory);
    expect(
        (await other.get('/api/fr4/preference-feedback'))['learning']
            ['currentFeedback'],
        isEmpty);
    await a.delete('/api/fr4/preference-feedback');
    expect(
        (await a.get('/api/fr4/preference-feedback'))['learning']
            ['currentFeedback'],
        isEmpty);
  });

  test(
      'standalone feedback invalidates snapshots and regeneration excludes the selected ID',
      () async {
    final base = <String, dynamic>{
      'travellerId': 'owner',
      'interests': ['Culture'],
      'preferenceProfileVersion': 'v1'
    };
    final memory = <String, String>{
      'travelmate_owner_preferences': jsonEncode(base)
    };
    final api = StandaloneApiService(uidOverride: 'owner', memoryStore: memory);
    final first = await api.post('/api/fr4/recommendations/generate',
        {'destinationArea': 'Penang', 'limit': 50});
    final item = first['recommendations'][0];
    final id = item['destinationId'];
    await api.post('/api/fr4/preference-feedback', {
      'destinationId': id,
      'recommendationGenerationId': first['recommendationGenerationId'],
      'feedbackType': 'not_for_me'
    });
    final stale = await api.get('/api/fr4/recommendations');
    expect(stale['stale'], true);
    expect(stale['recommendations'], isEmpty);
    final next = await api.post('/api/fr4/recommendations/generate',
        {'destinationArea': 'Penang', 'limit': 50});
    expect(
        (next['recommendations'] as List)
            .any((row) => row['destinationId'] == id),
        false);
    expect((await api.get('/api/fr2/preferences'))['preferences'], base);
  });

  test(
      'standalone reuses genuine-search cache identities without duplicates or foreign places',
      () async {
    final cached = {
      'destinationId': 'osm_fixture_1',
      'title': 'Isolated cached park',
      'type': 'Nature park',
      'address': 'Penang, Malaysia',
      'source': 'openstreetmap',
      'rating': null
    };
    final memory = <String, String>{
      'travelmate_owner_preferences': jsonEncode({
        'interests': ['Nature'],
        'travelType': 'Nature'
      }),
      'travelmate_owner_last_search_results': jsonEncode([
        cached,
        cached,
        {
          ...cached,
          'destinationId': 'outside',
          'address': 'Kuala Lumpur, Malaysia'
        }
      ]),
    };
    final api = StandaloneApiService(uidOverride: 'owner', memoryStore: memory);
    final result = await api.post('/api/fr4/recommendations/generate',
        {'destinationArea': 'Penang', 'limit': 50});
    final items = result['recommendations'] as List;
    expect(
        items.where((item) => item['destinationId'] == 'osm_fixture_1').length,
        1);
    expect(items.any((item) => item['destinationId'] == 'outside'), false);
    expect(result['source'], 'cache');
  });

  test(
      'three standalone profiles influence real chat selection without overwriting saved answers',
      () async {
    final fixture = jsonDecode(
        File('../backend_api/tests/fixtures/penang_core_demo.json')
            .readAsStringSync()) as Map;
    final memory = <String, String>{};
    final selections = <String>{};
    final year = DateTime.now().year + 1;
    for (final entry in (fixture['profiles'] as Map).entries) {
      final uid = '${entry.value['travellerId']}';
      memory['travelmate_${uid}_preferences'] = jsonEncode(entry.value);
      final api = StandaloneApiService(uidOverride: uid, memoryStore: memory);
      final first = await api.post('/api/fr11/chat', {
        'message': 'Plan a 3-day Penang trip with a budget of RM600.',
        'guidedPlanning': true
      });
      final sid = first['session']['id'];
      final second = await api.post('/api/fr11/chat', {
        'sessionId': sid,
        'message': '12 June $year to 14 June $year, 1 traveller.',
        'guidedPlanning': true
      });
      final plan = second['tripPlan'] ?? second['item']['tripPlan'];
      expect(plan, isNotNull);
      expect(plan['tripDays'], 3);
      expect(plan['budgetLimit'], 600);
      expect((plan['activities'] as List).map((a) => a['dayNo']).toSet(),
          {1, 2, 3});
      selections.add((plan['activities'] as List)
          .map((a) => a['destinationId'])
          .join('|'));
      final temporary = await api.post('/api/fr11/chat', {
        'sessionId': sid,
        'message':
            'I prefer nature instead of shopping. I want a relaxing trip and affordable attractions.'
      });
      final state = temporary['session']['planningState'];
      expect(state['excludedInterests'], contains('Shopping'));
      expect(state['pace'], 'Relaxed');
      expect(state['budgetRange'], 'Budget');
      final narrow = await api.post('/api/fr11/chat',
          {'sessionId': sid, 'message': 'I prefer culture, no museums.'});
      expect(narrow['session']['planningState']['excludedActivityTypes'],
          contains('Museum'));
      expect(narrow['session']['planningState']['excludedInterests'],
          isNot(contains('History')));
      expect(
          (await api.get('/api/fr2/preferences'))['preferences'], entry.value);
    }
    expect(selections.length, 3);
  });
}
