import 'dart:async';
import 'dart:convert';
import 'dart:collection';
import 'package:flutter_test/flutter_test.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travelmate_traveller/services/android_push_service.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';

class Store implements SharedPreferencesAsync {
  final values = <String, String>{};
  @override
  Future<String?> getString(String key) async => values[key];
  @override
  Future<void> setString(String key, String value) async {
    values[key] = value;
  }

  @override
  Future<void> remove(String key) async {
    values.remove(key);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class InterruptedMemory extends MapBase<String, String> {
  final entriesByKey = <String, String>{};
  bool interrupt = false;
  @override
  String? operator [](Object? key) => entriesByKey[key];
  @override
  void operator []=(String key, String value) {
    if (interrupt && key.endsWith('learning_bundle_v1'))
      throw StateError('interrupted write');
    entriesByKey[key] = value;
  }

  @override
  void clear() => entriesByKey.clear();
  @override
  Iterable<String> get keys => entriesByKey.keys;
  @override
  String? remove(Object? key) => entriesByKey.remove(key);
}

class Platform extends PushPlatform {
  bool allowed = true;
  String current = 'token-1-xxxxxxxxxxxxxxxxxxxxxxxx';
  int prompts = 0;
  int deletions = 0;
  int clears = 0;
  final shown = <String>[];
  @override
  Future<bool> permission({bool request = false}) async {
    if (request) prompts++;
    return allowed;
  }

  @override
  Future<String?> token() async => current;
  @override
  Future<void> deleteToken() async {
    deletions++;
  }

  @override
  Future<void> clear() async {
    clears++;
  }

  @override
  Future<void> show(String id) async {
    shown.add(id);
  }
}

class Api extends ApiService {
  final posts = <Map>[];
  bool fail = false;
  bool reject = false;
  Completer<dynamic>? postGate;
  Completer<dynamic>? held;
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (fail) throw StateError('offline');
    posts.add({'path': path, ...?body});
    if (postGate != null) return postGate!.future;
    return {'ok': !reject};
  }

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (fail) throw StateError('not owned');
    if (held != null) return held!.future;
    return {
      'ok': true,
      'item': {
        'id': path.split('/').last,
        'travellerId': 'a',
        'target': {'screen': 'trip', 'tripId': 'owned-trip'}
      }
    };
  }
}

class Service extends AndroidPushService {
  Service(Api api, Platform platform, Store storage)
      : super(api: api, platform: platform, storage: storage);
  @override
  bool get supported => true;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
      'standalone budget excludes unknown and foreign admissions and scales explicit person prices',
      () async {
    final trip = {
      'id': 't',
      'travellerId': 'a',
      'travellerCount': 2,
      'budgetLimit': 600,
      'foodCost': 0,
      'transportCost': 0,
      'activities': [
        {'activityId': 'unknown', 'estimatedCost': 0},
        {
          'activityId': 'priced',
          'unitPrice': 12,
          'pricingUnit': 'per_person',
          'currency': 'MYR',
          'costProvenance': 'verified_ticket'
        },
        {
          'activityId': 'foreign',
          'unitPrice': 10,
          'pricingUnit': 'per_person',
          'currency': 'USD'
        },
        {
          'activityId': 'free',
          'unitPrice': 0,
          'pricingUnit': 'per_person',
          'currency': 'MYR',
          'costProvenance': 'verified_ticket'
        },
      ]
    };
    final api = StandaloneApiService(uidOverride: 'a', memoryStore: {
      'travelmate_a_itineraries': jsonEncode([trip])
    });
    final budget = (await api.get('/api/fr5/itineraries/t/budget'))['budget'];
    expect(budget['activities'], 24);
    expect(budget['unknownActivityCount'], 2);
    expect(budget['incomplete'], true);
    expect(budget['knownEstimatedSubtotal'], 24);
    expect(budget['comparison'], isNot(contains('within budget')));
  });
  test('interrupted local bundle write cannot publish state without its audit',
      () async {
    final memory = InterruptedMemory();
    final api = StandaloneApiService(uidOverride: 'owner', memoryStore: memory);
    final feedback = {
      'destinationId': 'x',
      'destinationConcepts': ['culture'],
      'feedbackType': 'more_like_this'
    };
    memory.interrupt = true;
    await expectLater(
        api.post('/api/fr4/preference-feedback', feedback), throwsStateError);
    expect(
        (await api.get('/api/fr4/preference-feedback'))['learning']
            ['currentFeedback'],
        isEmpty);
    expect(memory['travelmate_owner_learning_bundle_v1'], isNull);
    memory.interrupt = false;
    await api.post('/api/fr4/preference-feedback', feedback);
    final saved = jsonDecode(memory['travelmate_owner_learning_bundle_v1']!);
    expect(saved['events'].length, 1);
    expect(saved['profile']['affinities']['culture'], .15);
  });
  test('denied permission never blocks normal inbox and never registers',
      () async {
    final api = Api();
    final platform = Platform()..allowed = false;
    final service = Service(api, platform, Store());
    await service.synchronize('a');
    await service.synchronize('a');
    expect(api.posts, isEmpty);
    expect(platform.prompts, 0);
    await service.synchronize('a', requestPermission: true);
    expect(platform.prompts, 1);
  });
  test(
      'token rotation revokes previous association before registering refreshed token',
      () async {
    final api = Api();
    final platform = Platform();
    final store = Store();
    final service = Service(api, platform, store);
    await service.synchronize('a');
    final binding = api.posts.single['bindingSecret'];
    platform.current = 'refreshed-token-xxxxxxxxxxxxxxxx';
    await service.synchronize('a');
    expect(api.posts[1]['path'], endsWith('/unregister'));
    expect(api.posts[2]['token'], platform.current);
    expect(api.posts[2]['bindingSecret'], binding);
    expect(store.values['android_push_uid'], 'a');
    await service.beforeLogout();
    expect(api.posts.last['path'], endsWith('/unregister'));
    expect(store.values['android_push_token'], isNull);
    expect(service.uid, isNull);
  });
  test('offline logout does not silently leave an active registration behind',
      () async {
    final api = Api();
    final platform = Platform();
    final service = Service(api, platform, Store());
    await service.synchronize('a');
    api.fail = true;
    await expectLater(service.beforeLogout(), throwsStateError);
    expect(service.uid, 'a');
    api.fail = false;
    await service.beforeLogout();
    expect(service.uid, isNull);
  });
  test('account switch deletes old transport and clears generic tray entries',
      () async {
    final api = Api();
    final platform = Platform();
    final service = Service(api, platform, Store());
    await service.synchronize('a');
    platform.current = 'new-account-token-xxxxxxxxxxx';
    await service.synchronize('b');
    expect(platform.deletions, 1);
    expect(platform.clears, 1);
    expect(service.uid, 'b');
  });
  test(
      'foreground presentation validates server ownership and rejects stale user response',
      () async {
    final api = Api();
    final platform = Platform();
    final service = Service(api, platform, Store())..uid = 'a';
    final id = 'a' * 64;
    await service.foreground(id);
    expect(platform.shown, [id]);
    api.fail = true;
    await expectLater(service.foreground('b' * 64), throwsStateError);
    expect(platform.shown, [id]);
    api.fail = false;
    api.held = Completer();
    final pending = service.foreground('c' * 64);
    service.uid = 'b';
    api.held!.complete({'ok': true});
    await pending;
    expect(platform.shown, [id]);
  });
  test(
      'cold/background tap IDs are queued once and malformed targets are ignored',
      () {
    final service = Service(Api(), Platform(), Store());
    final opened = <String>[];
    service.onTap = opened.add;
    service.tap('a' * 64);
    service.tap('a' * 64);
    service.tap('../private');
    service.tap(null);
    expect(opened, ['a' * 64]);
  });
  test(
      'background notification handler never shows a duplicate local notification',
      () async {
    await travelMateBackgroundMessage(
        const RemoteMessage(data: {'notificationId': 'id'}));
  });
  test(
      'standalone old feedback migrates lazily to one profile-audit bundle without rewriting questionnaire',
      () async {
    final memory = <String, String>{
      'travelmate_a_preferences': jsonEncode({
        'interests': ['Culture']
      }),
      'travelmate_a_learned_preference_profile':
          jsonEncode({'feedbackByDestination': {}, 'affinities': {}})
    };
    final api = StandaloneApiService(uidOverride: 'a', memoryStore: memory);
    await api.post('/api/fr4/preference-feedback', {
      'destinationId': 'x',
      'destinationConcepts': ['culture'],
      'feedbackType': 'more_like_this'
    });
    final bundle = jsonDecode(memory['travelmate_a_learning_bundle_v1']!);
    expect(bundle['profile']['affinities']['culture'], .15);
    expect(bundle['events'].length, 1);
    expect(
        memory['travelmate_a_preferences'],
        jsonEncode({
          'interests': ['Culture']
        }));
    await api.post('/api/fr4/preference-feedback', {
      'destinationId': 'x',
      'destinationConcepts': ['culture'],
      'feedbackType': 'more_like_this'
    });
    expect(
        jsonDecode(memory['travelmate_a_learning_bundle_v1']!)['events'].length,
        1);
    await api.delete('/api/fr4/preference-feedback');
    final reset = jsonDecode(memory['travelmate_a_learning_bundle_v1']!);
    expect(reset['profile']['feedbackByDestination'], isEmpty);
    expect(reset['events'].length, 2);
    expect(
        (await StandaloneApiService(uidOverride: 'b', memoryStore: memory)
                .get('/api/fr4/preference-feedback'))['learning']
            ['currentFeedback'],
        isEmpty);
  });
  test(
      'same foreground business event alerts once even under concurrent delivery',
      () async {
    final api = Api();
    final platform = Platform();
    final service = Service(api, platform, Store())..uid = 'a';
    await Future.wait(
        [service.foreground('a' * 64), service.foreground('a' * 64)]);
    await service.foreground('a' * 64);
    await service.foreground('b' * 64);
    expect(platform.shown, ['a' * 64, 'b' * 64]);
  });
  test(
      'permission granted later registers, later revocation removes association',
      () async {
    final api = Api();
    final platform = Platform()..allowed = false;
    final service = Service(api, platform, Store());
    await service.synchronize('a');
    expect(api.posts, isEmpty);
    expect(service.registered, isFalse);
    platform.allowed = true;
    await service.synchronize('a', requestPermission: true);
    expect(service.registered, isTrue);
    expect(platform.prompts, 1);
    platform.allowed = false;
    await service.synchronize('a');
    expect(api.posts.last['path'], endsWith('/unregister'));
    expect(service.registered, isFalse);
  });
  test('server rejection cannot be saved as successful device registration',
      () async {
    final api = Api()..reject = true;
    final store = Store();
    final service = Service(api, Platform(), store);
    await expectLater(service.synchronize('a'), throwsA(isA<ApiException>()));
    expect(store.values['android_push_token'], isNull);
    expect(service.registered, isFalse);
  });
  test(
      'logout invalidates pending foreground response before queued token work finishes',
      () async {
    final api = Api()..postGate = Completer<dynamic>();
    final platform = Platform();
    final service = Service(api, platform, Store());
    final registering = service.synchronize('a');
    for (var i = 0; i < 10 && api.posts.isEmpty; i++) {
      await Future<void>.delayed(Duration.zero);
    }
    expect(api.posts, isNotEmpty);
    api.held = Completer<dynamic>();
    final response = service.foreground('d' * 64);
    final logout = service.beforeLogout();
    api.held!.complete({
      'ok': true,
      'item': {'id': 'd' * 64, 'travellerId': 'a', 'read': false}
    });
    await response;
    expect(platform.shown, isEmpty);
    api.postGate!.complete({'ok': true});
    await registering;
    await logout;
    expect(service.uid, isNull);
    expect(service.registered, isFalse);
  });
  test(
      'account switch immediately invalidates a response while registration is queued',
      () async {
    final api = Api();
    final platform = Platform();
    final service = Service(api, platform, Store());
    await service.synchronize('a');
    api.held = Completer<dynamic>();
    final response = service.foreground('e' * 64);
    final switching = service.synchronize('b');
    expect(service.uid, 'b');
    api.held!.complete({
      'ok': true,
      'item': {'id': 'e' * 64, 'travellerId': 'a', 'read': false}
    });
    await response;
    await switching;
    expect(platform.shown, isEmpty);
  });
  test(
      'malformed successful detail responses cannot create a system notification',
      () async {
    final api = Api()..held = Completer<dynamic>();
    final platform = Platform();
    final service = Service(api, platform, Store())..uid = 'a';
    final response = service.foreground('f' * 64);
    api.held!.complete({'ok': true});
    await response;
    expect(platform.shown, isEmpty);
  });
}
