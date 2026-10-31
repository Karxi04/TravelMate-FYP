import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:travelmate_traveller/core/onboarding/traveller_entry_gate.dart';
import 'package:travelmate_traveller/modules/fr02_travel_preference/preferences_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _EntryApi extends ApiService {
  Map<String, dynamic>? profile;
  Map<String, dynamic>? preferences;
  Object? nextGetFailure;
  Object? nextPutFailure;
  Object? nextPostFailure;
  final calls = <String>[];
  final postBodies = <Map<String, dynamic>>[];
  int meCallCount = 0;
  int profileAvailableOnMeCall = 1;

  _EntryApi({
    this.profile = const {'uid': 'test-traveller', 'role': 'traveller'},
    this.preferences,
    this.profileAvailableOnMeCall = 1,
  });

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    calls.add('GET $path');
    if (nextGetFailure != null && path == '/api/fr2/preferences') {
      final failure = nextGetFailure!;
      nextGetFailure = null;
      throw failure;
    }
    if (path == '/api/fr1/me') {
      meCallCount++;
      if (meCallCount >= profileAvailableOnMeCall) {
        return {'ok': true, 'profile': profile};
      }
      return {'ok': true, 'profile': null};
    }
    if (path == '/api/fr2/preferences') {
      return {'ok': true, 'preferences': preferences};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    calls.add('POST $path');
    if (body != null) postBodies.add(body);
    if (nextPostFailure != null) {
      final failure = nextPostFailure!;
      nextPostFailure = null;
      throw failure;
    }
    if (path == '/api/fr1/profile') {
      profile = {
        'uid': 'test-traveller',
        'role': body?['role'] ?? 'traveller',
        'name': body?['name'] ?? 'Test Traveller',
      };
      return {'ok': true, 'profile': profile};
    }
    throw StateError('Unexpected POST $path');
  }

  @override
  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    calls.add('PUT $path');
    if (nextPutFailure != null) {
      final failure = nextPutFailure!;
      nextPutFailure = null;
      throw failure;
    }
    preferences = body;
    return {'ok': true, 'preferences': body};
  }
}

Widget _gate(
  _EntryApi api, {
  String? candidateName,
  Duration pollDelay = Duration.zero,
}) =>
    MaterialApp(
      home: TravellerEntryGate(
        api: api,
        home: const Scaffold(body: Text('TravelMate Home')),
        candidateName: candidateName,
        pollDelay: pollDelay,
      ),
    );

Future<void> _completeQuestionnaire(WidgetTester tester) async {
  for (var page = 0; page < 5; page++) {
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
  }
  await tester.tap(find.text('Start using TravelMate'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('authenticated existing profile goes directly to Home',
      (tester) async {
    final api = _EntryApi(preferences: {
      'travelType': 'Culture',
      'interests': ['Heritage']
    });

    await tester.pumpWidget(_gate(api));
    await tester.pump();

    expect(find.text('TravelMate Home'), findsOneWidget);
    expect(api.calls, ['GET /api/fr1/me', 'GET /api/fr2/preferences']);
  });

  testWidgets('new traveller saves questionnaire and goes to Home',
      (tester) async {
    final api = _EntryApi();

    await tester.pumpWidget(_gate(api));
    await tester.pump();

    expect(find.byType(PreferencesScreen), findsOneWidget);
    expect(api.calls, ['GET /api/fr1/me', 'GET /api/fr2/preferences']);

    await _completeQuestionnaire(tester);

    expect(api.calls.last, 'PUT /api/fr2/preferences');
    expect(find.text('TravelMate Home'), findsOneWidget);
  });

  testWidgets('profile timeout shows safe error and retry', (tester) async {
    final api = _EntryApi()
      ..nextGetFailure = TimeoutException('Future not completed');

    await tester.pumpWidget(_gate(api));
    await tester.pump();

    expect(find.text(backendConnectionMessage), findsOneWidget);
    expect(find.textContaining('TimeoutException'), findsNothing);
    expect(find.byType(PreferencesScreen), findsNothing);

    await tester.tap(find.text('Retry'));
    await tester.pump();

    expect(find.byType(PreferencesScreen), findsOneWidget);
  });

  testWidgets('unreachable API save can retry and navigate to Home',
      (tester) async {
    final api = _EntryApi()
      ..nextPutFailure = http.ClientException('Connection refused');

    await tester.pumpWidget(_gate(api));
    await tester.pump();
    await _completeQuestionnaire(tester);

    expect(find.text(backendConnectionMessage), findsOneWidget);
    expect(find.textContaining('ClientException'), findsNothing);

    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();

    expect(find.text('TravelMate Home'), findsOneWidget);
    expect(api.calls.where((call) => call.startsWith('PUT ')).length, 2);
  });

  testWidgets('delayed profile readiness resolves via polling and reaches questionnaire',
      (tester) async {
    final api = _EntryApi(
      profile: const {'uid': 'test-traveller', 'role': 'traveller'},
      profileAvailableOnMeCall: 2,
    );

    await tester.pumpWidget(_gate(api));
    await tester.pump();

    expect(find.byType(PreferencesScreen), findsOneWidget);
    expect(api.calls, contains('GET /api/fr1/me'));
    expect(api.meCallCount, 2);
  });

  testWidgets('missing profile self-heals via POST profile and reaches questionnaire',
      (tester) async {
    final api = _EntryApi(
      profile: null,
      profileAvailableOnMeCall: 99,
    );

    await tester.pumpWidget(_gate(api, candidateName: 'Alice'));
    await tester.pump();

    expect(find.byType(PreferencesScreen), findsOneWidget);
    expect(api.calls, contains('POST /api/fr1/profile'));
    expect(api.postBodies.first['name'], 'Alice');
    expect(api.postBodies.first['role'], 'traveller');
  });

  testWidgets('non-traveller role displays rejection error and sign out option',
      (tester) async {
    final api = _EntryApi(
      profile: const {'uid': 'test-operator', 'role': 'operator'},
    );

    await tester.pumpWidget(_gate(api));
    await tester.pump();

    expect(find.text('This account is not a Traveller account.'), findsOneWidget);
    expect(find.text('Back to Sign In'), findsOneWidget);
  });

  testWidgets('error state shows Back to Sign In button', (tester) async {
    final api = _EntryApi()
      ..nextGetFailure = TimeoutException('Timeout');

    await tester.pumpWidget(_gate(api));
    await tester.pump();

    expect(find.text(backendConnectionMessage), findsOneWidget);
    expect(find.text('Back to Sign In'), findsOneWidget);
  });
}
