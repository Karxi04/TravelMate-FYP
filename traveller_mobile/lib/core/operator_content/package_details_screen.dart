import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../modules/fr09_payment/payment_screen.dart';

class TourismPackageDetailsScreen extends StatefulWidget {
  final Map<String, dynamic> item;
  /// Retained for callers with the legacy add-to-trip callback.
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

class _TourismPackageDetailsScreenState extends State<TourismPackageDetailsScreen> {
  late final ApiService api;
  bool submitting = false;
  int adults = 1;
  int children = 0;
  String? selectedDepartureDate;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    adults = 1;
    children = 0;
    final dates = _list(widget.item['departureDates']);
    if (dates.length == 1) selectedDepartureDate = dates.first;
  }

  Future<void> _startCheckout() async {
    if (submitting) return;
    setState(() => submitting = true);
    try {
      final packageId = (widget.item['id'] ?? '').toString();
      if (packageId.isEmpty) throw Exception('This package is unavailable for checkout.');
      if (!_hasVerifiedPriceBasis) {
        throw Exception('Package pricing basis is not verified. Please contact the operator.');
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
      final scopeDate = selectedDepartureDate ?? 'open';
      final response = await api.post('/api/fr15/package-checkout-attempts', {
        'packageId': packageId,
        'participants': {'adults': adults, 'children': children},
        if (selectedDepartureDate != null) 'departureDate': selectedDepartureDate,
        'idempotencyKey': 'package_${packageId}_${adults}_${children}_$scopeDate',
      });
      final attempt = response is Map && response['attempt'] is Map
          ? Map<String, dynamic>.from(response['attempt'] as Map)
          : <String, dynamic>{};
      final attemptId = (attempt['id'] ?? '').toString();
      if (attemptId.isEmpty) throw Exception('Package checkout could not be prepared.');

      // Server-authoritative quote matching and tamper protection
      final serverAmount = _number(attempt['amount'])?.toDouble();
      if (serverAmount == null) {
        throw Exception('Server did not return an authoritative payable total.');
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
          content: Text('After verified payment, your new Package Trip will appear under Trips.'),
        ));
      }
    } catch (error) {
      if (mounted) showError(context, error);
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
      _number(widget.item['maximumTravellers'] ?? widget.item['maxTravellers'])?.toInt();

  int get _minimumTravellers =>
      (_number(widget.item['minimumTravellers'])?.toInt() ?? 1).clamp(1, 50).toInt();

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

  Widget _participantCounter(String label, int value, VoidCallback? subtract,
      VoidCallback? add, String keyName) {
    return Expanded(
      child: Semantics(
        label: '$label count $value',
        child: Row(children: [
          Expanded(child: Text('$label: $value', style: const TextStyle(fontWeight: FontWeight.w700))),
          IconButton(key: ValueKey('$keyName-remove'), onPressed: subtract, icon: const Icon(Icons.remove_circle_outline)),
          IconButton(key: ValueKey('$keyName-add'), onPressed: add, icon: const Icon(Icons.add_circle_outline)),
        ]),
      ),
    );
  }

  String get _duration {
    final days = _number(widget.item['durationDays']);
    if (days == null || days < 1) return '';
    final nights = _number(widget.item['durationNights']);
    final dayText = '${days.toInt()} ${days == 1 ? 'day' : 'days'}';
    if (nights == null) return dayText;
    return '$dayText · ${nights.toInt()} ${nights == 1 ? 'night' : 'nights'}';
  }

  Widget _heading(String title) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.sm),
        child: Text(title,
            style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w900)),
      );

  Widget _bullets(String title, dynamic value, IconData icon) {
    final values = _list(value);
    if (values.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: InkCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _heading(title),
            ...values.map((entry) => Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(icon, size: 18, color: InkWashColors.blueGrey),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(child: Text(entry)),
                    ],
                  ),
                )),
          ],
        ),
      ),
    );
  }

  Widget _textSection(String title, String value, IconData icon) {
    if (value.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: InkCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(icon, color: InkWashColors.blueGrey),
            const SizedBox(width: AppSpacing.xs),
            Expanded(child: _heading(title)),
          ]),
          Text(value),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final title = _text('title', 'packageTitle');
    final destination = _text('destination', 'destinationName');
    final hero = _text('heroImage', 'imageUrl');
    final description = _text('fullDescription', 'description');
    final campaigns = (widget.item['activeCampaigns'] as List? ?? const [])
        .whereType<Map>()
        .map((entry) => Map<String, dynamic>.from(entry))
        .toList();
    final capacity =
        _number(widget.item['maximumTravellers'] ?? widget.item['maxTravellers']);
    final departureDates = _list(widget.item['departureDates']);
    final transport = _list(widget.item['transportTypes']);
    final meals = _days.expand((day) => _list(day['meals'])).toSet().toList();
    final canAddParticipant =
        _maximumTravellers == null || adults + children < _maximumTravellers!;
    final canAddChild = canAddParticipant && _childPrice != null;

    return Scaffold(
      appBar: AppBar(title: const Text('Tourism package')),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.all(AppSpacing.md),
        child: FilledButton.icon(
          onPressed: (submitting || !_hasVerifiedPriceBasis) ? null : _startCheckout,
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
      body: ListView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.sm,
          AppSpacing.lg,
          AppSpacing.xxl,
        ),
        children: [
          TravelPlaceImage(
            place: {
              'title': title.isEmpty ? destination : title,
              'imageUrl': hero,
              'category': 'Travel package',
            },
            height: 230,
            width: double.infinity,
            borderRadius: BorderRadius.circular(AppRadii.large),
          ),
          const SizedBox(height: AppSpacing.md),
          const TravelStatusPill(
            text: 'VERIFIED OPERATOR PACKAGE',
            icon: Icons.verified_outlined,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            title.isEmpty ? 'Tourism package' : title,
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          if (destination.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(destination,
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                      color: AppColors.textSecondary,
                    )),
          ],
          const SizedBox(height: AppSpacing.sm),
          Wrap(spacing: AppSpacing.xs, runSpacing: AppSpacing.xs, children: [
            if (_price.isNotEmpty)
              TravelStatusPill(text: _price, icon: Icons.payments_outlined),
            if (_priceBasis == 'per_person' && _childPrice != null)
              TravelStatusPill(
                text: '$_currency ${_money(_childPrice!)} / child',
                icon: Icons.child_care_outlined,
              ),
            if (_priceBasis == 'per_person' && _childPrice == null && _regularAdultPrice != null)
              const TravelStatusPill(
                text: 'Child rate unavailable',
                icon: Icons.info_outline,
              ),
            if (_hasVerifiedPriceBasis)
              TravelStatusPill(
                text: _priceBasis == 'per_group' ? 'Fixed group pricing' : 'Per person pricing',
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
            if (_originalPrice != null && _originalPrice! > (_effectiveAdultPrice ?? 0))
              TravelStatusPill(
                text: 'Orig. $_currency ${_money(_originalPrice!)}',
                icon: Icons.history_outlined,
              ),
            if (_duration.isNotEmpty)
              TravelStatusPill(
                  text: _duration, icon: Icons.calendar_today_outlined),
            if (capacity != null)
              TravelStatusPill(
                  text: 'Up to ${capacity.toInt()} travellers',
                  icon: Icons.group_outlined),
          ]),
          const SizedBox(height: AppSpacing.lg),
          InkCard(
            key: const ValueKey('package-group-booking'),
            color: InkWashColors.cream,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _heading('Your group'),
              Text(_priceBasis == 'per_group'
                  ? 'This is a fixed group price within the package capacity.'
                  : !_hasVerifiedPriceBasis
                      ? 'Pricing basis is not verified for this package. Checkout is disabled.'
                      : _childPrice == null
                          ? 'Adult pricing is available. Child rate unavailable.'
                          : 'Adults: $_currency ${_money(_effectiveAdultPrice!)} · Children: $_currency ${_money(_childPrice!)}'),
              if (_minimumTravellers > 1) ...[
                const SizedBox(height: AppSpacing.xs),
                Text(
                  'Minimum requirement: $_minimumTravellers travellers',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: adults + children < _minimumTravellers
                        ? AppColors.warning
                        : AppColors.textSecondary,
                  ),
                ),
              ],
              const SizedBox(height: AppSpacing.sm),
              Row(children: [
                _participantCounter(
                  'Adults',
                  adults,
                  adults > 1 ? () => setState(() => adults -= 1) : null,
                  canAddParticipant ? () => setState(() => adults += 1) : null,
                  'package-adults',
                ),
              ]),
              Row(children: [
                _participantCounter(
                  'Children',
                  children,
                  children > 0 ? () => setState(() => children -= 1) : null,
                  canAddChild ? () => setState(() => children += 1) : null,
                  'package-children',
                ),
              ]),
              if (_priceBasis == 'per_person' && _childPrice == null)
                const Padding(
                  padding: EdgeInsets.only(top: AppSpacing.xxs),
                  child: Text(
                    'Child rate unavailable — children cannot be added to this booking.',
                    style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
                  ),
                ),
              if (adults + children < _minimumTravellers) ...[
                const SizedBox(height: AppSpacing.sm),
                Container(
                  padding: const EdgeInsets.all(AppSpacing.sm),
                  decoration: BoxDecoration(
                    color: AppColors.warningSoft,
                    borderRadius: BorderRadius.circular(AppRadii.small),
                    border: Border.all(color: AppColors.warning),
                  ),
                  child: Row(children: [
                    const Icon(Icons.info_outline, size: 18, color: AppColors.warning),
                    const SizedBox(width: AppSpacing.xs),
                    Expanded(
                      child: Text(
                        'Minimum group size: $_minimumTravellers travellers required (currently ${adults + children}).',
                        style: const TextStyle(fontWeight: FontWeight.w600, color: InkWashColors.ink),
                      ),
                    ),
                  ]),
                ),
              ],
              if (_departureDates.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.sm),
                DropdownButtonFormField<String>(
                  key: const ValueKey('package-departure-date'),
                  initialValue: selectedDepartureDate,
                  decoration: const InputDecoration(labelText: 'Departure date'),
                  items: _departureDates
                      .map((value) => DropdownMenuItem(value: value, child: Text(value)))
                      .toList(),
                  onChanged: (value) => setState(() => selectedDepartureDate = value),
                ),
              ],
              const Divider(height: AppSpacing.lg),
              if (_hasVerifiedPriceBasis && _groupTotal != null) ...[
                if (_priceBasis == 'per_person')
                  Text(
                    '$adults Adult${adults > 1 ? 's' : ''} × $_currency ${_money(_effectiveAdultPrice!)}'
                    '${children > 0 && _childPrice != null ? ' + $children Child${children > 1 ? 'ren' : ''} × $_currency ${_money(_childPrice!)}' : ''}',
                    style: const TextStyle(fontSize: 13, color: AppColors.textSecondary),
                  ),
                if (_calculatedSavings != null) ...[
                  const SizedBox(height: AppSpacing.xxs),
                  Text(
                    'Promotional savings: $_currency ${_money(_calculatedSavings!)}',
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.success),
                  ),
                ],
                const SizedBox(height: AppSpacing.xs),
              ],
              Text(
                _groupTotal == null
                    ? 'Group total unavailable'
                    : 'Group total: $_currency ${_money(_groupTotal!)}',
                key: const ValueKey('package-group-total'),
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: AppSpacing.xs),
              const Text('One signed-in traveller pays for the complete group. Stripe Checkout remains in Test Mode.'),
              const SizedBox(height: AppSpacing.xs),
              const Text('Verified payment creates a new independent Package Trip; existing personal Trips are not changed.'),
            ]),
          ),
          if (description.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.lg),
            InkCard(
              color: InkWashColors.cream,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _heading('Package overview'),
                    Text(description),
                  ]),
            ),
          ],
          if (campaigns.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.lg),
            _heading('Current promotion'),
            ...campaigns.map((campaign) => Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: InkCard(
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                              (campaign['campaignTitle'] ?? 'Promotion')
                                  .toString(),
                              style:
                                  const TextStyle(fontWeight: FontWeight.w900)),
                          if ((campaign['description'] ?? '')
                              .toString()
                              .trim()
                              .isNotEmpty)
                            Text(campaign['description'].toString()),
                          if ((campaign['promoCode'] ?? '')
                              .toString()
                              .trim()
                              .isNotEmpty)
                            TravelStatusPill(
                                text: 'Code ${campaign['promoCode']}',
                                icon: Icons.local_offer_outlined),
                        ]),
                  ),
                )),
          ],
          const SizedBox(height: AppSpacing.lg),
          _bullets('Highlights', widget.item['highlights'], Icons.place_outlined),
          if (_days.isNotEmpty) ...[
            _heading('Day-by-day itinerary'),
            ..._days.map((day) {
              final dayNumber = day['dayNumber'] ?? _days.indexOf(day) + 1;
              final activities = _list(day['activities']);
              return Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: InkCard(
                  child: ExpansionTile(
                    tilePadding: EdgeInsets.zero,
                    childrenPadding: EdgeInsets.zero,
                    title: Text('Day $dayNumber · ${day['title'] ?? ''}',
                        style: const TextStyle(fontWeight: FontWeight.w900)),
                    children: [
                      if ((day['description'] ?? '')
                          .toString()
                          .trim()
                          .isNotEmpty)
                        Align(
                            alignment: Alignment.centerLeft,
                            child: Text(day['description'].toString())),
                      if (activities.isNotEmpty)
                        Padding(
                            padding: const EdgeInsets.only(top: AppSpacing.sm),
                            child: Align(
                                alignment: Alignment.centerLeft,
                                child: Text(
                                    'Activities: ${activities.join(', ')}'))),
                      if (_list(day['meals']).isNotEmpty)
                        Align(
                            alignment: Alignment.centerLeft,
                            child: Text(
                                'Meals: ${_list(day['meals']).join(', ')}')),
                      if ((day['accommodation'] ?? '')
                          .toString()
                          .trim()
                          .isNotEmpty)
                        Align(
                            alignment: Alignment.centerLeft,
                            child: Text('Stay: ${day['accommodation']}')),
                      if ((day['transportNotes'] ?? '')
                          .toString()
                          .trim()
                          .isNotEmpty)
                        Align(
                            alignment: Alignment.centerLeft,
                            child: Text('Transport: ${day['transportNotes']}')),
                    ],
                  ),
                ),
              );
            }),
          ],
          _bullets('What is included', widget.item['inclusions'],
              Icons.check_circle_outline),
          _bullets(
              'Not included', widget.item['exclusions'], Icons.remove_circle_outline),
          _bullets('Meals', meals, Icons.restaurant_outlined),
          _bullets('Transport', transport, Icons.directions_bus_outlined),
          _bullets(
              'What to bring', widget.item['whatToBring'], Icons.backpack_outlined),
          _textSection(
              'Accommodation',
              [
                _text('accommodationName'),
                _text('accommodationCategory'),
                _text('roomType'),
                _text('accommodationNotes'),
              ].where((value) => value.isNotEmpty).join('\n'),
              Icons.hotel_outlined),
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
                  if (_text('departureNotes').isNotEmpty)
                    _text('departureNotes'),
                ].join('\n'),
                Icons.event_available_outlined),
          _textSection('Cancellation policy', _text('cancellationPolicy'),
              Icons.event_busy_outlined),
          _textSection('Refund policy', _text('refundPolicy'),
              Icons.currency_exchange_outlined),
          _textSection('Booking terms', _text('bookingTerms'),
              Icons.description_outlined),
          _textSection(
              'Important notes', _text('importantNotes'), Icons.info_outline),
          if (_text('operatorName').isNotEmpty)
            _textSection(
                'Tourism Operator',
                [
                  _text('operatorName'),
                  _text('operatorPhone'),
                  _text('operatorEmail'),
                ].where((value) => value.isNotEmpty).join('\n'),
                Icons.storefront_outlined),
        ],
      ),
    );
  }
}
