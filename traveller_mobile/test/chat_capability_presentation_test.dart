import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/personal_assistant_actions.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/packing_trip_selector_screen.dart';

import 'chat_action_audit_test.dart' show frame, tap;
import 'chat_personal_questions_test.dart' show PersonalApi;

class CapabilityApi extends PersonalApi {
  CapabilityApi() {
    sessions.single['messages'] = [
      {
        'id': 'packing-help',
        'message': 'Should I bring an umbrella?',
        'reply':
            'General advice is not a live forecast. Your checklist is unchanged.',
        'readOnlyAnswer': true,
        'assistantActions': [
          {'kind': 'packing', 'tripId': 'alpha'},
          {'kind': 'refund', 'tripId': 'alpha'},
          {'kind': 'https://untrusted.test'}
        ],
      },
    ];
  }
}

void main() {
  for (final width in [320.0, 840.0]) {
    testWidgets(
        'reopened capability help has safe accessible navigation at $width',
        (tester) async {
      final api = CapabilityApi();
      await frame(tester, ChatTab(api: api), width: width);
      expect(find.textContaining('not a live forecast'), findsOneWidget);
      expect(find.text('Save plan to Trips'), findsNothing);
      expect(find.text('Apply changes'), findsNothing);
      expect(api.posts, isEmpty);
      await tap(tester, find.text('Open Smart Packing'));
      expect(find.byType(PackingTripSelectorScreen), findsOneWidget);
      expect(api.gets, contains('/api/fr5/itineraries'));
      expect(api.posts, isEmpty);
      expect(api.gets.where((p) => p.contains('/packing')), isEmpty);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('unsupported capability actions cannot become mutations or URLs',
      (tester) async {
    final api = CapabilityApi();
    await frame(
        tester,
        Scaffold(
            body: PersonalAssistantActions(actions: [
          {'kind': 'refund'},
          {'kind': 'checkout'},
          {'kind': 'https://untrusted.test'},
          {'kind': 'trip', 'tripId': '../foreign'},
        ], api: api)));
    expect(find.byType(ActionChip), findsNothing);
    expect(api.gets, isEmpty);
    expect(api.posts, isEmpty);
  });
}
