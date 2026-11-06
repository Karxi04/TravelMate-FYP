import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/navigation/app_shell_navigation.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/packing_trip_selector_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import 'package:travelmate_traveller/modules/fr06_weather_forecast/weather_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';

Map<String, dynamic> copy(Map value) =>
    Map<String, dynamic>.from(jsonDecode(jsonEncode(value)));
Map<String, dynamic> fullPackage(String id) => {
      'id': id,
      'title': 'Complete $id',
      'destination': 'Penang',
      'operatorName': 'Operator $id',
      'operatorEmail': 'business@example.test',
      'fullDescription': 'Full public description $id',
      'currency': 'MYR',
      'adultPrice': 220,
      'childPrice': 100,
      'priceBasis': 'per_person',
      'durationDays': 2,
      'durationNights': 1,
      'departureDates': ['2030-12-12'],
      'bookingTerms': 'Actual public booking terms $id',
      'inclusions': ['Included service $id'],
      'exclusions': ['Excluded service $id'],
      'itineraryDays': List.generate(
          2,
          (day) => {
                'dayNumber': day + 1,
                'title': 'Day title $id ${day + 1}',
                'activities': [
                  {
                    'name': 'Activity $id ${day + 1}',
                    'time': '09:00',
                    'description': List.filled(
                            30, 'Public activity detail $id ${day + 1}.')
                        .join(' ')
                  }
                ]
              })
    };
Map<String, dynamic> place(String id) => {
      'id': id,
      'destinationId': id,
      'title': 'Place $id',
      'address': 'George Town, Penang, Malaysia',
      'city': 'George Town',
      'category': 'Culture',
      'description': 'Selected detail $id',
      'unitPrice': 20,
      'pricingUnit': 'per_person',
      'currency': 'MYR',
      'openingHours': '09:00-17:00',
      'gps_coordinates': {'latitude': 5.41, 'longitude': 100.33}
    };
Map<String, dynamic> trip(String id) => {
      'id': id,
      'title': 'Trip $id',
      'destinationArea': 'Penang',
      'startDate': '2030-12-12',
      'endDate': '2030-12-14',
      'activities': []
    };

class ActionApi extends ApiService {
  final gets = <String>[];
  final posts = <Map<String, dynamic>>[];
  final deletes = <String>[];
  final addedActivities = <Map<String, dynamic>>[];
  List<Map<String, dynamic>> sessions = [];
  List<Map<String, dynamic>> trips = [trip('alpha'), trip('beta')];
  List<Map<String, dynamic>> packages = [
    fullPackage('package-B'),
    fullPackage('package-A')
  ];
  Completer<dynamic>? packageGate, newChatGate, saveGate, tripGate;
  bool failChat = false,
      failPackages = false,
      failSessions = false,
      failActivity = false;
  bool rejectActivity = false;
  ActionApi({bool recommendations = false, bool draft = false}) {
    if (recommendations || draft) {
      final raw = copy(jsonDecode(
          File('test/fixtures/fr11_guided_contract.json').readAsStringSync()));
      final item = <String, dynamic>{
        'id': 'message-1',
        'message': 'Suggestions',
        'reply': 'Review these selected records.',
        if (recommendations) 'placeSuggestions': [place('A'), place('B')],
        if (recommendations)
          'packages': [
            {
              'id': 'recommendation-A',
              'packageId': 'package-A',
              'title': 'Summary A'
            },
            {
              'id': 'recommendation-B',
              'packageId': 'package-B',
              'title': 'Summary B',
              'isVerifiedOperator': true,
              'licenseNumber': 'UNVERIFIED'
            }
          ],
        if (draft) 'tripPlan': raw['item']['tripPlan']
      };
      sessions = [
        {
          'id': 'session-1',
          'title': 'First session',
          'messages': [item],
          'planningState': draft ? raw['session']['planningState'] : {}
        }
      ];
    }
  }
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    gets.add(path);
    if (path == '/api/fr11/sessions') {
      if (failSessions) throw Exception('Synthetic session failure');
      return {'items': sessions.map(copy).toList()};
    }
    if (path.startsWith('/api/fr11/sessions/'))
      return {
        'session':
            copy(sessions.firstWhere((s) => s['id'] == path.split('/').last))
      };
    if (path == '/api/public/tourism-packages') {
      if (failPackages) throw Exception('Synthetic package fetch failure');
      if (packageGate != null) return packageGate!.future;
      return {'ok': true, 'items': packages.map(copy).toList()};
    }
    if (path == '/api/fr9/checkout/capabilities')
      return {
        'ok': true,
        'mode': 'test',
        'hostedCheckout': true,
        'supportedQuoteTypes': ['package', 'hotel']
      };
    if (path == '/api/fr5/itineraries')
      return tripGate?.future ??
          Future.value({'items': trips.map(copy).toList()});
    if (path == '/api/fr1/me')
      return {
        'profile': {'name': 'Synthetic Traveller'}
      };
    if (path.contains('/destinations/') &&
        !path.endsWith('ratings-reviews') &&
        !path.endsWith('nearby'))
      return {'destination': place(Uri.decodeComponent(path.split('/').last))};
    if (path.endsWith('ratings-reviews'))
      return {
        'result': {'items': []}
      };
    return {'ok': true, 'items': [], 'results': []};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posts.add({'path': path, 'body': copy(body ?? {})});
    if (path == '/api/fr11/chat') {
      if (failChat) throw Exception('Synthetic send failure');
      final session = {
        'id': 'sent-session',
        'title': 'Sent chat',
        'planningState': {},
        'messages': [
          {'message': body!['message'], 'reply': 'Reply to ${body['message']}'}
        ]
      };
      sessions = [copy(session)];
      return {'ok': true, 'session': session};
    }
    if (path == '/api/fr11/sessions') {
      if (newChatGate != null) return newChatGate!.future;
      final session = {
        'id': 'new-session',
        'title': 'New travel chat',
        'messages': []
      };
      sessions.insert(0, copy(session));
      return {'session': session};
    }
    if (path == '/api/fr5/itineraries') {
      final created = {'id': 'created-trip', ...body!};
      trips.add(copy(created));
      return {'ok': true, 'id': 'created-trip', 'itinerary': created};
    }
    if (path.endsWith('/activities')) {
      if (failActivity) throw Exception('Synthetic activity failure');
      if (rejectActivity)
        return {'ok': false, 'error': 'The place was not added.'};
      addedActivities.add({'path': path, 'body': copy(body!)});
      return {'ok': true, 'activity': body};
    }
    if (path == '/api/fr11/save-plan') {
      if (saveGate != null) return saveGate!.future;
      return {
        'ok': true,
        'itinerary': {'id': 'saved-trip', 'title': 'Confirmed trip'}
      };
    }
    if (path == '/api/fr15/package-checkout-attempts')
      return {'ok': true, 'attempt': {}};
    return {'ok': true};
  }

  @override
  Future<dynamic> delete(String path) async {
    deletes.add(path);
    sessions.removeWhere((s) => s['id'] == path.split('/').last);
    return {'ok': true};
  }
}

Future<void> frame(WidgetTester tester, Widget child,
    {double width = 430}) async {
  tester.view.physicalSize = Size(width, 1200);
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(MaterialApp(theme: buildInkWashTheme(), home: child));
  await tester.pumpAndSettle();
}

Future<void> reveal(WidgetTester tester, Finder target) async {
  if (target.evaluate().isNotEmpty) {
    await tester.ensureVisible(target.first);
    await tester.pumpAndSettle();
    return;
  }
  final scroll = find
      .byWidgetPredicate(
          (w) => w is Scrollable && w.axisDirection == AxisDirection.down)
      .first;
  final position = tester.state<ScrollableState>(scroll).position;
  position.jumpTo(0);
  await tester.pumpAndSettle();
  for (var i = 0; i < 80; i++) {
    if (target.evaluate().isNotEmpty) {
      await tester.ensureVisible(target.first);
      await tester.pumpAndSettle();
      return;
    }
    position.jumpTo((i * 180.0).clamp(0, position.maxScrollExtent));
    await tester.pumpAndSettle();
  }
  fail('Action not reachable: $target');
}

Future<void> tap(WidgetTester tester, Finder target) async {
  await reveal(tester, target);
  await tester.tap(target.first);
  await tester.pumpAndSettle();
}

void main() {
  for (final prompt in [
    'Plan a 3-day cultural trip',
    'Vacation on RM1,500 budget',
    'What should I do if it rains?',
    'Adjust my itinerary'
  ]) {
    testWidgets('curated prompt sends exactly its own question: $prompt',
        (tester) async {
      final api = ActionApi();
      await frame(tester, ChatTab(api: api));
      await tap(tester, find.byKey(ValueKey('chat-prompt-$prompt')));
      expect(api.posts.single['path'], '/api/fr11/chat');
      expect(api.posts.single['body']['message'], prompt);
      expect(api.posts.single['body']['guidedPlanning'], isTrue);
      expect(find.byType(TourismPackageDetailsScreen), findsNothing);
    });
  }
  for (final suggestion in [
    'Plan things to do',
    'Adjust my itinerary',
    'Help with my budget',
    'What should I do if it rains?'
  ]) {
    testWidgets('quick chip sends its own question: $suggestion',
        (tester) async {
      final api = ActionApi();
      await frame(tester, ChatTab(api: api));
      await tap(tester, find.widgetWithText(ActionChip, suggestion));
      expect(api.posts.single['body']['message'], suggestion);
      expect(api.posts.single['path'], '/api/fr11/chat');
    });
  }
  for (final tool in ['Flights', 'Hotels', 'Packing', 'Weather', 'Trips']) {
    testWidgets(
        'travel tool $tool opens the correct existing screen with the same API',
        (tester) async {
      final api = ActionApi();
      await frame(tester, ChatTab(api: api));
      await tap(tester, find.byKey(ValueKey('chat-tool-$tool')));
      final Widget screen = switch (tool) {
        'Flights' => tester.widget<FlightScreen>(find.byType(FlightScreen)),
        'Hotels' => tester.widget<HotelScreen>(find.byType(HotelScreen)),
        'Packing' => tester.widget<PackingTripSelectorScreen>(
            find.byType(PackingTripSelectorScreen)),
        'Weather' => tester.widget<WeatherScreen>(find.byType(WeatherScreen)),
        _ => tester.widget<TripsTab>(find.byType(TripsTab)),
      };
      final dynamic selected = screen;
      expect(identical(selected.api, api), isTrue);
      expect(api.posts, isEmpty);
      Navigator.of(tester.element(find.byType(screen.runtimeType))).pop();
      await tester.pumpAndSettle();
      expect(find.byType(ChatTab), findsOneWidget);
    });
  }
  testWidgets(
      'Trips tool selects the existing root tab when a shell is present',
      (tester) async {
    final selected = <AppShellTab>[];
    final api = ActionApi();
    await frame(
        tester,
        AppShellNavigation(
            selectedTab: AppShellTab.assistant,
            onSelect: selected.add,
            child: ChatTab(api: api)));
    await tap(tester, find.byKey(const ValueKey('chat-tool-Trips')));
    expect(selected, [AppShellTab.trips]);
    expect(find.byType(TripsTab), findsNothing);
    expect(api.posts, isEmpty);
  });
  for (final id in ['A', 'B']) {
    testWidgets(
        'destination Details preserves selected $id and API and returns to the same draft',
        (tester) async {
      final api = ActionApi(recommendations: true, draft: true);
      await frame(tester, ChatTab(api: api));
      await tap(tester, find.byKey(ValueKey('chat-place-details-$id')));
      final screen = tester.widget<DestinationDetailsScreen>(
          find.byType(DestinationDetailsScreen));
      expect(screen.initialDestination['destinationId'], id);
      expect(identical(screen.api, api), isTrue);
      expect(api.gets, contains('/api/fr3/destinations/$id'));
      expect(api.posts, isEmpty);
      Navigator.of(tester.element(find.byType(DestinationDetailsScreen))).pop();
      await tester.pumpAndSettle();
      final dynamic state = tester.state(find.byType(ChatTab));
      expect(state.activeSessionId, 'session-1');
      expect(state.planningState['activePlan']['startDate'], '2026-12-12');
    });
    testWidgets(
        'package $id opens the matching authoritative full public record, never the partial summary',
        (tester) async {
      final api = ActionApi(recommendations: true, draft: true);
      await frame(tester, ChatTab(api: api));
      await tap(tester, find.byKey(ValueKey('chat-package-package-$id')));
      final screen = tester.widget<TourismPackageDetailsScreen>(
          find.byType(TourismPackageDetailsScreen));
      expect(screen.item, fullPackage('package-$id'));
      expect(identical(screen.api, api), isTrue);
      expect(api.gets.where((p) => p == '/api/public/tourism-packages'),
          hasLength(1));
      expect(screen.item['licenseNumber'], isNull);
      expect(screen.item['adultPrice'], 220);
      Navigator.of(tester.element(find.byType(TourismPackageDetailsScreen)))
          .pop();
      await tester.pumpAndSettle();
      final dynamic state = tester.state(find.byType(ChatTab));
      expect(state.messages, hasLength(1));
      expect(
          state.stalePlan(
              Map<String, dynamic>.from(state.planningState['activePlan'])),
          isFalse);
    });
  }
  for (final unavailable in [false, true]) {
    testWidgets(
        'package fetch ${unavailable ? 'withdrawn' : 'failed'} never opens an incomplete or unrelated package',
        (tester) async {
      final api = ActionApi(recommendations: true);
      if (unavailable) {
        api.packages = [];
      } else {
        api.failPackages = true;
      }
      await frame(tester, ChatTab(api: api));
      await tap(tester, find.byKey(const ValueKey('chat-package-package-B')));
      expect(find.byType(TourismPackageDetailsScreen), findsNothing);
      expect(api.posts, isEmpty);
      final button = tester.widget<FilledButton>(
          find.byKey(const ValueKey('chat-package-package-B')));
      expect(button.onPressed, isNotNull);
    });
  }
  testWidgets('pending package fetch blocks duplicate/wrong-item navigation',
      (tester) async {
    final api = ActionApi(recommendations: true)
      ..packageGate = Completer<dynamic>();
    await frame(tester, ChatTab(api: api));
    final selected = find.byKey(const ValueKey('chat-package-package-B'));
    await reveal(tester, selected);
    await tester.tap(selected);
    await tester.pump();
    expect(tester.widget<FilledButton>(selected).onPressed, isNull);
    expect(api.gets.where((p) => p == '/api/public/tourism-packages'),
        hasLength(1));
    expect(
        tester
            .widget<FilledButton>(
                find.byKey(const ValueKey('chat-package-package-A')))
            .onPressed,
        isNull);
    api.packageGate!.complete({'items': api.packages});
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<TourismPackageDetailsScreen>(
                find.byType(TourismPackageDetailsScreen))
            .item['id'],
        'package-B');
  });
  testWidgets(
      'Add to Trip keeps selected B, chosen trip and chosen day and pricing evidence',
      (tester) async {
    final api = ActionApi(recommendations: true);
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-add-place-B')));
    await tap(tester, find.text('Trip beta'));
    await tap(tester, find.byKey(const ValueKey('day-option-2')));
    expect(api.posts, hasLength(1));
    expect(api.posts.single['path'], '/api/fr5/itineraries/beta/activities');
    expect(api.posts.single['body'], containsPair('destinationId', 'B'));
    expect(api.posts.single['body']['dayNo'], 2);
    expect(api.posts.single['body']['unitPrice'], 20);
    expect(api.posts.single['body']['openingHours'], '09:00-17:00');
    expect(api.posts.single['body']['gps_coordinates'],
        place('B')['gps_coordinates']);
  });
  testWidgets('Add to Trip cancellation does not post any activity',
      (tester) async {
    final api = ActionApi(recommendations: true);
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-add-place-A')));
    Navigator.of(tester.element(find.text('Add to a trip'))).pop();
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    await tap(tester, find.byKey(const ValueKey('chat-add-place-A')));
    await tap(tester, find.text('Trip alpha'));
    Navigator.of(tester.element(find.text('Select Trip Day'))).pop();
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
  });
  testWidgets(
      'Add to Trip creation returns the created trip and resumes with the original place',
      (tester) async {
    final api = ActionApi(recommendations: true)..trips = [];
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-add-place-B')));
    await tap(tester, find.text('Go to Trips'));
    expect(tester.widget<TripsTab>(find.byType(TripsTab)).selectForActivity,
        isTrue);
    await tap(tester, find.byTooltip('More trip actions'));
    await tap(tester, find.text('Add trip manually'));
    expect(
        tester
            .widget<TextField>(find.widgetWithText(TextField, 'Destination'))
            .controller!
            .text,
        'George Town');
    await tester.enterText(find.widgetWithText(TextField, 'Trip title'),
        'Created for selected place');
    await tap(tester, find.widgetWithText(FilledButton, 'Create trip'));
    await tap(tester, find.byKey(const ValueKey('day-option-2')));
    expect(api.posts.map((p) => p['path']).toList(), [
      '/api/fr5/itineraries',
      '/api/fr5/itineraries/created-trip/activities'
    ]);
    expect(api.posts.last['body']['destinationId'], 'B');
    expect(api.posts.last['body']['dayNo'], 2);
    expect(find.byType(ChatTab), findsOneWidget);
  });
  testWidgets(
      'Add to Trip creation cancellation retains conversation and makes no writes',
      (tester) async {
    final api = ActionApi(recommendations: true)..trips = [];
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-add-place-A')));
    await tap(tester, find.text('Go to Trips'));
    Navigator.of(tester.element(find.byType(TripsTab))).pop();
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    expect(find.byType(ChatTab), findsOneWidget);
  });
  testWidgets('failed Add to Trip never claims success and can be retried',
      (tester) async {
    final api = ActionApi(recommendations: true)..failActivity = true;
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-add-place-A')));
    await tap(tester, find.text('Trip alpha'));
    await tap(tester, find.byKey(const ValueKey('day-option-2')));
    expect(api.posts.single['path'], '/api/fr5/itineraries/alpha/activities');
    expect(find.textContaining('Added to Trip'), findsNothing);
    expect(
        tester
            .widget<TextButton>(find.byKey(const ValueKey('chat-add-place-A')))
            .onPressed,
        isNotNull);
    api.failActivity = false;
    await tap(tester, find.byKey(const ValueKey('chat-add-place-A')));
    await tap(tester, find.text('Trip alpha'));
    await tap(tester, find.byKey(const ValueKey('day-option-2')));
    expect(api.posts, hasLength(2));
    expect(api.addedActivities, hasLength(1));
    expect(api.addedActivities.single['body']['destinationId'], 'A');
    expect(api.addedActivities.single['body']['dayNo'], 2);
  });
  testWidgets(
      'cancelling place A creation cannot attach A when B is selected later',
      (tester) async {
    final api = ActionApi(recommendations: true)..trips = [];
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-add-place-A')));
    await tap(tester, find.text('Go to Trips'));
    Navigator.of(tester.element(find.byType(TripsTab))).pop();
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    api.trips = [trip('beta')];
    await tap(tester, find.byKey(const ValueKey('chat-add-place-B')));
    await tap(tester, find.text('Trip beta'));
    await tap(tester, find.byKey(const ValueKey('day-option-3')));
    expect(api.posts, hasLength(1));
    expect(api.posts.single['path'], '/api/fr5/itineraries/beta/activities');
    expect(api.posts.single['body']['destinationId'], 'B');
    expect(api.posts.single['body']['dayNo'], 3);
  });
  testWidgets(
      'rapid Add to Trip taps create one picker and one activity request',
      (tester) async {
    final api = ActionApi(recommendations: true)
      ..tripGate = Completer<dynamic>();
    await frame(tester, ChatTab(api: api));
    final button = find.byKey(const ValueKey('chat-add-place-B'));
    await reveal(tester, button);
    await tester.tap(button);
    await tester.pump();
    expect(tester.widget<TextButton>(button).onPressed, isNull);
    await tester.tap(button);
    api.tripGate!.complete({'items': api.trips});
    await tester.pumpAndSettle();
    expect(find.text('Add to a trip'), findsOneWidget);
    expect(
        api.gets.where((path) => path == '/api/fr5/itineraries'), hasLength(1));
    await tap(tester, find.text('Trip beta'));
    await tap(tester, find.byKey(const ValueKey('day-option-2')));
    expect(api.posts, hasLength(1));
    expect(api.addedActivities, hasLength(1));
    expect(api.addedActivities.single['body']['destinationId'], 'B');
  });
  testWidgets('incomplete draft has no save side effect', (tester) async {
    final api = ActionApi(draft: true);
    api.sessions.single['messages'][0]['tripPlan']['coverageStatus'] =
        'partial';
    await frame(tester, ChatTab(api: api));
    await reveal(tester, find.text('Save plan to Trips'));
    await tester.tap(find.text('Save plan to Trips'));
    await tester.pumpAndSettle();
    expect(find.text('Save this trip?'), findsNothing);
    expect(api.posts, isEmpty);
  });
  testWidgets(
      'Save Plan uses the active draft and confirmation rather than a recommendation action',
      (tester) async {
    final api = ActionApi(recommendations: true, draft: true);
    final expected = copy(api.sessions.single['planningState']['activePlan']);
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.text('Save plan to Trips'));
    expect(api.posts, isEmpty);
    await tap(tester, find.text('Keep editing'));
    expect(api.posts, isEmpty);
    await tap(tester, find.text('Save plan to Trips'));
    await tap(tester, find.text('Confirm save'));
    expect(api.posts.single['path'], '/api/fr11/save-plan');
    expect(api.posts.single['body']['plan'], expected);
    expect(api.posts.single['body']['sessionId'], 'session-1');
    await tap(tester, find.text('Open saved trip in Trips'));
    expect(find.byType(TripsTab), findsOneWidget);
    expect(api.posts, hasLength(1));
  });
  testWidgets('stale draft cannot be saved by tapping its disabled action',
      (tester) async {
    final api = ActionApi(draft: true);
    api.sessions.single['planningState']['activePlan']['draftId'] =
        'different-current-draft';
    await frame(tester, ChatTab(api: api));
    await reveal(tester, find.text('Save plan to Trips'));
    await tester.tap(find.text('Save plan to Trips'));
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
    expect(find.text('Save this trip?'), findsNothing);
  });
  testWidgets(
      'send and Retry message use the exact failed question and never navigate',
      (tester) async {
    final api = ActionApi()..failChat = true;
    await frame(tester, ChatTab(api: api));
    await tester.enterText(find.byType(TextField), 'Show the itinerary');
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await tester.pumpAndSettle();
    expect(find.text('Message not sent'), findsOneWidget);
    api.failChat = false;
    await tap(tester, find.text('Retry message'));
    expect(api.posts.map((p) => p['body']['message']).toList(),
        ['Show the itinerary', 'Show the itinerary']);
    expect(api.posts.every((p) => p['path'] == '/api/fr11/chat'), isTrue);
  });
  testWidgets('new chat uses its own endpoint and never pops a pushed ChatTab',
      (tester) async {
    final api = ActionApi();
    await frame(
        tester,
        Builder(
            builder: (context) => Scaffold(
                body: TextButton(
                    onPressed: () => Navigator.push(context,
                        MaterialPageRoute(builder: (_) => ChatTab(api: api))),
                    child: const Text('Open chat')))));
    await tap(tester, find.text('Open chat'));
    await tap(tester, find.byTooltip('New chat'));
    expect(find.byType(ChatTab), findsOneWidget);
    expect(api.posts.single['path'], '/api/fr11/sessions');
  });
  testWidgets(
      'drawer new chat closes only the drawer and clears the previous draft',
      (tester) async {
    final api = ActionApi(draft: true);
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byTooltip('Open navigation menu'));
    await tap(tester, find.widgetWithText(FilledButton, 'New chat'));
    expect(api.posts.single['path'], '/api/fr11/sessions');
    expect(find.byType(ChatTab), findsOneWidget);
    final dynamic state = tester.state(find.byType(ChatTab));
    expect(state.planningState, isEmpty);
    expect(state.activeSessionId, 'new-session');
  });
  testWidgets('pending new-chat request ignores duplicate taps',
      (tester) async {
    final api = ActionApi()..newChatGate = Completer<dynamic>();
    await frame(tester, ChatTab(api: api));
    await tester.tap(find.byTooltip('New chat'));
    await tester.pump();
    await tester.tap(find.byTooltip('New chat'));
    await tester.pump();
    expect(api.posts, hasLength(1));
    api.newChatGate!.complete({
      'session': {'id': 'new-session', 'messages': []}
    });
    await tester.pumpAndSettle();
    expect(find.byType(ChatTab), findsOneWidget);
    expect(api.posts.single['path'], '/api/fr11/sessions');
  });
  testWidgets(
      'package recommendation without a stable ID is disabled, not guessed',
      (tester) async {
    final api = ActionApi(recommendations: true);
    api.sessions.single['messages'][0]['packages'] = [
      {'title': 'Missing identity'}
    ];
    await frame(tester, ChatTab(api: api));
    await reveal(tester, find.byKey(const ValueKey('chat-package-')));
    expect(
        tester
            .widget<FilledButton>(find.byKey(const ValueKey('chat-package-')))
            .onPressed,
        isNull);
    await tester.tap(find.byKey(const ValueKey('chat-package-')));
    await tester.pumpAndSettle();
    expect(api.gets, isNot(contains('/api/public/tourism-packages')));
  });
  testWidgets(
      'package Trips are not offered as editable destinations for Add to Trip',
      (tester) async {
    final api = ActionApi(recommendations: true)
      ..trips = [
        {...trip('purchased'), 'tripType': 'package'}
      ];
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-add-place-B')));
    await tap(tester, find.text('Go to Trips'));
    final segment =
        tester.widget<SegmentedButton<int>>(find.byType(SegmentedButton<int>));
    expect(segment.segments.last.enabled, isFalse);
    expect(api.posts, isEmpty);
    Navigator.of(tester.element(find.byType(TripsTab))).pop();
    await tester.pumpAndSettle();
    expect(api.posts, isEmpty);
  });
  testWidgets(
      'history opens the selected session and delete requires confirmation for that ID',
      (tester) async {
    final api = ActionApi(recommendations: true, draft: true);
    api.sessions.add({
      'id': 'session-2',
      'title': 'Second session',
      'planningState': {},
      'messages': [
        {'message': 'Second question', 'reply': 'Second reply'}
      ]
    });
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byTooltip('Open navigation menu'));
    await tap(tester, find.text('Second session'));
    expect(api.gets, contains('/api/fr11/sessions/session-2'));
    expect(find.text('Second reply'), findsOneWidget);
    await tap(tester, find.byTooltip('Open navigation menu'));
    final row = find
        .ancestor(
            of: find.text('Second session'), matching: find.byType(ListTile))
        .first;
    await tap(
        tester,
        find.descendant(
            of: row, matching: find.byType(PopupMenuButton<String>)));
    await tap(tester, find.text('Delete chat'));
    await tap(tester, find.text('Keep chat'));
    expect(api.deletes, isEmpty);
    await tap(
        tester,
        find.descendant(
            of: row, matching: find.byType(PopupMenuButton<String>)));
    await tap(tester, find.text('Delete chat'));
    await tap(tester, find.widgetWithText(FilledButton, 'Delete chat'));
    expect(api.deletes, ['/api/fr11/sessions/session-2']);
    final dynamic state = tester.state(find.byType(ChatTab));
    expect(state.planningState, isEmpty);
    expect(api.sessions.single['id'], 'session-1');
  });
  testWidgets('rejected Add to Trip response cannot produce a success message',
      (tester) async {
    final api = ActionApi(recommendations: true)..rejectActivity = true;
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-add-place-B')));
    await tap(tester, find.text('Trip beta'));
    await tap(tester, find.byKey(const ValueKey('day-option-2')));
    expect(api.posts.single['path'], '/api/fr5/itineraries/beta/activities');
    expect(find.textContaining('Added to Trip'), findsNothing);
    expect(find.text('The place was not added.'), findsOneWidget);
  });
  testWidgets(
      'drawer new-chat icon invokes session creation without sending a prompt',
      (tester) async {
    final api = ActionApi(draft: true);
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byTooltip('Open navigation menu'));
    await tap(
        tester,
        find.descendant(
            of: find.byType(Drawer), matching: find.byTooltip('New chat')));
    expect(api.posts.single['path'], '/api/fr11/sessions');
    expect(find.byType(ChatTab), findsOneWidget);
  });
  testWidgets('keyboard submit sends the exact entered question',
      (tester) async {
    final api = ActionApi();
    await frame(tester, ChatTab(api: api));
    await tester.enterText(find.byType(TextField), 'Show my plan');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(api.posts.single['path'], '/api/fr11/chat');
    expect(api.posts.single['body']['message'], 'Show my plan');
  });
  testWidgets(
      'new chat clears a previous failed-message retry instead of sending it to the new session',
      (tester) async {
    final api = ActionApi()..failChat = true;
    await frame(tester, ChatTab(api: api));
    await tester.enterText(find.byType(TextField), 'Old session question');
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await tester.pumpAndSettle();
    expect(find.text('Retry message'), findsOneWidget);
    await tap(tester, find.byTooltip('New chat'));
    expect(find.text('Retry message'), findsNothing);
    expect(find.text('Message not sent'), findsNothing);
    final dynamic state = tester.state(find.byType(ChatTab));
    expect(state.failedMessage, isNull);
    expect(state.activeSessionId, 'new-session');
    expect(api.posts.map((post) => post['path']).toList(),
        ['/api/fr11/chat', '/api/fr11/sessions']);
  });
  testWidgets('loading session retry only rereads chats', (tester) async {
    final api = ActionApi()..failSessions = true;
    await frame(tester, ChatTab(api: api));
    api.failSessions = false;
    await tap(tester, find.text('Try again'));
    expect(api.gets.where((p) => p == '/api/fr11/sessions'), hasLength(2));
    expect(api.posts, isEmpty);
  });
  testWidgets(
      'package day selectors, full descriptions, operator and pricing controls keep their own data',
      (tester) async {
    final api = ActionApi();
    final package = fullPackage('package-B');
    await frame(tester, TourismPackageDetailsScreen(item: package, api: api),
        width: 390);
    await tap(tester, find.text('Itinerary'));
    await tap(tester, find.widgetWithText(ChoiceChip, 'Day 2'));
    expect(find.text('Day 1 · Day title package-B 1'), findsNothing);
    final description = (package['itineraryDays'] as List)[1]['activities'][0]
        ['description'] as String;
    await reveal(tester, find.text('Day 2 · Day title package-B 2'));
    if (find.text(description).evaluate().isEmpty) {
      await tap(tester, find.text('Day 2 · Day title package-B 2'));
    }
    await tap(tester, find.text('Read more'));
    expect(tester.widget<Text>(find.text(description)).maxLines, isNull);
    await tap(tester, find.widgetWithText(ChoiceChip, 'All Days'));
    await reveal(tester, find.text('Day 1 · Day title package-B 1'));
    expect(find.text('Day 1 · Day title package-B 1'), findsOneWidget);
    await tap(tester, find.text('Overview'));
    await reveal(tester, find.text('Operator package-B'));
    expect(find.text('Operator package-B'), findsOneWidget);
    expect(find.textContaining('License:'), findsNothing);
    await tap(tester, find.text("What's Included"));
    await reveal(tester, find.text('Included service package-B'));
    expect(find.text('Included service package-B'), findsOneWidget);
    await reveal(tester, find.text('Excluded service package-B'));
    expect(find.text('Excluded service package-B'), findsOneWidget);
    expect(find.text('Included service package-A'), findsNothing);
    await tap(tester, find.text('Policies'));
    await reveal(tester, find.text('Actual public booking terms package-B'));
    expect(find.text('Actual public booking terms package-B'), findsOneWidget);
    expect(api.posts, isEmpty);
    await tap(tester, find.byKey(const ValueKey('package-book-now-cta')));
    expect(api.posts, isEmpty);
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('package-departure-date')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('2030-12-12').last);
    await tester.pumpAndSettle();
    await tap(tester, find.byKey(const ValueKey('package-checkout-btn')));
    final post = api.posts.single;
    expect(post['path'], '/api/fr15/package-checkout-attempts');
    expect(post['body']['packageId'], 'package-B');
    expect(post['body']['participants'], {'adults': 2, 'children': 0});
    expect(post['body']['departureDate'], '2030-12-12');
  });
}
