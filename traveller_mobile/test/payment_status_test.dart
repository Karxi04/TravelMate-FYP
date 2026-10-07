import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_status.dart';
import 'package:travelmate_traveller/widgets/ink_card.dart';

void main() {
  test('fallback payment references are explicitly simulation, not Stripe', () {
    expect(isSimulatedPayment({'transactionReference': 'pi_sim_demo'}), isTrue);
    expect(isSimulatedPayment({'transactionReference': 'TM-PAY-DEMO'}), isTrue);
    expect(isSimulatedPayment({'transactionReference': 'pi_test_demo'}), isFalse);
    expect(isSimulatedPayment(null), isFalse);
  });

  test('canonical payment success and legacy aliases disable retry', () {
    for (final status in ['succeeded', 'successful', 'success', 'completed']) {
      expect(canonicalPaymentStatus(status), 'succeeded');
      expect(isSuccessfulPayment(status), isTrue);
      expect(canRetryPayment(status), isFalse);
      expect(canCancelPayment(status), isFalse);
    }
  });

  test('failure pending and cancelled actions remain compatible', () {
    expect(canRetryPayment('failed'), isTrue);
    expect(canCancelPayment('failed'), isTrue);
    expect(canRetryPayment('pending'), isTrue);
    expect(canCancelPayment('pending'), isTrue);
    expect(canRetryPayment('requires_payment_method'), isTrue);
    expect(canonicalPaymentStatus('canceled'), 'cancelled');
    expect(canRetryPayment('cancelled'), isTrue);
    expect(canCancelPayment('cancelled'), isFalse);
  });

  test('traveller-facing status labels hide provider terminology', () {
    expect(paymentStatusLabel('succeeded'), 'Payment successful');
    expect(paymentStatusLabel('failed'), 'Payment failed');
    expect(paymentStatusLabel('pending'), 'Checking payment status');
    expect(paymentStatusLabel('cancelled'), 'Payment cancelled');
  });

  test('network failures use safe traveller language', () {
    final message = travellerErrorMessage(
      Exception('TimeoutException after 0:00:25.000000: Future not completed'),
    );
    expect(message, contains('couldn’t connect'));
    expect(message, isNot(contains('TimeoutException')));
  });
}
