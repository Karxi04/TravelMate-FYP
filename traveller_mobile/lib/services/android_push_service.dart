import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api_service.dart';
import 'firebase_startup.dart';

const pushBuildEnabled = bool.fromEnvironment('ENABLE_ANDROID_PUSH');
const pushTestBuild = bool.fromEnvironment('PUSH_TEST_BUILD');
const pushAppId = pushTestBuild
    ? FirebaseEmulatorConfig.package
    : 'com.example.travelmate_traveller';

/// Notification payloads are displayed by Android in background. Never duplicate them here.
@pragma('vm:entry-point')
Future<void> travelMateBackgroundMessage(RemoteMessage message) async {}

abstract class PushPlatform {
  Future<String?> installationBinding() async => null;
  Future<bool> permission({bool request = false});
  Future<String?> token();
  Future<void> deleteToken();
  Future<void> show(String id);
  Future<void> clear();
}

class FirebasePushPlatform implements PushPlatform {
  static const channel = MethodChannel('travelmate/notifications');
  @override
  Future<String?> installationBinding() =>
      channel.invokeMethod<String>('binding');
  @override
  Future<bool> permission({bool request = false}) async {
    final settings = request
        ? await FirebaseMessaging.instance.requestPermission()
        : await FirebaseMessaging.instance.getNotificationSettings();
    return settings.authorizationStatus == AuthorizationStatus.authorized;
  }

  @override
  Future<String?> token() async {
    await FirebaseMessaging.instance.setAutoInitEnabled(true);
    return FirebaseMessaging.instance.getToken();
  }

  @override
  Future<void> deleteToken() async {
    await FirebaseMessaging.instance.setAutoInitEnabled(false);
    await FirebaseMessaging.instance.deleteToken();
  }

  @override
  Future<void> show(String id) =>
      channel.invokeMethod('show', {'notificationId': id});
  @override
  Future<void> clear() => channel.invokeMethod('clear');
}

class AndroidPushService with WidgetsBindingObserver {
  static final instance = AndroidPushService();
  final ApiService api;
  final PushPlatform platform;
  final SharedPreferencesAsync? _storage;
  SharedPreferencesAsync get storage => _storage ?? SharedPreferencesAsync();
  String? uid;
  Future<void> work = Future.value();
  void Function(String)? onTap;
  final subscriptions = <StreamSubscription>[];
  bool started = false;
  String? lastTap;
  DateTime? lastTapAt;
  AndroidPushService(
      {ApiService? api,
      PushPlatform? platform,
      SharedPreferencesAsync? storage})
      : api = api ?? ApiService(),
        platform = platform ?? FirebasePushPlatform(),
        _storage = storage;
  bool get supported =>
      pushBuildEnabled &&
      !useFirebaseEmulator &&
      !api.isStandalone &&
      !kIsWeb &&
      defaultTargetPlatform == TargetPlatform.android;
  Future<void> serialize(Future<void> Function() action) {
    final next = work.then((_) => action());
    work = next.catchError((Object _) {});
    return next;
  }

  Future<String> binding() async {
    // Android's no-backup binding cannot be cloned to a second phone by app restore.
    final native = await platform.installationBinding();
    if (native != null) return native;
    final saved = await storage.getString('android_push_binding');
    if (saved != null) return saved;
    final random = Random.secure();
    final value = base64Url
        .encode(List.generate(32, (_) => random.nextInt(256)))
        .replaceAll('=', '');
    await storage.setString('android_push_binding', value);
    return value;
  }

  Future<Map<String, dynamic>> registration(String token) async =>
      {'token': token, 'bindingSecret': await binding(), 'appId': pushAppId};
  Future<void> synchronize(String? owner, {bool requestPermission = false}) =>
      serialize(() async {
        if (!supported) return;
        final previous = await storage.getString('android_push_uid');
        if (previous != null && previous != owner) {
          // A switched credential cannot revoke another UID: drop the transport token.
          await platform.deleteToken();
          await platform.clear();
          await storage.remove('android_push_token');
          await storage.remove('android_push_uid');
        }
        uid = owner;
        if (owner == null) return;
        if (!await platform.permission(request: requestPermission)) {
          await _unregister();
          return;
        }
        final token = await platform.token();
        if (token == null) return;
        final old = await storage.getString('android_push_token');
        if (old != null && old != token)
          await api.post('/api/traveller/notifications/devices/unregister',
              await registration(old));
        await api.post(
            '/api/traveller/notifications/devices', await registration(token));
        await storage.setString('android_push_token', token);
        await storage.setString('android_push_uid', owner);
      });
  Future<void> _unregister() async {
    final token = await storage.getString('android_push_token');
    if (token != null) {
      await api.post('/api/traveller/notifications/devices/unregister',
          await registration(token));
      await platform.deleteToken();
    }
    await platform.clear();
    await storage.remove('android_push_token');
    await storage.remove('android_push_uid');
  }

  Future<void> beforeLogout() => serialize(() async {
        if (supported) {
          await _unregister();
          uid = null;
        }
      });
  Future<void> foreground(String? id) async {
    if (uid == null || !validId(id)) return;
    final owner = uid;
    final result = await api.get('/api/traveller/notifications/$id');
    if (uid == owner && result['item']?['read'] != true)
      await platform.show(id!);
  }

  static bool validId(String? id) =>
      id != null && RegExp(r'^[a-f0-9]{64}$').hasMatch(id);
  void tap(String? id) {
    if (!validId(id)) return;
    final now = DateTime.now();
    if (lastTap == id &&
        lastTapAt != null &&
        now.difference(lastTapAt!).inSeconds < 2) return;
    lastTap = id;
    lastTapAt = now;
    onTap?.call(id!);
  }

  Future<void> start(void Function(String) callback) async {
    if (!supported || started) return;
    started = true;
    onTap = callback;
    WidgetsBinding.instance.addObserver(this);
    FirebaseMessaging.onBackgroundMessage(travelMateBackgroundMessage);
    subscriptions.add(FirebaseMessaging.onMessage.listen((message) {
      foreground(message.data['notificationId']).catchError((Object _) {});
    }));
    subscriptions.add(FirebaseMessaging.onMessageOpenedApp
        .listen((message) => tap(message.data['notificationId'])));
    subscriptions.add(FirebaseMessaging.instance.onTokenRefresh.listen((_) {
      synchronize(uid).catchError((Object _) {});
    }));
    subscriptions.add(FirebaseAuth.instance.authStateChanges().listen((user) {
      synchronize(user?.uid).catchError((Object _) {});
    }));
    FirebasePushPlatform.channel.setMethodCallHandler((call) async {
      if (call.method == 'tap') tap(call.arguments as String?);
    });
    tap((await FirebaseMessaging.instance.getInitialMessage())
        ?.data['notificationId']);
    tap(await FirebasePushPlatform.channel.invokeMethod<String>('initial'));
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed)
      synchronize(uid).catchError((Object _) {});
  }
}
