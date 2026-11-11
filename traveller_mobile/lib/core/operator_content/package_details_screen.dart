import 'dart:convert';
import '../utils/package_pricing.dart';
import 'package:flutter/material.dart';

import '../../modules/fr09_payment/payment_screen.dart';
import '../../modules/fr09_payment/payment_status.dart';
import '../../modules/fr09_payment/checkout_return_screen.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'package_gallery_viewer.dart';
import 'package_text_block.dart';
import '../utils/package_departures.dart';

class TourismPackageDetailsScreen extends StatefulWidget {
  final Map<String, dynamic> item;

  /// Retained for backwards compatibility with legacy callers.
  final VoidCallback? onAddToTrip;
  final ApiService? api;
  final int? initialAdults, initialChildren;
  final String? initialDepartureDate, initialPromoCode;

  const TourismPackageDetailsScreen({
    super.key,
    required this.item,
    this.onAddToTrip,
    this.api,
    this.initialAdults,
    this.initialChildren,
    this.initialDepartureDate,
    this.initialPromoCode,
  });

  @override
  State<TourismPackageDetailsScreen> createState() =>
      _TourismPackageDetailsScreenState();
}

class _TourismPackageDetailsScreenState
    extends State<TourismPackageDetailsScreen> {
  late final ApiService api;
  bool submitting = false;
  String promoCode = '';
  Map<String, dynamic>? _serverQuote;
  String? _quotedSelection;
  String _offerEvidence(dynamic value) => jsonEncode([
    for (final key in ['id','discountType','discountValue','startDate','endDate','termsConditions','promoCode'])
      value is Map ? value[key] : null,
  ]);
  String? _quoteError;
  bool _quoteLoading = false;
  int _quoteRequest = 0;
  bool get _canQuote => consumerPaymentsAvailable && !api.isStandalone && adults + children >= _minimumTravellers && packageDepartureError(_departureDates, selectedDepartureDate) == null;
  Future<void> _refreshQuote(StateSetter refresh, BuildContext sheetContext) async {
    if (!_canQuote) return;
    final request = ++_quoteRequest;
    setState(() { _quoteLoading = true; _quoteError = null; });
    refresh(() {});
    try { await _loadQuote(); } catch (error) { if (mounted && request == _quoteRequest) _quoteError = 'Price could not be refreshed. Update the price before payment.'; }
    finally { if (mounted && request == _quoteRequest) { setState(() => _quoteLoading = false); if (sheetContext.mounted) refresh(() {}); } }
  }
  String get _selection => '$adults:$children:$selectedDepartureDate:$promoCode';
  Map<String, dynamic>? get _currentPricing {
    if (_quotedSelection == _selection && _serverQuote?['pricingBreakdown'] is Map) return Map<String, dynamic>.from(_serverQuote!['pricingBreakdown']);
    final projected = PackagePricing.current(widget.item);
    final party = projected?['participants'];
    return promoCode.isEmpty && party is Map && party['adults'] == adults && party['children'] == children ? projected : null;
  }
  Future<Map<String, dynamic>> _loadQuote() async {
    final selection = _selection;
    final data = await api.post('/api/fr15/package-checkout-attempts/quote', {'packageId': widget.item['id'], 'participants': {'adults': adults, 'children': children}, if(selectedDepartureDate != null) 'departureDate': selectedDepartureDate, 'promoCode': promoCode});
    final quote = Map<String, dynamic>.from(data['quote'] as Map);
    if (!mounted || selection != _selection) throw Exception('Your selection changed. Review the current package price.');
    setState(() { _serverQuote = quote; _quotedSelection = selection; });
    return quote;
  }
  bool consumerPaymentsAvailable = false;
  int adults = 1;
  int children = 0;
  String? selectedDepartureDate;
  int _selectedTab = 0;
  int? _selectedItineraryDayIndex;
  final TransactionAttemptLifecycle _checkoutIntent =
      TransactionAttemptLifecycle('package_checkout');

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(() async {
      final types = await loadHostedCheckoutCapabilities(api);
      if (mounted) setState(() => consumerPaymentsAvailable = types.contains('package'));
    });
    adults = (widget.initialAdults ?? 1).clamp(1, 50);
    children = (widget.initialChildren ?? 0).clamp(0, 50 - adults);
    promoCode = widget.initialPromoCode ?? '';
    final dates = _list(widget.item['departureDates']);
    final requested = widget.initialDepartureDate;
    if (requested != null) {
      if ((dates.isEmpty || dates.contains(requested)) && packageDepartureAvailable(requested)) selectedDepartureDate = requested;
      else { Future.microtask(() { if (mounted) showError(context, 'The requested departure is no longer available. Review the current dates.'); }); }
    } else if (dates.length == 1 && packageDepartureAvailable(dates.first)) selectedDepartureDate = dates.first;
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
    if (!consumerPaymentsAvailable) {
      showError(context, 'Checkout is not configured or is temporarily unavailable. Please try again later.');
      return;
    }
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
      final departureError=packageDepartureError(_departureDates,selectedDepartureDate);
      if(departureError!=null) throw Exception(departureError);
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
      final viewedPromotion = _offerEvidence(_currentPricing?['promotion']);
      final quote = await _loadQuote();
      final response = await api.post('/api/fr15/package-checkout-attempts', {
        'quoteToken': quote['quoteToken'],
        'packageId': packageId,
        'promoCode': promoCode,
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
      if ((serverAmount - clientTotal).abs() > 0.001 || viewedPromotion != _offerEvidence((quote['pricingBreakdown'] as Map?)?['promotion'])) {
        if (!mounted) return;
        final accepted = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text('Review updated package amount'),
            content: Text(
                'The current server quote is $_currency ${_money(serverAmount)}.\nBefore discount: ${attempt['pricingBreakdown']?['originalSubtotal'] ?? serverAmount}\nDiscount: ${attempt['pricingBreakdown']?['promotionDiscount'] ?? 0}\n${attempt['pricingBreakdown']?['promotion']?['campaignTitle'] ?? ''}\n${attempt['pricingBreakdown']?['promotion']?['termsConditions'] ?? ''}\nReview before payment.'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  child: const Text('Review Checkout')),
            ],
          ),
        );
        if (accepted != true) return;
      }

      if (!mounted) return;
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => PaymentScreen(
            packageAttemptId: attemptId,
            initialAmount: serverAmount,
            pricingBreakdown: attempt['pricingBreakdown'] is Map
                ? Map<String, dynamic>.from(attempt['pricingBreakdown'])
                : null,
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

  bool get _isPromotionEligible => (_number((_currentPricing ?? PackagePricing.current(widget.item))?['promotionDiscount']) ?? 0) > 0;
  num? get _effectiveAdultPrice => _regularAdultPrice;

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
    if (_currentPricing != null) return _number(_currentPricing!['finalPayable']);
    if (_priceBasis == 'per_group') return _regularAdultPrice;
    if (_regularAdultPrice == null || (children > 0 && _childPrice == null)) return null;
    return _regularAdultPrice! * adults + (_childPrice ?? 0) * children;
  }

  num? get _calculatedSavings {
    final savings = _number(_currentPricing?['promotionDiscount']);
    return savings != null && savings > 0 ? savings : null;
  }

  String _money(num value) => value == value.roundToDouble()
      ? value.toStringAsFixed(0)
      : value.toStringAsFixed(2);

  String get _price => PackagePricing.label(widget.item);

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
    return intro
        .replaceAllMapped(RegExp(r'\*\*([^*]+)\*\*'), (match) => match[1]!)
        .replaceAll(RegExp(r'^#{1,6}\s+', multiLine: true), '')
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
        final rawImage = (item['imageUrl'] ??
                item['photoUrl'] ??
                item['image'] ??
                item['photo'] ??
                '')
            .toString()
            .trim();

        if (name.isEmpty && description.isEmpty) continue;

        final match = timePattern.firstMatch(name);
        if (match != null) {
          results.add({
            'name': match.group(2)!.trim(),
            'time': time.isNotEmpty ? time : match.group(1)!.trim(),
            'location': location.isNotEmpty ? location : null,
            'description': description.isNotEmpty ? description : null,
            'image': rawImage.isNotEmpty ? rawImage : null,
          });
        } else {
          results.add({
            'name': name.isNotEmpty ? name : 'Activity',
            'time': time.isNotEmpty ? time : null,
            'location': location.isNotEmpty ? location : null,
            'description': description.isNotEmpty ? description : null,
            'image': rawImage.isNotEmpty ? rawImage : null,
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
    if (_canQuote) { try { await _loadQuote(); } catch (_) { _quoteError = 'Price could not be refreshed. Update the price before payment.'; } }
    if (!mounted) return;
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
                                            _refreshQuote(setModalState, context);
                                          }
                                        : null,
                                    canAddParticipant
                                        ? () {
                                            setState(() => adults += 1);
                                            _checkoutIntent.startNewAttempt();
                                            setModalState(() {});
                                            _refreshQuote(setModalState, context);
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
                                            _refreshQuote(setModalState, context);
                                          }
                                        : null,
                                    canAddChild
                                        ? () {
                                            setState(() => children += 1);
                                            _checkoutIntent.startNewAttempt();
                                            setModalState(() {});
                                            _refreshQuote(setModalState, context);
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
                                          enabled: packageDepartureAvailable(value),
                                          child: Text(packageDepartureAvailable(value) ? value : '$value — unavailable')))
                                      .toList(),
                                  onChanged: (value) {
                                    setState(
                                        () => selectedDepartureDate = value);
                                    _checkoutIntent.startNewAttempt();
                                    setModalState(() {});
                                    _refreshQuote(setModalState, context);
                                  },
                                ),
                                if(packageDepartureError(_departureDates,selectedDepartureDate)!=null)
                                  Text(packageDepartureError(_departureDates,selectedDepartureDate)!,style:const TextStyle(color:AppColors.warning)),
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
                              TextFormField(
                                initialValue: promoCode,
                                key: const ValueKey('package-promo-code'),
                                decoration: const InputDecoration(
                                    labelText: 'Promo code (optional)'),
                                textCapitalization:
                                    TextCapitalization.characters,
                                onChanged: (value) {
                                  setState(() => promoCode = value.trim());
                                  _checkoutIntent.startNewAttempt();
                                  setModalState(() {});
                                },
                              ),
                              if (_quoteLoading) const Text('Updating authoritative price...'),
                              if (_quoteError != null) Text(_quoteError!),
                              TextButton.icon(key: const ValueKey('refresh-package-price'), onPressed: api.isStandalone ? null : () async {
                                try { await _loadQuote(); if (context.mounted) setModalState(() {}); } catch(error) { if(context.mounted) showError(context, error); }
                              }, icon: const Icon(Icons.refresh), label: const Text('Update price / apply code')),
                              if (_currentPricing?['promotion'] is Map && _isPromotionEligible) Text('${_currentPricing!['promotion']['campaignTitle']} · ${_currentPricing!['promotion']['startDate']} to ${_currentPricing!['promotion']['endDate']}\n${_currentPricing!['promotion']['termsConditions'] ?? ''}'),
                              const Text('One best applicable offer; discounts do not stack. Final price is verified before payment.'),
                              const SizedBox(height: AppSpacing.sm),
                              Text(
                                _groupTotal == null
                                    ? 'Group total unavailable'
                                    : '${_currentPricing == null && widget.item['packagePricing'] != null ? 'Estimated base total' : 'Group total'}: $_currency ${_money(_groupTotal!)}',
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
                                academicPaymentDisclosure,
                                style: TextStyle(
                                    fontSize: 12,
                                    color: AppColors.textSecondary),
                              ),
                              const SizedBox(height: AppSpacing.xxs),
                              const Text(
                                'Reviewing this package does not create a reservation or change your Trips.',
                                style: TextStyle(
                                    fontSize: 12,
                                    color: AppColors.textSecondary),
                              ),
                              const SizedBox(height: AppSpacing.md),
                              SizedBox(
                                width: double.infinity,
                                child: FilledButton.icon(
                                  key: const ValueKey('package-checkout-btn'),
                                  onPressed: (!consumerPaymentsAvailable || submitting || _quoteLoading ||
                                          !_hasVerifiedPriceBasis ||
                                          !meetsMin ||
                                          packageDepartureError(_departureDates,selectedDepartureDate)!=null)
                                      ? null
                                      : () async {
                                          Navigator.pop(modalContext);
                                          await _startCheckout();
                                        },
                                  icon: const Icon(Icons.payment_outlined),
                                  label: Text(
                                    !consumerPaymentsAvailable
                                        ? 'Purchase unavailable'
                                        : submitting
                                        ? 'Preparing checkout...'
                                        : !_hasVerifiedPriceBasis
                                            ? 'Price basis unverified'
                                            : 'Continue to Payment',
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
    final themeColor = color ?? AppColors.primary;
    final isPositive = color == AppColors.success;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: InkCard(
        child: ExpansionTile(
          key: PageStorageKey('package-list-$title'),
          initiallyExpanded: values.length <= 5,
          tilePadding: EdgeInsets.zero,
          childrenPadding: EdgeInsets.zero,
          leading: Container(
            padding: const EdgeInsets.all(AppSpacing.xs),
            decoration: BoxDecoration(
              color: isPositive
                  ? AppColors.successSoft
                  : (color != null
                      ? color.withValues(alpha: 0.12)
                      : AppColors.primarySoft),
              borderRadius: BorderRadius.circular(AppRadii.small),
            ),
            child: Icon(icon, size: 20, color: themeColor),
          ),
          title: Text(
            title,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          subtitle: values.length > 5
              ? Text('${values.length} items',
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 12))
              : null,
          children: [
            const SizedBox(height: AppSpacing.xs),
            ...values.map(
              (entry) => Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Icon(icon, size: 16, color: themeColor),
                    ),
                    const SizedBox(width: AppSpacing.xs),
                    Expanded(
                      child: PackageTextBlock(text: entry, collapsedLines: 3),
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
                Container(
                  padding: const EdgeInsets.all(6),
                  decoration: BoxDecoration(
                    color: AppColors.primarySoft,
                    borderRadius: BorderRadius.circular(AppRadii.small),
                  ),
                  child: Icon(icon, size: 18, color: AppColors.primary),
                ),
                const SizedBox(width: AppSpacing.xs),
                Expanded(child: _heading(title)),
              ],
            ),
            const SizedBox(height: AppSpacing.xxs),
            PackageTextBlock(text: value),
          ],
        ),
      ),
    );
  }

  Widget _buildOperatorCard() {
    final name = _text('operatorName');
    final phone = _text('operatorPhone');
    final email = _text('operatorEmail');
    if (name.isEmpty) return const SizedBox.shrink();

    final isVerified = widget.item['isVerifiedOperator'] == true ||
        widget.item['operatorVerified'] == true;
    final licenseNumber = (widget.item['licenseNumber'] ??
            widget.item['operatorLicense'] ??
            widget.item['motacLicense'] ??
            '')
        .toString()
        .trim();

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: AppColors.primarySoft,
                    borderRadius: BorderRadius.circular(AppRadii.small),
                  ),
                  child: const Icon(Icons.storefront_outlined,
                      size: 20, color: AppColors.primary),
                ),
                const SizedBox(width: AppSpacing.xs),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _heading('Tourism Operator'),
                      Text(
                        licenseNumber.isNotEmpty
                            ? 'License: $licenseNumber'
                            : 'Tour Operator & Travel Agency',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.textSecondary,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ),
                ),
                if (isVerified)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: AppColors.successSoft,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.verified, size: 12, color: AppColors.success),
                        SizedBox(width: 4),
                        Text(
                          'Verified',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            color: AppColors.success,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            const Divider(height: 20),
            Text(
              name,
              style: const TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w800,
                color: AppColors.textPrimary,
              ),
            ),
            if (phone.isNotEmpty) ...[
              const SizedBox(height: 6),
              Row(
                children: [
                  const Icon(Icons.phone_outlined,
                      size: 14, color: AppColors.textSecondary),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      phone,
                      style: const TextStyle(
                        fontSize: 13,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ),
                ],
              ),
            ],
            if (email.isNotEmpty) ...[
              const SizedBox(height: 4),
              Row(
                children: [
                  const Icon(Icons.email_outlined,
                      size: 14, color: AppColors.textSecondary),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      email,
                      style: const TextStyle(
                        fontSize: 13,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildReviewsSection() {
    final rawReviews = widget.item['reviews'];
    final reviews = rawReviews is List
        ? rawReviews
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList()
        : <Map<String, dynamic>>[];
    final rating =
        _number(widget.item['rating'] ?? widget.item['averageRating']);
    final reviewCount =
        _number(widget.item['reviewCount'] ?? reviews.length)?.toInt();

    if (reviews.isEmpty && rating == null) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(6),
                  decoration: BoxDecoration(
                    color: AppColors.warningSoft,
                    borderRadius: BorderRadius.circular(AppRadii.small),
                  ),
                  child: const Icon(Icons.star_rounded,
                      size: 20, color: AppColors.warning),
                ),
                const SizedBox(width: AppSpacing.xs),
                Expanded(child: _heading('Traveller Reviews')),
                if (rating != null)
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: AppColors.warningSoft,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.star, size: 13, color: AppColors.warning),
                        const SizedBox(width: 3),
                        Text(
                          '${rating.toStringAsFixed(1)}${reviewCount != null ? ' ($reviewCount)' : ''}',
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            color: AppColors.warning,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            if (reviews.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              ...reviews.take(3).map((r) {
                final author = (r['author'] ??
                        r['userName'] ??
                        r['user'] ??
                        'Traveller')
                    .toString();
                final comment =
                    (r['comment'] ?? r['text'] ?? r['review'] ?? '').toString();
                final userRating = _number(r['rating']);
                return Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                  child: Container(
                    padding: const EdgeInsets.all(AppSpacing.xs),
                    decoration: BoxDecoration(
                      color: AppColors.surfaceElevated,
                      borderRadius: BorderRadius.circular(AppRadii.small),
                      border: Border.all(color: AppColors.divider),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            CircleAvatar(
                              radius: 12,
                              backgroundColor: AppColors.primarySoft,
                              child: Text(
                                author.isNotEmpty
                                    ? author[0].toUpperCase()
                                    : 'T',
                                style: const TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.bold,
                                  color: AppColors.primaryStrong,
                                ),
                              ),
                            ),
                            const SizedBox(width: AppSpacing.xs),
                            Expanded(
                              child: Text(
                                author,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                  fontSize: 13,
                                ),
                              ),
                            ),
                            if (userRating != null)
                              Row(
                                children: List.generate(
                                  5,
                                  (i) => Icon(
                                    i < userRating
                                        ? Icons.star
                                        : Icons.star_border,
                                    size: 13,
                                    color: AppColors.warning,
                                  ),
                                ),
                              ),
                          ],
                        ),
                        if (comment.isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.xxs),
                          PackageTextBlock(
                            text: comment,
                            style: const TextStyle(
                              fontSize: 12,
                              color: AppColors.textSecondary,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                );
              }),
            ],
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
    final shortDescription = _text('shortDescription');
    final cleanIntro =
        _cleanOverviewText(shortDescription.isEmpty ? description : shortDescription);
    final campaigns = (widget.item['activeCampaigns'] as List? ?? const [])
        .whereType<Map>()
        .map((entry) => Map<String, dynamic>.from(entry))
        .toList();
    final departureDates = _list(widget.item['departureDates']);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_text('operatorName').isNotEmpty)
          _buildOperatorCard(),
        if (cleanIntro.isNotEmpty)
          InkCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _heading('Package overview'),
                PackageTextBlock(
                  text: description.isEmpty ? cleanIntro : description,
                  preview: cleanIntro,
                  expandLabel: 'Read full description',
                  separateParagraphs: true,
                ),
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
                        PackageTextBlock(text: campaign['description'].toString()),
                      ],
                      if ((_number(campaign['discountValue']) ?? 0) > 0 && ['percentage','fixed'].contains(campaign['discountType']))
                        Text('${campaign['discountType'] == 'percentage' ? '${campaign['discountValue']}% off' : 'MYR ${campaign['discountValue']} off'} · ${campaign['startDate']} to ${campaign['endDate']}'),
                      if ((campaign['termsConditions'] ?? '').toString().isNotEmpty) ...[
                        const SizedBox(height: AppSpacing.xs),
                        PackageTextBlock(
                          text: campaign['termsConditions'].toString(),
                          expandLabel: 'Read full promotion terms',
                        ),
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
        _buildReviewsSection(),
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

    final displayedDays = _selectedItineraryDayIndex == null
        ? _days
        : (_selectedItineraryDayIndex! < _days.length
            ? [_days[_selectedItineraryDayIndex!]]
            : _days);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _heading('Day-by-day itinerary'),
        if (_days.length > 1) ...[
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                ChoiceChip(
                  label: const Text('All Days'),
                  selected: _selectedItineraryDayIndex == null,
                  onSelected: (_) =>
                      setState(() => _selectedItineraryDayIndex = null),
                ),
                const SizedBox(width: 6),
                ...List.generate(_days.length, (idx) {
                  final dayNum = _days[idx]['dayNumber'] ?? idx + 1;
                  return Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ChoiceChip(
                      label: Text('Day $dayNum'),
                      selected: _selectedItineraryDayIndex == idx,
                      onSelected: (_) =>
                          setState(() => _selectedItineraryDayIndex = idx),
                    ),
                  );
                }),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
        ...displayedDays.map((day) {
          final dayNumber = day['dayNumber'] ?? _days.indexOf(day) + 1;
          final activities = _extractActivities(day['activities']);
          final meals = _list(day['meals']);
          final title = (day['title'] ?? '').toString().trim();
          final description = (day['description'] ?? '').toString().trim();
          final stay = (day['accommodation'] ?? '').toString().trim();
          final transport = (day['transportNotes'] ?? '').toString().trim();
          final hasAnyTimes = activities.any((a) => (a['time'] ?? '').isNotEmpty);

          return Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: InkCard(
              child: ExpansionTile(
                key: PageStorageKey('package-day-$dayNumber'),
                initiallyExpanded: _days.length <= 3 && description.length <= 300 && activities.length <= 4,
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                title: Text(
                  title.isEmpty ? 'Day $dayNumber' : 'Day $dayNumber · $title',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                children: [
                  if (description.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.xxs),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: PackageTextBlock(
                        text: description,
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
                    const SizedBox(height: AppSpacing.xs),
                    ...List.generate(activities.length, (index) {
                      final act = activities[index];
                      final isLastActivity = index == activities.length - 1;
                      final time = act['time'];
                      final name = act['name'] ?? 'Activity';
                      final actDescription = act['description'];
                      final location = act['location'];
                      final image = act['image'];
                      final hasTime = time != null && time.isNotEmpty;

                      final leftWidth = hasAnyTimes ? 54.0 : 28.0;

                      return Stack(
                        children: [
                          if (!isLastActivity)
                            Positioned(
                              left: leftWidth + 8.0 + 4.0,
                              top: 14.0,
                              bottom: 0.0,
                              child: Container(
                                width: 2.0,
                                color: AppColors.divider,
                              ),
                            ),
                          Padding(
                            padding: EdgeInsets.only(
                                bottom: isLastActivity ? 4 : 12),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                // Left column: Time or Step Number
                                SizedBox(
                                  width: leftWidth,
                                  child: Padding(
                                    padding: const EdgeInsets.only(top: 2),
                                    child: Text(
                                      hasTime
                                          ? time
                                          : (!hasAnyTimes ? '${index + 1}' : ''),
                                      textAlign: TextAlign.right,
                                      style: TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                        color: hasTime
                                            ? AppColors.primaryStrong
                                            : AppColors.textSecondary,
                                      ),
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                // Timeline marker dot
                                Container(
                                  margin: const EdgeInsets.only(top: 4),
                                  width: 10,
                                  height: 10,
                                  decoration: BoxDecoration(
                                    shape: BoxShape.circle,
                                    color: hasTime
                                        ? AppColors.primary
                                        : AppColors.surface,
                                    border: Border.all(
                                      color: hasTime
                                          ? AppColors.primaryStrong
                                          : AppColors.divider,
                                      width: 2,
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 12),
                                // Right column: Activity details card
                                Expanded(
                                  child: Container(
                                    padding: const EdgeInsets.all(AppSpacing.xs),
                                    decoration: BoxDecoration(
                                      color: AppColors.surfaceElevated,
                                      borderRadius:
                                          BorderRadius.circular(AppRadii.small),
                                      border: Border.all(color: AppColors.divider),
                                    ),
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        // Bold activity title
                                        PackageTextBlock(
                                          text: name,
                                          collapsedLines: 2,
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w700,
                                            fontSize: 13.5,
                                            color: AppColors.textPrimary,
                                          ),
                                        ),
                                        if (location != null &&
                                            location.isNotEmpty) ...[
                                          const SizedBox(height: 3),
                                          Row(
                                            children: [
                                              const Icon(
                                                  Icons.location_on_outlined,
                                                  size: 13,
                                                  color:
                                                      AppColors.textSecondary),
                                              const SizedBox(width: 3),
                                              Expanded(
                                                child: Text(
                                                  location,
                                                  style: const TextStyle(
                                                    fontSize: 11.5,
                                                    color: AppColors
                                                        .textSecondary,
                                                  ),
                                                ),
                                              ),
                                            ],
                                          ),
                                        ],
                                        if (actDescription != null &&
                                            actDescription.isNotEmpty) ...[
                                          const SizedBox(height: 4),
                                          PackageTextBlock(
                                            text: actDescription,
                                            style: const TextStyle(
                                              fontSize: 12,
                                              color: AppColors.textSecondary,
                                              height: 1.4,
                                            ),
                                          ),
                                        ],
                                        if (image != null &&
                                            image.isNotEmpty) ...[
                                          const SizedBox(height: 6),
                                          ClipRRect(
                                            borderRadius:
                                                BorderRadius.circular(6),
                                            child: Image.network(
                                              image,
                                              height: 100,
                                              width: double.infinity,
                                              fit: BoxFit.cover,
                                              errorBuilder: (_, __, ___) =>
                                                  const SizedBox.shrink(),
                                            ),
                                          ),
                                        ],
                                      ],
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      );
                    }),
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
                          child: PackageTextBlock(
                            text: 'Meals: ${meals.join(', ')}',
                            collapsedLines: 3,
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
                          child: PackageTextBlock(
                            text: 'Stay: $stay',
                            collapsedLines: 3,
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
                          child: PackageTextBlock(
                            text: 'Transport: $transport',
                            collapsedLines: 3,
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
        if (widget.item['transportIncluded'] is bool)
          Text(widget.item['transportIncluded'] == true
              ? 'Operator-arranged transportation included'
              : 'Operator-arranged transportation not included'),
        if (widget.item['guideActivitiesIncluded'] is bool)
          Text(widget.item['guideActivitiesIncluded'] == true
              ? 'Guide / reserved activities included'
              : 'Guide / reserved activities not included'),
        _bullets('Transport', transport, Icons.directions_bus_outlined),
        _bullets('What to bring', widget.item['whatToBring'],
            Icons.backpack_outlined),
        _buildAccommodationSection(),
      ],
    );
  }

  Widget _buildAccommodationSection() {
    if (widget.item['accommodationIncluded'] == false) {
      return _bullets('Accommodation', ['Accommodation not included'],
          Icons.hotel_outlined);
    }
    final rawHotel = widget.item['accommodationHotel'] ??
        (widget.item['accommodation'] is Map
            ? (widget.item['accommodation'] as Map)['accommodationHotel']
            : null);
    final hotel = rawHotel is Map ? Map<String, dynamic>.from(rawHotel) : null;

    if (hotel != null) {
      final name = (hotel['name'] ?? _text('accommodationName')).toString().trim();
      final address = [
        hotel['address']?.toString().trim(),
        hotel['city']?.toString().trim(),
        hotel['country']?.toString().trim(),
      ].where((e) => e != null && e.isNotEmpty).join(', ');
      final rawStars = hotel['stars'];
      final starsText = rawStars != null
          ? '⭐ $rawStars-Star'
          : 'Star classification not supplied';
      final guestRating = hotel['guestRating'];
      final mainPhoto = (hotel['mainPhoto'] ??
              (hotel['imageUrls'] is List && (hotel['imageUrls'] as List).isNotEmpty
                  ? (hotel['imageUrls'] as List).first
                  : null))
          ?.toString()
          .trim();
      final amenities = (hotel['amenities'] is List
              ? (hotel['amenities'] as List)
                  .map((e) => e.toString().trim())
                  .where((e) => e.isNotEmpty)
                  .toList()
              : <String>[]);
      final roomType = _text('roomType');
      final notes = _text('accommodationNotes');

      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: InkCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.hotel_outlined, size: 18, color: AppColors.primary),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(child: _heading('Accommodation')),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: AppColors.successSoft,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Text(
                      'Hotel Information from LiteAPI',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: AppColors.success,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              if (mainPhoto != null && mainPhoto.isNotEmpty) ...[
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.network(
                    mainPhoto,
                    height: 140,
                    width: double.infinity,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
              ],
              Text(
                name.isNotEmpty ? name : 'Selected Hotel',
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textPrimary,
                ),
              ),
              if (address.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(
                  address,
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
              const SizedBox(height: 6),
              Row(
                children: [
                  Text(
                    starsText,
                    style: const TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                      color: AppColors.warning,
                    ),
                  ),
                  if (guestRating != null) ...[
                    const SizedBox(width: 12),
                    Text(
                      'Guest Rating: $guestRating/10',
                      style: const TextStyle(
                        fontSize: 12.5,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ],
              ),
              if (amenities.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: amenities.take(5).map((a) {
                    return Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: AppColors.surfaceElevated,
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: AppColors.divider),
                      ),
                      child: Text(
                        a,
                        style: const TextStyle(fontSize: 11, color: AppColors.textSecondary),
                      ),
                    );
                  }).toList(),
                ),
              ],
              if (roomType.isNotEmpty || notes.isNotEmpty) ...[
                const Divider(height: 20),
                if (roomType.isNotEmpty) ...[
                  Text(
                    'Room Configuration: $roomType',
                    style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w500),
                  ),
                  const SizedBox(height: 2),
                ],
                if (notes.isNotEmpty) ...[
                  Text(
                    notes,
                    style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                  ),
                ],
              ],
              const SizedBox(height: 8),
              const Text(
                'Hotel information is provided for package planning. Selecting a property does not create or confirm a room reservation.',
                style: TextStyle(
                  fontSize: 11,
                  fontStyle: FontStyle.italic,
                  color: AppColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
      );
    }

    return _textSection(
      'Accommodation',
      [
        _text('accommodationName'),
        _text('accommodationCategory'),
        _text('roomType'),
        _text('accommodationNotes'),
      ].where((value) => value.isNotEmpty).join('\n'),
      Icons.hotel_outlined,
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
                  Expanded(child: _heading('Booking arrangements')),
                ],
              ),
              const Text(
                academicPaymentDisclosure,
                style: TextStyle(fontSize: 13, height: 1.45),
              ),
              const SizedBox(height: AppSpacing.xs),
              const Text(
                'Reviewing dates and group prices does not create a supplier reservation or a Package Trip.',
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
              final isNarrow = constraints.maxWidth < 480 ||
                  MediaQuery.textScalerOf(context).scale(14) > 16;
              final priceColumn = Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$_currency ${_money(_groupTotal ?? _regularAdultPrice ?? 0)}',
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
          if ((widget.item['status'] ?? widget.item['approvalStatus']) ==
              'approved')
            const TravelStatusPill(
              text: 'Approved Package',
              icon: Icons.check_circle_outline,
            ),
          const SizedBox(height: AppSpacing.xs),
          PackageTextBlock(
            text: title.isEmpty ? 'Tourism package' : title,
            collapsedLines: 2,
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
                Text(_price, style: const TextStyle(fontWeight: FontWeight.w800)),
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
                  text: 'Automatic campaign offer',
                  icon: Icons.local_offer_outlined,
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
