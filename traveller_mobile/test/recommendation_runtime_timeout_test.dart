import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:travelmate_traveller/services/local_backend.dart';
import 'package:travelmate_traveller/services/transaction_request.dart';

class _DelayedBackend {
  final Duration delay;
  int posts = 0;
  _DelayedBackend(this.delay);
  late final backend = LocalBackend(
    primary: 'http://192.168.100.26:5000',
    alternate: 'http://172.20.10.5:5000',
    publicKey: 'synthetic fixture',
    network: () async => (handle: 1, subnets: ['192.168.100.90/24']),
    verify: (_, __, ___) async => true,
    client: () => MockClient((request) async {
      if (request.url.path == '/api/health') {
        return http.Response(
            '{"ok":true,"service":"TravelMate Backend API","lanProof":"fixture"}',
            200);
      }
      posts++;
      await Future<void>.delayed(delay);
      return http.Response('{"ok":true}', 200);
    }),
  );
}

void main() {
  testWidgets('the observed 42-second generation returns without replay',
      (tester) async {
    final harness = _DelayedBackend(const Duration(seconds: 42));
    http.Response? response;
    Object? failure;
    unawaited(harness.backend
        .request('POST', '/api/fr4/recommendations/generate',
            timeout:
                RequestTimeouts.forPost('/api/fr4/recommendations/generate'),
            headers: () async => {'Authorization': 'Bearer synthetic-fixture'})
        .then<void>((value) => response = value,
            onError: (Object error) => failure = error));
    await tester.pump();
    await tester.pump(const Duration(seconds: 42));
    expect(failure, isNull);
    expect(response?.statusCode, 200);
    expect(harness.posts, 1);
  });

  testWidgets('generation still times out once within its bounded window',
      (tester) async {
    final harness = _DelayedBackend(const Duration(seconds: 180));
    Object? failure;
    unawaited(harness.backend
        .request('POST', '/api/fr4/recommendations/generate',
            timeout:
                RequestTimeouts.forPost('/api/fr4/recommendations/generate'),
            headers: () async => {'Authorization': 'Bearer synthetic-fixture'})
        .then<void>((_) {}, onError: (Object error) => failure = error));
    await tester.pump();
    await tester.pump(const Duration(seconds: 149));
    final beforeDeadline = failure;
    await tester.pump(const Duration(seconds: 2));
    final afterDeadline = failure;
    await tester.pump(const Duration(seconds: 30));
    expect(beforeDeadline, isNull);
    expect(afterDeadline, isA<TimeoutException>());
    expect(harness.posts, 1);
  });

  testWidgets('legacy 35-second deadline reproduces late server success',
      (tester) async {
    final harness = _DelayedBackend(const Duration(seconds: 42));
    Object? failure;
    unawaited(harness.backend
        .request('POST', '/api/fr4/recommendations/generate',
            timeout: const Duration(seconds: 35),
            headers: () async => {'Authorization': 'Bearer synthetic-fixture'})
        .then<void>((_) {}, onError: (Object error) => failure = error));
    await tester.pump();
    await tester.pump(const Duration(seconds: 42));
    expect(failure, isA<TimeoutException>());
    expect(harness.posts, 1);
  });

  test('only recommendation generation receives its longer deadline', () {
    expect(RequestTimeouts.forPost('/api/fr4/recommendations/generate'),
        const Duration(seconds: 150));
    expect(RequestTimeouts.forGet('/api/fr4/recommendations'),
        RequestTimeouts.ordinaryRead);
    expect(RequestTimeouts.forPost('/api/fr2/preferences'),
        RequestTimeouts.ordinaryWrite);
    expect(RequestTimeouts.forPost('/api/fr9/checkout/session'),
        RequestTimeouts.providerMutation);
    expect(RequestTimeouts.forPost('/api/fr8/hotels/book'),
        RequestTimeouts.providerMutation);
  });
}
