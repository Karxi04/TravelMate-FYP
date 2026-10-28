import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../modules/fr09_payment/payment_screen.dart';
import '../../modules/fr09_payment/checkout_return_screen.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'package_gallery_viewer.dart';

class TourismPackageDetailsScreen extends StatefulWidget {
  final Map<String, dynamic> item;

  /// Retained for backwards compatibility with legacy callers.
  final VoidCallback? onAddToTrip;
  final ApiService? api;

  const TourismPackageDetailsScreen({
    super.key,
    required this.item,
    this.onAddToTrip,
    this.api,
  });

  @override
  State<TourismPackageDetailsScreen> createState() =>
      _TourismPackageDetailsScreenState();
}

class _TourismPackageDetailsScreenState
    extends State<TourismPackageDetailsScreen> {
  late final ApiService api;
  bool submitting = false;
  int adults = 1;
  int children = 0;
  String? selectedDepartureDate;
  int _selectedTab = 0;
  bool _fullDescriptionExpanded = false;
  final TransactionAttemptLifecycle _checkoutIntent =
      TransactionAttemptLifecycle('package_checkout');

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    adults = 1;
    children = 0;
    final dates = _list(widget.item['departureDates']);
    if (dates.length == 1) selectedDepartureDate = dates.first;
  }

  Map<String, dynamic> _map(dynamic value) =>
      value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};

  String _dateKey(dynamic value) {
    final raw = (value ?? '').toString().trim();
    final isoDate = RegExp(r'^\d{4}-\d{2}-\d{2}').firstMatch(raw)?.group(0);
    return isoDate ?? raw;
  }

  bool _matchesCurrentPackageDate(Map<String, dynamic> order) {
    if ((order['quoteType'] ?? '').toString() != 'package') return false;
    final snapshot = _map(order['packageSnapshot']);
    final packageId =
        (order['packageId'] ?? snapshot['packageId'] ?? order['quoteId'] ?? '')
            .toString();
    final departure = order['departureDate'] ??
        order['selectedDepartureDate'] ??
        snapshot['selectedDepartureDate'];
    return packageId == (widget.item['id'] ?? '').toString() &&
        _dateKey(departure) == _dateKey(selectedDepartureDate);
  }

  bool _matchesCurrentPurchase(Map<String, dynamic> order) {
    if (!_matchesCurrentPackageDate(order)) return false;
    final snapshot = _map(order['packageSnapshot']);
    final participants = _map(
      order['participants'] is Map
          ? order['participants']
          : snapshot['participants'],
    );
    final previousAdults =
        participants['adults'] ?? order['adultCount'] ?? snapshot['adultCount'];
    final previousChildren = participants['children'] ??
        order['childCount'] ??
        snapshot['childCount'];
    return _number(previousAdults) == adults &&
        _number(previousChildren) == children;
  }

  bool _isPaid(Map<String, dynamic> order) {
    const paidStates = {'paid', 'succeeded', 'completed', 'payment_succeeded'};
    return paidStates.contains((order['status'] ?? '').toString().toLowerCase()) ||
        paidStates.contains(
            (order['paymentStatus'] ?? '').toString().toLowerCase());
  }

  bool _isTerminal(Map<String, dynamic> order) => {
        'expired',
        'checkout_failed',
        'payment_failed',
        'payment_mismatch',
        'cancelled',
        'canceled',
      }.contains((order['status'] ?? '').toString().toLowerCase());

  Future<void> _openExistingBooking(Map<String, dynamic> order) async {
    final tripId = (order['fulfilledTripId'] ?? '').toString();
    if (tripId.isNotEmpty) {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => PackageTripDetailsScreen(tripId: tripId, api: api),
        ),
      );
      return;
    }
    final orderId = (order['id'] ?? '').toString();
    if (orderId.isNotEmpty) {
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => CheckoutReturnScreen(
            link: CheckoutReturnLink(orderId, 'paid'),
            api: api,
          ),
        ),
      );
    }
  }

  Future<bool> _resolveExistingPurchase() async {
    final response = await api.get('/api/fr9/orders');
    final orders = (response is Map ? response['items'] : null) as List? ?? const [];
    final matches = orders
        .whereType<Map>()
        .map((raw) => Map<String, dynamic>.from(raw))
        .where(_matchesCurrentPurchase)
        .toList();

    final pending = matches.cast<Map<String, dynamic>?>().firstWhere(
          (order) => order != null && !_isPaid(order) && !_isTerminal(order),
          orElse: () => null,
        );
    if (pending != null) {
      final continueCheckout = await showDialog<bool>(
            context: context,
            builder: (dialogContext) => AlertDialog(
              title: const Text('Checkout already in progress'),
              content: const Text(
                'A matching package checkout is still open or being verified. Continue it instead of starting another payment.',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext, false),
                  child: const Text('Cancel'),
                ),
                FilledButton(
                  onPressed: () => Navigator.pop(dialogContext, true),
                  child: const Text('Continue Existing Checkout'),
                ),
              ],
            ),
          ) ??
          false;
      if (continueCheckout && mounted) {
        final attemptId = (pending['packageAttemptId'] ?? '').toString();
        final amount = _number(pending['amount'])?.toDouble();
        if (attemptId.isNotEmpty && amount != null) {
          await Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => PaymentScreen(
                packageAttemptId: attemptId,
                initialAmount: amount,
                api: api,
              ),
            ),
          );
        }
      }
      return false;
    }

    final paid = matches.cast<Map<String, dynamic>?>().firstWhere(
          (order) => order != null && _isPaid(order),
          orElse: () => null,
        );
    if (paid != null) {
      final action = await showDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text("You've booked this package before"),
          content: const Text(
            'We found a previous paid booking for this package, departure date and participant selection. Would you like to view your existing booking or make another purchase?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, 'cancel'),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, 'view'),
              child: const Text('View Existing Booking'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, 'buy'),
              child: const Text('Buy Again Anyway'),
            ),
          ],
        ),
      );
      if (action == 'view' && mounted) await _openExistingBooking(paid);
      if (action != 'buy') return false;
      _checkoutIntent.startNewAttempt();
      return true;
    }

    final similarPaid = orders
        .whereType<Map>()
        .map((raw) => Map<String, dynamic>.from(raw))
        .where((order) => _isPaid(order) && _matchesCurrentPackageDate(order))
        .cast<Map<String, dynamic>?>()
        .firstWhere((order) => order != null, orElse: () => null);
    if (similarPaid != null) {
      final action = await showDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Similar booking exists'),
          content: const Text(
            'A previous paid booking has the same package and departure date, but different adult or child counts.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, 'cancel'),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, 'view'),
              child: const Text('View Existing Booking'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, 'continue'),
              child: const Text('Continue New Purchase'),
            ),
          ],
        ),
      );
      if (action == 'view' && mounted) await _openExistingBooking(similarPaid);
      if (action != 'continue') return false;
      _checkoutIntent.startNewAttempt();
    }

    if (matches.any(_isTerminal)) _checkoutIntent.startNewAttempt();
    return true;
  }

  Future<void> _startCheckout() async {
    if (submitting) return;
    setState(() => submitting = true);
    try {
      final packageId = (widget.item['id'] ?? '').toString();
      if (packageId.isEmpty) {
        throw Exception('This package is unavailable for checkout.');
      }
      if (!_hasVerifiedPriceBasis) {
        throw Exception(
            'Package pricing basis is not verified. Please contact the operator.');
      }
      if (_departureDates.isNotEmpty && selectedDepartureDate == null) {
        throw Exception('Select an available departure date.');
      }
      final totalTravellers = adults + children;
      if (totalTravellers < _minimumTravellers) {
        throw Exception(
          'This package requires at least $_minimumTravellers travellers (currently $totalTravellers).',
        );
      }
      if (_maximumTravellers != null && totalTravellers > _maximumTravellers!) {
        throw Exception(
          'This package capacity is ${_maximumTravellers!} travellers (currently $totalTravellers).',
        );
      }
      if (_priceBasis == 'per_person' && children > 0 && _childPrice == null) {
        throw Exception('Child pricing is not available for this package.');
      }
      final clientTotal = _groupTotal?.toDouble();
      if (clientTotal == null || clientTotal <= 0) {
        throw Exception('This package has no supported checkout price.');
      }
      if (!await _resolveExistingPurchase()) return;
      final response = await api.post('/api/fr15/package-checkout-attempts', {
        'packageId': packageId,
        'participants': {'adults': adults, 'children': children},
        if (selectedDepartureDate != null)
          'departureDate': selectedDepartureDate,
        'idempotencyKey': _checkoutIntent.currentOrCreate,
      });
      final attempt = response is Map && response['attempt'] is Map
          ? Map<String, dynamic>.from(response['attempt'] as Map)
          : <String, dynamic>{};
      final attemptId = (attempt['id'] ?? '').toString();
      if (attemptId.isEmpty) {
        throw Exception('Package checkout could not be prepared.');
      }

      // Server-authoritative quote matching and tamper protection
      final serverAmount = _number(attempt['amount'])?.toDouble();
      if (serverAmount == null) {
        throw Exception(
            'Server did not return an authoritative payable total.');
      }
      if ((serverAmount - clientTotal).abs() > 0.01) {
        throw Exception(
          'Checkout price mismatch: server quote is $_currency ${_money(serverAmount)}, '
          'but estimate was $_currency ${_money(clientTotal)}. Please refresh and try again.',
        );
      }

      if (!mounted) return;
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => PaymentScreen(
            packageAttemptId: attemptId,
            initialAmount: serverAmount,
            api: api,
          ),
        ),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
              'After verified payment, your new Package Trip will appear under Trips.'),
        ));
      }
    } catch (error) {
      if (error is ApiException &&
          error.statusCode == 409 &&
          error.message.toLowerCase().contains('idempotency')) {
        _checkoutIntent.startNewAttempt();
        if (mounted) {
          showError(
            context,
            'This checkout request conflicts with an earlier attempt. No payment was created. Tap Checkout again to start a fresh purchase.',
          );
        }
      } else if (mounted) {
        showError(context, error);
      }
    } finally {
      if (mounted) setState(() => submitting = false);
    }
  }

  String _text(String primary, [String? legacy]) =>
      (widget.item[primary] ??
              (legacy == null ? null : widget.item[legacy]) ??
              '')
          .toString()
          .trim();

  List<String> _list(dynamic value) {
    if (value == null) return const [];
    final values =
        value is List ? value : value.toString().split(RegExp(r'\r?\n|,'));
    return values
        .map((entry) => entry.toString().trim())
        .where((entry) => entry.isNotEmpty)
        .toList();
  }

  List<Map<String, dynamic>> get _days =>
      (widget.item['itineraryDays'] as List? ?? const [])
          .whereType<Map>()
          .map((day) => Map<String, dynamic>.from(day))
          .toList();

  String get _currency =>
      _text('currency').isEmpty ? 'MYR' : _text('currency');

  num? _number(dynamic value) =>
      value is num ? value : num.tryParse(value?.toString() ?? '');

  String? get _rawPriceBasis =>
      widget.item['priceBasis']?.toString().trim().toLowerCase();

  bool get _hasVerifiedPriceBasis =>
      _rawPriceBasis == 'per_person' || _rawPriceBasis == 'per_group';

  String get _priceBasis =>
      _hasVerifiedPriceBasis ? _rawPriceBasis! : 'unverified';

  num? get _regularAdultPrice =>
      _number(widget.item['adultPrice']) ?? _number(widget.item['price']);

  num? get _childPrice => _number(widget.item['childPrice']);

  num? get _originalPrice => _number(widget.item['originalPrice']);

  num? get _promotionalPrice => _number(widget.item['promotionalPrice']);

  bool get _isPromotionEligible {
    final promo = _promotionalPrice;
    if (promo == null || promo <= 0) return false;
    final regular = _regularAdultPrice;
    if (regular != null && promo >= regular) return false;

    final startStr = widget.item['promotionStart']?.toString().trim();
    final endStr = widget.item['promotionEnd']?.toString().trim();
    if ((startStr == null || startStr.isEmpty) &&
        (endStr == null || endStr.isEmpty)) {
      return false;
    }

    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    if (startStr != null && startStr.isNotEmpty) {
      final start = DateTime.tryParse(startStr);
      if (start != null) {
        final startDate = DateTime(start.year, start.month, start.day);
        if (today.isBefore(startDate)) return false;
      }
    }
    if (endStr != null && endStr.isNotEmpty) {
      final end = DateTime.tryParse(endStr);
      if (end != null) {
        final endDate = DateTime(end.year, end.month, end.day);
        if (today.isAfter(endDate)) return false;
      }
    }
    return true;
  }

  num? get _effectiveAdultPrice =>
      (_isPromotionEligible && _promotionalPrice != null)
          ? _promotionalPrice
          : _regularAdultPrice;

  num? get _adultPrice => _effectiveAdultPrice;

  List<String> get _departureDates => _list(widget.item['departureDates']);

  int? get _maximumTravellers =>
      _number(widget.item['maximumTravellers'] ?? widget.item['maxTravellers'])
          ?.toInt();

  int get _minimumTravellers =>
      (_number(widget.item['minimumTravellers'])?.toInt() ?? 1)
          .clamp(1, 50)
          .toInt();

  num? get _groupTotal {
    if (!_hasVerifiedPriceBasis) return null;
    if (_priceBasis == 'per_group') {
      if (_isPromotionEligible && _promotionalPrice != null) {
        return _promotionalPrice;
      }
      return _regularAdultPrice;
    }
    final adultRate = _effectiveAdultPrice;
    if (adultRate == null) return null;
    if (children > 0 && _childPrice == null) return null;
    return adultRate * adults + (_childPrice ?? 0) * children;
  }

  num? get _calculatedSavings {
    if (!_isPromotionEligible ||
        _promotionalPrice == null ||
        _regularAdultPrice == null) {
      return null;
    }
    final diff = _regularAdultPrice! - _promotionalPrice!;
    if (diff <= 0) return null;
    if (_priceBasis == 'per_group') return diff;
    return diff * adults;
  }

  String _money(num value) => value == value.roundToDouble()
      ? value.toStringAsFixed(0)
      : value.toStringAsFixed(2);

  String get _price {
    final amount = _adultPrice;
    if (amount == null) return '';
    final basis = _priceBasis == 'per_group' ? 'group' : 'adult';
    return '$_currency ${_money(amount)} / $basis';
  }

  String get _duration {
    final days = _number(widget.item['durationDays']);
    if (days == null || days < 1) return '';
    final nights = _number(widget.item['durationNights']);
    final dayText = '${days.toInt()} ${days == 1 ? 'day' : 'days'}';
    if (nights == null) return dayText;
    return '$dayText · ${nights.toInt()} ${nights == 1 ? 'night' : 'nights'}';
  }

  String _cleanOverviewText(String raw) {
    if (raw.trim().isEmpty) return '';
    // Strip repeated Day 1/2/3 sections from overview introduction
    final daySplit = raw.split(RegExp(
      r'(?:\r?\n\s*|\A)(?:[*#_\s]*Day\s*1\b|[*#_\s]*Itinerary\b)',
      caseSensitive: false,
    ));
    String intro = daySplit.first.trim();
    if (intro.isEmpty && daySplit.length > 1) {
      intro = raw.trim();
    }
    // Normalize raw markdown artifacts like **Day 1**, ###, etc.
    return intro
        .replaceAll(RegExp(r'\*\*([^*]+)\*\*'), r'$1')
        .replaceAll(RegExp(r'#{1,6}\s*'), '')
        .trim();
  }

  List<Map<String, String?>> _extractActivities(dynamic rawActivities) {
    if (rawActivities == null) return const [];
    List<dynamic> list;
    if (rawActivities is List) {
      list = rawActivities;
    } else if (rawActivities is String) {
      list = rawActivities
          .replaceAll('\r', '')
          .split('\n')
          .where((s) => s.trim().isNotEmpty)
          .toList();
    } else {
      return const [];
    }

    final results = <Map<String, String?>>[];
    final timePattern =
        RegExp(r'^(\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?)\s*[-:–—]\s*(.+)$');

    for (final item in list) {
      if (item is Map) {
        final name = (item['activityName'] ??
                item['title'] ??
                item['name'] ??
                '')
            .toString()
            .trim();
        final time = (item['scheduledTime'] ??
                item['timeSlot'] ??
                item['time'] ??
                '')
            .toString()
            .trim();
        final location =
            (item['location'] ?? item['address'] ?? '').toString().trim();
        final description = (item['description'] ?? '').toString().trim();

        if (name.isEmpty && description.isEmpty) continue;

        final match = timePattern.firstMatch(name);
        if (match != null) {
          results.add({
            'name': match.group(2)!.trim(),
            'time': time.isNotEmpty ? time : match.group(1)!.trim(),
            'location': location.isNotEmpty ? location : null,
            'description': description.isNotEmpty ? description : null,
          });
        } else {
          results.add({
            'name': name.isNotEmpty ? name : 'Activity',
            'time': time.isNotEmpty ? time : null,
            'location': location.isNotEmpty ? location : null,
            'description': description.isNotEmpty ? description : null,
          });
        }
      } else if (item is String) {
        final text = item.trim();
        if (text.isEmpty) continue;
        final match = timePattern.firstMatch(text);
        if (match != null) {
          results.add({
            'name': match.group(2)!.trim(),
            'time': match.group(1)!.trim(),
            'location': null,
            'description': null,
          });
        } else {
          results.add({
            'name': text,
            'time': null,
            'location': null,
            'description': null,
          });
        }
      }
    }
    return results;
  }

  Widget _participantCounter(String label, int value, VoidCallback? subtract,
      VoidCallback? add, String keyName) {
    return Expanded(
      child: Semantics(
        label: '$label count $value',
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.xs,
          ),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: AppRadii.control,
            border: Border.all(color: AppColors.divider),
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '$label: $value',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              IconButton(
                key: ValueKey('$keyName-remove'),
                onPressed: subtract,
                icon: const Icon(Icons.remove_circle_outline),
                iconSize: 22,
                visualDensity: VisualDensity.compact,
              ),
              IconButton(
                key: ValueKey('$keyName-add'),
                onPressed: add,
                icon: const Icon(Icons.add_circle_outline),
                iconSize: 22,
                visualDensity: VisualDensity.compact,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _openBookingModal() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (modalContext) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            final totalTravellers = adults + children;
            final canAddParticipant = _maximumTravellers == null ||
                totalTravellers < _maximumTravellers!;
            final canAddChild = canAddParticipant && _childPrice != null;
            final meetsMin = totalTravellers >= _minimumTravellers;

            return Container(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.sizeOf(context).height * 0.88,
              ),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surface,
                borderRadius: const BorderRadius.vertical(
                  top: Radius.circular(AppRadii.large),
                ),
              ),
              child: SafeArea(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // Handle and title
                    Padding(
                      padding: const EdgeInsets.fromLTRB(
                        AppSpacing.md,
                        AppSpacing.sm,
                        AppSpacing.sm,
                        AppSpacing.xs,
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              'Select Travellers & Date',
                              style: Theme.of(context)
                                  .textTheme
                                  .titleLarge
                                  ?.copyWith(
                                    fontWeight: FontWeight.w800,
                                  ),
                            ),
                          ),
                          IconButton(
                            icon: const Icon(Icons.close_rounded),
                            onPressed: () => Navigator.pop(modalContext),
                          ),
                        ],
                      ),
                    ),
                    const Divider(height: 1),
                    Flexible(
                      child: SingleChildScrollView(
                        padding: const EdgeInsets.all(AppSpacing.md),
                        child: Container(
                          key: const ValueKey('package-group-booking'),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _priceBasis == 'per_group'
                                    ? 'This is a fixed group price within the package capacity.'
                                    : !_hasVerifiedPriceBasis
                                        ? 'Pricing basis is not verified for this package. Checkout is disabled.'
                                        : _childPrice == null
                                            ? 'Adult pricing is available. Child rate unavailable.'
                                            : 'Adults: $_currency ${_money(_effectiveAdultPrice!)} · Children: $_currency ${_money(_childPrice!)}',
                                style: Theme.of(context)
                                    .textTheme
                                    .bodySmall
                                    ?.copyWith(
                                      color: AppColors.textSecondary,
                                    ),
                              ),
                              if (_minimumTravellers > 1) ...[
                                const SizedBox(height: AppSpacing.xs),
                                Text(
                                  'Minimum requirement: $_minimumTravellers travellers',
                                  style: TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                    color: totalTravellers < _minimumTravellers
                                        ? AppColors.warning
                                        : AppColors.textSecondary,
                                  ),
                                ),
                              ],
                              const SizedBox(height: AppSpacing.sm),
                              Row(
                                children: [
                                  _participantCounter(
                                    'Adults',
                                    adults,
                                    adults > 1
                                        ? () {
                                            setState(() => adults -= 1);
                                            _checkoutIntent.startNewAttempt();
                                            setModalState(() {});
                                          }
                                        : null,
                                    canAddParticipant
                                        ? () {
                                            setState(() => adults += 1);
                                            _checkoutIntent.startNewAttempt();
                                            setModalState(() {});
                                          }
                                        : null,
                                    'package-adults',
                                  ),
                                ],
                              ),
                              const SizedBox(height: AppSpacing.xs),
                              Row(
                                children: [
                                  _participantCounter(
                                    'Children',
                                    children,
                                    children > 0
                                        ? () {
                                            setState(() => children -= 1);
                                            _checkoutIntent.startNewAttempt();
                                            setModalState(() {});
                                          }
                                        : null,
                                    canAddChild
                                        ? () {
                                            setState(() => children += 1);
                                            _checkoutIntent.startNewAttempt();
                                            setModalState(() {});
                                          }
                                        : null,
                                    'package-children',
                                  ),
                                ],
                              ),
                              if (_priceBasis == 'per_person' &&
                                  _childPrice == null)
                                const Padding(
                                  padding:
                                      EdgeInsets.only(top: AppSpacing.xxs),
                                  child: Text(
                                    'Child rate unavailable — children cannot be added to this booking.',
                                    style: TextStyle(
                                        fontSize: 12,
                                        color: AppColors.textSecondary),
                                  ),
                                ),
                              if (!meetsMin) ...[
                                const SizedBox(height: AppSpacing.sm),
                                Container(
                                  padding:
                                      const EdgeInsets.all(AppSpacing.sm),
                                  decoration: BoxDecoration(
                                    color: AppColors.warningSoft,
                                    borderRadius: BorderRadius.circular(
                                        AppRadii.small),
                                    border:
                                        Border.all(color: AppColors.warning),
                                  ),
                                  child: Row(
                                    children: [
                                      const Icon(Icons.info_outline,
                                          size: 18, color: AppColors.warning),
                                      const SizedBox(width: AppSpacing.xs),
                                      Expanded(
                                        child: Text(
                                          'Minimum group size: $_minimumTravellers travellers required (currently $totalTravellers).',
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w600,
                                            color: InkWashColors.ink,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                              if (_departureDates.isNotEmpty) ...[
                                const SizedBox(height: AppSpacing.sm),
                                DropdownButtonFormField<String>(
                                  key: const ValueKey('package-departure-date'),
                                  initialValue: selectedDepartureDate,
                                  decoration: const InputDecoration(
                                    labelText: 'Departure date',
                                    border: OutlineInputBorder(),
                                  ),
                                  items: _departureDates
                                      .map((value) => DropdownMenuItem(
                                          value: value,
                                          child: Text(value)))
                                      .toList(),
                                  onChanged: (value) {
                                    setState(
                                        () => selectedDepartureDate = value);
                                    _checkoutIntent.startNewAttempt();
                                    setModalState(() {});
                                  },
                                ),
                              ],
                              const Divider(height: AppSpacing.lg),
                              if (_hasVerifiedPriceBasis &&
                                  _groupTotal != null) ...[
                                if (_priceBasis == 'per_person')
                                  Text(
                                    '$adults Adult${adults > 1 ? 's' : ''} × $_currency ${_money(_effectiveAdultPrice!)}'
                                    '${children > 0 && _childPrice != null ? ' + $children Child${children > 1 ? 'ren' : ''} × $_currency ${_money(_childPrice!)}' : ''}',
                                    style: const TextStyle(
                                        fontSize: 13,
                                        color: AppColors.textSecondary),
                                  ),
                                if (_calculatedSavings != null) ...[
                                  const SizedBox(height: AppSpacing.xxs),
                                  Text(
                                    'Promotional savings: $_currency ${_money(_calculatedSavings!)}',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      fontWeight: FontWeight.w700,
                                      color: AppColors.success,
                                    ),
                                  ),
                                ],
                                const SizedBox(height: AppSpacing.xs),
                              ],
                              Text(
                                _groupTotal == null
                                    ? 'Group total unavailable'
                                    : 'Group total: $_currency ${_money(_groupTotal!)}',
                                key: const ValueKey('package-group-total'),
                                style: Theme.of(context)
                                    .textTheme
                                    .titleLarge
                                    ?.copyWith(
                                      fontWeight: FontWeight.w800,
                                    ),
                              ),
                              const SizedBox(height: AppSpacing.xs),
                              const Text(
                                'One signed-in traveller pays for the complete group. Stripe Checkout remains in Test Mode.',
                                style: TextStyle(
                                    fontSize: 12,
                                    color: AppColors.textSecondary),
                              ),
                              const SizedBox(height: AppSpacing.xxs),
                              const Text(
                                'Verified payment creates a new independent Package Trip; existing personal Trips are not changed.',
                                style: TextStyle(
                                    fontSize: 12,
                                    color: AppColors.textSecondary),
                              ),
                              const SizedBox(height: AppSpacing.md),
                              SizedBox(
                                width: double.infinity,
                                child: FilledButton.icon(
                                  key: const ValueKey('package-checkout-btn'),
                                  onPressed: (submitting ||
                                          !_hasVerifiedPriceBasis ||
                                          !meetsMin ||
                                          (_departureDates.isNotEmpty &&
                                              selectedDepartureDate == null))
                                      ? null
                                      : () async {
                                          Navigator.pop(modalContext);
                                          await _startCheckout();
                                        },
                                  icon: const Icon(Icons.payment_outlined),
                                  label: Text(
                                    submitting
                                        ? 'Preparing checkout...'
                                        : !_hasVerifiedPriceBasis
                                            ? 'Price basis unverified'
                                            : 'Checkout package',
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Widget _heading(String title) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.sm),
        child: Text(
          title,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
        ),
      );

  Widget _bullets(String title, dynamic value, IconData icon,
      {Color? color}) {
    final values = _list(value);
    if (values.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _heading(title),
            ...values.map(
              (entry) => Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(icon, size: 18, color: color ?? AppColors.primary),
                    const SizedBox(width: AppSpacing.xs),
                    Expanded(
                      child: Text(
                        entry,
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _textSection(String title, String value, IconData icon) {
    if (value.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 18, color: AppColors.primary),
                const SizedBox(width: AppSpacing.xs),
                Expanded(child: _heading(title)),
              ],
            ),
            Text(
              value,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    height: 1.45,
                  ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSectionTabs() {
    final tabs = [
      (0, 'Overview', Icons.info_outline),
      (1, 'Itinerary', Icons.calendar_month_outlined),
      (2, "What's Included", Icons.checklist_outlined),
      (3, 'Policies', Icons.policy_outlined),
    ];

    return Container(
      margin: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.xxs),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: AppRadii.control,
        border: Border.all(color: AppColors.divider),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: tabs.map((tab) {
            final isSelected = _selectedTab == tab.$1;
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 2),
              child: InkWell(
                onTap: () => setState(() => _selectedTab = tab.$1),
                borderRadius: BorderRadius.circular(AppRadii.small),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 150),
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm,
                    vertical: AppSpacing.xs,
                  ),
                  decoration: BoxDecoration(
                    color: isSelected ? AppColors.primary : Colors.transparent,
                    borderRadius: BorderRadius.circular(AppRadii.small),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        tab.$3,
                        size: 16,
                        color:
                            isSelected ? Colors.white : AppColors.textSecondary,
                      ),
                      const SizedBox(width: AppSpacing.xxs),
                      Text(
                        tab.$2,
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight:
                              isSelected ? FontWeight.w700 : FontWeight.w500,
                          color:
                              isSelected ? Colors.white : AppColors.textPrimary,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      ),
    );
  }

  Widget _buildOverviewTab(String description) {
    final cleanIntro = _cleanOverviewText(description);
    final campaigns = (widget.item['activeCampaigns'] as List? ?? const [])
        .whereType<Map>()
        .map((entry) => Map<String, dynamic>.from(entry))
        .toList();
    final departureDates = _list(widget.item['departureDates']);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (cleanIntro.isNotEmpty)
          InkCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _heading('Package overview'),
                Text(
                  _fullDescriptionExpanded || cleanIntro.length <= 260
                      ? cleanIntro
                      : '${cleanIntro.substring(0, math.min(cleanIntro.length, 260)).trim()}…',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        height: 1.45,
                      ),
                ),
                if (cleanIntro.length > 260) ...[
                  const SizedBox(height: AppSpacing.xs),
                  GestureDetector(
                    onTap: () => setState(() =>
                        _fullDescriptionExpanded = !_fullDescriptionExpanded),
                    child: Text(
                      _fullDescriptionExpanded
                          ? 'Show less'
                          : 'Read full description',
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.primary,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        const SizedBox(height: AppSpacing.sm),
        _bullets('Highlights', widget.item['highlights'], Icons.place_outlined),
        if (campaigns.isNotEmpty) ...[
          _heading('Current promotion'),
          ...campaigns.map((campaign) => Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: InkCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        (campaign['campaignTitle'] ?? 'Promotion').toString(),
                        style: const TextStyle(fontWeight: FontWeight.w800),
                      ),
                      if ((campaign['description'] ?? '')
                          .toString()
                          .trim()
                          .isNotEmpty) ...[
                        const SizedBox(height: AppSpacing.xxs),
                        Text(campaign['description'].toString()),
                      ],
                      if ((campaign['promoCode'] ?? '')
                          .toString()
                          .trim()
                          .isNotEmpty) ...[
                        const SizedBox(height: AppSpacing.xs),
                        TravelStatusPill(
                          text: 'Code ${campaign['promoCode']}',
                          icon: Icons.local_offer_outlined,
                        ),
                      ],
                    ],
                  ),
                ),
              )),
          const SizedBox(height: AppSpacing.sm),
        ],
        if (departureDates.isNotEmpty ||
            _text('departureLocation').isNotEmpty ||
            _text('meetingPoint').isNotEmpty)
          _textSection(
            'Departure details',
            [
              if (departureDates.isNotEmpty)
                'Dates: ${departureDates.join(', ')}',
              if (_text('departureLocation').isNotEmpty)
                'Location: ${_text('departureLocation')}',
              if (_text('meetingPoint').isNotEmpty)
                'Meeting point: ${_text('meetingPoint')}',
              if (_text('departureNotes').isNotEmpty) _text('departureNotes'),
            ].join('\n'),
            Icons.event_available_outlined,
          ),
        if (_text('operatorName').isNotEmpty)
          _textSection(
            'Tourism Operator',
            [
              _text('operatorName'),
              _text('operatorPhone'),
              _text('operatorEmail'),
            ].where((value) => value.isNotEmpty).join('\n'),
            Icons.storefront_outlined,
          ),
      ],
    );
  }

  Widget _buildItineraryTab() {
    if (_days.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(AppSpacing.lg),
        child: Center(
          child: Text(
            'No itinerary details available for this package.',
            style: TextStyle(color: AppColors.textSecondary),
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _heading('Day-by-day itinerary'),
        ..._days.map((day) {
          final dayNumber = day['dayNumber'] ?? _days.indexOf(day) + 1;
          final activities = _extractActivities(day['activities']);
          final meals = _list(day['meals']);
          final title = (day['title'] ?? '').toString().trim();
          final description = (day['description'] ?? '').toString().trim();
          final stay = (day['accommodation'] ?? '').toString().trim();
          final transport = (day['transportNotes'] ?? '').toString().trim();

          return Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: InkCard(
              child: ExpansionTile(
                initiallyExpanded: true,
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                title: Text(
                  'Day $dayNumber · $title',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                children: [
                  if (description.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.xxs),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        description,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: AppColors.textSecondary,
                            ),
                      ),
                    ),
                  ],
                  if (activities.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'Scheduled activities',
                        style: Theme.of(context).textTheme.labelLarge?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xxs),
                    ...activities.map(
                      (act) => Padding(
                        padding: const EdgeInsets.symmetric(
                            vertical: AppSpacing.xxs),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 6,
                                vertical: 2,
                              ),
                              decoration: BoxDecoration(
                                color: act['time'] != null
                                    ? AppColors.primarySoft
                                    : AppColors.surface,
                                borderRadius:
                                    BorderRadius.circular(AppRadii.small),
                                border: Border.all(
                                  color: act['time'] != null
                                      ? AppColors.primary
                                      : AppColors.divider,
                                ),
                              ),
                              child: Text(
                                act['time'] ?? 'Time not specified',
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w700,
                                  color: act['time'] != null
                                      ? AppColors.primaryStrong
                                      : AppColors.textSecondary,
                                ),
                              ),
                            ),
                            const SizedBox(width: AppSpacing.xs),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    act['name'] ?? 'Activity',
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w600,
                                      fontSize: 13,
                                    ),
                                  ),
                                  if (act['description'] != null &&
                                      act['description']!.isNotEmpty)
                                    Text(
                                      act['description']!,
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: AppColors.textSecondary,
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                  if (meals.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.restaurant_outlined,
                            size: 16, color: AppColors.textSecondary),
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(
                          child: Text(
                            'Meals: ${meals.join(', ')}',
                            style: const TextStyle(fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (stay.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.hotel_outlined,
                            size: 16, color: AppColors.textSecondary),
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(
                          child: Text(
                            'Stay: $stay',
                            style: const TextStyle(fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (transport.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.directions_bus_outlined,
                            size: 16, color: AppColors.textSecondary),
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(
                          child: Text(
                            'Transport: $transport',
                            style: const TextStyle(fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          );
        }),
      ],
    );
  }

  Widget _buildIncludedTab() {
    final transport = _list(widget.item['transportTypes']);
    final meals =
        _days.expand((day) => _list(day['meals'])).toSet().toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _bullets('What is included', widget.item['inclusions'],
            Icons.check_circle_outline,
            color: AppColors.success),
        _bullets('Not included', widget.item['exclusions'],
            Icons.remove_circle_outline,
            color: AppColors.textSecondary),
        _bullets('Meals', meals, Icons.restaurant_outlined),
        _bullets('Transport', transport, Icons.directions_bus_outlined),
        _bullets('What to bring', widget.item['whatToBring'],
            Icons.backpack_outlined),
        _textSection(
          'Accommodation',
          [
            _text('accommodationName'),
            _text('accommodationCategory'),
            _text('roomType'),
            _text('accommodationNotes'),
          ].where((value) => value.isNotEmpty).join('\n'),
          Icons.hotel_outlined,
        ),
      ],
    );
  }

  Widget _buildPoliciesTab() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _textSection('Cancellation policy', _text('cancellationPolicy'),
            Icons.event_busy_outlined),
        _textSection('Refund policy', _text('refundPolicy'),
            Icons.currency_exchange_outlined),
        _textSection('Booking terms', _text('bookingTerms'),
            Icons.description_outlined),
        _textSection(
            'Important notes', _text('importantNotes'), Icons.info_outline),
        InkCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.shield_outlined,
                      size: 18, color: AppColors.primary),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(child: _heading('Reservation & Payment Notice')),
                ],
              ),
              const Text(
                'Test payment recorded. Your Package Trip is available in TravelMate. No external supplier reservation has been created.',
                style: TextStyle(fontSize: 13, height: 1.45),
              ),
              const SizedBox(height: AppSpacing.xs),
              const Text(
                'Stripe checkout runs in Test Mode. Verified payment creates a dedicated, read-only Package Trip under Trips.',
                style: TextStyle(
                    fontSize: 12,
                    color: AppColors.textSecondary,
                    height: 1.4),
              ),
            ],
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final title = _text('title', 'packageTitle');
    final destination = _text('destination', 'destinationName');
    final hero = _text('heroImage', 'imageUrl');
    final description = _text('fullDescription', 'description');
    final capacity = _number(
        widget.item['maximumTravellers'] ?? widget.item['maxTravellers']);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Tourism package'),
      ),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(
          AppSpacing.md,
          AppSpacing.xs,
          AppSpacing.md,
          AppSpacing.sm,
        ),
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.xs,
          ),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surface,
            borderRadius: AppRadii.card,
            border: Border.all(color: AppColors.divider),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.04),
                blurRadius: 6,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final isNarrow = constraints.maxWidth < 360 ||
                  MediaQuery.textScalerOf(context).scale(14) > 16;
              final priceColumn = Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _priceBasis == 'per_group'
                        ? '$_currency ${_money(_groupTotal ?? _regularAdultPrice ?? 0)}'
                        : '$_currency ${_money(_effectiveAdultPrice ?? 0)}',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w800,
                          color: AppColors.primary,
                        ),
                  ),
                  Text(
                    _priceBasis == 'per_group'
                        ? 'total group rate'
                        : (_groupTotal != null &&
                                (adults > 1 || children > 0))
                            ? 'Total: $_currency ${_money(_groupTotal!)} ($adults adult${adults > 1 ? 's' : ''}${children > 0 ? ', $children child${children > 1 ? 'ren' : ''}' : ''})'
                            : '/ adult',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.textSecondary,
                          fontSize: 11,
                        ),
                  ),
                ],
              );

              final actionButton = FilledButton(
                key: const ValueKey('package-book-now-cta'),
                onPressed:
                    !_hasVerifiedPriceBasis ? null : _openBookingModal,
                child: Text(
                  !_hasVerifiedPriceBasis
                      ? 'Price basis unverified'
                      : 'Select travellers & date',
                ),
              );

              if (isNarrow) {
                return Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    priceColumn,
                    const SizedBox(height: AppSpacing.xs),
                    actionButton,
                  ],
                );
              }

              return Row(
                children: [
                  Expanded(child: priceColumn),
                  const SizedBox(width: AppSpacing.xs),
                  actionButton,
                ],
              );
            },
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.sm,
          AppSpacing.lg,
          AppSpacing.xxl,
        ),
        children: [
          PackageGalleryCarousel(
            photos: PackageGalleryCarousel.extractPhotos(widget.item),
            title: title.isEmpty ? destination : title,
            destination: destination,
            fallbackHeroUrl: hero,
          ),
          const SizedBox(height: AppSpacing.md),
          const TravelStatusPill(
            text: 'VERIFIED OPERATOR PACKAGE',
            icon: Icons.verified_outlined,
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            title.isEmpty ? 'Tourism package' : title,
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
          ),
          if (destination.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xxs),
            Row(
              children: [
                const Icon(Icons.location_on_outlined,
                    size: 16, color: AppColors.textSecondary),
                const SizedBox(width: AppSpacing.xxs),
                Expanded(
                  child: Text(
                    destination,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: AppColors.textSecondary,
                        ),
                  ),
                ),
              ],
            ),
          ],
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            children: [
              if (_price.isNotEmpty)
                TravelStatusPill(
                    text: _price, icon: Icons.payments_outlined),
              if (_priceBasis == 'per_person' && _childPrice != null)
                TravelStatusPill(
                  text: '$_currency ${_money(_childPrice!)} / child',
                  icon: Icons.child_care_outlined,
                ),
              if (_priceBasis == 'per_person' &&
                  _childPrice == null &&
                  _regularAdultPrice != null)
                const TravelStatusPill(
                  text: 'Child rate unavailable',
                  icon: Icons.info_outline,
                ),
              if (_hasVerifiedPriceBasis)
                TravelStatusPill(
                  text: _priceBasis == 'per_group'
                      ? 'Fixed group pricing'
                      : 'Per person pricing',
                  icon: Icons.sell_outlined,
                ),
              if (!_hasVerifiedPriceBasis)
                const TravelStatusPill(
                  text: 'Unverified price basis',
                  icon: Icons.warning_amber_outlined,
                ),
              if (_isPromotionEligible)
                const TravelStatusPill(
                  text: 'Special promo rate',
                  icon: Icons.local_offer_outlined,
                ),
              if (_originalPrice != null &&
                  _originalPrice! > (_effectiveAdultPrice ?? 0))
                TravelStatusPill(
                  text: 'Orig. $_currency ${_money(_originalPrice!)}',
                  icon: Icons.history_outlined,
                ),
              if (_duration.isNotEmpty)
                TravelStatusPill(
                  text: _duration,
                  icon: Icons.calendar_today_outlined,
                ),
              if (capacity != null)
                TravelStatusPill(
                  text: 'Up to ${capacity.toInt()} travellers',
                  icon: Icons.group_outlined,
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          _buildSectionTabs(),
          const SizedBox(height: AppSpacing.xs),
          if (_selectedTab == 0) _buildOverviewTab(description),
          if (_selectedTab == 1) _buildItineraryTab(),
          if (_selectedTab == 2) _buildIncludedTab(),
          if (_selectedTab == 3) _buildPoliciesTab(),
          const SizedBox(height: AppSpacing.xxl),
        ],
      ),
    );
  }
}
