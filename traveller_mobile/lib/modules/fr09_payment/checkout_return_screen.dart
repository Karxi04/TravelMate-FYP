import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import '../fr08_hotel_booking/hotel_order_details_screen.dart';
import 'payment_history_screen.dart';
import 'payment_status.dart';

class CheckoutReturnLink {
  static final _orderId = RegExp(r'^[A-Za-z0-9_-]{8,180}$');

  final String orderId;
  final String stateHint;

  const CheckoutReturnLink(this.orderId, this.stateHint);

  static CheckoutReturnLink? parse(String? raw) {
    if (raw == null || raw.isEmpty) return null;
    final Uri uri;
    try {
      uri = Uri.parse(raw);
    } on FormatException {
      return null;
    }
    if (uri.scheme != 'travelmate' ||
        uri.host != 'checkout' ||
        uri.path != '/return' ||
        uri.hasFragment ||
        uri.userInfo.isNotEmpty ||
        uri.queryParametersAll.keys.any((key) => key != 'order_id' && key != 'state')) {
      return null;
    }
    final orderValues = uri.queryParametersAll['order_id'] ?? const [];
    final stateValues = uri.queryParametersAll['state'] ?? const [];
    if (orderValues.length != 1 || stateValues.length != 1) return null;
    final orderId = orderValues.single;
    final state = stateValues.single;
    if (!_orderId.hasMatch(orderId) ||
        !{'paid', 'processing', 'not_completed'}.contains(state)) {
      return null;
    }
    return CheckoutReturnLink(orderId, state);
  }
}

class CheckoutReturnChannel {
  static const _channel = MethodChannel('travelmate/checkout_return');

  Future<CheckoutReturnLink?> initialLink() async {
    final raw = await _channel.invokeMethod<String>('getInitialLink');
    return CheckoutReturnLink.parse(raw);
  }

  void listen(ValueChanged<CheckoutReturnLink> onLink) {
    _channel.setMethodCallHandler((call) async {
      if (call.method != 'onLink') return;
      final link = CheckoutReturnLink.parse(call.arguments as String?);
      if (link != null) onLink(link);
    });
  }

  void dispose() => _channel.setMethodCallHandler(null);
}

class CheckoutReturnScreen extends StatefulWidget {
  final CheckoutReturnLink link;
  final ApiService? api;

  const CheckoutReturnScreen({super.key, required this.link, this.api});

  @override
  State<CheckoutReturnScreen> createState() => _CheckoutReturnScreenState();
}

class _CheckoutReturnScreenState extends State<CheckoutReturnScreen> {
  late final ApiService api;
  Map<String, dynamic>? order;
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(load);
  }

  bool _needsReconciliation(Map<String, dynamic> value) => {
        'checkout_open',
        'checkout_pending',
        'payment_pending',
      }.contains((value['status'] ?? '').toString().toLowerCase());

  Future<void> load() async {
    if (mounted) setState(() { loading = true; error = null; });
    try {
      final owned = await api.get(
        '/api/fr9/orders/${Uri.encodeComponent(widget.link.orderId)}',
      );
      var current = Map<String, dynamic>.from(owned['order'] as Map);
      if ((await loadHostedCheckoutCapabilities(api)).contains(current['quoteType']) && _needsReconciliation(current)) {
        final recovered = await api.get(
          '/api/fr9/orders/${Uri.encodeComponent(widget.link.orderId)}/reconcile',
        );
        if (recovered['order'] is Map) {
          current = Map<String, dynamic>.from(recovered['order'] as Map);
        }
      }
      final refreshedOrders = await api.get('/api/fr9/orders');
      await api.get('/api/fr9/payments');
      for (final raw in refreshedOrders['items'] as List? ?? const []) {
        if (raw is Map && raw['id'] == widget.link.orderId) {
          current = Map<String, dynamic>.from(raw);
          break;
        }
      }
      if (mounted) setState(() { order = current; loading = false; });
    } catch (failure) {
      if (!mounted) return;
      setState(() {
        loading = false;
        error = failure is ApiException && failure.statusCode == 404
            ? 'This Checkout order is not available for the signed-in Traveller.'
            : userFacingApiError(failure);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = (order?['status'] ?? '').toString().toLowerCase();
    final paymentStatus = (order?['paymentStatus'] ?? '').toString().toLowerCase();
    final quoteType = (order?['quoteType'] ?? '').toString().toLowerCase();
    final isHotel = quoteType == 'hotel';
    final paid = status == 'paid' || paymentStatus == 'paid';
    final processing = _needsReconciliation(order ?? const {}) &&
        widget.link.stateHint != 'not_completed';
    final tripId = (order?['fulfilledTripId'] ?? '').toString();
    final orderId = (order?['id'] ?? widget.link.orderId).toString();
    final title = paid
        ? 'Payment Completed'
        : processing
            ? 'Payment Processing'
            : 'Payment Not Completed';
    final message = paid
        ? (isHotel
            ? 'Your payment is verified. $academicPaymentDisclosure'
            : 'Your payment is verified. $academicPaymentDisclosure Your Orders and Payment History are refreshed.')
        : processing
            ? 'Your payment is being verified. Check My Orders again shortly.'
            : 'No successful payment has been confirmed for this order.';

    return Scaffold(
      appBar: AppBar(title: const Text('Checkout return')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : error != null
              ? AppErrorState(message: error!, retryLabel: 'Try again', onRetry: load)
              : ListView(
                  padding: const EdgeInsets.all(20),
                  children: [
                    Icon(
                      paid
                          ? Icons.check_circle_rounded
                          : processing
                              ? Icons.hourglass_top_rounded
                              : Icons.info_outline_rounded,
                      size: 58,
                      color: paid
                          ? AppColors.success
                          : processing
                              ? AppColors.warning
                              : InkWashColors.mutedInk,
                    ),
                    const SizedBox(height: 16),
                    Text(title, textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900)),
                    const SizedBox(height: 8),
                    Text(message, textAlign: TextAlign.center),
                    if (paid && isHotel) ...[
                      const SizedBox(height: 16),
                      InkCard(
                        color: InkWashColors.cream,
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
                            const SizedBox(height: 8),
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
                    const SizedBox(height: 24),
                    if (processing)
                      FilledButton.icon(
                        onPressed: load,
                        icon: const Icon(Icons.refresh_rounded),
                        label: const Text('Check payment status'),
                      ),
                    if (paid && isHotel) ...[
                      FilledButton.icon(
                        key: const ValueKey('view-hotel-order-button'),
                        onPressed: () => Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => HotelOrderDetailsScreen(
                              orderId: orderId,
                              initialOrder: order,
                              api: api,
                            ),
                          ),
                        ),
                        icon: const Icon(Icons.receipt_long_rounded),
                        label: const Text('View Order Details'),
                      ),
                      const SizedBox(height: 8),
                    ],
                    if (paid && tripId.isNotEmpty) ...[
                      FilledButton.icon(
                        onPressed: () => Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => PackageTripDetailsScreen(tripId: tripId, api: api),
                          ),
                        ),
                        icon: const Icon(Icons.luggage_rounded),
                        label: const Text('Open Package Trip'),
                      ),
                      const SizedBox(height: 8),
                    ],
                    OutlinedButton.icon(
                      onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(builder: (_) => PaymentHistoryScreen(api: api)),
                      ),
                      icon: const Icon(Icons.receipt_long_rounded),
                      label: const Text('View Payment History'),
                    ),
                  ],
                ),
    );
  }
}
