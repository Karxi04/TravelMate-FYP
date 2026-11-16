import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';

import 'chat_action_audit_test.dart' show ActionApi, frame, tap, copy;

void main() {
  for (final width in [320.0, 840.0]) {
    testWidgets('historical comparison is read-only and reopenable at $width', (tester) async {
      final api = ActionApi(draft: true);
      final earlier = copy(api.sessions.single['messages'].single['tripPlan']);
      earlier.remove('draftId');
      earlier['viewOnly'] = true;
      earlier['savedTripId'] = 'trip5';
      earlier['historyVersion'] = 1;
      final current = copy(earlier)..['historyVersion'] = 2;
      api.sessions.single['messages'].single.addAll({
        'tripPlan': earlier, 'proposedPlan': current,
        'comparisonLabel': 'Itinerary version 2 (read-only)',
      });
      await frame(tester, ChatTab(api: api), width: width);
      expect(find.text('Itinerary version 1 (read-only)'), findsOneWidget);
      expect(find.text('Apply changes'), findsNothing);
      expect(find.text('Save plan to Trips'), findsNothing);
      expect(api.posts, isEmpty);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      await frame(tester, ChatTab(api: api), width: width);
      expect(find.text('Itinerary version 1 (read-only)'), findsOneWidget);
      expect(api.posts, isEmpty);
    });
  }

  testWidgets('restore uses existing explicit confirmation and sends one save', (tester) async {
    final api = ActionApi(draft: true);
    final proposal = copy(api.sessions.single['messages'].single['tripPlan']);
    proposal.addAll({'adjustmentTripId': 'trip5', 'restoresVersion': 1,
      'restorationScope': 'budget'});
    api.sessions.single['planningState']['activePlan'] = copy(proposal);
    api.sessions.single['messages'].single['tripPlan'] = proposal;
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.text('Restore version 1'));
    expect(find.text('Restore this saved version?'), findsOneWidget);
    expect(api.posts, isEmpty);
    await tap(tester, find.text('Keep editing'));
    expect(api.posts, isEmpty);
    await tap(tester, find.text('Restore version 1'));
    await tap(tester, find.text('Confirm save'));
    expect(api.posts.where((p) => p['path'] == '/api/fr11/save-plan'), hasLength(1));
    expect(api.posts.single['body']['confirmed'], isTrue);
    expect(api.posts.single['body']['plan']['restoresVersion'], 1);
    expect(tester.takeException(), isNull);
  });
}
