import '../../services/api_service.dart';

const academicPaymentDisclosure =
    'Academic demonstration — no actual charge or supplier reservation.';

Future<Set<String>> loadHostedCheckoutCapabilities(ApiService api) async {
  if (api.isStandalone) return {};
  try {
    final data = await api.get('/api/fr9/checkout/capabilities');
    if (data['ok'] != true || data['mode'] != 'test' ||
        data['hostedCheckout'] != true) return {};
    return (data['supportedQuoteTypes'] as List? ?? const [])
        .whereType<String>().where({'hotel', 'package'}.contains).toSet();
  } catch (_) {
    return {}; // Missing/unreachable capability must never enable Checkout.
  }
}

bool isTestPaymentRecord(Map<String, dynamic> record) =>
    record['testMode'] == true || record['isSimulated'] == true ||
    isSimulatedPayment(record) ||
    '${record['paymentProvider'] ?? record['provider'] ?? ''}'.toLowerCase().endsWith('_test');

String canonicalPaymentStatus(Object? raw) {
  final value = (raw ?? 'unknown').toString().trim().toLowerCase();
  return switch (value) {
    'successful' || 'success' || 'completed' || 'paid' => 'succeeded',
    'canceled' => 'cancelled',
    _ => value,
  };
}

bool isSuccessfulPayment(Object? raw) =>
    canonicalPaymentStatus(raw) == 'succeeded';

bool isSimulatedPayment(Map<String, dynamic>? payment) {
  final reference = (payment?['transactionReference'] ?? '').toString();
  return reference.startsWith('pi_sim_') || reference.startsWith('TM-PAY-');
}

bool canRetryPayment(Object? raw) {
  final status = canonicalPaymentStatus(raw);
  return status != 'succeeded';
}

bool canCancelPayment(Object? raw) {
  final status = canonicalPaymentStatus(raw);
  return status != 'succeeded' && status != 'cancelled';
}

String paymentStatusLabel(Object? raw) {
  return switch (canonicalPaymentStatus(raw)) {
    'succeeded' => 'Payment successful',
    'failed' || 'requires_payment_method' => 'Payment failed',
    'cancelled' => 'Payment cancelled',
    'pending' || 'processing' => 'Checking payment status',
    _ => 'Payment status unavailable',
  };
}
