import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:travelmate_traveller/main.dart';
import 'package:travelmate_traveller/core/onboarding/traveller_entry_gate.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/traveller_notifications/notification_center.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_history_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/android_push_service.dart';
import 'core_personalization_notifications_test.dart' show NoticesApi;

class TapApi extends ApiService {
  final gets = <String>[], patches = <String>[];
  String uid = 'owner';
  bool missing = false, malformed = false, failRead = false;
  Completer<dynamic>? gate;
  Map target = {'screen': 'package_trip', 'tripId': 'real-trip'};
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    gets.add(path);
    if (path.startsWith('/api/fr5/itineraries'))
      return {'ok': true, 'items': []};
    if (gate != null) return gate!.future;
    if (missing) throw const ApiException('Unavailable', 404, {});
    return {
      'ok': true,
      'item': {
        'id': malformed ? 'wrong' : path.split('/').last,
        'travellerId': uid,
        'target': target
      }
    };
  }

  @override
  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) async {
    patches.add(path);
    return {'ok': !failRead};
  }
}

class ScopeUser implements User {
  @override
  final String uid;
  ScopeUser(this.uid);
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class ScopeAuth implements FirebaseAuth {
  final changes = StreamController<User?>.broadcast();
  User? user = ScopeUser('first');
  @override
  User? get currentUser => user;
  @override
  Stream<User?> authStateChanges() async* {
    yield user;
    yield* changes.stream;
  }

  void change(String id) {
    user = ScopeUser(id);
    changes.add(user);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final id = 'a' * 64;
  test('cold/background tap resolves exact owned record and marks it read',
      () async {
    final api = TapApi();
    final screen = await notificationForTap(id, api,
        owner: 'owner', currentOwner: () => 'owner');
    expect(screen, isA<PackageTripDetailsScreen>());
    expect((screen as PackageTripDetailsScreen).tripId, 'real-trip');
    expect(api.gets, ['$notificationPath/$id']);
    expect(api.patches, ['$notificationPath/$id']);
    api.target = {
      'screen': 'payments',
      'orderId': 'package_checkout:real-order'
    };
    final payment = await notificationForTap(id, api,
        owner: 'owner', currentOwner: () => 'owner');
    expect((payment as PaymentHistoryScreen).focusOrderId,
        'package_checkout:real-order');
  });
  test('expired login and malformed push IDs perform no private lookup',
      () async {
    final api = TapApi();
    expect(
        await notificationForTap(id, api,
            owner: 'owner', currentOwner: () => null),
        isNull);
    expect(
        await notificationForTap('../private', api,
            owner: 'owner', currentOwner: () => 'owner'),
        isNull);
    expect(api.gets, isEmpty);
    expect(api.patches, isEmpty);
  });
  test('foreign, deleted, malformed and unsupported destinations never open',
      () async {
    for (final api in [
      TapApi()..uid = 'another',
      TapApi()..missing = true,
      TapApi()..malformed = true,
      TapApi()
        ..target = {'screen': 'https://external.test', 'tripId': 'real-trip'},
      TapApi()..target = {'screen': 'payments', 'orderId': '../foreign'},
      TapApi()..target = {'screen': 'payments'}
    ]) {
      await expectLater(
          notificationForTap(id, api,
              owner: 'owner', currentOwner: () => 'owner'),
          throwsA(isA<ApiException>()));
      expect(api.patches, isEmpty);
    }
  });
  test(
      'account change while lookup pending discards old target before read write',
      () async {
    final api = TapApi()..gate = Completer<dynamic>();
    String? owner = 'owner';
    final pending =
        notificationForTap(id, api, owner: 'owner', currentOwner: () => owner);
    owner = 'another';
    api.gate!.complete({
      'ok': true,
      'item': {'id': id, 'travellerId': 'owner', 'target': api.target}
    });
    expect(await pending, isNull);
    expect(api.patches, isEmpty);
  });
  test('failed read persistence does not report successful tap navigation',
      () async {
    final api = TapApi()..failRead = true;
    await expectLater(
        notificationForTap(id, api,
            owner: 'owner', currentOwner: () => 'owner'),
        throwsA(isA<ApiException>()));
  });
  testWidgets(
      'verified push refreshes open inbox and bell, without page polling',
      (tester) async {
    final api = NoticesApi();
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: NotificationBell(api: api))));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Notifications, 1 unread'), findsOneWidget);
    api.items.add({
      'id': 'event2',
      'title': 'Distinct booking update',
      'category': 'package_booking',
      'read': false
    });
    AndroidPushService.instance.inboxChanged();
    await tester.pumpAndSettle();
    expect(find.byTooltip('Notifications, 2 unread'), findsOneWidget);
    await tester.tap(find.byTooltip('Notifications, 2 unread'));
    await tester.pumpAndSettle();
    api.items.add({
      'id': 'event3',
      'title': 'New arrangement update',
      'category': 'arrangements_update',
      'read': false
    });
    AndroidPushService.instance.inboxChanged();
    await tester.pumpAndSettle();
    expect(find.text('New arrangement update'), findsOneWidget);
  });
  test(
      'native foreground presentation and system settings use the scoped channel',
      () async {
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(FirebasePushPlatform.channel, (call) async {
      calls.add(call);
      return null;
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(FirebasePushPlatform.channel, null));
    final platform = FirebasePushPlatform();
    await platform.showUpdate(id, {
      'title': 'TravelMate — Payment update',
      'body': 'Review your recorded status securely.'
    });
    await platform.openSettings();
    expect(calls.map((c) => c.method), ['show', 'settings']);
    expect(calls.first.arguments['notificationId'], id);
    expect(calls.first.arguments['title'], 'TravelMate — Payment update');
  });
  testWidgets('returning to an open inbox refreshes background event state',
      (tester) async {
    final api = NoticesApi();
    await tester
        .pumpWidget(MaterialApp(home: NotificationCenterScreen(api: api)));
    await tester.pumpAndSettle();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    api.items.add({
      'id': 'new-background-event',
      'title': 'Background booking update',
      'read': false
    });
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(find.text('Background booking update'), findsOneWidget);
  });
  testWidgets(
      'a deleted package trip presents the existing unavailable-record state',
      (tester) async {
    final api = TapApi();
    final screen = await notificationForTap(id, api,
        owner: 'owner', currentOwner: () => 'owner');
    await tester.pumpWidget(MaterialApp(home: screen));
    await tester.pumpAndSettle();
    expect(
        find.text('Package trip record could not be found.'), findsOneWidget);
    expect(api.gets, contains('/api/fr5/itineraries/real-trip'));
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'account change removes a cached notification detail above the home route',
      (tester) async {
    final auth = ScopeAuth();
    addTearDown(auth.changes.close);
    await tester.pumpWidget(TravelMateApp(auth: auth, initialize: () async {}));
    await tester.pumpAndSettle();
    final context = tester.element(find.byType(TravellerEntryGate));
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) =>
            const Scaffold(body: Text('First account private booking'))));
    await tester.pumpAndSettle();
    expect(find.text('First account private booking'), findsOneWidget);
    auth.change('second');
    await tester.pumpAndSettle();
    expect(find.text('First account private booking'), findsNothing);
    expect(find.byKey(const ValueKey('second')), findsOneWidget);
  });
}
