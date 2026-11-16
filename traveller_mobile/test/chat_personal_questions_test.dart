import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/personal_assistant_actions.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_expenses_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_history_screen.dart';
import 'package:travelmate_traveller/modules/fr02_travel_preference/preferences_screen.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/favourites_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';

import 'chat_action_audit_test.dart' show ActionApi, frame, tap;

class PersonalApi extends ActionApi {
  PersonalApi() : super(draft: true) {
    sessions.single['messages'] = [
      {
        'id': 'answer',
        'message': 'Explain my trip budget',
        'reply':
            'Modelled subtotal MYR 585.00. Missing prices are unavailable, not free.',
        'readOnlyAnswer': true,
        'assistantActions': [
          {'kind': 'budget', 'tripId': 'trip5'},
          {'kind': 'payments'}
        ]
      },
    ];
  }
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    gets.add(path);
    if (path.endsWith('/expenses'))
      return {
        'ok': true,
        'expenses': [],
        'revision': 0,
        'overview': {
          'currency': 'MYR',
          'systemEstimateMinor': 58500,
          'budgetLimitMinor': 50000,
          'actualMinor': 0,
          'plannedMinor': 0,
          'verifiedMinor': 0,
          'committedHotelMinor': 0,
          'unknownCategories': []
        }
      };
    if (path == '/api/fr9/payments') return {'ok': true, 'items': []};
    if (path == '/api/fr9/checkout/capabilities')
      return {'ok': true, 'supportedQuoteTypes': []};
    return super.get(path, query);
  }
}

void main() {
  for (final entry in <(String, String, Type, String)>[
    ('trip', 'Open Trip Details', TripDetailsScreen, '/api/fr5/itineraries'),
    ('trips', 'Open Trips', TripsTab, '/api/fr5/itineraries'),
    (
      'preferences',
      'Open Preferences',
      PreferencesScreen,
      '/api/fr2/preferences'
    ),
    ('saved', 'Open Saved Places', FavouritesScreen, '/api/fr3/favourites'),
  ]) {
    testWidgets('${entry.$1} action uses the supported screen and read API',
        (tester) async {
      final api = PersonalApi();
      await frame(
          tester,
          Scaffold(
              body: PersonalAssistantActions(actions: [
            {'kind': entry.$1, 'tripId': 'alpha'},
          ], api: api)));
      await tester.tap(find.text(entry.$2));
      await tester.pumpAndSettle();
      expect(find.byType(entry.$3), findsOneWidget);
      expect(api.gets, contains(entry.$4));
      expect(api.posts, isEmpty);
      if (entry.$1 == 'trip') {
        expect(
            tester
                .widget<TripDetailsScreen>(find.byType(TripDetailsScreen))
                .tripId,
            'alpha');
      }
      expect(tester.takeException(), isNull);
    });
  }
  for (final width in [320.0, 840.0]) {
    testWidgets(
        'reopened read-only budget answer has safe working navigation at $width',
        (tester) async {
      final api = PersonalApi();
      await frame(tester, ChatTab(api: api), width: width);
      expect(find.textContaining('Missing prices are unavailable'),
          findsOneWidget);
      expect(find.text('Save plan to Trips'), findsNothing);
      expect(find.text('Apply changes'), findsNothing);
      await tap(tester, find.text('Open Trip Budget'));
      expect(find.byType(TripExpensesScreen), findsOneWidget);
      expect(api.gets, contains('/api/fr5/itineraries/trip5/expenses'));
      expect(api.gets.where((p) => p.endsWith('/budget')), isEmpty);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('payment history navigation cannot reconcile or start checkout',
      (tester) async {
    final api = PersonalApi();
    await frame(
        tester,
        Scaffold(
            body: PersonalAssistantActions(actions: const [
          {'kind': 'payments'}
        ], api: api)));
    await tester.tap(find.text('Open Payment History'));
    await tester.pumpAndSettle();
    expect(find.byType(PaymentHistoryScreen), findsOneWidget);
    expect(api.gets, contains('/api/fr9/payments'));
    expect(api.gets.any((p) => p.contains('/reconcile')), isFalse);
  });
  testWidgets('unknown actions, URLs and unsafe trip IDs are ignored',
      (tester) async {
    await frame(
        tester,
        PersonalAssistantActions(actions: const [
          {'kind': 'checkout', 'url': 'https://example.invalid'},
          {'kind': 'budget', 'tripId': '../other-owner'},
          {'kind': 'trip', 'tripId': 'https://example.invalid'},
          {'kind': 'deleteTrip', 'tripId': 'trip5'},
        ], api: PersonalApi()));
    expect(find.byType(ActionChip), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
