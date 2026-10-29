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
import '../fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import '../fr08_hotel_booking/hotel_order_details_screen.dart';
import 'payment_history_screen.dart';
import 'payment_status.dart';

class PaymentScreen extends StatefulWidget {
  final String initialBookingReference;
  final double? initialAmount;
  final String quoteType;
  final String quoteId;
  final String offerId;
  final String searchId;
  final String optionId;
  final String packageAttemptId;
  final String acceptedPrebookSnapshotId;
  final Map<String, dynamic>? acceptedPrebook;
  final String? hotelBookingAttemptId;
  final ApiService? api;

  const PaymentScreen({
    super.key,
    this.initialBookingReference = '',
    this.initialAmount,
    this.quoteType = '',
    this.quoteId = '',
    this.offerId = '',
    this.searchId = '',
    this.optionId = '',
    this.packageAttemptId = '',
    this.acceptedPrebookSnapshotId = '',
    this.acceptedPrebook,
    this.hotelBookingAttemptId,
    this.api,
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
  late final ApiService api;

  Map<String, dynamic>? result;
  List<dynamic> history = [];
  List<dynamic> orders = [];
  bool busy = false;
  bool showCard = false;
  final paymentAttempt = TransactionAttemptLifecycle('payment');
  final checkoutAttempts = CheckoutAttemptStore();

  String currentAttemptId = '';
  Map<String, dynamic>? activeOrder;
  String checkoutAction = 'open_checkout';
  String? checkoutUrl;
  final TransactionAttemptLifecycle _packageRestartIntent =
      TransactionAttemptLifecycle('package_checkout_restart');

  bool get hostedCheckout =>
      (widget.quoteType.isNotEmpty || widget.packageAttemptId.isNotEmpty) && !api.isStandalone;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    currentAttemptId = widget.packageAttemptId;
    bookingId = TextEditingController(text: widget.initialBookingReference);
    amount = TextEditingController(
        text: widget.initialAmount?.toStringAsFixed(2) ?? '100.00');
    try {
      billingEmail.text = FirebaseAuth.instance.currentUser?.email ?? '';
    } catch (_) {}
    Future.microtask(() async {
      await loadHistory();
      if (hostedCheckout) await loadOrders();
    });
  }

  Future<void> loadHistory() async {
    try {
      final data = await api.get('/api/fr9/payments');
      if (mounted) setState(() => history = data['items'] ?? []);
    } catch (_) {}
  }

  void _syncActiveOrderFromList(List<Map<String, dynamic>> list) {
    final isPackage = (currentAttemptId.isNotEmpty || widget.packageAttemptId.isNotEmpty);
    final targetAttempt = currentAttemptId.isNotEmpty ? currentAttemptId : widget.packageAttemptId;

    Map<String, dynamic>? match;
    if (activeOrder?['id'] != null) {
      match = list.cast<Map<String, dynamic>?>().firstWhere(
        (item) => item?['id'] == activeOrder!['id'],
        orElse: () => null,
      );
    }
    if (match == null && isPackage && targetAttempt.isNotEmpty) {
      match = list.cast<Map<String, dynamic>?>().firstWhere(
        (item) => item?['packageAttemptId'] == targetAttempt || item?['orderAttemptId'] == targetAttempt,
        orElse: () => null,
      );
    }
    if (match == null && !isPackage && widget.quoteType.isNotEmpty) {
      match = list.cast<Map<String, dynamic>?>().firstWhere(
        (item) => item?['quoteType'] == widget.quoteType &&
            (item?['quoteId'] == (widget.quoteType == 'hotel' ? widget.quoteId : widget.searchId) ||
             (widget.quoteType == 'hotel' && widget.acceptedPrebookSnapshotId.isNotEmpty &&
              item?['acceptedPrebookSnapshotId'] == widget.acceptedPrebookSnapshotId)),
        orElse: () => null,
      );
    }

    if (match != null) {
      activeOrder = match;
      final action = (match['checkoutAction'] ?? _deriveAction(match)).toString();
      checkoutAction = action;
      final url = (match['checkoutUrl'] ?? '').toString();
      if (url.isNotEmpty) checkoutUrl = url;
      result = {
        'paymentStatus': match['paymentStatus'] ?? 'unpaid',
        'orderStatus': match['status'],
        'orderId': match['id'],
        if (match['fulfilledTripId'] != null)
          'fulfilledTripId': match['fulfilledTripId'],
      };
    }
  }

  Future<void> loadOrders() async {
    try {
      final data = await api.get('/api/fr9/orders');
      if (!mounted) return;
      final rawList = data['items'] as List? ?? [];
      final parsed = rawList
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
      if (mounted) {
        setState(() {
          orders = parsed;
          _syncActiveOrderFromList(parsed);
        });
      }
    } catch (_) {}
  }

  String _deriveAction(Map<String, dynamic> order) {
    final status = (order['status'] ?? '').toString().toLowerCase();
    final paymentStatus = (order['paymentStatus'] ?? '').toString().toLowerCase();
    if (status == 'paid' || paymentStatus == 'paid' || paymentStatus == 'succeeded') {
      return 'view_booking';
    }
    if ({'expired', 'payment_failed', 'cancelled', 'canceled', 'checkout_failed'}.contains(status)) {
      return 'restart_payment';
    }
    if (status == 'checkout_open' && (order['checkoutUrl'] ?? '').toString().isNotEmpty) {
      return 'continue_payment';
    }
    return 'check_status';
  }

  bool _paymentUnavailable() {
    if (consumerPaymentsAvailable) return false;
    showError(context, 'Payments are not available in TravelMate. Your saved travel details and history are unchanged.');
    return true;
  }

  Future<void> launchCheckout() async {
    if (_paymentUnavailable() || busy) return;

    if (checkoutAction == 'view_booking' || isSuccessfulPayment(result?['paymentStatus']) || activeOrder?['status'] == 'paid') {
      _navigateToBooking();
      return;
    }

    if (checkoutAction == 'continue_payment' && checkoutUrl != null && checkoutUrl!.isNotEmpty) {
      final uri = Uri.tryParse(checkoutUrl!);
      if (uri != null && await launchUrl(uri, mode: LaunchMode.externalApplication)) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Secure Checkout opened. Return here to check the order status.'),
          ));
        }
        return;
      }
    }

    if (checkoutAction == 'check_status' && activeOrder?['id'] != null) {
      await reconcileOrder((activeOrder!['id']).toString());
      return;
    }

    if (checkoutAction == 'restart_payment') {
      await _handleRestartPayment();
      return;
    }

    if (widget.quoteType == 'flight') {
      showError(context,
          'TravelMate can save this fare as a planning estimate, but cannot issue or reserve an airline ticket.');
      return;
    }

    if (widget.quoteType == 'hotel') {
      if (widget.acceptedPrebookSnapshotId.isEmpty) {
        showError(context,
            'An accepted hotel prebook snapshot is required before Checkout.');
        return;
      }
      if (widget.acceptedPrebook != null &&
          widget.acceptedPrebook!['expiresAt'] != null) {
        final exp = DateTime.tryParse(
            widget.acceptedPrebook!['expiresAt'].toString());
        if (exp != null && DateTime.now().toUtc().isAfter(exp.toUtc())) {
          showError(context,
              'This accepted hotel price has expired. Search and validate the offer again.');
          return;
        }
      }
    }

    setState(() => busy = true);
    try {
      final isPackage = currentAttemptId.isNotEmpty || widget.packageAttemptId.isNotEmpty;
      final scope = isPackage ? (currentAttemptId.isNotEmpty ? currentAttemptId : widget.packageAttemptId) : [
        widget.quoteType,
        widget.quoteId,
        widget.offerId,
        if (widget.quoteType == 'hotel' && widget.acceptedPrebookSnapshotId.isNotEmpty)
          widget.acceptedPrebookSnapshotId,
        widget.searchId,
        widget.optionId,
      ].join('_');

      final terminalOrder = orders.any((raw) {
        final item = Map<String, dynamic>.from(raw as Map);
        final sameQuote = isPackage
            ? (item['packageAttemptId'] == scope || item['orderAttemptId'] == scope)
            : (item['quoteType'] == widget.quoteType &&
                item['quoteId'] == (widget.quoteType == 'hotel' ? widget.quoteId : widget.searchId));
        return sameQuote &&
            {'expired', 'payment_failed', 'payment_mismatch', 'cancelled'}.contains(item['status']);
      });
      String attemptId = scope;
      if (!isPackage) {
        if (terminalOrder) await checkoutAttempts.clear(scope);
        attemptId = await checkoutAttempts.loadOrCreate(scope);
      }

      final endpoint = isPackage
          ? '/api/fr9/package-checkout-attempts/$scope/checkout/session'
          : '/api/fr9/checkout/session';

      final data = await api.post(endpoint, {
        if (!isPackage) ...{
          'orderAttemptId': attemptId,
          'quoteType': widget.quoteType,
          if (widget.quoteType == 'hotel') ...{
            'quoteId': widget.quoteId,
            'offerId': widget.offerId,
            'acceptedPrebookSnapshotId': widget.acceptedPrebookSnapshotId,
          },
          if (widget.quoteType == 'flight') ...{
            'searchId': widget.searchId,
            'optionId': widget.optionId,
          },
        },
      });

      final order = data['order'] is Map
          ? Map<String, dynamic>.from(data['order'] as Map)
          : <String, dynamic>{};
      final action = (order['checkoutAction'] ?? _deriveAction(order)).toString();
      final url = (order['checkoutUrl'] ?? '').toString();

      activeOrder = order;
      checkoutAction = action;
      if (url.isNotEmpty) checkoutUrl = url;

      if (mounted) {
        setState(() => result = {
              'paymentStatus': order['paymentStatus'] ?? 'unpaid',
              'orderStatus': order['status'],
              'orderId': order['id'],
              if (order['fulfilledTripId'] != null)
                'fulfilledTripId': order['fulfilledTripId'],
            });
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(switch (action) {
            'continue_payment' => 'Secure Checkout opened. Return here to check the order status.',
            'view_booking' => 'Payment is already verified. No additional payment was opened.',
            'restart_payment' => 'This Checkout Session has ended. You can restart payment.',
            _ => 'Payment status is still being verified. No additional payment was opened.',
          }),
        ));
      }

      if (action == 'continue_payment') {
        if (url.isEmpty || !await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication)) {
          throw Exception('Stripe Checkout could not be opened.');
        }
      }
    } on ApiException catch (e) {
      if (mounted) {
        if (e.code == 'flight_ticketing_unavailable') {
          showError(context,
              'TravelMate can save this fare as a planning estimate, but cannot issue or reserve an airline ticket.');
        } else {
          showError(context, e.message.isNotEmpty ? e.message : e.toString());
        }
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
      unawaited(loadOrders());
    }
  }

  Future<void> reconcileActiveOrder() async {
    if (_paymentUnavailable()) return;
    final orderId = (activeOrder?['id'] ?? result?['orderId'] ?? '').toString();
    if (orderId.isNotEmpty) {
      await reconcileOrder(orderId);
    } else {
      await loadOrders();
    }
  }

  Future<void> reconcileOrder(String orderId) async {
    if (_paymentUnavailable()) return;
    if (orderId.isEmpty || busy) return;
    setState(() => busy = true);
    try {
      final response = await api.get('/api/fr9/orders/$orderId/reconcile');
      final order = response['order'] is Map
          ? Map<String, dynamic>.from(response['order'] as Map)
          : <String, dynamic>{};
      final action = (order['checkoutAction'] ?? _deriveAction(order)).toString();
      final url = (order['checkoutUrl'] ?? '').toString();

      activeOrder = order;
      checkoutAction = action;
      if (url.isNotEmpty) checkoutUrl = url;

      if (mounted) {
        setState(() {
          result = {
            'paymentStatus': order['paymentStatus'] ?? 'unpaid',
            'orderStatus': order['status'],
            'orderId': order['id'],
            if (order['fulfilledTripId'] != null)
              'fulfilledTripId': order['fulfilledTripId'],
          };
        });

        final msg = switch (action) {
          'view_booking' => widget.quoteType == 'hotel'
              ? 'Payment verified (Stripe Test Mode). Hotel reservations require direct property confirmation and are not submitted to suppliers.'
              : 'Payment verified! Your booking is confirmed.',
          'continue_payment' => 'Checkout is open. Tap Continue Payment on Stripe to complete.',
          'restart_payment' => 'Previous session has expired. You may restart payment.',
          _ => 'Payment status is still being verified. No additional payment was opened.',
        };
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
      }
    } on ApiException catch (e) {
      if (mounted) {
        if (e.code == 'flight_ticketing_unavailable') {
          showError(context,
              'TravelMate can save this fare as a planning estimate, but cannot issue or reserve an airline ticket.');
        } else {
          showError(context, e.message.isNotEmpty ? e.message : e.toString());
        }
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
      unawaited(loadOrders());
    }
  }

  Future<void> _handleRestartPayment() async {
    if (_paymentUnavailable()) return;
    setState(() => busy = true);
    try {
      final isPackage = currentAttemptId.isNotEmpty || widget.packageAttemptId.isNotEmpty || (activeOrder?['quoteType'] == 'package');
      if (!isPackage) {
        final scope = [
          widget.quoteType,
          widget.quoteId,
          widget.offerId,
          widget.searchId,
          widget.optionId,
        ].join('_');
        await checkoutAttempts.clear(scope);
        activeOrder = null;
        checkoutAction = 'open_checkout';
        checkoutUrl = null;
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Previous session cleared. Tap to open fresh Checkout.'),
          ));
        }
        return;
      }

      final snapshot = activeOrder?['packageSnapshot'] is Map
          ? Map<String, dynamic>.from(activeOrder!['packageSnapshot'] as Map)
          : <String, dynamic>{};
      final packageId = (activeOrder?['packageId'] ?? snapshot['packageId'] ?? '').toString();
      final departureDate = (activeOrder?['departureDate'] ?? snapshot['selectedDepartureDate'])?.toString();
      final participants = (activeOrder?['participants'] ?? snapshot['participants']) is Map
          ? Map<String, dynamic>.from((activeOrder?['participants'] ?? snapshot['participants']) as Map)
          : <String, dynamic>{'adults': 1, 'children': 0};

      if (packageId.isEmpty) {
        throw Exception('Package details are unavailable to restart payment. Please return to the package page.');
      }

      _packageRestartIntent.startNewAttempt();
      final restartResponse = await api.post('/api/fr15/package-checkout-attempts', {
        'packageId': packageId,
        if (departureDate != null && departureDate.isNotEmpty)
          'departureDate': departureDate,
        'participants': {
          'adults': participants['adults'] ?? 1,
          'children': participants['children'] ?? 0,
        },
        'idempotencyKey': _packageRestartIntent.currentOrCreate,
      });

      final newAttempt = restartResponse['attempt'] is Map
          ? Map<String, dynamic>.from(restartResponse['attempt'] as Map)
          : <String, dynamic>{};
      final newAttemptId = (newAttempt['id'] ?? '').toString();
      if (newAttemptId.isEmpty) {
        throw Exception('A new package checkout attempt could not be prepared.');
      }

      currentAttemptId = newAttemptId;
      activeOrder = null;
      checkoutAction = 'open_checkout';
      checkoutUrl = null;

      final sessionResponse = await api.post(
        '/api/fr9/package-checkout-attempts/$newAttemptId/checkout/session',
        {},
      );

      final order = sessionResponse['order'] is Map
          ? Map<String, dynamic>.from(sessionResponse['order'] as Map)
          : <String, dynamic>{};
      final action = (order['checkoutAction'] ?? _deriveAction(order)).toString();
      final url = (order['checkoutUrl'] ?? '').toString();

      activeOrder = order;
      checkoutAction = action;
      if (url.isNotEmpty) checkoutUrl = url;

      if (mounted) {
        setState(() {
          result = {
            'paymentStatus': order['paymentStatus'] ?? 'unpaid',
            'orderStatus': order['status'],
            'orderId': order['id'],
            if (order['fulfilledTripId'] != null)
              'fulfilledTripId': order['fulfilledTripId'],
          };
        });
      }

      if (action == 'continue_payment' && url.isNotEmpty) {
        if (!await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication)) {
          throw Exception('Stripe Checkout could not be opened.');
        }
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Fresh Stripe Checkout opened.'),
          ));
        }
      } else {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(action == 'view_booking'
                ? 'Payment is verified.'
                : 'New payment session created. Return here to check status.'),
          ));
        }
      }
    } on ApiException catch (e) {
      if (mounted) {
        if (e.code == 'flight_ticketing_unavailable') {
          showError(context,
              'TravelMate can save this fare as a planning estimate, but cannot issue or reserve an airline ticket.');
        } else {
          showError(context, e.message.isNotEmpty ? e.message : e.toString());
        }
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
      unawaited(loadOrders());
    }
  }

  void _navigateToBooking() {
    final tripId = (activeOrder?['fulfilledTripId'] ?? activeOrder?['tripId'] ?? result?['fulfilledTripId'] ?? '').toString();
    final isHotel = widget.quoteType == 'hotel' || activeOrder?['quoteType'] == 'hotel';
    final orderId = (activeOrder?['id'] ?? result?['orderId'] ?? '').toString();

    if (tripId.isNotEmpty) {
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => PackageTripDetailsScreen(tripId: tripId, api: api),
        ),
      );
    } else if (isHotel && orderId.isNotEmpty) {
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => HotelOrderDetailsScreen(
            orderId: orderId,
            initialOrder: activeOrder,
            api: api,
          ),
        ),
      );
    } else {
      Navigator.pop(context, true);
    }
  }

  Future<void> _reopenStripe() async {
    if (_paymentUnavailable()) return;
    if (checkoutUrl != null && checkoutUrl!.isNotEmpty) {
      final uri = Uri.tryParse(checkoutUrl!);
      if (uri != null && await launchUrl(uri, mode: LaunchMode.externalApplication)) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Secure Checkout opened. Return here to check the order status.'),
          ));
        }
      }
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
    if (_paymentUnavailable()) return;
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
    if (_paymentUnavailable()) return;
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
    } on ApiException catch (e) {
      if (mounted) {
        if (e.code == 'flight_ticketing_unavailable') {
          showError(context,
              'TravelMate can save this fare as a planning estimate, but cannot issue or reserve an airline ticket.');
        } else {
          showError(context, e.message.isNotEmpty ? e.message : e.toString());
        }
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Widget _buildDisclaimer() {
    final isPackage = widget.packageAttemptId.isNotEmpty ||
        widget.quoteType == 'package' ||
        activeOrder?['quoteType'] == 'package';
    final isHotel = widget.quoteType == 'hotel';

    final String text;
    if (isPackage) {
      text =
          'This is a Stripe test-mode order for an operator tourism package. Payment confirms your booking and fulfills a dedicated Package Trip in TravelMate. Supplier reservations remain managed by the licensed operator. TravelMate does not receive or store card numbers or security codes.';
    } else if (isHotel) {
      text =
          'Stripe Test Mode — No real payment will be charged. This checkout does not confirm a reservation with the hotel. The selected hotel quote is a provider sandbox quote and is not live inventory. The provider offer total covers the requested stay and occupancy; any excluded property fees remain due at the property. TravelMate does not receive or store card numbers or security codes.';
    } else {
      text =
          'This is a Stripe test-mode order. Payment confirms your verified fare quote. TravelMate does not receive or store card numbers or security codes.';
    }

    return InkCard(
      color: InkWashColors.cream,
      child: Text(
        text,
        style: const TextStyle(color: InkWashColors.ink, height: 1.35),
      ),
    );
  }

  Widget _buildHostedCheckout() {
    final isPackage = widget.packageAttemptId.isNotEmpty ||
        widget.quoteType == 'package' ||
        activeOrder?['quoteType'] == 'package';
    final isHotel = widget.quoteType == 'hotel';
    final snapshot = activeOrder?['packageSnapshot'] is Map
        ? Map<String, dynamic>.from(activeOrder!['packageSnapshot'] as Map)
        : (activeOrder?['quoteSnapshot'] is Map
            ? Map<String, dynamic>.from(activeOrder!['quoteSnapshot'] as Map)
            : null);
    final productTitle = (snapshot?['title'] ??
            snapshot?['name'] ??
            snapshot?['roomName'] ??
            widget.initialBookingReference)
        .toString()
        .trim();

    final departure =
        (activeOrder?['departureDate'] ?? snapshot?['selectedDepartureDate'])
            ?.toString();
    final rawParticipants =
        activeOrder?['participants'] ?? snapshot?['participants'];
    String? participantsDesc;
    if (rawParticipants is Map) {
      final a = rawParticipants['adults'] ?? 0;
      final c = rawParticipants['children'] ?? 0;
      participantsDesc =
          '$a Adult${a != 1 ? 's' : ''}${c > 0 ? ', $c Child${c != 1 ? 'ren' : ''}' : ''}';
    }

    final displayAmount = activeOrder?['amount'] != null
        ? num.tryParse(activeOrder!['amount'].toString())?.toDouble()
        : widget.initialAmount;

    final currentAction = checkoutAction;
    final bool isFlight = widget.quoteType == 'flight';
    final bool isPaid = activeOrder?['status'] == 'paid' ||
        activeOrder?['paymentStatus'] == 'paid' ||
        result?['paymentStatus'] == 'paid' ||
        currentAction == 'view_booking';
    final bool isHotelMissingSnapshot =
        isHotel && widget.acceptedPrebookSnapshotId.isEmpty && activeOrder == null;
    final (statusLabel, statusTone, statusIcon) = switch (currentAction) {
      'view_booking' => (
          isHotel
              ? 'Payment Verified (Stripe Test)'
              : isFlight
                  ? 'Payment Verified (Historical)'
                  : 'Payment Verified · Booking Confirmed',
          AppStatusTone.success,
          Icons.check_circle_rounded
        ),
      'continue_payment' => (
          'Stripe Checkout Open',
          AppStatusTone.warning,
          Icons.open_in_new_rounded
        ),
      'check_status' => (
          'Payment Status Verifying',
          AppStatusTone.warning,
          Icons.hourglass_top_rounded
        ),
      'restart_payment' => (
          'Session Expired · Restart Required',
          AppStatusTone.neutral,
          Icons.replay_rounded
        ),
      _ => isHotelMissingSnapshot
          ? (
              'Validation Required',
              AppStatusTone.warning,
              Icons.warning_amber_rounded,
            )
          : (isFlight && !isPaid)
              ? (
                  'Ticketing Unavailable',
                  AppStatusTone.neutral,
                  Icons.info_outline_rounded,
                )
              : (
                  'Ready for Checkout',
                  AppStatusTone.neutral,
                  Icons.shopping_bag_outlined,
                ),
    };

    final buttonLabel = busy
        ? 'Preparing Checkout…'
        : switch (currentAction) {
            'continue_payment' => 'Continue Payment on Stripe',
            'check_status' => 'Check Payment Status',
            'restart_payment' => 'Restart Payment',
            'view_booking' =>
                isHotel ? 'View Order Details' : 'View Confirmed Booking',
            _ => (isFlight && !isPaid)
                ? 'Flight ticketing unavailable'
                : 'Open Stripe test Checkout',
          };

    final buttonIcon = busy
        ? null
        : switch (currentAction) {
            'continue_payment' => Icons.open_in_new_rounded,
            'check_status' => Icons.refresh_rounded,
            'restart_payment' => Icons.replay_rounded,
            'view_booking' => Icons.check_circle_outline_rounded,
            _ => (isFlight && !isPaid)
                ? Icons.info_outline_rounded
                : Icons.open_in_new_rounded,
          };

    return Scaffold(
      appBar: AppBar(title: const Text('TravelMate Checkout')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
        children: [
          const TravelSectionHeader(
            title: 'Stripe test Checkout',
            subtitle: 'Card details are entered only on Stripe-hosted Checkout.',
          ),
          const SizedBox(height: 12),
          _buildDisclaimer(),
          const SizedBox(height: 14),
          InkCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        isPackage
                            ? 'Tourism Package'
                            : (widget.quoteType == 'hotel'
                                ? 'Hotel Booking'
                                : (widget.quoteType == 'flight'
                                    ? 'Flight Planning'
                                    : 'Order Checkout')),
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: InkWashColors.blueGrey,
                        ),
                      ),
                    ),
                    StatusChip(
                      text: statusLabel,
                      tone: statusTone,
                      icon: statusIcon,
                    ),
                  ],
                ),
                if (productTitle.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text(
                    productTitle,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
                if ((departure != null && departure.isNotEmpty) ||
                    participantsDesc != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    [
                      if (departure != null && departure.isNotEmpty)
                        'Date: $departure',
                      if (participantsDesc != null) participantsDesc,
                    ].join(' · '),
                    style: const TextStyle(
                      fontSize: 13,
                      color: InkWashColors.mutedInk,
                    ),
                  ),
                ],
                if (isHotel && (currentAction == 'view_booking' || activeOrder?['status'] == 'paid' || activeOrder?['paymentStatus'] == 'paid')) ...[
                  const SizedBox(height: 10),
                  InkCard(
                    color: InkWashColors.cream,
                    padding: const EdgeInsets.all(AppSpacing.sm),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Wrap(
                          spacing: 8,
                          runSpacing: 4,
                          children: [
                            StatusChip(
                              text: 'Paid — Stripe Test Mode',
                              tone: AppStatusTone.success,
                              icon: Icons.check_circle_rounded,
                            ),
                            StatusChip(
                              text: 'Test Mode',
                              tone: AppStatusTone.neutral,
                              icon: Icons.info_outline_rounded,
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Hotel Reservation Status: No supplier reservation created',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                fontWeight: FontWeight.w700,
                                color: AppColors.textPrimary,
                              ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'This is a test payment in Stripe Test Mode. No real charges were incurred, and no room has been reserved with the hotel.',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                color: AppColors.textSecondary,
                              ),
                        ),
                      ],
                    ),
                  ),
                ],
                if (isHotelMissingSnapshot) ...[
                  const SizedBox(height: 10),
                  InkCard(
                    color: const Color(0xFFFEF3C7),
                    child: const Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(Icons.warning_amber_rounded,
                            size: 18, color: Color(0xFFD97706)),
                        SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'An accepted hotel prebook snapshot is required before Checkout. Return to Hotel search and validate the quote to proceed.',
                            style: TextStyle(
                              fontSize: 12,
                              color: Color(0xFF92400E),
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                if (isFlight && !isPaid) ...[
                  const SizedBox(height: 10),
                  InkCard(
                    color: InkWashColors.cream,
                    child: const Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(Icons.info_outline_rounded,
                            size: 18, color: InkWashColors.blueGrey),
                        SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Flight ticketing is unavailable.',
                                style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w800,
                                  color: InkWashColors.ink,
                                ),
                              ),
                              SizedBox(height: 3),
                              Text(
                                'TravelMate supports flight planning estimates, but airline ticketing and seat reservations cannot be purchased. You can save this flight to your travel plan.',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: InkWashColors.mutedInk,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 10),
                const Divider(height: 1),
                const SizedBox(height: 10),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Payable total:',
                      style: TextStyle(
                        fontSize: 14,
                        color: InkWashColors.mutedInk,
                      ),
                    ),
                    Flexible(
                      child: Text(
                        displayAmount != null
                            ? 'Authoritative quote: MYR ${displayAmount.toStringAsFixed(2)}'
                            : 'MYR 0.00',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: InkWashColors.ink,
                        ),
                        textAlign: TextAlign.end,
                      ),
                    ),
                  ],
                ),
                if (widget.initialBookingReference.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    'Booking reference: ${widget.initialBookingReference}',
                    style: const TextStyle(
                      fontSize: 12,
                      color: InkWashColors.mutedInk,
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: (busy || (isFlight && !isPaid)) ? null : launchCheckout,
            icon: busy
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : Icon(buttonIcon),
            label: Text(buttonLabel),
          ),
          if (isFlight && !isPaid) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () => Navigator.pop(context),
              icon: const Icon(Icons.arrow_back_rounded),
              label: const Text('Back to Trip Planning'),
            ),
          ],
          if (isHotel && (currentAction == 'view_booking' || activeOrder?['status'] == 'paid')) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: busy ? null : _navigateToBooking,
              icon: const Icon(Icons.receipt_long_rounded),
              label: const Text('View Paid Order'),
            ),
          ],
          if (currentAction == 'continue_payment') ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: busy ? null : reconcileActiveOrder,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Check Payment Status'),
            ),
          ],
          if (currentAction == 'check_status' &&
              checkoutUrl != null &&
              checkoutUrl!.isNotEmpty) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: busy ? null : _reopenStripe,
              icon: const Icon(Icons.open_in_new_rounded),
              label: const Text('Re-open Stripe Checkout'),
            ),
          ],
          const SizedBox(height: 24),
          const TravelSectionHeader(
            title: 'Order history',
            subtitle: 'Pending orders are reconciled when you return to the app.',
          ),
          const SizedBox(height: 10),
          if (orders.isEmpty)
            const TravelEmptyState(
              icon: Icons.receipt_long_outlined,
              title: 'No Checkout orders yet',
              message: 'Your Stripe test orders will appear here.',
            ),
          ...orders.take(3).map((raw) {
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
                                const TextStyle(fontWeight: FontWeight.w800),
                          ),
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
          if (orders.isNotEmpty) ...[
            const SizedBox(height: 6),
            Center(
              child: TextButton.icon(
                onPressed: () {
                  Navigator.push(
                    context,
                    MaterialPageRoute(
                        builder: (_) => PaymentHistoryScreen(api: api)),
                  );
                },
                icon: const Icon(Icons.history_rounded, size: 16),
                label: const Text('View full payment history'),
              ),
            ),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!consumerPaymentsAvailable) {
      return Scaffold(
        appBar: AppBar(title: const Text('Payments unavailable')),
        body: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            const TravelEmptyState(icon: Icons.bookmark_outline,
              title: 'Keep planning your trip',
              message: 'TravelMate can save travel options, but cannot take payment or confirm supplier reservations.'),
            TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute(
              builder: (_) => TravelRecordsScreen(api: api))),
              child: const Text('View Travel Records')),
          ]),
        ),
      );
    }
    if (hostedCheckout) return _buildHostedCheckout();
    return Scaffold(
      appBar: AppBar(title: const Text('Secure card payment')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
        children: [
          const TravelSectionHeader(
            title: 'Checkout',
            subtitle:
                'Review the amount and complete your test payment.',
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
                    'This test checkout reproduces the complete payment process but does not charge real money. Full card numbers and security codes are never saved.',
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
                            ? 'Test payment · no real charge'
                            : paymentStatusLabel(result?['paymentStatus']),
                        style: const TextStyle(
                            fontWeight: FontWeight.w900, fontSize: 18))
                  ]),
                  const SizedBox(height: 10),
                  if (!isSuccessfulPayment(result?['paymentStatus']))
                    const Text('We’re still checking this payment. Use Check status before trying again.'),
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
            const kind = 'Test Mode';
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
