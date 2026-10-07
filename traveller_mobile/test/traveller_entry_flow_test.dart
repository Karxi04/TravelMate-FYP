import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:travelmate_traveller/core/onboarding/traveller_entry_gate.dart';
import 'package:travelmate_traveller/modules/fr02_travel_preference/preferences_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _EntryApi extends ApiService {
  Map<String, dynamic>? preferences;
  Object? nextGetFailure;
  Object? nextPutFailure;
  final calls = <String>[];

  _EntryApi({this.preferences});

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    calls.add('GET $path');
    if (nextGetFailure != null && path == '/api/fr2/preferences') {
      final failure = nextGetFailure!;
      nextGetFailure = null;
      throw failure;
    }
    if (path == '/api/fr1/me') {
      return {
        'ok': true,
        'profile': {'uid': 'test-traveller', 'role': 'traveller'}
      };
    }
    if (path == '/api/fr2/preferences') {
      return {'ok': true, 'preferences': preferences};
    }
    throw StateError('Unexpected GET $path');
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

Widget _gate(_EntryApi api) => MaterialApp(
      home: TravellerEntryGate(
        api: api,
        home: const Scaffold(body: Text('TravelMate Home')),
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
}
