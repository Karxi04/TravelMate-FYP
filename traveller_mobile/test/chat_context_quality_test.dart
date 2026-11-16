import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr06_weather_forecast/weather_screen.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/database_chat_cards.dart';

import 'chat_action_audit_test.dart' show ActionApi, frame, tap, copy, place;
import 'database_chatbot_test.dart' show card;

ActionApi history(List<Map<String, dynamic>> messages) {
  final api = ActionApi();
  api.sessions = [
    {
      'id': 'context-session',
      'title': 'Context',
      'messages': messages,
      'planningState': {}
    }
  ];
  return api;
}

void main() {
  testWidgets('no-proposal compare and undo show honest replies without save actions', (tester) async {
    final api = history([
      {'id': 'compare', 'message': 'Compare old and new',
       'reply': 'There is no current proposal to compare. Your saved trip is unchanged.'},
      {'id': 'undo', 'message': 'Undo changes',
       'reply': 'There is no unconfirmed proposal to undo. Your saved trip is unchanged.'},
    ]);
    await frame(tester, ChatTab(api: api), width: 320);
    expect(find.textContaining('no current proposal'), findsOneWidget);
    expect(find.textContaining('no unconfirmed proposal'), findsOneWidget);
    expect(find.text('Apply changes'), findsNothing);
    expect(api.posts, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'unchanged results collapse and each shortlist can expand locally',
      (tester) async {
    final rows = ['A', 'B', 'C', 'D'].map(place).toList();
    final api = history([
      {
        'id': 'one',
        'message': 'Places in Penang',
        'reply': 'Here are the recorded places.',
        'placeSuggestions': rows
      },
      {
        'id': 'two',
        'message': 'Same places again?',
        'reply': 'The results are unchanged.',
        'placeSuggestions': rows
      },
    ]);
    await frame(tester, ChatTab(api: api), width: 320);
    expect(find.byKey(const ValueKey('chat-place-details-A')), findsOneWidget);
    expect(find.byKey(const ValueKey('chat-place-details-D')), findsNothing);
    expect(find.text('View results again'), findsOneWidget);
    await tap(tester, find.text('Show all 4 results'));
    expect(find.byKey(const ValueKey('chat-place-details-D')), findsOneWidget);
    await tap(tester, find.text('View results again'));
    expect(
        find.byKey(const ValueKey('chat-place-details-A')), findsNWidgets(2));
    expect(api.posts, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets('changed quote is not hidden as a duplicate result',
      (tester) async {
    final first = card();
    final second = copy(first);
    second['chatQuote']['finalPayable'] = 400;
    final api = history([
      {
        'id': 'old',
        'message': 'Package',
        'reply': 'Recorded quote.',
        'packages': [first]
      },
      {
        'id': 'updated',
        'message': 'Refresh the quote',
        'reply': 'Updated recorded quote.',
        'packages': [second]
      },
    ]);
    await frame(tester, ChatTab(api: api));
    expect(find.byType(DatabasePackageCard), findsNWidgets(2));
    expect(find.text('View results again'), findsNothing);
    expect(api.posts, isEmpty);
  });

  testWidgets('weather reply opens existing Weather screen with destination',
      (tester) async {
    final api = history([
      {
        'id': 'weather',
        'message': 'What if raining?',
        'reply': 'Open Weather for the current forecast.',
        'weatherAction': {'destination': 'Penang'}
      }
    ]);
    await frame(tester, ChatTab(api: api), width: 320);
    await tap(tester, find.text('View Weather'));
    expect(find.byType(WeatherScreen), findsOneWidget);
    expect(
        tester.widget<WeatherScreen>(find.byType(WeatherScreen)).initialPlace,
        'Penang');
    expect(api.posts, isEmpty);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'comparison keeps saved view read-only and proposed revision confirmable',
      (tester) async {
    final api = ActionApi(draft: true);
    final proposed = copy(api.sessions.single['planningState']['activePlan']);
    proposed['adjustmentTripId'] = 'trip5';
    api.sessions.single['planningState']['activePlan'] = copy(proposed);
    final saved = copy(proposed)
      ..remove('draftId')
      ..remove('adjustmentTripId');
    saved['viewOnly'] = true;
    saved['savedTripId'] = 'trip5';
    api.sessions.single['messages'].single['tripPlan'] = saved;
    api.sessions.single['messages'].single['proposedPlan'] = proposed;
    await frame(tester, ChatTab(api: api));
    expect(find.text('Saved itinerary (read-only)'), findsOneWidget);
    expect(find.text('Proposed changes (not saved)'), findsOneWidget);
    expect(find.text('Apply changes'), findsOneWidget);
    expect(find.text('Save plan to Trips'), findsNothing);
    expect(api.posts, isEmpty);
  });
}
