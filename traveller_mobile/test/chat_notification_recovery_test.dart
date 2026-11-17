import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/modules/traveller_notifications/notification_center.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'chat_action_audit_test.dart' show ActionApi, copy, frame, tap;

const prompt = 'Recommend 3 nature places in Penang';
const storageError = ApiException('Account storage unavailable', 503,
    {'code': 'profile_storage_unavailable'});

class RecoveryApi extends ActionApi {
  String outcome = 'completed';
  bool unavailable = false, checkUnavailable = false, completed = false;
  int sends = 0, checks = 0, inboxReads = 0;
  String? identity;
  final inbox = <Map<String, dynamic>>[
    {
      'id': 'notice-fixture',
      'title': 'Payment successful',
      'message': 'Existing fixture payment',
      'category': 'payment',
      'read': false,
      'createdAt': '2026-11-01T00:00:00Z',
      'target': {'screen': 'payments', 'orderId': 'paid-fixture'}
    }
  ];
  RecoveryApi() {
    sessions = [
      {
        'id': 'original',
        'title': 'Original conversation',
        'planningState': {},
        'messages': <Map<String, dynamic>>[
          {'message': 'Earlier question', 'reply': 'Earlier saved answer'}
        ]
      },
      {
        'id': 'other',
        'title': 'Other conversation',
        'planningState': {},
        'messages': <Map<String, dynamic>>[
          {'message': 'Other question', 'reply': 'Other saved answer'}
        ]
      },
    ];
  }
  Map<String, dynamic> get original =>
      sessions.firstWhere((s) => s['id'] == 'original');
  void finish() {
    if (completed) return;
    completed = true;
    (original['messages'] as List).add({
      'id': 'answer-fixture',
      'message': prompt,
      'reply': 'The saved nature answer',
      'clientRequestId': identity
    });
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posts.add({'path': path, 'body': copy(body ?? {})});
    if (path == '/api/fr11/chat') {
      sends++;
      identity = body!['clientRequestId'] as String;
      if (unavailable || outcome == 'rejected-profile') throw storageError;
      if (outcome == 'completed' || outcome == 'late-saved') finish();
      if (outcome == 'completed')
        return {'ok': true, 'session': copy(original)};
      if (outcome == 'server-unknown') {
        throw const ApiException(
            'Unavailable', 503, {'code': 'chat_delivery_unknown'});
      }
      throw TimeoutException('Synthetic uncertain transport');
    }
    if (path == '/api/fr11/sessions') {
      if (unavailable) throw storageError;
      final session = {
        'id': 'new-fixture',
        'title': 'New travel chat',
        'messages': [],
        'planningState': {}
      };
      sessions.insert(0, copy(session));
      return {'ok': true, 'session': session};
    }
    throw StateError('Unexpected write: $path');
  }

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    gets.add(path);
    if (path.startsWith('/api/fr11/chat-requests/')) checks++;
    if (unavailable ||
        (path.startsWith('/api/fr11/chat-requests/') && checkUnavailable))
      throw storageError;
    if (path.startsWith('/api/fr11/chat-requests/')) {
      return {
        'ok': true,
        'status': completed ? 'completed' : 'unknown',
        if (completed) 'session': copy(original)
      };
    }
    if (path == '/api/fr11/sessions')
      return {'ok': true, 'items': sessions.map(copy).toList()};
    if (path.startsWith('/api/fr11/sessions/')) {
      return {
        'ok': true,
        'session':
            copy(sessions.firstWhere((s) => s['id'] == path.split('/').last))
      };
    }
    if (path == notificationPath) {
      inboxReads++;
      return {'ok': true, 'items': inbox.map(copy).toList(), 'unreadCount': 1};
    }
    throw StateError('Unexpected read: $path');
  }
}

class CombinedFlow extends StatelessWidget {
  final RecoveryApi api;
  const CombinedFlow(this.api, {super.key});
  @override
  Widget build(BuildContext context) => Scaffold(
          body: Column(children: [
        TextButton(
            onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (_) => NotificationCenterScreen(api: api))),
            child: const Text('Open notifications')),
        Expanded(child: ChatTab(api: api)),
      ]));
}

Future<void> sendQuestion(WidgetTester tester) async {
  await tester.enterText(find.byType(TextField).last, prompt);
  await tap(tester, find.byIcon(Icons.arrow_upward_rounded));
}

Future<void> openHistory(WidgetTester tester, String title) async {
  if (find.byType(Drawer).evaluate().isEmpty) {
    await tap(tester, find.byTooltip('Open navigation menu'));
  }
  await tap(tester, find.widgetWithText(ListTile, title));
}

void main() {
  for (final outcome in ['completed', 'late-saved']) {
    testWidgets(
        '$outcome reply then New Chat, history and inbox preserve records',
        (tester) async {
      final api = RecoveryApi()..outcome = outcome;
      await frame(tester, CombinedFlow(api));
      await sendQuestion(tester);
      final dynamic chatState = tester.state(find.byType(ChatTab));
      expect(chatState.messages.last['reply'], 'The saved nature answer');
      expect(find.text('The saved nature answer'), findsOneWidget);
      await tap(tester, find.byTooltip('New chat'));
      await openHistory(tester, 'Other conversation');
      expect(find.text('Other saved answer'), findsOneWidget);
      await openHistory(tester, 'Original conversation');
      expect(find.text('The saved nature answer'), findsOneWidget);
      final saved = copy(api.original);
      await tap(tester, find.text('Open notifications'));
      expect(find.text('Existing fixture payment'), findsOneWidget);
      expect(api.inbox.single['read'], isFalse);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('The saved nature answer'), findsOneWidget);
      expect(api.original, saved);
      expect(api.sends, 1);
      expect(api.checks, outcome == 'completed' ? 0 : 1);
      expect(
          api.posts.where((p) => p['path'] == '/api/fr11/save-plan'), isEmpty);
      expect(api.deletes, isEmpty);
    });
  }
  testWidgets(
      'known authentication rejection does not become an unrecoverable unknown turn',
      (tester) async {
    final api = RecoveryApi()..outcome = 'rejected-profile';
    await frame(tester, CombinedFlow(api));
    final saved = copy(api.original);
    await sendQuestion(tester);
    dynamic state = tester.state(find.byType(ChatTab));
    expect(state.deliveryUnknown, isFalse);
    expect(state.pendingRequestId, isNull);
    expect(api.checks, 0);
    expect(
        tester.widget<TextField>(find.byType(TextField).last).enabled, isTrue);
    expect(api.original, saved);
    api.outcome = 'completed';
    await tap(tester, find.text('Retry message'));
    expect(api.sends, 2);
    expect(find.text('The saved nature answer'), findsOneWidget);
    expect(
        (api.original['messages'] as List).where((m) => m['message'] == prompt),
        hasLength(1));
  });
  for (final outcome in ['pending', 'server-unknown']) {
    testWidgets(
        '$outcome delivery survives failed navigation and storage recovery without replay',
        (tester) async {
      final api = RecoveryApi()
        ..outcome = outcome
        ..checkUnavailable = true;
      await frame(tester, CombinedFlow(api));
      await sendQuestion(tester);
      dynamic state = tester.state(find.byType(ChatTab));
      final identity = state.pendingRequestId;
      final saved = copy(api.original);
      expect(state.deliveryUnknown, isTrue);
      api.unavailable = true;
      await tap(tester, find.byTooltip('New chat'));
      expect(state.activeSessionId, 'original');
      expect(state.pendingRequestId, identity);
      await openHistory(tester, 'Other conversation');
      expect(state.activeSessionId, 'original');
      expect(state.pendingRequestId, identity);
      expect(state.busy, isFalse);
      expect(api.original, saved);
      expect(api.sessions, hasLength(2));
      state.scaffoldKey.currentState.closeDrawer();
      await tester.pumpAndSettle();
      await tap(tester, find.text('Open notifications'));
      expect(find.text('Notifications are unavailable. Please try again.'),
          findsOneWidget);
      expect(api.inbox.single['read'], isFalse);
      await tester.pageBack();
      await tester.pumpAndSettle();
      api.unavailable = false;
      api.checkUnavailable = false;
      api.finish();
      await tap(tester, find.text('Check conversation'));
      expect(state.deliveryUnknown, isFalse);
      expect(find.text('The saved nature answer'), findsOneWidget);
      await openHistory(tester, 'Other conversation');
      await openHistory(tester, 'Original conversation');
      expect(find.text('The saved nature answer'), findsOneWidget);
      await tap(tester, find.text('Open notifications'));
      expect(find.text('Existing fixture payment'), findsOneWidget);
      expect(api.sends, 1);
      expect(
          api.posts.where((p) => p['path'] == '/api/fr11/save-plan'), isEmpty);
      expect(api.deletes, isEmpty);
    });
  }
}
