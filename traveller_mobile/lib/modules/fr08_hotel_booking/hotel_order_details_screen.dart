import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class HotelOrderDetailsScreen extends StatefulWidget {
  final String orderId;
  final ApiService? api;
  final Map<String, dynamic>? initialOrder;

  const HotelOrderDetailsScreen({
    super.key,
    required this.orderId,
    this.api,
    this.initialOrder,
  });

  @override
  State<HotelOrderDetailsScreen> createState() => _HotelOrderDetailsScreenState();
}

class _HotelOrderDetailsScreenState extends State<HotelOrderDetailsScreen> {
  late final ApiService api;
  Map<String, dynamic>? order;
  bool loading = true;
  bool reconciling = false;
  String? error;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    if (widget.initialOrder != null) {
      order = Map<String, dynamic>.from(widget.initialOrder!);
      loading = false;
    }
    Future.microtask(load);
  }

  bool _needsReconciliation(Map<String, dynamic> data) {
    final status = (data['status'] ?? '').toString().toLowerCase();
    final paymentStatus = (data['paymentStatus'] ?? '').toString().toLowerCase();
    return {'checkout_open', 'checkout_pending', 'payment_pending'}.contains(status) ||
        {'pending', 'unpaid'}.contains(paymentStatus);
  }

  Future<void> load() async {
    if (order == null && mounted) {
      setState(() {
        loading = true;
        error = null;
      });
    }
    try {
      final response = await api.get('/api/fr9/orders/${Uri.encodeComponent(widget.orderId)}');
      var current = Map<String, dynamic>.from(response['order'] as Map);

      if (_needsReconciliation(current) && current['checkoutSessionId'] != null) {
        try {
          final recovered = await api.get('/api/fr9/orders/${Uri.encodeComponent(widget.orderId)}/reconcile');
          if (recovered is Map && recovered['order'] is Map) {
            current = Map<String, dynamic>.from(recovered['order'] as Map);
          }
        } catch (_) {}
      }

      if (mounted) {
        setState(() {
          order = current;
          loading = false;
          error = null;
        });
      }
    } catch (exc) {
      if (!mounted) return;
      if (order == null) {
        setState(() {
          loading = false;
          error = exc is ApiException && exc.statusCode == 404
              ? 'This Hotel order is not available for the signed-in Traveller.'
              : userFacingApiError(exc);
        });
      } else {
        setState(() {
          loading = false;
        });
      }
    }
  }

  Future<void> reconcile() async {
    if (reconciling) return;
    setState(() => reconciling = true);
    try {
      final response = await api.get('/api/fr9/orders/${Uri.encodeComponent(widget.orderId)}/reconcile');
      if (response is Map && response['order'] is Map && mounted) {
        setState(() {
          order = Map<String, dynamic>.from(response['order'] as Map);
        });
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Order status updated.'),
          duration: Duration(seconds: 2),
        ));
      }
    } catch (exc) {
      if (mounted) showError(context, exc);
    } finally {
      if (mounted) setState(() => reconciling = false);
    }
  }

  String _formatDate(dynamic raw) {
    if (raw == null || raw.toString().trim().isEmpty) return 'Date unavailable';
    final str = raw.toString().trim();
    final dt = DateTime.tryParse(str);
    if (dt == null) return str;
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return '${dt.day} ${months[dt.month - 1]} ${dt.year}';
  }

  int? _calculateNights(dynamic checkinRaw, dynamic checkoutRaw) {
    if (checkinRaw == null || checkoutRaw == null) return null;
    final inDate = DateTime.tryParse(checkinRaw.toString());
    final outDate = DateTime.tryParse(checkoutRaw.toString());
    if (inDate != null && outDate != null && outDate.isAfter(inDate)) {
      return outDate.difference(inDate).inDays;
    }
    return null;
  }

  String _formatAmount(dynamic amount, dynamic currency) {
    if (amount == null) return '—';
    final curr = (currency ?? 'MYR').toString().toUpperCase();
    if (amount is num) {
      return '$curr ${amount.toStringAsFixed(2)}';
    }
    final parsed = double.tryParse(amount.toString());
    if (parsed != null) {
      return '$curr ${parsed.toStringAsFixed(2)}';
    }
    return '$curr $amount';
  }

  String _formatOccupancy(dynamic rawOccupancies) {
    if (rawOccupancies is List && rawOccupancies.isNotEmpty) {
      final roomDescriptions = <String>[];
      for (var i = 0; i < rawOccupancies.length; i++) {
        final occ = rawOccupancies[i];
        if (occ is Map) {
          final adults = occ['adults'] ?? 1;
          final children = occ['children'];
          final roomNum = i + 1;
          var desc = 'Room $roomNum: $adults Adult${adults != 1 ? 's' : ''}';
          if (children is List && children.isNotEmpty) {
            final agesStr = children.map((c) => 'Age $c').join(', ');
            desc += ', ${children.length} Child${children.length != 1 ? 'ren' : ''} ($agesStr)';
          }
          roomDescriptions.add(desc);
        }
      }
      if (roomDescriptions.isNotEmpty) {
        return roomDescriptions.join('\n');
      }
    }
    return 'Occupancy details unavailable';
  }

  (String label, AppStatusTone tone, IconData icon) _resolvePaymentStatus(Map<String, dynamic> data) {
    final status = (data['status'] ?? '').toString().toLowerCase();
    final paymentStatus = (data['paymentStatus'] ?? '').toString().toLowerCase();

    if (status == 'paid' || paymentStatus == 'paid' || paymentStatus == 'succeeded') {
      return ('Paid — Stripe Test Mode', AppStatusTone.success, Icons.check_circle_rounded);
    }
    if (status == 'payment_failed' || paymentStatus == 'failed') {
      return ('Payment Failed', AppStatusTone.error, Icons.error_outline_rounded);
    }
    if (status == 'expired') {
      return ('Checkout Expired', AppStatusTone.neutral, Icons.timer_off_outlined);
    }
    return ('Payment Pending / Unpaid', AppStatusTone.warning, Icons.schedule_rounded);
  }

  (String label, AppStatusTone tone, IconData icon, String subtitle) _resolveFulfillmentStatus(Map<String, dynamic> data) {
    final supplierStatus = (data['supplierBookingStatus'] ?? '').toString().toLowerCase();
    final bookingRef = data['bookingReference']?.toString();
    final fulfillmentStatus = data['fulfillmentStatus']?.toString().toLowerCase();
    final isPaid = (data['status'] ?? '').toString().toLowerCase() == 'paid' ||
        (data['paymentStatus'] ?? '').toString().toLowerCase() == 'paid';

    if (supplierStatus == 'confirmed' && bookingRef != null && bookingRef.isNotEmpty) {
      return ('Supplier Confirmed', AppStatusTone.success, Icons.hotel_rounded, 'Reservation confirmed with supplier');
    }
    if (fulfillmentStatus == 'demo_only') {
      return ('Demo Only — No Room Reserved', AppStatusTone.neutral, Icons.science_outlined, 'No supplier reservation created');
    }
    if (fulfillmentStatus == 'not_started' || (!isPaid && (fulfillmentStatus == null || fulfillmentStatus.isEmpty))) {
      return ('Not Started', AppStatusTone.neutral, Icons.pause_circle_outline, 'No supplier reservation created');
    }
    if (isPaid && (fulfillmentStatus == null || fulfillmentStatus.isEmpty)) {
      return ('Supplier reservation not verified', AppStatusTone.neutral, Icons.help_outline_rounded, 'No supplier reservation verified');
    }
    return ('Supplier reservation not verified', AppStatusTone.neutral, Icons.help_outline_rounded, 'No supplier reservation verified');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: const ValueKey('hotel-order-details-screen'),
      appBar: AppBar(
        title: const Text('Hotel Order Details'),
        actions: [
          IconButton(
            key: const ValueKey('hotel-order-refresh-button'),
            icon: reconciling
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh order',
            onPressed: (loading || reconciling) ? null : reconcile,
          ),
        ],
      ),
      body: loading
          ? const Center(
              child: AppLoadingState(
                key: ValueKey('hotel-order-loading'),
                message: 'Loading hotel order…',
              ),
            )
          : error != null
              ? ListView(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  children: [
                    AppErrorState(
                      key: const ValueKey('hotel-order-error'),
                      message: error!,
                      retryLabel: 'Try again',
                      onRetry: load,
                    ),
                  ],
                )
              : _buildContent(context),
    );
  }

  Widget _buildContent(BuildContext context) {
    final data = order ?? const {};
    final snapshot = data['quoteSnapshot'] is Map
        ? Map<String, dynamic>.from(data['quoteSnapshot'] as Map)
        : <String, dynamic>{};

    final hotelName = (snapshot['name'] ?? snapshot['hotelName'] ?? data['hotelName'] ?? 'Hotel Reservation').toString();
    final roomName = (snapshot['roomName'] ?? data['roomName'] ?? 'Room details not provided').toString();
    final checkin = snapshot['checkin'] ?? data['checkin'];
    final checkout = snapshot['checkout'] ?? data['checkout'];
    final nights = _calculateNights(checkin, checkout);
    final roomQuantity = snapshot['roomQuantity'] ?? data['roomQuantity'] ?? 1;
    final occupancies = snapshot['occupancies'] ?? data['occupancies'];

    final (paymentLabel, paymentTone, paymentIcon) = _resolvePaymentStatus(data);
    final (fulfillmentLabel, fulfillmentTone, fulfillmentIcon, fulfillmentSubtitle) = _resolveFulfillmentStatus(data);

    final amountStr = _formatAmount(data['amount'], data['currency']);
    final orderId = (data['id'] ?? widget.orderId).toString();
    final bookingRef = data['bookingReference']?.toString();
    final checkoutAction = (data['checkoutAction'] ?? '').toString();
    final checkoutUrl = data['checkoutUrl']?.toString();
    final isPaid = (data['status'] ?? '').toString().toLowerCase() == 'paid' ||
        (data['paymentStatus'] ?? '').toString().toLowerCase() == 'paid';
    final demoDisclosure = (data['demoDisclosure'] ??
        'This is a test payment for demonstration purposes. No real payment was charged, and no room has been reserved with the hotel.').toString();

    return RefreshIndicator(
      onRefresh: reconcile,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(18, 12, 18, 32),
        children: [
          // Header Hotel Info
          InkCard(
            key: const ValueKey('hotel-order-header-card'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const CircleAvatar(
                      backgroundColor: InkWashColors.paleBlue,
                      child: Icon(Icons.hotel_rounded, color: InkWashColors.blueGrey),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            hotelName,
                            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                  fontWeight: FontWeight.w800,
                                ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            roomName,
                            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                  color: AppColors.textSecondary,
                                ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                const Divider(height: 1),
                const SizedBox(height: AppSpacing.sm),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    _dateColumn('Check-in', _formatDate(checkin)),
                    if (nights != null)
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppColors.surfaceElevated,
                          borderRadius: BorderRadius.circular(AppRadii.pill),
                          border: Border.all(color: AppColors.divider),
                        ),
                        child: Text(
                          '$nights Night${nights != 1 ? 's' : ''}',
                          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                fontWeight: FontWeight.w700,
                                color: InkWashColors.blueGrey,
                              ),
                        ),
                      ),
                    _dateColumn('Check-out', _formatDate(checkout)),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // Status & Truthful State Section
          InkCard(
            key: const ValueKey('hotel-order-status-card'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Order & Reservation Status',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                ),
                const SizedBox(height: AppSpacing.sm),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Payment Status',
                            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                  color: AppColors.textSecondary,
                                ),
                          ),
                          const SizedBox(height: 4),
                          StatusChip(
                            key: const ValueKey('hotel-order-payment-status-chip'),
                            text: paymentLabel,
                            tone: paymentTone,
                            icon: paymentIcon,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                const Divider(height: 1),
                const SizedBox(height: AppSpacing.sm),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Hotel Reservation Status',
                            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                  color: AppColors.textSecondary,
                                ),
                          ),
                          const SizedBox(height: 4),
                          StatusChip(
                            key: const ValueKey('hotel-order-fulfillment-status-chip'),
                            text: fulfillmentLabel,
                            tone: fulfillmentTone,
                            icon: fulfillmentIcon,
                          ),
                          const SizedBox(height: 2),
                          Text(
                            fulfillmentSubtitle,
                            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                  color: AppColors.textSecondary,
                                  fontSize: 11,
                                ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // Demo Disclosure Card
          InkCard(
            key: const ValueKey('hotel-order-disclosure-card'),
            color: InkWashColors.cream,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.info_outline_rounded, size: 20, color: InkWashColors.blueGrey),
                const SizedBox(width: AppSpacing.xs),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'FYP Demonstration Notice',
                        style: Theme.of(context).textTheme.labelMedium?.copyWith(
                              fontWeight: FontWeight.w800,
                              color: AppColors.textPrimary,
                            ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        demoDisclosure,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: AppColors.textSecondary,
                              height: 1.35,
                            ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // Stay & Occupancy Details
          InkCard(
            key: const ValueKey('hotel-order-stay-details-card'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Stay & Guest Details',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                ),
                const SizedBox(height: AppSpacing.sm),
                _itemRow('Number of Rooms', '$roomQuantity Room${roomQuantity != 1 ? 's' : ''}'),
                const SizedBox(height: AppSpacing.xs),
                _itemRow('Room Type', roomName),
                const SizedBox(height: AppSpacing.xs),
                _itemRow('Guest Occupancy', _formatOccupancy(occupancies)),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // Payment & Reference Details
          InkCard(
            key: const ValueKey('hotel-order-payment-details-card'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Payment & Order Reference',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                ),
                const SizedBox(height: AppSpacing.sm),
                _itemRow('Accepted Amount', amountStr, isEmphasized: true),
                const SizedBox(height: AppSpacing.xs),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: _itemRow('Order Reference', orderId),
                    ),
                    IconButton(
                      icon: const Icon(Icons.copy_rounded, size: 18),
                      tooltip: 'Copy Reference',
                      onPressed: () {
                        Clipboard.setData(ClipboardData(text: orderId));
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                          content: Text('Order reference copied to clipboard'),
                          duration: Duration(seconds: 2),
                        ));
                      },
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.xs),
                _itemRow('Payment Provider', 'Stripe (Test Mode)'),
                const SizedBox(height: AppSpacing.xs),
                _itemRow(
                  'Supplier Confirmation',
                  (bookingRef != null && bookingRef.isNotEmpty)
                      ? bookingRef
                      : 'None (Demo mode — no supplier reservation)',
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.lg),

          // Action Buttons
          if (!isPaid && checkoutAction == 'continue_payment' && checkoutUrl != null && checkoutUrl.isNotEmpty) ...[
            FilledButton.icon(
              key: const ValueKey('hotel-order-continue-checkout-button'),
              icon: const Icon(Icons.open_in_new_rounded),
              label: const Text('Continue to Stripe Checkout'),
              onPressed: () async {
                final uri = Uri.tryParse(checkoutUrl);
                if (uri != null) {
                  await launchUrl(uri, mode: LaunchMode.externalApplication);
                }
              },
            ),
            const SizedBox(height: AppSpacing.sm),
          ],
          if (!isPaid) ...[
            OutlinedButton.icon(
              key: const ValueKey('hotel-order-check-status-button'),
              icon: reconciling
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh_rounded),
              label: const Text('Check Payment Status'),
              onPressed: reconciling ? null : reconcile,
            ),
            const SizedBox(height: AppSpacing.sm),
          ],
          OutlinedButton.icon(
            key: const ValueKey('hotel-order-back-button'),
            icon: const Icon(Icons.arrow_back_rounded),
            label: const Text('Back to Orders'),
            onPressed: () => Navigator.pop(context),
          ),
        ],
      ),
    );
  }

  Widget _dateColumn(String label, String value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: AppColors.textSecondary,
              ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                fontWeight: FontWeight.w700,
              ),
        ),
      ],
    );
  }

  Widget _itemRow(String label, String value, {bool isEmphasized = false}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: AppColors.textSecondary,
              ),
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                fontWeight: isEmphasized ? FontWeight.w900 : FontWeight.w600,
                color: isEmphasized ? AppColors.textPrimary : null,
              ),
        ),
      ],
    );
  }
}
