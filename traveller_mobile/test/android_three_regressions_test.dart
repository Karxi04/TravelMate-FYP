import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/travel_dates.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_airport_catalog.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';

Map<String, dynamic> contract() => jsonDecode(
        File('test/fixtures/fr11_guided_contract.json').readAsStringSync())
    as Map<String, dynamic>;

class ContractApi extends ApiService {
  final response = contract();
  final flightQueries = <Map<String, String>>[];
  Completer<dynamic>? save;
  bool failSave = false;
  int saves = 0;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr11/sessions')
      return {
        'items': [response['session']]
      };
    if (path.startsWith('/api/fr11/sessions/')) return response;
    if (path.endsWith('/flights/search')) {
      flightQueries.add(query!);
      return {'items': []};
    }
    return {'items': []};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path.endsWith('save-plan')) {
      saves++;
      if (failSave) throw Exception('Synthetic save failure');
      if (save != null) return save!.future;
      return {
        'ok': true,
        'itinerary': {'id': 'persisted-trip', 'title': 'Johor trip'}
      };
    }
    return response;
  }
}

StandaloneApiService local() {
  final plan = contract()['item']['tripPlan'] as Map;
  final places = (plan['activities'] as List)
      .map((a) => {...a as Map, 'title': a['activityName']})
      .toList();
  return StandaloneApiService(uidOverride: 'synthetic', memoryStore: {
    'travelmate_synthetic_preferences': jsonEncode({
      'interests': ['Culture'],
      'travelPace': 'relaxed'
    }),
    'travelmate_synthetic_last_search_results': jsonEncode(places),
  });
}

Future<void> frame(WidgetTester tester, Widget widget) async {
  tester.view.physicalSize = const Size(320, 1000);
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = 1.2;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.platformDispatcher.clearTextScaleFactorTestValue();
  });
  await tester.pumpWidget(MaterialApp(home: widget));
  await tester.pumpAndSettle();
}

Future<void> show(WidgetTester tester, Finder target) async {
  if (target.evaluate().isNotEmpty) {
    await tester.ensureVisible(target.first);
    await tester.pumpAndSettle();
    return;
  }
  final scroll = find
      .byWidgetPredicate(
          (w) => w is Scrollable && w.axisDirection == AxisDirection.down)
      .first;
  tester.state<ScrollableState>(scroll).position.jumpTo(0);
  await tester.pumpAndSettle();
  for (var i = 0; i < 70; i++) {
    if (target.evaluate().isNotEmpty) {
      await tester.ensureVisible(target.first);
      await tester.pumpAndSettle();
      return;
    }
    await tester.drag(scroll, const Offset(0, -250));
    await tester.pumpAndSettle();
  }
  fail('Missing $target');
}

void main() {
  for (final text in [
    '12 Dec until 16 Dec',
    '12 Dec to 16 Dec',
    '12 December until 16 December',
    '12/12/2026 to 16/12/2026',
    '2026-12-12 to 2026-12-16',
    '12 to 16 December',
    '12–16 Dec',
    'from 12 Dec to 16 Dec'
  ]) {
    test('standalone date grammar: $text', () {
      final range =
          parseTravelDateRange(text, today: DateTime.utc(2026, 11, 5))!;
      expect(range.$1, DateTime.utc(2026, 12, 12));
      expect(range.$2, DateTime.utc(2026, 12, 16));
      expect(range.$2.difference(range.$1).inDays, 4);
    });
  }
  for (final text in [
    '31 Feb 2030 to 3 Mar 2030',
    '16 Dec 2030 to 12 Dec 2030',
    '01/02/2030 to 03/04/2030',
    '1 Dec 2020 to 3 Dec 2020',
    '12 Dec until'
  ]) {
    test(
        'standalone rejects invalid or ambiguous dates: $text',
        () => expect(
            () => parseTravelDateRange(text, today: DateTime.utc(2026, 11, 5)),
            throwsFormatException));
  }
  test('standalone rollover and next-upcoming year', () {
    expect(
        parseTravelDateRange('28 Dec to 2 Jan',
                today: DateTime.utc(2026, 11, 5))!
            .$2,
        DateTime.utc(2027, 1, 2));
    expect(
        parseTravelDateRange('12 Dec to 16 Dec',
                today: DateTime.utc(2026, 12, 20))!
            .$1,
        DateTime.utc(2027, 12, 12));
  });
  test(
      'actual standalone conversation keeps dates, preview, followup, save and reopen',
      () async {
    final api = local();
    Map<String, dynamic>? session;
    Future<dynamic> send(String message) async {
      final response = await api.post('/api/fr11/chat', {
        'message': message,
        'guidedPlanning': true,
        if (session != null) 'sessionId': session!['id']
      });
      session = Map<String, dynamic>.from(response['session']);
      return response;
    }

    await send('I want to travel to Johor');
    var response = await send('12 Dec until 16 Dec, 2 days');
    expect(session!['planningState']['days'], 5);
    expect(response['reply'], contains('4 nights'));
    await send('RM1000');
    response = await send('2 travellers');
    final plan = Map<String, dynamic>.from(response['item']['tripPlan']);
    expect(plan['tripDays'], 5);
    expect(plan['nights'], 4);
    expect(plan['destinationArea'], 'Johor');
    expect((plan['activities'] as List).map((a) => a['dayNo']).toSet(),
        {1, 2, 3, 4, 5});
    expect((await api.get('/api/fr5/itineraries'))['items'], isEmpty);
    final weather = await send('What is the weather for my trip?');
    expect(weather['item']['tripPlan'], isNull);
    expect(session!['planningState']['activePlan'], plan);
    response = await send('where the trips');
    expect(response['item']['tripPlan'], plan);
    final payload = {
      'sessionId': session!['id'],
      'confirmed': true,
      'plan': plan
    };
    final saved = await api.post('/api/fr11/save-plan', payload);
    final again = await api.post('/api/fr11/save-plan', payload);
    expect(again['id'], saved['id']);
    final trips = (await api.get('/api/fr5/itineraries'))['items'] as List;
    expect(trips, hasLength(1));
    expect(trips.single['startDate'], plan['startDate']);
    expect(trips.single['endDate'], plan['endDate']);
    response = await send('show my plan');
    expect(response['item']['savedTripId'], saved['id']);
    response = await send('Actually change to 14 Dec until 18 Dec');
    expect(response['item']['tripPlan']['startDate'], endsWith('-12-14'));
    await expectLater(
        api.post('/api/fr11/save-plan', payload), throwsException);
  });
  for (final duration in ['5 days', '4 nights']) {
    test('standalone duration $duration asks for dates without inventing them',
        () async {
      final response = await local().post('/api/fr11/chat',
          {'message': 'Plan Johor $duration', 'guidedPlanning': true});
      expect(response['session']['planningState']['days'], 5);
      expect(response['session']['planningState']['startDate'], isNull);
      expect(response['reply'], contains('calendar dates'));
      expect(response['item']['tripPlan'], isNull);
    });
  }
  testWidgets(
      'actual Flask response renders all five dated expandable days and save action',
      (tester) async {
    final api = ContractApi();
    await frame(tester, ChatTab(api: api));
    for (var day = 1; day <= 5; day++) {
      final title = find.text('Day $day — 2026-12-${day + 11}');
      await show(tester, title);
      expect(title, findsOneWidget);
      if (day != 1) {
        await tester.tap(title);
        await tester.pumpAndSettle();
      }
      await show(tester,
          find.textContaining('Johor test attraction ${(day - 1) * 3}'));
    }
    await show(tester, find.text('Save plan to Trips'));
    expect(find.text('Save plan to Trips'), findsOneWidget);
    expect(find.text('Using saved travel guidance'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'save confirmation, pending taps, confirmed persistence and saved action',
      (tester) async {
    final api = ContractApi()..save = Completer<dynamic>();
    await frame(tester, ChatTab(api: api));
    await show(tester, find.text('Save plan to Trips'));
    await tester.tap(find.text('Save plan to Trips'));
    await tester.pumpAndSettle();
    expect(api.saves, 0);
    await tester.tap(find.text('Keep editing'));
    await tester.pumpAndSettle();
    expect(api.saves, 0);
    await tester.tap(find.text('Save plan to Trips'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm save'));
    await tester.pump();
    final dynamic state = tester.state(find.byType(ChatTab));
    state.savePlan(Map<String, dynamic>.from(api.response['item']['tripPlan']));
    await tester.pump();
    expect(api.saves, 1);
    expect(find.textContaining('saved to Trips.'), findsNothing);
    api.save!.complete({
      'ok': true,
      'itinerary': {'id': 'persisted-trip', 'title': 'Johor trip'}
    });
    await tester.pumpAndSettle();
    await show(tester, find.text('Open saved trip in Trips'));
    expect(api.saves, 1);
    expect(tester.takeException(), isNull);
  });
  testWidgets('failed save leaves draft available and never claims success',
      (tester) async {
    final api = ContractApi()..failSave = true;
    await frame(tester, ChatTab(api: api));
    await show(tester, find.text('Save plan to Trips'));
    await tester.tap(find.text('Save plan to Trips'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm save'));
    await tester.pumpAndSettle();
    expect(api.saves, 1);
    expect(find.textContaining('saved to Trips.'), findsNothing);
    expect(find.text('Open saved trip in Trips'), findsNothing);
    expect(find.text('Save plan to Trips'), findsOneWidget);
  });
  testWidgets(
      'all Malaysian airports reachable by IATA; international names excluded; city/state aliases work',
      (tester) async {
    final api = ContractApi();
    await frame(tester, FlightScreen(api: api));
    final from = find.byType(TextField).first;
    for (final entry in flightAirportLabels.entries) {
      await tester.enterText(from, entry.key);
      await tester.pumpAndSettle();
      expect(find.text('${entry.value} (${entry.key})'), findsOneWidget);
    }
    for (final query in ['London', 'Heathrow', 'JFK', 'Narita']) {
      await tester.enterText(from, query);
      await tester.pumpAndSettle();
      expect(find.byType(ListTile), findsNothing);
    }
    for (final entry in {
      'Penang': 'PEN',
      'Johor': 'JHB',
      'Kota Kinabalu': 'BKI',
      'Subang': 'SZB',
      'Sarawak': 'MYY',
      'Sultan Haji Ahmad Shah': 'KUA'
    }.entries) {
      await tester.enterText(from, entry.key);
      await tester.pumpAndSettle();
      final option =
          find.text('${flightAirportLabels[entry.value]} (${entry.value})');
      if (option.evaluate().isEmpty) {
        final popup = find
            .ancestor(
                of: find.byType(ListTile).first,
                matching: find.byType(Scrollable))
            .first;
        final position = tester.state<ScrollableState>(popup).position;
        for (var step = 0; step <= 40 && option.evaluate().isEmpty; step++) {
          position.jumpTo((step * 100.0).clamp(0, position.maxScrollExtent));
          await tester.pumpAndSettle();
        }
      }
      expect(option, findsOneWidget);
    }
    await tester.enterText(from, 'Subang');
    await tester.pumpAndSettle();
    await tester.tap(find.text('${flightAirportLabels['SZB']} (SZB)'));
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(FlightScreen));
    expect(state.from.text, 'SZB');
    state.to.text = 'KBR';
    await state.search();
    await tester.pumpAndSettle();
    expect(api.flightQueries.single['departure_id'], 'SZB');
    state.to.text = 'JFK';
    await state.search();
    await tester.pumpAndSettle();
    expect(api.flightQueries, hasLength(1));
    expect(tester.takeException(), isNull);
  });
}
