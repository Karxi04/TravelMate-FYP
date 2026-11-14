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
  final String? initialProductName;
  final Map<String, dynamic>? pricingBreakdown;
  final String quoteType;
  final String quoteId;
  final String offerId;
  final String searchId;
  final String optionId;
  final String packageAttemptId;
  final String acceptedPrebookSnapshotId;
  final Map<String, dynamic>? acceptedPrebook;
  final String? hotelBookingAttemptId;
  final String? itineraryId;
  final ApiService? api;

  const PaymentScreen({
    super.key,
    this.initialBookingReference = '',
    this.initialAmount,
    this.initialProductName,
    this.pricingBreakdown,
    this.quoteType = '',
    this.quoteId = '',
    this.offerId = '',
    this.searchId = '',
    this.optionId = '',
    this.packageAttemptId = '',
    this.acceptedPrebookSnapshotId = '',
    this.acceptedPrebook,
    this.hotelBookingAttemptId,
    this.itineraryId,
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
  bool capabilityLoading = true;
  Set<String> checkoutTypes = {};
  String get checkoutType => widget.packageAttemptId.isNotEmpty ? 'package' : widget.quoteType;
  bool get consumerPaymentsAvailable => hostedCheckout && checkoutTypes.contains(checkoutType);
  final paymentAttempt = TransactionAttemptLifecycle('payment');
  final checkoutAttempts = CheckoutAttemptStore();

  String currentAttemptId = '';
  Map<String, dynamic>? activeOrder;
  double? _refreshedPackageAmount;
  Map<String, dynamic>? _refreshedPackagePricing;
  String checkoutAction = 'open_checkout';
  String? checkoutUrl;
  final TransactionAttemptLifecycle _packageRestartIntent =
      TransactionAttemptLifecycle('package_checkout_restart');

  bool get hostedCheckout =>
      (widget.quoteType.isNotEmpty || widget.packageAttemptId.isNotEmpty) && !api.isStandalone;

  double? get authoritativeAmount {
    if (activeOrder?['amount'] != null) {
      final amt = num.tryParse(activeOrder!['amount'].toString())?.toDouble();
      if (amt != null && amt > 0) return amt;
    }
    if (_refreshedPackageAmount != null) return _refreshedPackageAmount;
    if (widget.initialAmount != null && widget.initialAmount! > 0) {
      return widget.initialAmount;
    }
    if (widget.acceptedPrebook != null) {
      final raw = widget.acceptedPrebook!['amount'] ?? widget.acceptedPrebook!['price'];
      if (raw != null) {
        final amt = (raw is num) ? raw.toDouble() : double.tryParse(raw.toString());
        if (amt != null && amt > 0) return amt;
      }
    }
    return null;
  }

  bool get isHotelQuoteValid {
    if (widget.quoteType != 'hotel') return true;
    if (widget.acceptedPrebookSnapshotId.isEmpty) return false;
    if (widget.acceptedPrebook != null && widget.acceptedPrebook!['expiresAt'] != null) {
      final exp = DateTime.tryParse(widget.acceptedPrebook!['expiresAt'].toString());
      if (exp != null && DateTime.now().toUtc().isAfter(exp.toUtc())) {
        return false;
      }
    }
    return true;
  }

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
      final types = await loadHostedCheckoutCapabilities(api);
      if (!mounted) return;
      setState(() { checkoutTypes = types; capabilityLoading = false; });
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
    if (match == null && !isPackage && widget.quoteType == 'hotel') {
      if (widget.hotelBookingAttemptId != null && widget.hotelBookingAttemptId!.isNotEmpty) {
        match = list.cast<Map<String, dynamic>?>().firstWhere(
          (item) => item?['quoteType'] == 'hotel' &&
              (item?['hotelBookingAttemptId'] == widget.hotelBookingAttemptId ||
               item?['orderAttemptId'] == widget.hotelBookingAttemptId),
          orElse: () => null,
        );
      }
      if (match == null && (widget.acceptedPrebookSnapshotId.isNotEmpty || widget.quoteId.isNotEmpty)) {
        match = list.cast<Map<String, dynamic>?>().firstWhere(
          (item) {
            if (item?['quoteType'] != 'hotel') return false;
            final itemSnapshot = (item?['acceptedPrebookSnapshotId'] ?? '').toString();
            final itemOffer = (item?['offerId'] ?? '').toString();
            final itemQuote = (item?['quoteId'] ?? '').toString();

            // If both have snapshot IDs, they MUST match
            if (itemSnapshot.isNotEmpty && widget.acceptedPrebookSnapshotId.isNotEmpty) {
              return itemSnapshot == widget.acceptedPrebookSnapshotId;
            }
            // If both have offer IDs, they must match
            if (itemOffer.isNotEmpty && widget.offerId.isNotEmpty && itemOffer != widget.offerId) {
              return false;
            }
            // If item has a snapshot ID but widget doesn't, cannot match
            if (itemSnapshot.isNotEmpty && widget.acceptedPrebookSnapshotId.isEmpty) {
              return false;
            }
            // If item has NO snapshot ID, match if quoteId matches
            if (itemSnapshot.isEmpty && widget.quoteId.isNotEmpty) {
              return itemQuote == widget.quoteId;
            }
            return false;
          },
          orElse: () => null,
        );
      }
    }
    if (match == null && !isPackage && widget.quoteType == 'flight') {
      match = list.cast<Map<String, dynamic>?>().firstWhere(
        (item) => item?['quoteType'] == 'flight' &&
            widget.searchId.isNotEmpty && item?['quoteId'] == widget.searchId &&
            widget.optionId.isNotEmpty && item?['optionId'] == widget.optionId,
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
    showError(context, 'Checkout is unavailable for this selection. Your saved details and history are unchanged.');
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
            ? (scope.isNotEmpty && (item['packageAttemptId'] == scope || item['orderAttemptId'] == scope))
            : (item['quoteType'] == widget.quoteType &&
                (widget.quoteType == 'hotel'
                    ? (widget.acceptedPrebookSnapshotId.isNotEmpty &&
                       item['acceptedPrebookSnapshotId'] == widget.acceptedPrebookSnapshotId &&
                       (widget.offerId.isEmpty || item['offerId'] == widget.offerId))
                    : (widget.searchId.isNotEmpty && item['quoteId'] == widget.searchId &&
                       widget.optionId.isNotEmpty && item['optionId'] == widget.optionId)));
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
            if (widget.itineraryId != null) 'itineraryId': widget.itineraryId,
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
              : 'Payment verified. View your order for fulfillment status.',
          'continue_payment' => 'Checkout is open. Tap Continue to Payment to complete.',
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
        'promoCode': (snapshot['requestedPromoCode'] ?? '').toString(),
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

      if (!mounted) return;
      final updatedAmount = num.tryParse('${newAttempt['amount']}')?.toDouble();
      final updatedPricing = newAttempt['pricingBreakdown'] is Map ? Map<String,dynamic>.from(newAttempt['pricingBreakdown']) : null;
      final accepted = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
        title: const Text('Review refreshed package quote'),
        content: Text('MYR ${updatedAmount?.toStringAsFixed(2) ?? 'unavailable'}\nBefore discount: ${updatedPricing?['originalSubtotal'] ?? '-'}\nDiscount: ${updatedPricing?['promotionDiscount'] ?? 0}\n${updatedPricing?['promotion']?['campaignTitle'] ?? ''}\n${updatedPricing?['promotion']?['termsConditions'] ?? ''}'),
        actions: [TextButton(onPressed:()=>Navigator.pop(ctx,false),child:const Text('Cancel')), FilledButton(onPressed:updatedAmount==null?null:()=>Navigator.pop(ctx,true),child:const Text('Accept quote'))]));
      if (accepted != true) return;
      _refreshedPackageAmount = updatedAmount;
      _refreshedPackagePricing = updatedPricing;
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
    showError(context, 'Use hosted Checkout for an eligible Hotel or Package.');
  }

  Future<void> updatePayment(String paymentId, String action) async {
    showError(context, 'Use the order status and hosted Checkout recovery actions.');
  }

  Widget _buildHostedCheckout() {
    final isPackage = widget.packageAttemptId.isNotEmpty ||
        widget.quoteType == 'package' ||
        activeOrder?['quoteType'] == 'package';
    final isHotel = widget.quoteType == 'hotel' || activeOrder?['quoteType'] == 'hotel';
    final snapshot = activeOrder?['packageSnapshot'] is Map
        ? Map<String, dynamic>.from(activeOrder!['packageSnapshot'] as Map)
        : (activeOrder?['quoteSnapshot'] is Map
            ? Map<String, dynamic>.from(activeOrder!['quoteSnapshot'] as Map)
            : null);
    final productTitle = [
      if (isHotel) ...[
        snapshot?['name'],
        snapshot?['hotelName'],
        activeOrder?['hotelName'],
        widget.acceptedPrebook?['name'],
        widget.acceptedPrebook?['hotelName'],
      ],
      if (!isHotel) ...[snapshot?['title'], snapshot?['name'], activeOrder?['packageTitle']],
      activeOrder?['productTitle'],
      widget.initialProductName,
      isHotel ? 'Hotel stay' : 'Tourism package',
    ].whereType<String>().map((name) => name.trim()).firstWhere((name) =>
        name.isNotEmpty && !RegExp(r'^TravelMate (hotel|package) test order',
            caseSensitive: false).hasMatch(name));

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

    final displayAmount = authoritativeAmount;
    final pricing = snapshot?['pricingBreakdown'] is Map
        ? Map<String, dynamic>.from(snapshot!['pricingBreakdown'])
        : _refreshedPackagePricing ?? widget.pricingBreakdown;

    final currentAction = checkoutAction;
    final bool isFlight = widget.quoteType == 'flight';
    final bool isPaid = activeOrder?['status'] == 'paid' ||
        activeOrder?['paymentStatus'] == 'paid' ||
        result?['paymentStatus'] == 'paid' ||
        currentAction == 'view_booking';
    final (statusLabel, statusTone, statusIcon) = switch (currentAction) {
      'view_booking' => (
          'Payment Completed',
          AppStatusTone.success,
          Icons.check_circle_rounded
        ),
      'continue_payment' => (
          'Checkout Open',
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
      _ => !isHotelQuoteValid
          ? (
              'Price Unavailable',
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
            'continue_payment' => 'Continue to Payment',
            'check_status' => 'Check Payment Status',
            'restart_payment' => 'Restart Payment',
            'view_booking' => 'View Order Details',
            _ => (isFlight && !isPaid)
                ? 'Flight ticketing unavailable'
                : 'Continue to Payment',
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
            title: 'Review Payment',
            subtitle: 'Card details are entered only on Stripe-hosted Checkout.',
          ),
          const SizedBox(height: 12),
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
                if (isHotel && !isHotelQuoteValid) ...[
                  const SizedBox(height: 10),
                  InkCard(
                    color: const Color(0xFFFEF3C7),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.warning_amber_rounded,
                            size: 18, color: Color(0xFFD97706)),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            widget.acceptedPrebookSnapshotId.isEmpty
                                ? 'Price unavailable — refresh hotel offer. An accepted hotel prebook snapshot is required before Checkout.'
                                : 'This accepted hotel price has expired. Search and validate the offer again.',
                            style: const TextStyle(
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
                        !isHotelQuoteValid
                            ? 'Price unavailable — refresh hotel offer'
                            : displayAmount != null
                                ? 'Authoritative quote: MYR ${displayAmount.toStringAsFixed(2)}'
                                : 'Loading price...',
                        style: TextStyle(
                          fontSize: !isHotelQuoteValid ? 13 : 16,
                          fontWeight: FontWeight.w800,
                          color: !isHotelQuoteValid
                              ? const Color(0xFFD97706)
                              : InkWashColors.ink,
                        ),
                        textAlign: TextAlign.end,
                      ),
                    ),
                  ],
                ),
                if (isPackage && pricing != null) ...[
                  const SizedBox(height: 8),
                  if (pricing['promotion'] is Map && (pricing['promotion'] as Map).isNotEmpty) ...[
                    Text('${pricing['promotion']['campaignTitle'] ?? 'Promotion'} · ${pricing['promotion']['startDate'] ?? ''} to ${pricing['promotion']['endDate'] ?? ''}'),
                    if ('${pricing['promotion']['termsConditions'] ?? ''}'.isNotEmpty) Text('${pricing['promotion']['termsConditions']}'),
                  ],
                  for (final entry in const {
                    'originalSubtotal': 'Original package subtotal',
                    'promotionDiscount': 'Promotion discount',
                    'finalPayable': 'Final payable'
                  }.entries)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Text(
                          '${entry.value}: ${entry.key == 'promotionDiscount' ? '-' : ''}${pricing['currency']} ${(num.tryParse('${pricing[entry.key]}') ?? 0).toStringAsFixed(2)}'),
                    ),
                ],
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
            onPressed: (busy || (isFlight && !isPaid) || !isHotelQuoteValid || (displayAmount == null && !isPaid))
                ? null
                : launchCheckout,
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
            label: Text(!isHotelQuoteValid
                ? 'Price unavailable — refresh hotel offer'
                : (displayAmount == null && !isPaid)
                    ? 'Loading price...'
                    : buttonLabel),
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
              label: const Text('View Order Details'),
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
              label: const Text('Complete Checkout'),
            ),
          ],
          const SizedBox(height: 24),
          const TravelSectionHeader(
            title: 'Payment History',
            subtitle: 'Pending orders are reconciled when you return to the app.',
          ),
          const SizedBox(height: 10),
          if (orders.isEmpty)
            const TravelEmptyState(
              icon: Icons.receipt_long_outlined,
              title: 'No Checkout orders yet',
              message: 'Your orders will appear here.',
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
                label: const Text('View Payment History'),
              ),
            ),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (capabilityLoading) {
      return Scaffold(appBar: AppBar(title: const Text('Review Payment')),
        body: const Center(child: CircularProgressIndicator()));
    }
    if (!consumerPaymentsAvailable) {
      return Scaffold(
        appBar: AppBar(title: const Text('Payments unavailable')),
        body: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            const TravelEmptyState(icon: Icons.bookmark_outline,
              title: 'Keep planning your trip',
              message: 'Checkout is unavailable for this selection or is not configured. Your saved details and payment history remain available.'),
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
