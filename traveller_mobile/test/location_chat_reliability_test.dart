import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/malaysian_locations.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/services/transaction_request.dart';
import 'chat_action_audit_test.dart' show ActionApi, frame, tap, copy;
import 'core_personalization_notifications_test.dart' show RecsApi;

final areas = <Map<String, dynamic>>[
  {
    'canonicalName': 'Malaysia',
    'scopeKey': 'my',
    'kind': 'country',
    'aliases': ['my']
  },
  {
    'canonicalName': 'Penang, Malaysia',
    'scopeKey': 'my:penang',
    'state': 'Penang',
    'kind': 'state',
    'aliases': ['pulau pinang']
  },
  for (final city in ['George Town', 'Butterworth', 'Bukit Mertajam'])
    {
      'canonicalName': '$city, Penang, Malaysia',
      'scopeKey': 'my:penang:${city.toLowerCase().replaceAll(' ', '_')}',
      'state': 'Penang',
      'city': city,
      'aliases': city == 'George Town' ? ['georgetown'] : []
    },
  {
    'canonicalName': 'Bukit Bintang, Kuala Lumpur, Malaysia',
    'scopeKey': 'my:kuala_lumpur:bukit_bintang',
    'state': 'Kuala Lumpur',
    'city': 'Bukit Bintang'
  },
  {
    'canonicalName': 'Langkawi, Kedah, Malaysia',
    'state': 'Kedah',
    'city': 'Langkawi'
  },
  {
    'canonicalName': 'Kota Kinabalu, Sabah, Malaysia',
    'state': 'Sabah',
    'city': 'Kota Kinabalu'
  },
];

class LocationApi extends RecsApi {
  int catalogueReads = 0;
  final generatedBodies = <Map<String, dynamic>>[];
  Completer<dynamic>? gate;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr4/locations') {
      catalogueReads++;
      return {'locations': areas};
    }
    return super.get(path, query);
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr4/recommendations/generate') {
      generatedBodies.add(copy(body!));
      if (gate != null) return gate!.future;
    }
    return super.post(path, body);
  }
}

class DeliveryApi extends ActionApi {
  int sends = 0, checks = 0;
  bool completed = false, failCheck = false;
  String? identity;
  DeliveryApi() {
    sessions = [
      {
        'id': 'owned',
        'title': 'Existing conversation',
        'planningState': {},
        'messages': []
      }
    ];
  }
  Map<String, dynamic> receipt() => {
        'id': 'receipt',
        'clientRequestId': identity,
        'message': 'Recommend 3 nature places in Penang',
        'reply': 'The authoritative late reply',
      };
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr11/chat') {
      sends++;
      identity = body!['clientRequestId'] as String?;
      throw TimeoutException('Synthetic ambiguous transport deadline');
    }
    return super.post(path, body);
  }

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path.startsWith('/api/fr11/chat-requests/')) {
      checks++;
      if (failCheck) throw TimeoutException('Synthetic read unavailable');
      if (completed)
        sessions.firstWhere((s) => s['id'] == 'owned')['messages'] = [
          receipt()
        ];
      return {
        'ok': true,
        'status': completed ? 'completed' : 'pending',
        'session': copy(sessions.firstWhere((s) => s['id'] == 'owned'))
      };
    }
    return super.get(path, query);
  }
}

void main() {
  for (final query in [
    'bukit',
    'PEN',
    'george',
    'butter',
    'lang',
    'kota',
    'bukit mer',
    'pulau pinang'
  ]) {
    test('local autocomplete matches $query without provider data', () {
      final matches = matchingMalaysianLocations(areas, query);
      expect(matches, isNotEmpty);
      expect(matches.map((r) => r['canonicalName']).toSet().length,
          matches.length);
      if (query == 'bukit') expect(matches, hasLength(2));
      if (query == 'PEN') expect(matches.first['state'], 'Penang');
      if (query == 'bukit mer')
        expect(matches.single['city'], 'Bukit Mertajam');
    });
  }
  test('empty, unknown and attraction inputs are not destination areas', () {
    expect(matchingMalaysianLocations(areas, ''), isEmpty);
    expect(matchingMalaysianLocations(areas, 'unrecognised area'), isEmpty);
    expect(matchingMalaysianLocations(areas, 'Kek Lok Si Temple'), isEmpty);
  });
  testWidgets(
      'typing is local; a suggestion and keyboard submission use its canonical scope',
      (tester) async {
    final api = LocationApi();
    await frame(tester, RecommendationScreen(api: api));
    await tester.enterText(find.byType(TextField).first, 'buk');
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'bukit');
    await tester.pumpAndSettle();
    expect(api.catalogueReads, 1);
    expect(api.generatedBodies, isEmpty);
    await tester.tap(find.text('Bukit Mertajam, Penang, Malaysia'));
    await tester.pumpAndSettle();
    expect(api.generatedBodies, isEmpty);
    expect(
        tester.widget<TextField>(find.byType(TextField).first).controller!.text,
        'Bukit Mertajam, Penang, Malaysia');
    await tester.showKeyboard(find.byType(TextField).first);
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();
    expect(api.generatedBodies.single['destinationScopeKey'],
        'my:penang:bukit_mertajam');
  });
  testWidgets(
      'changing area cannot unlock a second generation or accept its late old response',
      (tester) async {
    final api = LocationApi();
    await frame(tester, RecommendationScreen(api: api));
    await tester.enterText(find.byType(TextField).first, 'Malaysia');
    api.gate = Completer<dynamic>();
    dynamic state = tester.state(find.byType(RecommendationScreen));
    final pending = state.generate() as Future<void>;
    await tester.pump();
    await tester.enterText(find.byType(TextField).first, 'Penang, Malaysia');
    await tester.pump();
    await state.generate();
    expect(api.generatedBodies, hasLength(1));
    final old = api.response(
        {'destinationArea': 'Malaysia', 'discoveryMode': 'relevant_v1'});
    api.gate!.complete(old);
    await pending;
    await tester.pumpAndSettle();
    expect(state.items, isEmpty);
    expect(state.destination.text, 'Penang, Malaysia');
    expect(state.busy, isFalse);
    api.gate = null;
    await state.generate();
    await tester.pumpAndSettle();
    expect(api.generatedBodies, hasLength(2));
    expect(api.generatedBodies.last['destinationArea'], 'Penang, Malaysia');
  });
  testWidgets(
      'unknown chat delivery checks history instead of retrying or saving',
      (tester) async {
    final api = DeliveryApi();
    await frame(tester, ChatTab(api: api));
    await tester.enterText(
        find.byType(TextField).last, 'Recommend 3 nature places in Penang');
    await tap(tester, find.byIcon(Icons.arrow_upward_rounded));
    expect(api.identity, matches(RegExp(r'^chat_[a-f0-9]{36}$')));
    expect(api.sends, 1);
    expect(api.checks, 1);
    expect(find.text('Delivery unconfirmed'), findsOneWidget);
    expect(find.text('Retry message'), findsNothing);
    expect(
        tester.widget<TextField>(find.byType(TextField).last).enabled, isFalse);
    dynamic state = tester.state(find.byType(ChatTab));
    await state.send('Recommend 3 nature places in Penang');
    expect(api.sends, 1);
    api.completed = true;
    await tap(tester, find.text('Check conversation'));
    expect(api.sends, 1);
    expect(api.checks, 2);
    expect(find.text('The authoritative late reply'), findsOneWidget);
    expect(find.text('Delivery unconfirmed'), findsNothing);
    expect(
        tester.widget<TextField>(find.byType(TextField).last).enabled, isTrue);
    expect(
        api.posts.where((p) => '${p['path']}'.endsWith('/save-plan')), isEmpty);
  });
  testWidgets('unavailable reconciliation never enables a blind duplicate send',
      (tester) async {
    final api = DeliveryApi()..failCheck = true;
    await frame(tester, ChatTab(api: api));
    await tester.enterText(
        find.byType(TextField).last, 'Recommend 3 nature places in Penang');
    await tap(tester, find.byIcon(Icons.arrow_upward_rounded));
    await tap(tester, find.text('Check conversation'));
    expect(api.sends, 1);
    expect(api.checks, 2);
    expect(find.text('Delivery unconfirmed'), findsOneWidget);
  });
  test('FR11 has its own bounded deadline; other paths stay unchanged', () {
    expect(RequestTimeouts.forPost('/api/fr11/chat'),
        const Duration(seconds: 120));
    expect(RequestTimeouts.forPost('/api/fr4/recommendations/generate'),
        const Duration(seconds: 150));
    expect(RequestTimeouts.forPost('/api/fr11/save-plan'),
        RequestTimeouts.ordinaryWrite);
    expect(RequestTimeouts.forPost('/api/fr9/checkout/session'),
        RequestTimeouts.providerMutation);
  });
}
