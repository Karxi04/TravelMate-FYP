import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';

import 'chat_action_audit_test.dart' show ActionApi, frame, tap;

void main() {
  for (final width in [320.0, 840.0]) {
    testWidgets('saved Day 2 is read-only and reopenable at width $width',
        (tester) async {
      final api = ActionApi();
      api.sessions = [
        {
          'id': 'preview-session',
          'title': 'Saved trip',
          'planningState': {
            'adjustment': {'tripId': 'trip5', 'pendingDay': 2}
          },
          'messages': [
            {
              'id': 'preview-message',
              'message': 'Show me Day 2 first',
              'reply': 'Here is your saved itinerary.',
              'tripPlan': {
                'viewOnly': true,
                'savedTripId': 'trip5',
                'previewDay': 2,
                'title': 'Actual saved Penang trip',
                'destinationArea': 'Penang',
                'startDate': '2020-02-10',
                'endDate': '2020-02-12',
                'budgetLimit': 500,
                'travellerCount': 4,
                'activities': [
                  {
                    'activityName': 'Saved Day 2 temple',
                    'dayNo': 2,
                    'timeSlot': '09:00 - 10:00'
                  }
                ],
              },
            },
          ],
        },
      ];
      await frame(tester, ChatTab(api: api), width: width);
      expect(find.text('Saved itinerary (read-only)'), findsOneWidget);
      expect(find.text('Saved Day 2 temple'), findsOneWidget);
      expect(find.textContaining('Day 1'), findsNothing);
      expect(find.textContaining('Day 3'), findsNothing);
      expect(find.text('Apply changes'), findsNothing);
      expect(find.text('Save plan to Trips'), findsNothing);
      expect(find.text('Regenerate'), findsNothing);
      expect(find.textContaining('Earlier draft'), findsNothing);
      expect(api.posts, isEmpty);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      await frame(tester, ChatTab(api: api), width: width);
      expect(find.text('Saved Day 2 temple'), findsOneWidget);
      expect(api.posts, isEmpty);
    });
  }

  testWidgets('a genuine adjustment draft still requires explicit confirmation',
      (tester) async {
    final api = ActionApi(draft: true);
    api.sessions.single['messages'].single['tripPlan']['adjustmentTripId'] =
        'trip5';
    api.sessions.single['planningState']['activePlan']['adjustmentTripId'] =
        'trip5';
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.text('Apply changes'));
    expect(find.text('Apply changes to this trip?'), findsOneWidget);
    expect(api.posts, isEmpty);
    await tap(tester, find.text('Keep editing'));
    expect(api.posts, isEmpty);
  });
}
