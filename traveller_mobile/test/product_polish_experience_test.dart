import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/navigation/app_shell.dart';
import 'package:travelmate_traveller/modules/fr01_user_management/profile_tab.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';

Map<String, dynamic> _trip(String id, String title) => {
      'id': id,
      'title': title,
      'destinationArea': 'Penang, Malaysia',
      'startDate': '2026-10-25',
      'endDate': '2026-10-28',
      'status': 'planned',
      'budgetEstimate': {'total': 720, 'limit': 1200},
      'activities': [
        {'activityName': 'Penang Hill', 'dayNo': 1},
      ],
    };

class _TripsApi extends ApiService {
  _TripsApi({List<Map<String, dynamic>>? trips})
      : trips = trips ?? <Map<String, dynamic>>[];

  final List<Map<String, dynamic>> trips;
  int deleteCalls = 0;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries') {
      return {'ok': true, 'items': trips};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> delete(String path) async {
    deleteCalls += 1;
    trips.removeWhere((trip) => path.endsWith('/${trip['id']}'));
    return {'ok': true};
  }
}

class _ChatApi extends ApiService {
  _ChatApi({
    this.existingFallback = false,
    this.failSessions = false,
    this.chatCompleter,
    this.customSource,
  });

  final bool existingFallback;
  final bool failSessions;
  final Completer<dynamic>? chatCompleter;
  final String? customSource;

  Map<String, dynamic> get _session => {
        'id': 'chat-session-1',
        'title': 'Penang ideas',
        'updatedAt': '2026-10-05T10:00:00Z',
        'messages': (existingFallback || customSource != null)
            ? [
                {
                  'message': 'What can I do?',
                  'reply': 'Here are a few saved ideas for your trip.',
                  'source': customSource ?? 'fallback',
                }
              ]
            : <dynamic>[],
      };

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr11/sessions') {
      if (failSessions) throw Exception('HTTP 500 internal stack trace');
      return {
        'ok': true,
        'items': (existingFallback || customSource != null)
            ? [_session]
            : <dynamic>[],
      };
    }
    if (path == '/api/fr11/sessions/chat-session-1') {
      return {'ok': true, 'session': _session};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr11/chat') {
      if (chatCompleter != null) return chatCompleter!.future;
      return {'ok': true, 'session': _session};
    }
    if (path == '/api/fr11/sessions') {
      return {'ok': true, 'session': _session};
    }
    throw StateError('Unexpected POST $path');
  }
}

class _ProfileApi extends ApiService {
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr1/me') {
      return {
        'ok': true,
        'profile': {
          'name': 'Alya Rahman',
          'email': 'alya@example.com',
          'preferredLanguage': 'English',
        },
      };
    }
    if (path == '/api/fr2/preferences') {
      return {
        'ok': true,
        'preferences': {
          'travelPersonality': 'Explorer',
          'interests': ['Food', 'Culture'],
          'travelPace': 'Relaxed',
        },
      };
    }
    throw StateError('Unexpected GET $path');
  }
}

Widget _app(Widget home, {double textScale = 1}) => MaterialApp(
      theme: buildInkWashTheme(),
      home: home,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: TextScaler.linear(textScale),
        ),
        child: child!,
      ),
    );

Future<void> _pumpAtSize(
  WidgetTester tester,
  Widget widget, {
  Size size = const Size(430, 900),
  double textScale = 1,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(_app(widget, textScale: textScale));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

void main() {
  testWidgets('Trips empty state offers the personalised planning action',
      (tester) async {
    await _pumpAtSize(tester, TripsTab(api: _TripsApi()));

    expect(find.text('No travel plans yet'), findsOneWidget);
    expect(find.text('Start planning your first personalised trip with custom activities and budget.'),
        findsOneWidget);
    expect(find.text('Plan a trip'), findsWidgets);
    expect(find.textContaining('trip_'), findsNothing);
  });

  testWidgets('Trips uses friendly summaries and opens the exact trip ID',
      (tester) async {
    final api = _TripsApi(trips: [
      _trip('trip-one', 'Penang Getaway'),
      _trip('trip-two', 'Second Penang Trip'),
    ]);
    await _pumpAtSize(tester, TripsTab(api: api, referenceDate: DateTime(2026, 10, 24)));

    expect(find.text('Planned'), findsNWidgets(3));
    expect(find.text('1 activity · RM 720 estimated'), findsNWidgets(2));
    expect(find.textContaining('generation'), findsNothing);

    await tester.drag(find.byType(ListView), const Offset(0, -200));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Continue').last);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.byKey(const ValueKey('trip-details-trip-two')), findsOneWidget);
  });

  testWidgets('Deleting a trip requires confirmation', (tester) async {
    final api = _TripsApi(trips: [_trip('trip-one', 'Penang Getaway')]);
    await _pumpAtSize(tester, TripsTab(api: api));

    await tester.tap(find.byTooltip('Trip actions'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete trip').last);
    await tester.pumpAndSettle();

    expect(find.text('Delete this trip?'), findsOneWidget);
    expect(api.deleteCalls, 0);

    await tester.tap(find.text('Keep trip'));
    await tester.pumpAndSettle();
    expect(api.deleteCalls, 0);
  });

  testWidgets('Assistant shows calm empty, thinking and retry states',
      (tester) async {
    final completer = Completer<dynamic>();
    await _pumpAtSize(
      tester,
      ChatTab(api: _ChatApi(chatCompleter: completer)),
    );

    expect(find.text('TravelMate Assistant'), findsOneWidget);
    expect(find.text('How can I help with your trip?'), findsWidgets);
    expect(find.textContaining('AI travel'), findsNothing);

    await tester.tap(find.text('Help with my budget'));
    await tester.pump();
    expect(find.text('TravelMate is thinking…'), findsOneWidget);

    completer.completeError(Exception('HTTP 500 internal stack trace'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('Message not sent'), findsOneWidget);
    expect(find.text('Retry message'), findsOneWidget);
    expect(find.textContaining('HTTP 500'), findsNothing);
  });

  testWidgets('Assistant clearly identifies saved fallback guidance',
      (tester) async {
    await _pumpAtSize(
      tester,
      ChatTab(api: _ChatApi(existingFallback: true)),
    );

    expect(find.text('Using saved travel guidance'), findsOneWidget);
    expect(find.text('Check live details before making bookings.'),
        findsOneWidget);
    expect(find.textContaining('Gemini'), findsNothing);
  });

  testWidgets(
      'Assistant clearly identifies backend travelmate-assistant fallback guidance',
      (tester) async {
    await _pumpAtSize(
      tester,
      ChatTab(api: _ChatApi(customSource: 'travelmate-assistant')),
    );

    expect(find.text('Using saved travel guidance'), findsOneWidget);
    expect(find.text('Check live details before making bookings.'),
        findsOneWidget);
  });

  testWidgets(
      'Assistant does not show saved guidance chip for live gemini responses',
      (tester) async {
    await _pumpAtSize(
      tester,
      ChatTab(api: _ChatApi(customSource: 'gemini')),
    );

    expect(find.text('Using saved travel guidance'), findsNothing);
  });

  testWidgets('Assistant session failure uses a persistent retry state',
      (tester) async {
    await _pumpAtSize(
      tester,
      ChatTab(api: _ChatApi(failSessions: true)),
    );

    expect(find.text('We couldn’t load your previous chats. Try again.'),
        findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    expect(find.textContaining('HTTP 500'), findsNothing);
  });

  testWidgets('Profile summarizes travel style and opens preferences',
      (tester) async {
    final api = _ProfileApi();
    await _pumpAtSize(tester, ProfileTab(api: api));

    expect(find.text('Explorer'), findsOneWidget);
    expect(find.text('Food · Culture · Relaxed pace'), findsOneWidget);
    expect(find.text('Edit travel preferences'), findsOneWidget);
    expect(find.text('traveller'), findsNothing);

    await tester.tap(find.text('Edit travel preferences'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Travel preferences'), findsOneWidget);
  });

  testWidgets('Profile asks for confirmation before signing out',
      (tester) async {
    var signOutCalls = 0;
    await _pumpAtSize(
      tester,
      ProfileTab(
        api: _ProfileApi(),
        onSignOut: () async => signOutCalls += 1,
      ),
    );

    await tester.scrollUntilVisible(
      find.text('Sign out'),
      500,
      scrollable: find.byType(Scrollable).first,
      maxScrolls: 10,
    );
    await tester.ensureVisible(find.text('Sign out'));
    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle();

    expect(find.text('Sign out of TravelMate?'), findsOneWidget);
    expect(signOutCalls, 0);
    await tester.tap(find.text('Stay signed in'));
    await tester.pumpAndSettle();
    expect(signOutCalls, 0);
  });

  testWidgets('Root navigation switches existing tabs without nested routes',
      (tester) async {
    const pages = [
      Center(child: Text('Home content')),
      Center(child: Text('Explore content')),
      Center(child: Text('Trips content')),
      Center(child: Text('Assistant content')),
      Center(child: Text('Profile content')),
    ];
    await _pumpAtSize(tester, const AppShell(pages: pages));

    await tester.tap(find.text('Trips'));
    await tester.pump();
    expect(find.text('Trips content'), findsOneWidget);
    expect(find.byType(Navigator), findsOneWidget);

    await tester.tap(find.text('Profile'));
    await tester.pump();
    expect(find.text('Profile content'), findsOneWidget);
  });

  testWidgets('Changed screens support narrow width and larger text',
      (tester) async {
    await _pumpAtSize(
      tester,
      TripsTab(
          api: _TripsApi(
              trips: [_trip('trip-one', 'A very long Penang getaway title')])),
      size: const Size(320, 700),
      textScale: 1.3,
    );

    expect(tester.takeException(), isNull);
    expect(find.text('A very long Penang getaway title'), findsOneWidget);
  });
}
