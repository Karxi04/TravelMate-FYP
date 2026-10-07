import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'payment_status.dart';

class PaymentScreen extends StatefulWidget {
  final String initialBookingReference;
  final double? initialAmount;

  const PaymentScreen({
    super.key,
    this.initialBookingReference = '',
    this.initialAmount,
  });

  @override
  State<PaymentScreen> createState() => _PaymentScreenState();
}

class _PaymentScreenState extends State<PaymentScreen> {
  late final TextEditingController bookingId;
  late final TextEditingController amount;
  final cardholder = TextEditingController();
  final cardNumber = TextEditingController();
  final expiry = TextEditingController();
  final cvc = TextEditingController();
  final billingEmail = TextEditingController();
  final api = ApiService();

  Map<String, dynamic>? result;
  List<dynamic> history = [];
  bool busy = false;
  bool showCard = false;
  final paymentAttempt = TransactionAttemptLifecycle('payment');

  @override
  void initState() {
    super.initState();
    bookingId = TextEditingController(text: widget.initialBookingReference);
    amount = TextEditingController(
        text: widget.initialAmount?.toStringAsFixed(2) ?? '100.00');
    billingEmail.text = FirebaseAuth.instance.currentUser?.email ?? '';
    Future.microtask(loadHistory);
  }

  Future<void> loadHistory() async {
    try {
      final data = await api.get('/api/fr9/payments');
      if (mounted) setState(() => history = data['items'] ?? []);
    } catch (_) {}
  }

  String digits(String value) => value.replaceAll(RegExp(r'\D'), '');

  bool luhnValid(String value) {
    final number = digits(value);
    if (number.length < 13 || number.length > 19) return false;
    var sum = 0;
    var alternate = false;
    for (var i = number.length - 1; i >= 0; i--) {
      var n = int.parse(number[i]);
      if (alternate) {
        n *= 2;
        if (n > 9) n -= 9;
      }
      sum += n;
      alternate = !alternate;
    }
    return sum % 10 == 0;
  }

  bool expiryValid(String value) {
    final clean = value.replaceAll('/', '');

    if (clean.length != 4) {
      return false;
    }

    final month = int.tryParse(clean.substring(0, 2));

    final year = int.tryParse(clean.substring(2, 4));
    if (month == null || year == null || month < 1 || month > 12) return false;
    final fullYear = year < 100 ? 2000 + year : year;
    final now = DateTime.now();
    return fullYear > now.year || (fullYear == now.year && month >= now.month);
  }

  String cardBrand(String number) {
    final n = digits(number);
    if (n.startsWith('4')) return 'Visa';
    if (n.startsWith('5') || n.startsWith('2')) return 'Mastercard';
    if (n.startsWith('34') || n.startsWith('37')) return 'American Express';
    return 'Card';
  }

  Future<void> process() async {
    if (busy || isSuccessfulPayment(result?['paymentStatus'])) return;
    final value = double.tryParse(amount.text.trim()) ?? 0;
    final number = digits(cardNumber.text);

    if (value <= 0) {
      showError(context, 'Enter a valid payment amount.');
      return;
    }
    if (cardholder.text.trim().length < 2) {
      showError(context, 'Enter the cardholder name.');
      return;
    }
    if (number.length < 16) {
      showError(context, 'Card number must contain at least 16 digits.');
      return;
    }
    if (!expiryValid(expiry.text.trim())) {
      showError(context, 'Enter a valid future expiry date in MM/YY format.');
      return;
    }
    if (cvc.text.trim().length < 3) {
      showError(context, 'Enter a valid security code.');
      return;
    }
    if (!billingEmail.text.contains('@')) {
      showError(context, 'Enter a valid billing email.');
      return;
    }

    setState(() => busy = true);
    try {
      final paymentAttemptId = paymentAttempt.currentOrCreate;
      if (canonicalPaymentStatus(result?['paymentStatus']) == 'pending') {
        final reconciled = await api.get(
          '/api/fr9/payments/attempts/$paymentAttemptId',
        );
        if (reconciled['payment'] is Map) {
          result = Map<String, dynamic>.from(reconciled['payment'] as Map);
        }
        if (isSuccessfulPayment(result?['paymentStatus'])) {
          if (mounted) setState(() {});
          await loadHistory();
          return;
        }
      }
      await Future<void>.delayed(const Duration(milliseconds: 900));
      final data = await api.post('/api/fr9/payments/process', {
        'paymentAttemptId': paymentAttemptId,
        'bookingId': bookingId.text.trim(),
        'amount': value,
        'cardholderName': cardholder.text.trim(),
        'billingEmail': billingEmail.text.trim(),
        'cardBrand': cardBrand(number),
        'cardLast4': number.substring(number.length - 4),
      });
      if (!mounted) return;
      setState(
          () => result = Map<String, dynamic>.from(data['payment'] as Map));
      if (isSuccessfulPayment(result?['paymentStatus'])) {
        cardNumber.clear();
        expiry.clear();
        cvc.clear();
      }
      await loadHistory();
    } on TimeoutException {
      if (!mounted) return;
      setState(() => result = {
            'paymentAttemptId': paymentAttempt.current,
            'paymentStatus': 'pending',
            'transactionReference': 'Verification pending',
            'amount': value,
            'currency': 'MYR',
          });
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text(
          'The payment outcome is still being checked. The same attempt will be reconciled; no new payment was created.',
        ),
      ));
    } catch (e) {
      if (e is ApiException && e.data['newAttemptRequired'] == true) {
        paymentAttempt.startNewAttempt();
      }
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> updatePayment(String paymentId, String action) async {
    if (paymentId.isEmpty) {
      showError(context, 'Payment reference is unavailable.');
      return;
    }
    setState(() => busy = true);
    try {
      final data = await api.post('/api/fr9/payments/$paymentId/$action');
      if (!mounted) return;
      if (data['payment'] is Map) {
        result = Map<String, dynamic>.from(data['payment'] as Map);
      }
      await loadHistory();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(action == 'retry'
            ? 'Payment status checked.'
            : (data['message'] ?? 'Payment cancelled in TravelMate.')
                .toString()),
      ));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Secure card payment')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
        children: [
          const TravelSectionHeader(
            title: 'Checkout',
            subtitle:
                'Review the amount and complete a sandbox or simulated payment.',
          ),
          const SizedBox(height: 12),
          InkCard(
            color: InkWashColors.cream,
            child: const Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.lock_outline_rounded, color: InkWashColors.blueGrey),
                SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'This FYP checkout reproduces the complete card-payment process but does not charge real money. Full card numbers and security codes are never saved.',
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: bookingId,
            onChanged: (_) {
              if (!busy) {
                setState(() {
                  paymentAttempt.startNewAttempt();
                  result = null;
                });
              }
            },
            decoration: const InputDecoration(
                labelText: 'Booking reference',
                prefixIcon: Icon(Icons.confirmation_number_outlined)),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: amount,
            readOnly: widget.initialAmount != null,
            onChanged: (_) => setState(() {
              paymentAttempt.startNewAttempt();
              result = null;
            }),
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))
            ],
            decoration: InputDecoration(
              labelText: widget.initialAmount != null
                  ? 'Authoritative booking amount (RM)'
                  : 'Amount (RM)',
              prefixIcon: const Icon(Icons.payments_outlined),
              suffixIcon: widget.initialAmount != null
                  ? const Tooltip(
                      message:
                          'Amount is authoritative and tied to your booking.',
                      child: Icon(Icons.lock_outline, size: 18),
                    )
                  : null,
            ),
          ),
          const SizedBox(height: 18),
          const Text('Card details',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
          const SizedBox(height: 10),
          TextField(
            controller: cardholder,
            textCapitalization: TextCapitalization.words,
            decoration: const InputDecoration(
                labelText: 'Cardholder name',
                prefixIcon: Icon(Icons.person_outline_rounded)),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: cardNumber,
            keyboardType: TextInputType.number,
            obscureText: !showCard,
            inputFormatters: [
              CardNumberFormatter(),
              LengthLimitingTextInputFormatter(19),
            ],
            decoration: InputDecoration(
              labelText: 'Card number',
              hintText: '4242 4242 4242 4242',
              prefixIcon: const Icon(Icons.credit_card_rounded),
              suffixIcon: IconButton(
                onPressed: () => setState(() => showCard = !showCard),
                icon: Icon(showCard
                    ? Icons.visibility_off_outlined
                    : Icons.visibility_outlined),
              ),
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: expiry,
                  keyboardType: TextInputType.datetime,
                  inputFormatters: [LengthLimitingTextInputFormatter(5)],
                  decoration: const InputDecoration(
                      labelText: 'Expiry', hintText: 'MM/YY'),
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: TextField(
                  controller: cvc,
                  keyboardType: TextInputType.number,
                  obscureText: true,
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                    LengthLimitingTextInputFormatter(4)
                  ],
                  decoration:
                      const InputDecoration(labelText: 'CVC', hintText: '123'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            controller: billingEmail,
            keyboardType: TextInputType.emailAddress,
            decoration: const InputDecoration(
                labelText: 'Billing email',
                prefixIcon: Icon(Icons.email_outlined)),
          ),
          const SizedBox(height: 15),
          FilledButton.icon(
            onPressed: busy || isSuccessfulPayment(result?['paymentStatus'])
                ? null
                : process,
            icon: busy
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.lock_rounded),
            label: Text(busy
                ? 'Authorising payment...'
                : 'Pay RM ${amount.text.trim()}'),
          ),
          if (result != null) ...[
            const SizedBox(height: 18),
            InkCard(
              color: InkWashColors.cream,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    const Icon(Icons.check_circle_rounded,
                        color: InkWashColors.blueGrey),
                    const SizedBox(width: 8),
                    Text(
                        isSuccessfulPayment(result?['paymentStatus'])
                            ? (isSimulatedPayment(result)
                                ? 'Simulated payment completed'
                                : 'Sandbox payment completed')
                            : 'Payment verification pending',
                        style: const TextStyle(
                            fontWeight: FontWeight.w900, fontSize: 18))
                  ]),
                  const SizedBox(height: 10),
                  Text('Reference: ${result!['transactionReference']}'),
                  Text(
                      'Amount: ${result!['currency'] ?? 'MYR'} ${result!['amount']}'),
                  Text(
                      'Card: ${result!['cardBrand'] ?? 'Card'} •••• ${result!['cardLast4'] ?? ''}'),
                  Text('Status: ${result!['paymentStatus']}'),
                ],
              ),
            ),
          ],
          const SizedBox(height: 24),
          const TravelSectionHeader(
              title: 'Payment history',
              subtitle:
                  'Only transaction references and masked card information are stored.'),
          const SizedBox(height: 10),
          if (history.isEmpty)
            const TravelEmptyState(
                icon: Icons.receipt_long_outlined,
                title: 'No payments yet',
                message: 'Completed checkout records will appear here.'),
          ...history.take(10).map((raw) {
            final item = Map<String, dynamic>.from(raw as Map);
            final paymentId =
                (item['id'] ?? item['transactionReference'] ?? '').toString();
            final status = canonicalPaymentStatus(item['paymentStatus']);
            final kind = isSimulatedPayment(Map<String, dynamic>.from(item as Map))
                ? 'Simulated'
                : 'Sandbox';
            return Padding(
              padding: const EdgeInsets.only(bottom: 9),
              child: InkCard(
                child: Column(
                  children: [
                    Row(
                      children: [
                        const CircleAvatar(
                            backgroundColor: InkWashColors.paleBlue,
                            child: Icon(Icons.receipt_long_outlined,
                                color: InkWashColors.blueGrey)),
                        const SizedBox(width: 11),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                  (item['transactionReference'] ?? '')
                                      .toString(),
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w800)),
                              Text(
                                  '${item['cardBrand'] ?? 'Card'} •••• ${item['cardLast4'] ?? ''}',
                                  style: const TextStyle(
                                      color: InkWashColors.mutedInk,
                                      fontSize: 12)),
                              Text('$kind status: $status',
                                  style: const TextStyle(
                                      color: InkWashColors.mutedInk,
                                      fontSize: 12)),
                            ],
                          ),
                        ),
                        Text('RM ${item['amount'] ?? 0}',
                            style:
                                const TextStyle(fontWeight: FontWeight.w900)),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton.icon(
                          onPressed: busy || !canRetryPayment(status)
                              ? null
                              : () => updatePayment(paymentId, 'retry'),
                          icon: const Icon(Icons.refresh_rounded),
                          label: const Text('Retry'),
                        ),
                        const SizedBox(width: 6),
                        TextButton.icon(
                          onPressed: busy || !canCancelPayment(status)
                              ? null
                              : () => updatePayment(paymentId, 'cancel'),
                          icon: const Icon(Icons.cancel_outlined),
                          label: const Text('Cancel'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            );
          }),
        ],
      ),
    );
  }
}

class CardNumberFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
      TextEditingValue oldValue, TextEditingValue newValue) {
    String digits = newValue.text.replaceAll(' ', '');

    String formatted = '';

    for (int i = 0; i < digits.length; i++) {
      if (i > 0 && i % 4 == 0) {
        formatted += ' ';
      }

      formatted += digits[i];
    }

    return TextEditingValue(
        text: formatted,
        selection: TextSelection.collapsed(offset: formatted.length));
  }
}
