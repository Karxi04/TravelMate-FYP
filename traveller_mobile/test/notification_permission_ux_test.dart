import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/android_push_service.dart';
import 'package:travelmate_traveller/modules/traveller_notifications/android_notification_permission.dart';
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
}

Future<void> frame(WidgetTester tester, Widget child) async {
  await tester.pumpWidget(
      MaterialApp(home: Scaffold(body: SingleChildScrollView(child: child))));
  await tester.pumpAndSettle();
}

Widget gate(Push push) => AndroidNotificationPermission(
    push: push, child: const Text('Traveller home'));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            FirebasePushPlatform.channel, (call) async => null);
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(FirebasePushPlatform.channel, null);
  });
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
      'signed-in entry asks once and only Allow requests native permission',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform();
    final push = Push(api, platform, Store());
    await frame(tester, gate(push));
    expect(find.text('Allow notifications?'), findsOneWidget);
    expect(platform.prompts, 0);
    expect(api.posts, 0);
    await tester.tap(find.text('Allow'));
    await tester.pumpAndSettle();
    expect(platform.prompts, 1);
    expect(api.posts, 1);
    expect(push.registered, isTrue);
    expect(find.text('Traveller home'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await frame(tester, gate(push));
    expect(find.text('Allow notifications?'), findsNothing);
    expect(platform.prompts, 1);
  });

  testWidgets('Not Now keeps home available and remembers the choice',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform();
    final push = Push(api, platform, Store());
    await frame(tester, gate(push));
    await tester.tap(find.text('Not Now'));
    await tester.pumpAndSettle();
    expect(platform.prompts, 0);
    expect(api.posts, 0);
    expect(find.text('Traveller home'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await frame(tester, gate(push));
    expect(find.text('Allow notifications?'), findsNothing);
  });

  testWidgets('already granted permission never prompts', (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform()..granted = true;
    final push = Push(api, platform, Store());
    await frame(tester, gate(push));
    expect(find.text('Allow notifications?'), findsNothing);
    expect(platform.prompts, 0);
    expect(find.text('Traveller home'), findsOneWidget);
  });

  testWidgets('unsupported build never offers permission', (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform();
    final push = Push(api, platform, Store())..available = false;
    await frame(tester, gate(push));
    expect(find.text('Allow notifications?'), findsNothing);
    expect(find.text('Traveller home'), findsOneWidget);
    expect(platform.prompts, 0);
    expect(api.posts, 0);
  });

  testWidgets('disabled backend does not block home after native grant',
      (tester) async {
    final api = RegistrationApi()..disabled = true;
    final platform = PermissionPlatform();
    final push = Push(api, platform, Store());
    await frame(tester, gate(push));
    await tester.tap(find.text('Allow'));
    await tester.pumpAndSettle();
    expect(platform.prompts, 1);
    expect(api.posts, 1);
    expect(push.registered, isFalse);
    expect(find.text('Traveller home'), findsOneWidget);
    expect(find.textContaining('backend'), findsNothing);
  });

  testWidgets('inbox shows notification content without Android controls',
      (tester) async {
    final api = NoticesApi();
    await tester
        .pumpWidget(MaterialApp(home: NotificationCenterScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Payment status updated'), findsOneWidget);
    expect(find.text('Android system notifications'), findsNothing);
    expect(find.text('Retry device registration'), findsNothing);
    expect(find.text('Open Android settings'), findsNothing);
    expect(find.text('Allow notifications?'), findsNothing);
    expect(api.updates, isEmpty);
  });

  testWidgets('native denial is respected when signed-in entry reopens',
      (tester) async {
    final api = RegistrationApi();
    final platform = PermissionPlatform()..grantOnRequest = false;
    final push = Push(api, platform, Store());
    await frame(tester, gate(push));
    await tester.tap(find.text('Allow'));
    await tester.pumpAndSettle();
    expect(platform.prompts, 1);
    expect(api.posts, 0);
    expect(push.registered, isFalse);
    await tester.pumpWidget(const SizedBox.shrink());
    await frame(tester, gate(push));
    expect(find.text('Allow notifications?'), findsNothing);
    expect(platform.prompts, 1);
  });

  testWidgets('permission SDK failure leaves the home available',
      (tester) async {
    final api = RegistrationApi();
    final push = Push(api, UnavailablePlatform(), Store());
    await frame(tester, gate(push));
    expect(find.textContaining('PRIVATE'), findsNothing);
    expect(find.text('Traveller home'), findsOneWidget);
    expect(api.posts, 0);
    expect(tester.takeException(), isNull);
  });
}
