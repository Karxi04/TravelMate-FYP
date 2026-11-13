import 'dart:async';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/android_push_service.dart';
import 'package:travelmate_traveller/services/trip_reminders.dart';
import 'package:travelmate_traveller/modules/traveller_notifications/notification_center.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';

Map<String, dynamic> trip(
        {String date = '2030-11-12', String owner = 'owner'}) =>
    {
      'id': 'penang-trip',
      'travellerId': owner,
      'title': 'Penang trip',
      'startDate': date,
      'endDate': date
    };

class TripsApi extends ApiService {
  List items = [trip()];
  bool offline = false;
  int listReads = 0;
  Completer<dynamic>? gate;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries') listReads++;
    if (offline) throw StateError('private connection details');
    if (gate != null) return gate!.future;
    return path == '/api/fr5/itineraries'
        ? {'ok': true, 'items': items}
        : {'ok': true, 'itinerary': items.single};
  }
}

class Alarms extends TripReminderPlatform {
  List<Map<String, dynamic>> items = [];
  int clears = 0;
  Map? tap;
  String? owner;
  @override
  Future<void> adoptOwner(String next) async {
    if (owner != next) {
      await clear();
      owner = next;
    }
  }

  @override
  Future<bool> available() async => true;
  @override
  Future<void> clear() async {
    clears++;
    items = [];
  }

  @override
  Future<void> replace(String owner, List<Map<String, dynamic>> next) async {
    items = next;
  }

  @override
  Future<Map?> target(String owner, String id) async => tap;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('normal builds enable Android push by default',
      () => expect(pushBuildEnabled, isTrue));
  test('real calendar date schedules at approved 9 AM Malaysia on previous day',
      () {
    final plan = tripReminderPlan('owner', [trip()], DateTime.utc(2030, 11, 1));
    expect(
        DateTime.fromMillisecondsSinceEpoch(plan.single['triggerAt'],
            isUtc: true),
        DateTime.utc(2030, 11, 11, 1));
    expect(
        DateTime.fromMillisecondsSinceEpoch(plan.single['expiresAt'],
            isUtc: true),
        DateTime.utc(2030, 11, 11, 16));
    expect(plan.single['title'], 'Penang trip');
    expect(plan.single['screen'], 'trip');
    expect(plan.single['id'], matches(RegExp(r'^[a-f0-9]{64}$')));
  });
  test(
      'stable identity deduplicates repeated sync; changed date creates a replacement',
      () {
    final a = tripReminderPlan('owner', [trip()], DateTime.utc(2030, 1, 1));
    expect(a, tripReminderPlan('owner', [trip()], DateTime.utc(2030, 1, 2)));
    expect(
        a.single['id'],
        isNot(tripReminderPlan(
                'owner', [trip(date: '2030-11-13')], DateTime.utc(2030, 1, 2))
            .single['id']));
  });
  test(
      'foreign, cancelled, deleted, declined, invalid and started trips are excluded',
      () {
    final cases = [
      trip(owner: 'foreign'),
      {...trip(), 'status': 'cancelled'},
      {...trip(), 'status': 'archived'},
      {...trip(), 'deletedAt': 'recorded'},
      {...trip(), 'fulfillmentStatus': 'fulfillment_declined'},
      trip(date: '2030-02-30'),
      trip(date: 'nonsense'),
      trip(date: '2020-01-01'),
      trip(date: '2030-01-01'),
      {...trip(), 'endDate': '2020-01-01'}
    ];
    expect(tripReminderPlan('owner', cases, DateTime.utc(2030, 1, 1)), isEmpty);
  });
  test('package trip targets retain their screen and actual ID', () {
    expect(
        tripReminderPlan(
                'owner',
                [
                  {...trip(), 'tripType': 'package'}
                ],
                DateTime.utc(2030, 1, 1))
            .single['screen'],
        'package_trip');
  });
  test(
      'save/reopen, date changes and cancellation replace the complete native plan',
      () async {
    final api = TripsApi(), alarms = Alarms();
    final service = TripReminders(api: api, platform: alarms);
    await service.changeOwner('owner');
    await service.refresh('owner', allowed: true);
    final first = alarms.items.single['id'];
    await service.refresh('owner', allowed: true);
    expect(alarms.items.single['id'], first);
    api.items = [trip(date: '2030-11-13')];
    await service.refresh('owner', allowed: true);
    expect(alarms.items.single['id'], isNot(first));
    api.items = [
      {...trip(), 'status': 'cancelled'}
    ];
    await service.refresh('owner', allowed: true);
    expect(alarms.items, isEmpty);
    api.items = [];
    await service.refresh('owner', allowed: true);
    expect(alarms.items, isEmpty);
  });
  test('Trips response refreshes owned alarms without a second itinerary read',
      () async {
    final api = TripsApi(), alarms = Alarms();
    final service = TripReminders(api: api, platform: alarms);
    await service.changeOwner('owner');
    final response = await api.get('/api/fr5/itineraries');
    await service.refresh('owner', allowed: true, trips: [
      ...response['items'] as List,
      trip(owner: 'foreign'),
    ]);
    expect(api.listReads, 1);
    expect(alarms.items.single['tripId'], 'penang-trip');

    await service.refresh('owner', allowed: true, trips: []);
    expect(api.listReads, 1);
    expect(alarms.items, isEmpty);

    await service.refresh('owner', allowed: true);
    expect(api.listReads, 2);
    expect(alarms.items, hasLength(1));
  });
  test(
      'permission denial cancels scheduled alarms; logout clears the device plan',
      () async {
    final alarms = Alarms();
    final service = TripReminders(api: TripsApi(), platform: alarms);
    await service.changeOwner('owner');
    await service.refresh('owner', allowed: true);
    expect(alarms.items, hasLength(1));
    await service.refresh('owner', allowed: false);
    expect(alarms.items, isEmpty);
    await service.refresh('owner', allowed: true);
    await service.changeOwner(null);
    expect(alarms.items, isEmpty);
  });
  test('offline refresh preserves the previously acknowledged native schedule',
      () async {
    final api = TripsApi(), alarms = Alarms();
    final service = TripReminders(api: api, platform: alarms);
    await service.changeOwner('owner');
    await service.refresh('owner', allowed: true);
    final previous = alarms.items;
    api.offline = true;
    await service.refresh('owner', allowed: true);
    expect(alarms.items, previous);
    expect(service.problem, contains('could not be refreshed'));
    expect(service.problem, isNot(contains('private')));
  });
  test('late response after account change never restores another owner alarms',
      () async {
    final api = TripsApi()..gate = Completer<dynamic>();
    final alarms = Alarms();
    final service = TripReminders(api: api, platform: alarms);
    await service.changeOwner('owner');
    final pending = service.refresh('owner', allowed: true);
    await Future<void>.delayed(Duration.zero);
    await service.changeOwner('other');
    api.gate!.complete({
      'ok': true,
      'items': [trip()]
    });
    await pending;
    expect(alarms.items, isEmpty);
  });
  test('native adapter acknowledges schedule and uses existing channel',
      () async {
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(TripReminderPlatform.channel, (call) async {
      calls.add(call);
      return call.method == 'reminderTarget' ? {'tripId': 'penang-trip'} : true;
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(TripReminderPlatform.channel, null));
    final platform = TripReminderPlatform();
    expect(await platform.available(), true);
    await platform.replace(reminderOwner('owner'), []);
    await platform.clear();
    expect(await platform.target(reminderOwner('owner'), 'a' * 64),
        {'tripId': 'penang-trip'});
    expect(calls.map((c) => c.method), [
      'remindersAvailable',
      'replaceReminders',
      'clearReminders',
      'reminderTarget'
    ]);
  });
  test(
      'local tap resolves current owned trip, rejects foreign/cancelled and account switch',
      () async {
    final api = TripsApi(), alarms = Alarms()..tap = {'tripId': 'penang-trip'};
    expect(
        await localReminderTarget('a' * 64, 'owner', api, () => 'owner',
            platform: alarms),
        {'screen': 'trip', 'tripId': 'penang-trip'});
    api.items = [
      {...trip(), 'tripType': 'package'}
    ];
    expect(
        (await localReminderTarget('a' * 64, 'owner', api, () => 'owner',
            platform: alarms))!['screen'],
        'package_trip');
    for (final row in [
      trip(owner: 'foreign'),
      {...trip(), 'status': 'cancelled'}
    ]) {
      api.items = [row];
      expect(
          await localReminderTarget('a' * 64, 'owner', api, () => 'owner',
              platform: alarms),
          isNull);
    }
    expect(
        await localReminderTarget('a' * 64, 'owner', api, () => 'other',
            platform: alarms),
        isNull);
  });
  test(
      'real tap resolver chooses the local trip screen without inventing an inbox row',
      () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            TripReminderPlatform.channel,
            (call) async => call.method == 'reminderTarget'
                ? {'tripId': 'penang-trip'}
                : null);
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(TripReminderPlatform.channel, null));
    final api = TripsApi();
    expect(
        await notificationForTap('a' * 64, api,
            owner: 'owner', currentOwner: () => 'owner'),
        isA<TripDetailsScreen>());
    api.items = [
      {...trip(), 'tripType': 'package'}
    ];
    expect(
        await notificationForTap('a' * 64, api,
            owner: 'owner', currentOwner: () => 'owner'),
        isA<PackageTripDetailsScreen>());
  });
  test(
      'successful trip mutations notify once, HTTP failures and unrelated writes do not',
      () {
    final before = ApiService.tripChanges.value;
    ApiService.decodeMutationResponse(
        '/api/fr5/itineraries/trip', http.Response('{"ok":true}', 200));
    expect(ApiService.tripChanges.value, before + 1);
    ApiService.decodeMutationResponse(
        '/api/fr10/feedback', http.Response('{"ok":true}', 200));
    expect(
        () => ApiService.decodeMutationResponse('/api/fr5/itineraries/trip',
            http.Response('{"error":"failure"}', 409)),
        throwsA(isA<ApiException>()));
    expect(ApiService.tripChanges.value, before + 1);
  });
  test('cold reopen offline retains the same-owner native alarms', () async {
    final api = TripsApi(), alarms = Alarms();
    final first = TripReminders(api: api, platform: alarms);
    await first.changeOwner('owner');
    await first.refresh('owner', allowed: true);
    final previous = alarms.items;
    api.offline = true;
    final reopened = TripReminders(api: api, platform: alarms);
    await reopened.changeOwner('owner');
    await reopened.refresh('owner', allowed: true);
    expect(alarms.items, previous);
    await reopened.changeOwner('other');
    expect(alarms.items, isEmpty);
  });
  test('signed-out cold startup clears any previous native account schedule',
      () async {
    final alarms = Alarms()
      ..owner = reminderOwner('previous')
      ..items = [
        {'id': 'old'}
      ];
    final service = TripReminders(api: TripsApi(), platform: alarms);
    await service.changeOwner(null);
    expect(alarms.items, isEmpty);
  });
  test('backend-disabled code survives the real API sanitizer', () {
    try {
      ApiService.decodeResponse(http.Response(
          '{"code":"push_disabled","error":"Android push is not configured on this backend."}',
          503));
      fail('expected API error');
    } on ApiException catch (error) {
      expect(error.code, 'push_disabled');
      expect(error.message, backendUnavailableMessage);
    }
  });
}
