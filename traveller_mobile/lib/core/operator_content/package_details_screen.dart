import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class TourismPackageDetailsScreen extends StatelessWidget {
  final Map<String, dynamic> item;
  final VoidCallback? onAddToTrip;

  const TourismPackageDetailsScreen({
    super.key,
    required this.item,
    this.onAddToTrip,
  });

  String _text(String primary, [String? legacy]) =>
      (item[primary] ?? (legacy == null ? null : item[legacy]) ?? '')
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
      (item['itineraryDays'] as List? ?? const [])
          .whereType<Map>()
          .map((day) => Map<String, dynamic>.from(day))
          .toList();

  String get _currency => _text('currency').isEmpty ? 'MYR' : _text('currency');

  num? _number(dynamic value) =>
      value is num ? value : num.tryParse(value?.toString() ?? '');

  String _money(num value) => value == value.roundToDouble()
      ? value.toStringAsFixed(0)
      : value.toStringAsFixed(2);

  String get _price {
    final amount = _number(item['promotionalPrice']) ??
        _number(item['adultPrice']) ??
        _number(item['price']);
    if (amount == null) return '';
    final basis = item['priceBasis'] == 'per_group' ? 'group' : 'person';
    return '$_currency ${_money(amount)} / $basis';
  }

  String get _duration {
    final days = _number(item['durationDays']);
    if (days == null || days < 1) return '';
    final nights = _number(item['durationNights']);
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
    final campaigns = (item['activeCampaigns'] as List? ?? const [])
        .whereType<Map>()
        .map((entry) => Map<String, dynamic>.from(entry))
        .toList();
    final capacity =
        _number(item['maximumTravellers'] ?? item['maxTravellers']);
    final departureDates = _list(item['departureDates']);
    final transport = _list(item['transportTypes']);
    final meals = _days.expand((day) => _list(day['meals'])).toSet().toList();
    final original = _number(item['originalPrice']);
    final promo = _number(item['promotionalPrice']);

    return Scaffold(
      appBar: AppBar(title: const Text('Tourism package')),
      bottomNavigationBar: onAddToTrip == null
          ? null
          : SafeArea(
              minimum: const EdgeInsets.all(AppSpacing.md),
              child: FilledButton.icon(
                onPressed: onAddToTrip,
                icon: const Icon(Icons.add_location_alt_outlined),
                label: const Text('Add package to trip'),
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
            if (_duration.isNotEmpty)
              TravelStatusPill(
                  text: _duration, icon: Icons.calendar_today_outlined),
            if (capacity != null)
              TravelStatusPill(
                  text: 'Up to ${capacity.toInt()} travellers',
                  icon: Icons.group_outlined),
          ]),
          if (original != null && promo != null && original > promo) ...[
            const SizedBox(height: AppSpacing.xs),
            Text('Usual price $_currency ${_money(original)}',
                style: const TextStyle(
                    color: AppColors.textSecondary,
                    decoration: TextDecoration.lineThrough)),
          ],
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
          _bullets('Highlights', item['highlights'], Icons.place_outlined),
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
          _bullets('What is included', item['inclusions'],
              Icons.check_circle_outline),
          _bullets(
              'Not included', item['exclusions'], Icons.remove_circle_outline),
          _bullets('Meals', meals, Icons.restaurant_outlined),
          _bullets('Transport', transport, Icons.directions_bus_outlined),
          _bullets(
              'What to bring', item['whatToBring'], Icons.backpack_outlined),
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
