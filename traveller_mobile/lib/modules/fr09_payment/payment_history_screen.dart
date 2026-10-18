import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import 'payment_status.dart';

class PaymentHistoryScreen extends StatefulWidget {
  final ApiService? api;

  const PaymentHistoryScreen({super.key, this.api});

  @override
  State<PaymentHistoryScreen> createState() => _PaymentHistoryScreenState();
}

class _PaymentHistoryScreenState extends State<PaymentHistoryScreen> {
  late final ApiService api;
  List<Map<String, dynamic>> payments = [];
  bool loading = true;
  String? errorMessage;
  bool isSessionExpired = false;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(loadPayments);
  }

  Future<void> loadPayments() async {
    if (!mounted) return;
    setState(() {
      loading = true;
      errorMessage = null;
      isSessionExpired = false;
    });

    try {
      final response = await api.get('/api/fr9/payments');
      if (!mounted) return;

      if (response is Map && response['ok'] == true) {
        final rawItems = response['items'] as List? ?? [];
        final parsed = rawItems
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();

        // Ensure records are sorted newest-first by timestamp or createdAt
        parsed.sort((a, b) {
          final timeA = (a['timestamp'] ?? a['createdAt'] ?? a['updatedAt'] ?? '').toString();
          final timeB = (b['timestamp'] ?? b['createdAt'] ?? b['updatedAt'] ?? '').toString();
          return timeB.compareTo(timeA);
        });

        setState(() {
          payments = parsed;
          loading = false;
        });
      } else {
        setState(() {
          errorMessage = 'Unable to load payment history.';
          loading = false;
        });
      }
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString().toLowerCase();
      if (e is ApiException && e.statusCode == 401 ||
          msg.contains('unauthorized') ||
          msg.contains('token') ||
          msg.contains('authenticated')) {
        setState(() {
          isSessionExpired = true;
          errorMessage = 'Your session has expired. Please sign in again to view your payment history.';
          loading = false;
        });
      } else {
        setState(() {
          errorMessage = travellerErrorMessage(e);
          loading = false;
        });
      }
    }
  }

  String _formatTitle(Map<String, dynamic> item) {
    final productTitle = (item['productTitle'] ?? '').toString().trim();
    final bookingType = (item['bookingType'] ?? '').toString().trim();

    if (productTitle.isNotEmpty) {
      final typePrefix = _bookingTypeLabel(bookingType);
      return typePrefix.isNotEmpty ? '$typePrefix — $productTitle' : productTitle;
    }

    if (bookingType.isNotEmpty) {
      final typePrefix = _bookingTypeLabel(bookingType);
      return '$typePrefix Booking';
    }

    final source = (item['source'] ?? '').toString();
    if (source == 'checkout_order') return 'Checkout Order';
    return 'Payment Record';
  }

  String _bookingTypeLabel(String raw) {
    return switch (raw.toLowerCase()) {
      'package' => 'Package',
      'hotel' => 'Hotel',
      'flight' => 'Flight',
      'legacy_payment' => 'Legacy Payment',
      _ => raw.isNotEmpty ? raw[0].toUpperCase() + raw.substring(1) : '',
    };
  }

  IconData _iconForBookingType(String raw) {
    return switch (raw.toLowerCase()) {
      'package' => Icons.backpack_rounded,
      'hotel' => Icons.hotel_rounded,
      'flight' => Icons.flight_rounded,
      _ => Icons.receipt_long_rounded,
    };
  }

  String _formatDate(String? raw) {
    if (raw == null || raw.trim().isEmpty) return 'Date unavailable';
    final dt = DateTime.tryParse(raw.trim());
    if (dt == null) return raw;
    final local = dt.toLocal();
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];
    final month = months[local.month - 1];
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '${local.day} $month ${local.year}, $hour:$minute';
  }

  String _formatShortDate(String? raw) {
    if (raw == null || raw.trim().isEmpty) return 'Date unavailable';
    final dt = DateTime.tryParse(raw.trim());
    if (dt == null) return raw;
    final local = dt.toLocal();
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];
    final month = months[local.month - 1];
    return '${local.day} $month ${local.year}';
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

  (String label, AppStatusTone tone, IconData icon) _resolveStatus(Map<String, dynamic> item) {
    final paymentStatus = (item['paymentStatus'] ?? '').toString().trim().toLowerCase();
    final orderStatus = (item['orderStatus'] ?? '').toString().trim().toLowerCase();

    // Paid / Succeeded
    if (paymentStatus == 'paid' ||
        paymentStatus == 'succeeded' ||
        paymentStatus == 'successful' ||
        paymentStatus == 'completed') {
      return ('Paid', AppStatusTone.success, Icons.check_circle_rounded);
    }

    // Failed
    if (paymentStatus == 'failed' ||
        paymentStatus == 'payment_failed' ||
        paymentStatus == 'requires_payment_method') {
      return ('Failed', AppStatusTone.error, Icons.error_outline_rounded);
    }

    // Cancelled
    if (paymentStatus == 'cancelled' ||
        paymentStatus == 'canceled' ||
        orderStatus == 'cancelled' ||
        orderStatus == 'canceled') {
      return ('Cancelled', AppStatusTone.neutral, Icons.cancel_outlined);
    }

    // Pending / Unpaid
    if (paymentStatus == 'unpaid' ||
        paymentStatus == 'pending' ||
        paymentStatus == 'payment_pending' ||
        paymentStatus == 'processing' ||
        orderStatus == 'checkout_open' ||
        orderStatus == 'checkout_pending' ||
        orderStatus == 'payment_pending') {
      return ('Pending', AppStatusTone.warning, Icons.schedule_rounded);
    }

    return (
      paymentStatus.isNotEmpty ? paymentStatus : 'Pending',
      AppStatusTone.neutral,
      Icons.help_outline_rounded,
    );
  }

  void _showPaymentDetails(BuildContext context, Map<String, dynamic> item) {
    final title = _formatTitle(item);
    final bookingType = (item['bookingType'] ?? '').toString().trim();
    final orderRef = (item['orderReference'] ?? item['id'] ?? '').toString();
    final date = _formatDate((item['timestamp'] ?? item['createdAt'] ?? item['updatedAt'] ?? '').toString());
    final amount = _formatAmount(item['amount'], item['currency']);
    final (statusLabel, statusTone, statusIcon) = _resolveStatus(item);
    final isTestMode = item['testMode'] == true ||
        (item['paymentProvider'] ?? '').toString().contains('sim') ||
        isSimulatedPayment(item);
    final provider = (item['paymentProvider'] ?? item['provider'] ?? 'Stripe').toString();
    final cardBrand = (item['cardBrand'] ?? '').toString();
    final cardLast4 = (item['cardLast4'] ?? '').toString();
    final relatedTripId = (item['relatedTripId'] ?? '').toString();
    final relatedBookingId = (item['relatedBookingId'] ?? item['bookingId'] ?? '').toString();
    final orderStatus = (item['orderStatus'] ?? '').toString();

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetContext) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Center(
                    child: Container(
                      width: 44,
                      height: 4,
                      decoration: BoxDecoration(
                        color: AppColors.divider,
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                  ),
                  const SizedBox(height: AppSpacing.md),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Payment Details',
                        style: Theme.of(sheetContext).textTheme.titleLarge?.copyWith(
                              fontWeight: FontWeight.w800,
                            ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close_rounded),
                        tooltip: 'Close',
                        onPressed: () => Navigator.pop(sheetContext),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    title,
                    style: Theme.of(sheetContext).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w800,
                        ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Row(
                    children: [
                      StatusChip(
                        text: statusLabel,
                        tone: statusTone,
                        icon: statusIcon,
                      ),
                      if (isTestMode) ...[
                        const SizedBox(width: AppSpacing.xs),
                        const StatusChip(
                          text: 'Stripe Test Mode',
                          tone: AppStatusTone.neutral,
                          icon: Icons.science_outlined,
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: AppSpacing.md),
                  const Divider(),
                  const SizedBox(height: AppSpacing.sm),
                  _detailRow(
                    sheetContext,
                    'Amount',
                    amount,
                    isEmphasized: true,
                  ),
                  if (orderRef.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: _detailRow(
                            sheetContext,
                            'Order Reference',
                            orderRef,
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.copy_rounded, size: 18),
                          tooltip: 'Copy Reference',
                          onPressed: () {
                            Clipboard.setData(ClipboardData(text: orderRef));
                            ScaffoldMessenger.of(sheetContext).showSnackBar(
                              const SnackBar(
                                content: Text('Order reference copied to clipboard'),
                                duration: Duration(seconds: 2),
                              ),
                            );
                          },
                        ),
                      ],
                    ),
                  ],
                  const SizedBox(height: AppSpacing.sm),
                  _detailRow(sheetContext, 'Date & Time', date),
                  if (bookingType.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    _detailRow(sheetContext, 'Booking Type', _bookingTypeLabel(bookingType)),
                  ],
                  if (orderStatus.isNotEmpty && orderStatus != statusLabel.toLowerCase()) ...[
                    const SizedBox(height: AppSpacing.sm),
                    _detailRow(sheetContext, 'Order Status', orderStatus.replaceAll('_', ' ')),
                  ],
                  if (provider.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    _detailRow(
                      sheetContext,
                      'Payment Provider',
                      provider == 'travelmate_simulation' ? 'TravelMate Simulation' : provider.toUpperCase(),
                    ),
                  ],
                  if (cardBrand.isNotEmpty || cardLast4.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    _detailRow(
                      sheetContext,
                      'Payment Method',
                      '${cardBrand.isNotEmpty ? cardBrand : 'Card'} •••• $cardLast4',
                    ),
                  ],
                  if (relatedBookingId.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    _detailRow(sheetContext, 'Booking Reference', relatedBookingId),
                  ],
                  const SizedBox(height: AppSpacing.md),
                  if (isTestMode)
                    InkCard(
                      color: InkWashColors.cream,
                      padding: const EdgeInsets.all(AppSpacing.sm),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.info_outline_rounded, size: 18, color: InkWashColors.blueGrey),
                          const SizedBox(width: AppSpacing.xs),
                          Expanded(
                            child: Text(
                              'This payment was processed in Stripe Test Mode. No real financial transaction was executed.',
                              style: Theme.of(sheetContext).textTheme.bodySmall?.copyWith(
                                    color: AppColors.textSecondary,
                                  ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  if (relatedTripId.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.md),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        icon: const Icon(Icons.map_rounded),
                        label: const Text('View Package Trip Itinerary'),
                        onPressed: () {
                          Navigator.pop(sheetContext);
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => PackageTripDetailsScreen(
                                tripId: relatedTripId,
                                api: api,
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _detailRow(BuildContext context, String label, String value, {bool isEmphasized = false}) {
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: const ValueKey('payment-history-screen'),
      appBar: AppBar(
        title: const Text('Payment History'),
        actions: [
          IconButton(
            key: const ValueKey('payment-history-refresh'),
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh history',
            onPressed: loading ? null : loadPayments,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: loadPayments,
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (loading) {
      return const Center(
        child: AppLoadingState(
          key: ValueKey('payment-history-loading'),
          message: 'Loading payment history…',
        ),
      );
    }

    if (isSessionExpired) {
      return ListView(
        key: const ValueKey('payment-history-session-expired'),
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          InkCard(
            color: InkWashColors.cream,
            child: Column(
              children: [
                const Icon(Icons.lock_clock_outlined, size: 48, color: AppColors.warning),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  'Session Expired',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  errorMessage ?? 'Please sign in again to view your payments.',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: AppColors.textSecondary,
                      ),
                ),
                const SizedBox(height: AppSpacing.md),
                FilledButton.icon(
                  onPressed: loadPayments,
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text('Retry'),
                ),
              ],
            ),
          ),
        ],
      );
    }

    if (errorMessage != null) {
      return ListView(
        key: const ValueKey('payment-history-error'),
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          AppErrorState(
            message: errorMessage!,
            onRetry: loadPayments,
          ),
        ],
      );
    }

    if (payments.isEmpty) {
      return ListView(
        key: const ValueKey('payment-history-empty'),
        padding: const EdgeInsets.fromLTRB(18, 40, 18, 40),
        children: const [
          TravelEmptyState(
            icon: Icons.receipt_long_outlined,
            title: 'No payment records yet',
            message: 'Completed package bookings and checkout transactions will appear here.',
          ),
        ],
      );
    }

    return ListView.builder(
      key: const ValueKey('payment-history-list'),
      padding: const EdgeInsets.fromLTRB(18, 12, 18, 28),
      itemCount: payments.length,
      itemBuilder: (context, index) {
        final item = payments[index];
        final id = (item['id'] ?? item['orderReference'] ?? index).toString();
        final title = _formatTitle(item);
        final bookingType = (item['bookingType'] ?? '').toString();
        final date = _formatShortDate((item['timestamp'] ?? item['createdAt'] ?? item['updatedAt'] ?? '').toString());
        final amount = _formatAmount(item['amount'], item['currency']);
        final (statusLabel, statusTone, statusIcon) = _resolveStatus(item);
        final isTestMode = item['testMode'] == true ||
            (item['paymentProvider'] ?? '').toString().contains('sim') ||
            isSimulatedPayment(item);
        final orderRef = (item['orderReference'] ?? item['id'] ?? '').toString();

        return Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
          child: LayoutBuilder(
            builder: (context, constraints) {
              return InkWell(
                key: ValueKey('payment-item-$id'),
                onTap: () => _showPaymentDetails(context, item),
                borderRadius: BorderRadius.circular(12),
                child: InkCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        CircleAvatar(
                          backgroundColor: InkWashColors.paleBlue,
                          child: Icon(
                            _iconForBookingType(bookingType),
                            color: InkWashColors.blueGrey,
                          ),
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                title,
                                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                      fontWeight: FontWeight.w800,
                                    ),
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                              ),
                              const SizedBox(height: 3),
                              Text(
                                date,
                                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                      color: AppColors.textSecondary,
                                    ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: AppSpacing.xs),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(
                              amount,
                              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                    fontWeight: FontWeight.w900,
                                    color: AppColors.textPrimary,
                                  ),
                            ),
                            const SizedBox(height: 4),
                            StatusChip(
                              text: statusLabel,
                              tone: statusTone,
                              icon: statusIcon,
                            ),
                          ],
                        ),
                      ],
                    ),
                    if (isTestMode || orderRef.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.xs),
                      Row(
                        children: [
                          if (isTestMode)
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: AppColors.surfaceElevated,
                                borderRadius: BorderRadius.circular(AppRadii.pill),
                                border: Border.all(color: AppColors.divider),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  const Icon(Icons.science_outlined, size: 11, color: AppColors.textSecondary),
                                  const SizedBox(width: 3),
                                  Text(
                                    'Test Mode',
                                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                          color: AppColors.textSecondary,
                                          fontSize: 10,
                                        ),
                                  ),
                                ],
                              ),
                            ),
                          if (isTestMode && orderRef.isNotEmpty)
                            const SizedBox(width: 6),
                          if (orderRef.isNotEmpty)
                            Expanded(
                              child: Text(
                                'Ref: $orderRef',
                                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                      color: AppColors.textSecondary,
                                      fontSize: 11,
                                    ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            );
          },
          ),
        );
      },
    );
  }
}
