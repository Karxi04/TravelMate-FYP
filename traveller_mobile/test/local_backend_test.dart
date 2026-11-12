import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:travelmate_traveller/services/local_backend.dart';

const home = 'http://192.168.100.26:5000';
const hotspot = 'http://172.20.10.5:5000';
const homeNetwork = (handle: 1, subnets: ['192.168.100.24/24']);
const hotspotNetwork = (handle: 2, subnets: ['172.20.10.7/28']);

class Harness {
  LocalNetwork? network = homeNetwork;
  final requests = <http.Request>[];
  int headerCalls = 0;
  bool verifies = true;
  bool redirect = false;
  Future<http.Response> Function(http.Request)? sendApi;

  late final backend = LocalBackend(
    primary: home,
    alternate: hotspot,
    publicKey: 'test key',
    network: () async => network,
    verify: (key, message, proof) async {
      final challenge = requests.last.url;
      expect(key, 'test key');
      expect(message,
          'travelmate-local-lan-v1\n${challenge.origin}\n${challenge.queryParameters['lanChallenge']}');
      return verifies && proof == 'expected proof';
    },
    client: () => MockClient((request) async {
      requests.add(request);
      expect(request.followRedirects, isFalse);
      if (request.url.path == '/api/health') {
        expect(request.headers.containsKey('Authorization'), isFalse);
        expect(request.url.queryParameters['lanChallenge'],
            matches(r'^[0-9a-f]{64}$'));
        if (redirect) {
          return http.Response('', 302,
              headers: {'location': '$hotspot/api/health'});
        }
        return http.Response(
            jsonEncode({
              'ok': true,
              'service': 'TravelMate Backend API',
              'lanProof': 'expected proof',
            }),
            200);
      }
      expect(request.headers['Authorization'], 'Bearer synthetic-fixture');
      return sendApi == null
          ? http.Response('{}', 200)
          : await sendApi!(request);
    }),
  );

  Future<http.Response> call(
    String method,
    String path, {
    Future<void> Function()? beforeSend,
  }) =>
      backend.request(method, path, timeout: const Duration(seconds: 1),
          headers: () async {
        headerCalls++;
        if (beforeSend != null) await beforeSend();
        return {'Authorization': 'Bearer synthetic-fixture'};
      });
}

void main() {
  test(
      'selects the two approved networks and reprobes when Android changes network',
      () async {
    final harness = Harness();
    await harness.call('GET', '/api/fr1/me');
    await harness.call('GET', '/api/fr5/itineraries');
    harness.network = hotspotNetwork;
    await harness.call('GET', '/api/fr1/me');
    harness.network = (handle: 3, subnets: homeNetwork.subnets);
    await harness.call('GET', '/api/fr1/me');
    expect(harness.requests.map((r) => '${r.url.origin}${r.url.path}'), [
      '$home/api/health',
      '$home/api/fr1/me',
      '$home/api/fr5/itineraries',
      '$hotspot/api/health',
      '$hotspot/api/fr1/me',
      '$home/api/health',
      '$home/api/fr1/me',
    ]);
  });

  test(
      'sends no Firebase headers for an unknown network, invalid proof, or redirect',
      () async {
    final harness = Harness()
      ..network = (handle: 4, subnets: ['192.168.42.19/24']);
    await expectLater(harness.call('GET', '/api/fr1/me'),
        throwsA(isA<http.ClientException>()));
    expect(harness.requests, isEmpty);
    harness.network = homeNetwork;
    harness.verifies = false;
    await expectLater(harness.call('POST', '/api/fr11/save-plan'),
        throwsA(isA<http.ClientException>()));
    harness.verifies = true;
    harness.redirect = true;
    await expectLater(harness.call('GET', '/api/fr1/me'),
        throwsA(isA<http.ClientException>()));
    expect(harness.headerCalls, 0);
    expect(harness.requests.map((r) => r.url.origin), [home, home]);
    expect(harness.requests.every((r) => r.url.path == '/api/health'), isTrue);
  });

  test('does not send the mutation if Wi-Fi changes while fetching auth',
      () async {
    final harness = Harness();
    await expectLater(
      harness.call('POST', '/api/fr11/save-plan', beforeSend: () async {
        harness.network = hotspotNetwork;
      }),
      throwsA(isA<http.ClientException>()),
    );
    expect(harness.requests.map((r) => r.url.path), ['/api/health']);
  });

  for (final (method, path) in [
    ('POST', '/api/fr9/checkout/session'),
    ('POST', '/api/fr8/hotels/book'),
    ('POST', '/api/fr11/save-plan'),
    ('PUT', '/api/fr5/itineraries/trip'),
    ('PATCH', '/api/fr5/itineraries/trip/packing-checklist'),
    ('DELETE', '/api/fr5/itineraries/trip'),
    ('GET', '/api/fr9/orders/order/reconcile'),
  ]) {
    test('$method $path stays on one origin and never replays on failure',
        () async {
      final inFlight = Completer<http.Response>();
      final entered = Completer<void>();
      final harness = Harness()
        ..sendApi = (_) {
          entered.complete();
          return inFlight.future;
        };
      final mutation = harness.call(method, path);
      final failure =
          expectLater(mutation, throwsA(isA<http.ClientException>()));
      await entered.future;
      harness.network = hotspotNetwork;
      await expectLater(harness.call('GET', '/api/fr1/me'),
          throwsA(isA<http.ClientException>()));
      inFlight.completeError(http.ClientException('Connection interrupted'));
      await failure;
      harness.sendApi = null;
      await harness.call('GET', '/api/fr1/me');
      expect(harness.requests.map((r) => '${r.url.origin}${r.url.path}'), [
        '$home/api/health',
        '$home$path',
        '$hotspot/api/health',
        '$hotspot/api/fr1/me',
      ]);
    });
  }

  test('the allowlist requires explicit private IPv4 HTTP origins', () {
    expect(privateLanOrigin('$home/').toString(), home);
    for (final invalid in [
      'http://travelmate.example:5000',
      'http://100.64.1.1:5000',
      'http://127.0.0.1:5000',
      'http://10.0.2.2:5000',
      '$home/path',
      '$home?key=value',
      'http://user@192.168.100.26:5000',
    ]) {
      expect(() => privateLanOrigin(invalid), throwsStateError,
          reason: invalid);
    }
  });
}
