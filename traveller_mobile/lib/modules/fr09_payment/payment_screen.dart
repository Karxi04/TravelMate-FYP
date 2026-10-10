import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'payment_status.dart';
import 'orders_screen.dart';
import 'flight_quote_summary.dart';

class PaymentScreen extends StatefulWidget {
  final String initialBookingReference;
  final double? initialAmount;
  final String quoteType;
  final String quoteId;
  final String offerId;
  final String searchId;
  final String optionId;
  final String itineraryId;
  final ApiService? api;
  final CheckoutAttemptStore? attemptStore;

  const PaymentScreen({
    super.key,
    this.initialBookingReference = '',
    this.initialAmount,
    this.quoteType = '',
    this.quoteId = '',
    this.offerId = '',
    this.searchId = '',
    this.optionId = '',
    this.itineraryId = '',
    this.api,
    this.attemptStore,
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
  late final api = widget.api ?? ApiService();

  Map<String, dynamic>? result;
  List<dynamic> history = [];
  List<dynamic> orders = [];
  bool busy = false;
  bool showCard = false;
  final paymentAttempt = TransactionAttemptLifecycle('payment');
  late final checkoutAttempts = widget.attemptStore ?? CheckoutAttemptStore();
  Map<String, dynamic>? flightReview;
  String? flightFingerprint;
  String? flightReviewError;
  bool reviewLoading = false;

  bool get hostedCheckout => widget.quoteType.isNotEmpty && !api.isStandalone;

  @override
  void initState() {
    super.initState();
    bookingId = TextEditingController(text: widget.initialBookingReference);
    amount = TextEditingController(
        text: widget.initialAmount?.toStringAsFixed(2) ?? '100.00');
    if (!hostedCheckout)
      billingEmail.text = FirebaseAuth.instance.currentUser?.email ?? '';
    Future.microtask(() async {
      await loadHistory();
      if (hostedCheckout) await loadOrders();
      if (hostedCheckout && widget.quoteType == 'flight')
        await loadFlightReview();
    });
  }

  Future<void> loadHistory() async {
    try {
      final data = await api.get('/api/fr9/payments');
      if (mounted) setState(() => history = data['items'] ?? []);
    } catch (_) {}
  }

  Future<void> loadOrders() async {
    try {
      final data = await api.get('/api/fr9/orders');
      if (!mounted) return;
      setState(() => orders = data['items'] ?? []);
      for (final raw in orders.take(5)) {
        final item = Map<String, dynamic>.from(raw as Map);
        final status = (item['status'] ?? '').toString();
        if (item['id'] != null &&
            {'checkout_open', 'payment_pending', 'checkout_pending'}
                .contains(status)) {
          try {
            await api.get('/api/fr9/orders/${item['id']}/reconcile');
          } catch (_) {}
        }
      }
      final refreshed = await api.get('/api/fr9/orders');
      if (mounted) setState(() => orders = refreshed['items'] ?? []);
    } catch (_) {}
  }

  Future<void> loadFlightReview() async {
    if (!mounted) return;
    setState(() {
      reviewLoading = true;
      flightReview = null;
      flightFingerprint = null;
      flightReviewError = null;
    });
    try {
      final data = await api.post('/api/fr9/checkout/flight-review', {
        'searchId': widget.searchId,
        'optionId': widget.optionId,
        if (widget.itineraryId.isNotEmpty) 'itineraryId': widget.itineraryId,
      });
      if (mounted)
        setState(() {
          flightReview = Map<String, dynamic>.from(data['review'] as Map);
          flightFingerprint = data['fingerprint'].toString();
        });
    } catch (e) {
      if (mounted) setState(() => flightReviewError = userFacingApiError(e));
    } finally {
      if (mounted) setState(() => reviewLoading = false);
    }
  }

  bool get flightAlreadyPaid =>
      flightFingerprint != null &&
      orders.any((raw) =>
          raw is Map &&
          raw['quoteType'] == 'flight' &&
          raw['status'] == 'paid' &&
          raw['quoteFingerprint'] == flightFingerprint);

  Future<void> launchCheckout() async {
    if (busy) return;
    if (widget.quoteType == 'flight') {
      if (flightReview == null ||
          flightFingerprint == null ||
          reviewLoading ||
          flightAlreadyPaid) return;
      final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
                title: const Text('Confirm flight demo quote'),
                content: SingleChildScrollView(
                    child: FlightQuoteSummary(quote: flightReview!)),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Cancel')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Confirm this quote')),
                ],
              ));
      if (confirmed != true || !mounted) return;
    }
    setState(() => busy = true);
    try {
      final scope = [
        widget.quoteType,
        widget.quoteId,
        widget.offerId,
        widget.searchId,
        widget.optionId,
        if (widget.quoteType == 'flight') flightFingerprint,
      ].join('_');
      final terminalOrder = orders.any((raw) {
        final item = Map<String, dynamic>.from(raw as Map);
        final sameQuote = item['quoteType'] == widget.quoteType &&
            item['quoteId'] ==
                (widget.quoteType == 'hotel'
                    ? widget.quoteId
                    : widget.searchId);
        return sameQuote &&
            {'expired', 'payment_failed', 'payment_mismatch'}
                .contains(item['status']);
      });
      if (terminalOrder) await checkoutAttempts.clear(scope);
      final attemptId = await checkoutAttempts.loadOrCreate(scope);
      final data = await api.post('/api/fr9/checkout/session', {
        'orderAttemptId': attemptId,
        'quoteType': widget.quoteType,
        if (widget.quoteType == 'hotel') ...{
          'quoteId': widget.quoteId,
          'offerId': widget.offerId,
        },
        if (widget.quoteType == 'flight') ...{
          'searchId': widget.searchId,
          'optionId': widget.optionId,
          'confirmedFlightQuote': true,
          'flightQuoteFingerprint': flightFingerprint,
          if (widget.itineraryId.isNotEmpty) 'itineraryId': widget.itineraryId,
        },
      });
      final order = data['order'] is Map
          ? Map<String, dynamic>.from(data['order'] as Map)
          : <String, dynamic>{};
      final checkoutUrl = (order['checkoutUrl'] ?? '').toString();
      if (checkoutUrl.isEmpty ||
          !await launchUrl(Uri.parse(checkoutUrl),
              mode: LaunchMode.externalApplication)) {
        throw Exception('Stripe Checkout could not be opened.');
      }
      if (mounted) {
        setState(() => result = {
              'paymentStatus': order['paymentStatus'] ?? 'unpaid',
              'orderStatus': order['status'],
              'orderId': order['id'],
            });
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
              'Stripe test Checkout opened. Return here to check the order status.'),
        ));
      }
      await loadOrders();
    } catch (e) {
      if (mounted) showError(context, e);
      if (widget.quoteType == 'flight') await loadFlightReview();
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> reconcileOrder(String orderId) async {
    if (orderId.isEmpty || busy) return;
    setState(() => busy = true);
    try {
      await api.get('/api/fr9/orders/$orderId/reconcile');
      await loadOrders();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
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

  Widget _buildHostedCheckout() {
    return Scaffold(
      appBar: AppBar(title: const Text('TravelMate Checkout')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
        children: [
          const TravelSectionHeader(
            title: 'Stripe test Checkout',
            subtitle:
                'Card details are entered only on Stripe-hosted Checkout.',
          ),
          const SizedBox(height: 12),
          if (widget.quoteType == 'flight') ...[
            if (reviewLoading) const CircularProgressIndicator(),
            if (flightReviewError != null) Text(flightReviewError!),
            if (flightReview != null) FlightQuoteSummary(quote: flightReview!),
            TextButton(
                onPressed: busy || reviewLoading ? null : loadFlightReview,
                child: const Text('Refresh flight quote')),
          ] else
            InkCard(
              color: InkWashColors.cream,
              child: const Text(
                'This is a Stripe test-mode order. The selected hotel quote is a provider sandbox quote and is not live inventory. The provider offer total covers the requested stay and occupancy; any excluded property fees remain due at the property. TravelMate does not receive or store card numbers or security codes.',
              ),
            ),
          const SizedBox(height: 14),
          if (widget.initialBookingReference.isNotEmpty)
            Text('Booking reference: ${widget.initialBookingReference}'),
          if (widget.initialAmount != null)
            Text(
                'Authoritative quote: MYR ${widget.initialAmount!.toStringAsFixed(2)}'),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: busy ||
                    (widget.quoteType == 'flight' &&
                        (reviewLoading ||
                            flightReview == null ||
                            flightAlreadyPaid))
                ? null
                : launchCheckout,
            icon: busy
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.open_in_new_rounded),
            label: Text(busy
                ? 'Preparing Checkout…'
                : flightAlreadyPaid && widget.quoteType == 'flight'
                    ? 'This flight demo order is paid'
                    : 'Open Stripe test Checkout'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
              builder: (_) => const OrdersScreen(),
            )),
            child: const Text('View Orders and order details'),
          ),
          const SizedBox(height: 24),
          const TravelSectionHeader(
            title: 'Order history',
            subtitle:
                'Pending orders are reconciled when you return to the app.',
          ),
          const SizedBox(height: 10),
          if (orders.isEmpty)
            const TravelEmptyState(
              icon: Icons.receipt_long_outlined,
              title: 'No Checkout orders yet',
              message: 'Your Stripe test orders will appear here.',
            ),
          ...orders.take(10).map((raw) {
            final item = Map<String, dynamic>.from(raw as Map);
            final orderId = (item['id'] ?? '').toString();
            final status = (item['status'] ?? 'unknown').toString();
            return Padding(
              padding: const EdgeInsets.only(bottom: 9),
              child: InkCard(
                child: Row(
                  children: [
                    const CircleAvatar(
                      backgroundColor: InkWashColors.paleBlue,
                      child: Icon(Icons.receipt_long_outlined,
                          color: InkWashColors.blueGrey),
                    ),
                    const SizedBox(width: 11),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                              '${item['quoteType'] ?? 'Order'} · ${item['currency'] ?? 'MYR'} ${item['amount'] ?? ''}',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w800)),
                          Text(status,
                              style: const TextStyle(
                                  color: InkWashColors.mutedInk, fontSize: 12)),
                        ],
                      ),
                    ),
                    if ({'checkout_open', 'payment_pending', 'checkout_pending'}
                        .contains(status))
                      IconButton(
                        tooltip: 'Check status',
                        onPressed: busy ? null : () => reconcileOrder(orderId),
                        icon: const Icon(Icons.refresh_rounded),
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

  @override
  Widget build(BuildContext context) {
    if (hostedCheckout) return _buildHostedCheckout();
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
                                ? 'Demo payment · no real charge'
                                : 'Test payment · no real charge')
                            : paymentStatusLabel(result?['paymentStatus']),
                        style: const TextStyle(
                            fontWeight: FontWeight.w900, fontSize: 18))
                  ]),
                  const SizedBox(height: 10),
                  if (!isSuccessfulPayment(result?['paymentStatus']))
                    const Text(
                        'We’re still checking this payment. Use Check status before trying again.'),
                  Text(
                      'Amount: ${result!['currency'] ?? 'MYR'} ${result!['amount']}'),
                  Text(
                      'Card: ${result!['cardBrand'] ?? 'Card'} •••• ${result!['cardLast4'] ?? ''}'),
                  Text(paymentStatusLabel(result!['paymentStatus'])),
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
            final kind =
                isSimulatedPayment(Map<String, dynamic>.from(item as Map))
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
                              Text('$kind · ${paymentStatusLabel(status)}',
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
