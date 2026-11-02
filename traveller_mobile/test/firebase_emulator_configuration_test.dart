import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/firebase_startup.dart';

void main() {
  test('default flag is opt-in', () => expect(useFirebaseEmulator, isFalse));
  test('explicit Android Emulator configuration accepted', () {
    expect(
        const FirebaseEmulatorConfig(apiUrl: 'http://10.0.2.2:5005')
            .validate(platform: TargetPlatform.android)
            .port,
        5005);
  });
  for (final url in [
    '',
    'http://10.0.2.2:5000',
    'https://10.0.2.2:5005',
    'http://example.com:5005',
    'http://10.0.2.2:5005/api',
    'http://user@10.0.2.2:5005',
    'http://10.0.2.2:5005?x=1',
    'http://10.0.2.2:9099'
  ]) {
    test(
        'unsafe/missing API rejected: $url',
        () => expect(
            () => FirebaseEmulatorConfig(apiUrl: url)
                .validate(platform: TargetPlatform.android),
            throwsStateError));
  }
  for (final config in [
    const FirebaseEmulatorConfig(
        host: '192.168.1.2', apiUrl: 'http://192.168.1.2:5005'),
    const FirebaseEmulatorConfig(
        apiUrl: 'http://10.0.2.2:5005', standalone: true),
    const FirebaseEmulatorConfig(apiUrl: 'http://10.0.2.2:5005', authPort: 0),
    const FirebaseEmulatorConfig(
        apiUrl: 'http://10.0.2.2:5005', authPort: 5000),
    const FirebaseEmulatorConfig(
        apiUrl: 'http://10.0.2.2:5005', firestorePort: 65536),
    const FirebaseEmulatorConfig(
        apiUrl: 'http://10.0.2.2:5005', firestorePort: 9099),
  ]) {
    test(
        'unsafe routing configuration rejected: ${config.host}/${config.authPort}/${config.firestorePort}/${config.standalone}',
        () => expect(() => config.validate(platform: TargetPlatform.android),
            throwsStateError));
  }
  test('release and unsupported platforms rejected', () {
    const c = FirebaseEmulatorConfig(apiUrl: 'http://10.0.2.2:5005');
    expect(() => c.validate(platform: TargetPlatform.android, release: true),
        throwsStateError);
    expect(() => c.validate(platform: TargetPlatform.android, web: true),
        throwsStateError);
    expect(
        () => c.validate(platform: TargetPlatform.windows), throwsStateError);
  });
  test('native production initialization and owner package fail closed', () {
    const c = FirebaseEmulatorConfig();
    final native = {
      'package': FirebaseEmulatorConfig.package,
      'emulatorBuild': true,
      'productionResourcesAbsent': true,
      'projects': <String>[]
    };
    c.validateNative(native);
    for (final bad in [
      <String, dynamic>{},
      {...native, 'package': 'com.example.travelmate_traveller'},
      {...native, 'productionResourcesAbsent': false},
      {
        ...native,
        'projects': ['travelmate2-30a8a']
      }
    ]) {
      expect(() => c.validateNative(bad), throwsStateError);
    }
  });
  test('backend must report actual matching demo project and endpoints', () {
    const c = FirebaseEmulatorConfig();
    final ready = {
      'projectId': FirebaseEmulatorConfig.project,
      'anonymous': true,
      'providerNetworkBlocked': true,
      'auth': '127.0.0.1:9099',
      'firestore': '127.0.0.1:18085'
    };
    c.validateBackend(ready);
    for (final bad in [
      <String, dynamic>{},
      {...ready, 'projectId': 'travelmate2-30a8a'},
      {...ready, 'auth': '127.0.0.1:9999'},
      {...ready, 'providerNetworkBlocked': false}
    ]) {
      expect(() => c.validateBackend(bad), throwsStateError);
    }
  });
}
