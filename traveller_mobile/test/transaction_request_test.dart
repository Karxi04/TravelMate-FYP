import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/transaction_request.dart';

void main() {
  test('ambiguous recovery retains the same attempt until explicitly reset',
      () {
    var sequence = 0;
    final lifecycle = TransactionAttemptLifecycle(
      'payment',
      generator: (prefix) => '${prefix}_attempt_${++sequence}',
    );

    final original = lifecycle.currentOrCreate;
    expect(lifecycle.retainForReconciliation(), original);
    expect(lifecycle.currentOrCreate, original);

    lifecycle.startNewAttempt();
    expect(lifecycle.currentOrCreate, isNot(original));
  });

  test('provider mutation timeout exceeds expected backend provider windows',
      () {
    expect(
      RequestTimeouts.forPost('/api/fr9/payments/process'),
      RequestTimeouts.providerMutation,
    );
    expect(
      RequestTimeouts.forPost('/api/fr8/hotels/book'),
      RequestTimeouts.providerMutation,
    );
    expect(RequestTimeouts.providerMutation.inSeconds, greaterThan(80));
    expect(RequestTimeouts.longProviderRead.inSeconds, greaterThan(65));
    expect(
      RequestTimeouts.forGet('/api/fr8/places/search'),
      RequestTimeouts.longProviderRead,
    );
    expect(
      RequestTimeouts.forGet('/api/fr1/me'),
      RequestTimeouts.ordinaryRead,
    );
    expect(
      RequestTimeouts.forPost('/api/fr5/personalised-trips/generate'),
      RequestTimeouts.personalisedGeneration,
    );
  });

  test('generated attempt IDs are opaque stable-format values', () {
    final first = newTransactionAttemptId('hotel');
    final second = newTransactionAttemptId('hotel');
    expect(first, matches(RegExp(r'^hotel_[a-f0-9]{36}$')));
    expect(second, isNot(first));
  });
}
