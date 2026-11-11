import 'dart:convert';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../firebase_options.dart';
import 'api_service.dart';

const useFirebaseEmulator = bool.fromEnvironment('USE_FIREBASE_EMULATOR');
const privateReviewDemo = bool.fromEnvironment('PRIVATE_REVIEW_DEMO');

class FirebaseEmulatorConfig {
  static const project = 'demo-travelmate-f3p2v';
  static const package = 'org.travelmate.hermetic.travelmate_hermetic';

  final String host;
  final String apiUrl;
  final int authPort;
  final int firestorePort;
  final bool standalone;
  final bool reviewDemo;

  const FirebaseEmulatorConfig({
    this.host = const String.fromEnvironment('FIREBASE_EMULATOR_HOST',
        defaultValue: '10.0.2.2'),
    this.apiUrl = const String.fromEnvironment('API_BASE_URL'),
    this.authPort =
        const int.fromEnvironment('FIREBASE_AUTH_PORT', defaultValue: 9099),
    this.firestorePort = const int.fromEnvironment('FIREBASE_FIRESTORE_PORT',
        defaultValue: 18085),
    this.standalone = ApiService.forceStandalone,
    this.reviewDemo = privateReviewDemo,
  });

  factory FirebaseEmulatorConfig.fromEnvironment() => FirebaseEmulatorConfig(
        authPort: int.tryParse(const String.fromEnvironment(
                'FIREBASE_AUTH_PORT',
                defaultValue: '9099')) ??
            0,
        firestorePort: int.tryParse(const String.fromEnvironment(
                'FIREBASE_FIRESTORE_PORT',
                defaultValue: '18085')) ??
            0,
      );

  Uri validate(
      {bool release = kReleaseMode,
      bool web = kIsWeb,
      TargetPlatform? platform}) {
    final api = Uri.tryParse(apiUrl);
    if (release ||
        web ||
        (platform ?? defaultTargetPlatform) != TargetPlatform.android ||
        standalone ||
        (reviewDemo && host != '10.0.2.2') ||
        !{'10.0.2.2', '127.0.0.1'}.contains(host) ||
        authPort < 1024 ||
        authPort > 65535 ||
        firestorePort < 1024 ||
        firestorePort > 65535 ||
        authPort == firestorePort ||
        api == null ||
        api.scheme != 'http' ||
        api.host != host ||
        {5000, 5001, 5002}.contains(authPort) ||
        {5000, 5001, 5002}.contains(firestorePort) ||
        api.userInfo.isNotEmpty ||
        api.hasQuery ||
        api.hasFragment ||
        (api.path.isNotEmpty && api.path != '/') ||
        !api.hasPort ||
        api.port < 1024 ||
        api.port > 65535 ||
        {5000, 5001, 5002, authPort, firestorePort}.contains(api.port)) {
      throw StateError(
          'Emulator isolation requires Android debug, backend-connected mode, an explicit matching loopback/emulator API host and distinct unprotected ports.');
    }
    return api;
  }

  void validateNative(Map<dynamic, dynamic> native) {
    final projects = native['projects'];
    final expectedPackage = reviewDemo ? 'com.example.travelmate_traveller' : package;
    if (native['package'] != expectedPackage ||
        (native['privateReviewDemo'] == true) != reviewDemo ||
        (reviewDemo && native['androidEmulator'] != true) ||
        native['emulatorBuild'] != true ||
        native['productionResourcesAbsent'] != true ||
        projects is! List ||
        projects.any((id) => id != project)) {
      throw StateError(
          'Emulator isolation requires the matching Android preview build with no production Firebase resources. The private review preview runs on an Android emulator.');
    }
  }

  void validateBackend(Map<String, dynamic> ready) {
    if (ready['projectId'] != project ||
        ready['anonymous'] != true ||
        ready['providerNetworkBlocked'] != true ||
        ready['auth'] != '127.0.0.1:$authPort' ||
        ready['firestore'] != '127.0.0.1:$firestorePort') {
      throw StateError(
          'Isolated backend project or Emulator endpoints do not match the client.');
    }
  }
}

Future<void> initializeTravelMateFirebase() async {
  const rawFlag =
      String.fromEnvironment('USE_FIREBASE_EMULATOR', defaultValue: 'false');
  if (!{'true', 'false'}.contains(rawFlag))
    throw StateError('USE_FIREBASE_EMULATOR must be true or false.');
  if (privateReviewDemo && !useFirebaseEmulator) {
    throw StateError('The private review preview requires Firebase emulators.');
  }
  if (!useFirebaseEmulator) {
    if (const bool.fromEnvironment('PUSH_TEST_BUILD')) {
      const project = String.fromEnvironment('PUSH_TEST_FIREBASE_PROJECT_ID');
      const appId = String.fromEnvironment('PUSH_TEST_FIREBASE_APP_ID');
      const apiKey = String.fromEnvironment('PUSH_TEST_FIREBASE_API_KEY');
      const sender = String.fromEnvironment('PUSH_TEST_FIREBASE_SENDER_ID');
      if (kReleaseMode || project.isEmpty || project.startsWith('demo-') ||
          project == DefaultFirebaseOptions.currentPlatform.projectId ||
          appId.isEmpty || apiKey.isEmpty || sender.isEmpty) {
        throw StateError('Push test requires explicit non-production Firebase Android configuration.');
      }
      await Firebase.initializeApp(options:const FirebaseOptions(projectId:project,appId:appId,apiKey:apiKey,messagingSenderId:sender));
      return;
    }
    await Firebase.initializeApp(
        options: DefaultFirebaseOptions.currentPlatform);
    return;
  }
  final config = FirebaseEmulatorConfig.fromEnvironment();
  final api = config.validate();
  final native = await const MethodChannel('travelmate/firebase_emulator')
      .invokeMapMethod<dynamic, dynamic>('configuration');
  config.validateNative(native ?? {});
  final client = http.Client();
  try {
    Future<http.Response> get(Uri uri) =>
        client.get(uri).timeout(const Duration(seconds: 5));
    final backend = await get(api.resolve('/__hermetic/ready'));
    if (backend.statusCode != 200)
      throw StateError('Isolated backend readiness unavailable.');
    config.validateBackend(jsonDecode(backend.body) as Map<String, dynamic>);
    final authProbe = await get(Uri.http('${config.host}:${config.authPort}',
        '/emulator/v1/projects/${FirebaseEmulatorConfig.project}/config'));
    if (authProbe.statusCode != 200)
      throw StateError('Auth Emulator unavailable.');
    final firestoreProbe = await get(Uri.http(
        '${config.host}:${config.firestorePort}',
        '/v1/projects/${FirebaseEmulatorConfig.project}/databases/(default)/documents/_client_startup/probe'));
    if (!{200, 403, 404}.contains(firestoreProbe.statusCode))
      throw StateError('Firestore Emulator unavailable.');
  } finally {
    client.close();
  }
  // Use the installed FlutterFire SDK's official demo options, for the DEFAULT app.
  final app = await Firebase.initializeApp(
      name: '[DEFAULT]', demoProjectId: FirebaseEmulatorConfig.project);
  if (app.options.projectId != FirebaseEmulatorConfig.project ||
      Firebase.apps
          .any((a) => a.options.projectId != FirebaseEmulatorConfig.project)) {
    throw StateError('Firebase project isolation failed.');
  }
  final auth = FirebaseAuth.instance;
  await auth.useAuthEmulator(config.host, config.authPort,
      automaticHostMapping: false);
  final firestore = FirebaseFirestore.instance;
  firestore.settings = const Settings(persistenceEnabled: false);
  firestore.useFirestoreEmulator(config.host, config.firestorePort,
      automaticHostMapping: false);
  // This package is separate from the owner app; never reuse its test identity.
  await auth.signOut();
  ApiService.setBaseUrl(api.toString());
  debugPrint(
      'FIREBASE_EMULATOR_READY project=${app.options.projectId} auth=${config.host}:${config.authPort} firestore=${firestore.settings.host} api=$api');
}
