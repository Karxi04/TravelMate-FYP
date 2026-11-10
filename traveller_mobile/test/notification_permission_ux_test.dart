import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/android_push_service.dart';
import 'package:travelmate_traveller/modules/traveller_notifications/android_notification_settings.dart';
import 'package:travelmate_traveller/modules/traveller_notifications/notification_center.dart';
import 'android_push_service_test.dart' show Store;
import 'core_personalization_notifications_test.dart' show NoticesApi;

class Settings implements NotificationSettings {
  @override
  final AuthorizationStatus authorizationStatus;
  Settings(this.authorizationStatus);
  @override
  dynamic noSuchMethod(Invocation i) => super.noSuchMethod(i);
}

class Messaging implements FirebaseMessaging {
  AuthorizationStatus status = AuthorizationStatus.denied;
  int requests = 0;
  @override
  Future<NotificationSettings> getNotificationSettings() async =>
      Settings(status);
  @override
  dynamic noSuchMethod(Invocation i) {
    if (i.memberName == #requestPermission) {
      requests++;
      status = AuthorizationStatus.authorized;
      return Future<NotificationSettings>.value(Settings(status));
    }
    return super.noSuchMethod(i);
  }
}

class PermissionPlatform extends PushPlatform {
  bool granted = false, channel = true, grantOnRequest = true;
  int prompts = 0;
  @override
  Future<bool> authorizationGranted() async => granted;
  @override
  Future<bool> permission({bool request = false}) async {
    if (request && !granted) {
      prompts++;
      granted = grantOnRequest;
    }
    return granted && channel;
  }

  @override
  Future<String?> token() async => 'synthetic-registration-token';
  @override
  Future<void> deleteToken() async {}
  @override
  Future<void> clear() async {}
  @override
  Future<void> show(String id) async {}
}

class UnavailablePlatform extends PermissionPlatform {
  @override
  Future<bool> authorizationGranted() async =>
      throw StateError('PRIVATE_SDK_DETAIL');
}

class RegistrationApi extends ApiService {
  int posts = 0;
  bool disabled = false;
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posts++;
    if (disabled)
      throw const ApiException('Unavailable', 503,
          {'error': 'Android push is not configured on this backend.'});
    return {'ok': true};
  }
}

class Push extends AndroidPushService {
  bool available = true;
  Push(RegistrationApi api, PermissionPlatform platform, Store store)
      : super(api: api, platform: platform, storage: store) {
    uid = 'synthetic-owner';
  }
  @override
  bool get supported => available;
  @override
  String? get unavailableReason => available
      ? null
      : 'Android system alerts are disabled in this build. Enabling Android permission alone cannot enable delivery. Your in-app inbox still works.';
}

Future<void> frame(WidgetTester tester, Widget child) async {
  await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: SingleChildScrollView(child: child))));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
      'actual Firebase adapter checks granted state before any permission request',
      () async {
    final messaging = Messaging()..status = AuthorizationStatus.authorized;
    final calls = <MethodCall>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(FirebasePushPlatform.channel, (call) async {
      calls.add(call);
      return true;
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(FirebasePushPlatform.channel, null));
    final platform = FirebasePushPlatform(messaging: messaging);
    expect(await platform.permission(request: true), isTrue);
    expect(await platform.permission(request: true), isTrue);
    expect(messaging.requests, 0);
    expect(calls.map((c) => c.method), ['canDisplay', 'canDisplay']);
  });
  test(
      'denied Firebase permission requests once and a granted recheck never prompts',
      () async {
    final messaging = Messaging();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            FirebasePushPlatform.channel, (call) async => true);
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(FirebasePushPlatform.channel, null));
    final platform = FirebasePushPlatform(messaging: messaging);
    expect(await platform.permission(), isFalse);
    expect(messaging.requests, 0);
    expect(await platform.permission(request: true), isTrue);
    expect(messaging.requests, 1);
    expect(await platform.permission(request: true), isTrue);
    expect(messaging.requests, 1);
  });
  test(
      'an authorized but disabled channel never causes another permission request',
      () async {
    final messaging = Messaging()..status = AuthorizationStatus.authorized;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            FirebasePushPlatform.channel, (call) async => false);
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(FirebasePushPlatform.channel, null));
    expect(
        await FirebasePushPlatform(messaging: messaging)
            .permission(request: true),
        isFalse);
    expect(messaging.requests, 0);
  });
  testWidgets(
      'opening notification settings explains permission then requests on Allow',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform();
    final store = Store();
    final push = Push(api, platform, store);
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(find.text('Allow Android alerts?'), findsOneWidget);
    expect(platform.prompts, 0);
    expect(api.posts, 0);
    await tester.tap(find.text('Allow alerts'));
    await tester.pumpAndSettle();
    expect(platform.prompts, 1);
    expect(api.posts, 1);
    expect(push.registered, isTrue);
    expect(
        find.textContaining('does not confirm FCM delivery'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(find.text('Allow Android alerts?'), findsNothing);
    expect(platform.prompts, 1);
  });
  testWidgets(
      'Not now preserves inbox use and does not automatically ask again',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform();
    final push = Push(api, platform, Store());
    await frame(tester, AndroidNotificationSettings(push: push));
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(platform.prompts, 0);
    expect(api.posts, 0);
    await tester.pumpWidget(const SizedBox.shrink());
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(find.text('Allow Android alerts?'), findsNothing);
    expect(find.text('Enable Android alerts'), findsOneWidget);
  });
  testWidgets(
      'already allowed permission registers without an explanation or native prompt',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform()..granted = true;
    final push = Push(api, platform, Store());
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(platform.prompts, 0);
    expect(api.posts, 1);
    expect(find.text('Allow Android alerts?'), findsNothing);
  });
  testWidgets(
      'disabled build explains the blocker and never asks for permission',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform();
    final push = Push(api, platform, Store())..available = false;
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(find.textContaining('disabled in this build'), findsOneWidget);
    expect(find.text('Enable Android alerts'), findsNothing);
    expect(find.text('Allow Android alerts?'), findsNothing);
    expect(platform.prompts, 0);
    expect(api.posts, 0);
  });
  testWidgets(
      'permission granted but backend disabled is visibly distinct from enabled delivery',
      (tester) async {
    final api = RegistrationApi()..disabled = true;
    final platform = PermissionPlatform()..granted = true;
    final push = Push(api, platform, Store());
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(find.textContaining('backend has not enabled push dispatch'),
        findsOneWidget);
    expect(push.registered, isFalse);
    expect(platform.prompts, 0);
    expect(find.text('Retry device registration'), findsOneWidget);
    api.disabled = false;
    await tester.tap(find.text('Retry device registration'));
    await tester.pumpAndSettle();
    expect(push.registered, isTrue);
    expect(platform.prompts, 0);
    expect(api.posts, 2);
    expect(
        find.textContaining('does not confirm FCM delivery'), findsOneWidget);
  });
  testWidgets(
      'channel disabled goes to settings rather than requesting granted permission',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform()
      ..granted = true
      ..channel = false;
    final push = Push(api, platform, Store());
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(find.textContaining('channel is disabled'), findsOneWidget);
    expect(platform.prompts, 0);
    expect(api.posts, 0);
  });
  testWidgets('notification long press exposes only its support reference',
      (tester) async {
    final api = NoticesApi();
    await tester
        .pumpWidget(MaterialApp(home: NotificationCenterScreen(api: api)));
    await tester.pumpAndSettle();
    await tester.longPress(find.text('Payment status updated'));
    await tester.pumpAndSettle();
    expect(find.text('Notification reference'), findsOneWidget);
    expect(find.text('event1'), findsOneWidget);
    expect(api.updates, isEmpty);
  });
  testWidgets(
      'native denial does not cause automatic permission loops on reopening',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform()..grantOnRequest = false;
    final push = Push(api, platform, Store());
    await frame(tester, AndroidNotificationSettings(push: push));
    await tester.tap(find.text('Allow alerts'));
    await tester.pumpAndSettle();
    expect(platform.prompts, 1);
    expect(api.posts, 0);
    expect(push.registered, isFalse);
    await tester.pumpWidget(const SizedBox.shrink());
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(find.text('Allow Android alerts?'), findsNothing);
    expect(platform.prompts, 1);
    expect(find.text('Open Android settings'), findsOneWidget);
  });
  testWidgets(
      'unavailable SDK gives a sanitized status without an unhandled prompt failure',
      (tester) async {
    final api = RegistrationApi();
    final push = Push(api, UnavailablePlatform(), Store());
    await frame(tester, AndroidNotificationSettings(push: push));
    expect(find.textContaining('status could not be checked'), findsOneWidget);
    expect(find.textContaining('PRIVATE'), findsNothing);
    expect(api.posts, 0);
    expect(find.text('Allow Android alerts?'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
