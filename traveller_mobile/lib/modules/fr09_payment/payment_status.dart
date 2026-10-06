String canonicalPaymentStatus(Object? raw) {
  final value = (raw ?? 'unknown').toString().trim().toLowerCase();
  return switch (value) {
    'successful' || 'success' || 'completed' => 'succeeded',
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
