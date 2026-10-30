import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'hotel_description.dart';

class HotelDetailsScreen extends StatelessWidget {
  final Map<String, dynamic> hotel;
  final VoidCallback? onProceed;

  const HotelDetailsScreen({
    super.key,
    required this.hotel,
    this.onProceed,
  });

  Widget row(String label, dynamic value, {IconData? icon}) {
    final text = (value ?? '').toString();
    if (text.trim().isEmpty || text == '-') return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 19, color: InkWashColors.blueGrey),
            const SizedBox(width: 9),
          ],
          SizedBox(
              width: 110,
              child: Text(label,
                  style: const TextStyle(color: InkWashColors.mutedInk))),
          Expanded(
              child: Text(text,
                  style: const TextStyle(fontWeight: FontWeight.w700))),
        ],
      ),
    );
  }

  String stayDate(dynamic date, dynamic time) {
    final values = [date, time]
        .map((value) => (value ?? '').toString().trim())
        .where((value) => value.isNotEmpty && value != '-')
        .toList();
    return values.isEmpty ? 'Not provided' : values.join(' • ');
  }

  @override
  Widget build(BuildContext context) {
    final amenities =
        (hotel['amenities'] as List? ?? []).map((e) => e.toString()).toList();
    final rules =
        (hotel['houseRules'] as List? ?? []).map((e) => e.toString()).toList();
    final currency = (hotel['currency'] ?? 'Unknown currency').toString();
    final price = hotel['priceStatus'] == 'available'
        ? '${hotel['price'] ?? '-'}'
        : 'Unavailable';
    final priceBasis = (hotel['priceBasis'] ?? '').toString();
    final fees = (hotel['taxesAndFeesStatus'] ?? '').toString();
    final cancellation = hotel['cancellation'] is Map
        ? Map<String, dynamic>.from(hotel['cancellation'] as Map)
        : <String, dynamic>{};
    final cancellationDeadline = cancellation['deadline']?.toString().trim() ?? '';
    final cancellationPenalties = (cancellation['penalties'] as List? ?? [])
        .map((value) => value.toString())
        .where((value) => value.isNotEmpty)
        .join(' • ');
    final images = <String>{
      (hotel['mainPhoto'] ?? hotel['main_photo'] ?? '').toString(),
      ...(hotel['imageUrls'] as List? ?? []).map((e) => e.toString()),
    }.where((e) => e.isNotEmpty && (e.startsWith('http://') || e.startsWith('https://'))).take(6).toList();
    final roomImages = (hotel['roomImageUrls'] as List? ?? [])
        .map((e) => e.toString())
        .where((e) => e.isNotEmpty)
        .take(6)
        .toList();
    final roomAmenities = (hotel['roomAmenities'] as List? ?? [])
        .map((e) => e.toString())
        .toList();
    final descriptionStyle =
        Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: InkWashColors.ink,
                  height: 1.5,
                  decoration: TextDecoration.none,
                  decorationColor: Colors.transparent,
                  backgroundColor: Colors.transparent,
                ) ??
            const TextStyle(color: InkWashColors.ink, height: 1.5);

    return Scaffold(
      appBar: AppBar(title: const Text('Hotel details')),
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
          decoration: const BoxDecoration(
              color: Colors.white,
              border: Border(top: BorderSide(color: Color(0xFFE7E7E2)))),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Stay price',
                        style: TextStyle(
                            color: InkWashColors.mutedInk, fontSize: 12)),
                    Text('$currency $price',
                        style: const TextStyle(
                            fontSize: 21, fontWeight: FontWeight.w900)),
                  ],
                ),
              ),
              if (onProceed != null) FilledButton.icon(
                  onPressed: onProceed,
                  icon: const Icon(Icons.hotel_class_outlined),
                  label: const Text('Select room')),
            ],
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 100),
        children: [
          if (images.isNotEmpty) ...[
            SizedBox(
              height: 180,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: images.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (_, index) => ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: Image.network(
                    images[index],
                    width: 260,
                    fit: BoxFit.cover,
                    loadingBuilder: (ctx, child, progress) {
                      if (progress == null) return child;
                      return Container(
                        width: 260,
                        color: InkWashColors.cream,
                        alignment: Alignment.center,
                        child: const SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      );
                    },
                    errorBuilder: (_, __, ___) => Container(
                      width: 260,
                      color: InkWashColors.cream,
                      alignment: Alignment.center,
                      child: const Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.hotel_outlined, size: 42, color: InkWashColors.blueGrey),
                          SizedBox(height: 4),
                          Text('Photo unavailable', style: TextStyle(fontSize: 12, color: InkWashColors.mutedInk)),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 14),
          ],
          InkCard(
            color: InkWashColors.cream,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text((hotel['name'] ?? 'Hotel').toString(),
                    style: const TextStyle(
                        fontSize: 23, fontWeight: FontWeight.w900)),
                const SizedBox(height: 5),
                Text((hotel['address'] ?? '').toString(),
                    style: const TextStyle(color: InkWashColors.mutedInk)),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    TravelStatusPill(
                        text: 'Rating ${hotel['rating'] ?? '-'}',
                        icon: Icons.star_rounded),
                    TravelStatusPill(
                        text: '${hotel['stars'] ?? '-'} stars',
                        icon: Icons.hotel_class_outlined),
                    TravelStatusPill(
                        text: hotel['refundable'] == true
                            ? 'Refundable'
                            : hotel['refundable'] == false
                                ? 'Non-refundable'
                                : 'Refund terms unavailable',
                        icon: Icons.policy_outlined),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'About this stay'),
          const SizedBox(height: 8),
          InkCard(
              child: RichText(
                  text: TextSpan(
                      style: descriptionStyle,
                      children: HotelDescription.spans((hotel['description'] ??
                              'Hotel information is available for the selected offer.')
                          .toString(),
                          bodyStyle: descriptionStyle)))),
          if (hotel['_allOffers'] is List && (hotel['_allOffers'] as List).length > 1) ...[
            const SizedBox(height: 18),
            const TravelSectionHeader(title: 'Available room types'),
            const SizedBox(height: 8),
            InkCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('${(hotel['_allOffers'] as List).length} room options offered by this property:',
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: InkWashColors.blueGrey)),
                  const SizedBox(height: 8),
                  ...((hotel['_allOffers'] as List).whereType<Map>()).map((off) {
                    final isCurrent = off['offerId'] == hotel['offerId'];
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        children: [
                          Icon(isCurrent ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded,
                              size: 16, color: isCurrent ? AppColors.success : InkWashColors.blueGrey),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              '${off['roomName'] ?? 'Room'}: ${off['currency'] ?? 'MYR'} ${off['price'] ?? '-'}',
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: isCurrent ? FontWeight.w800 : FontWeight.w500,
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  }),
                ],
              ),
            ),
          ],
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Room & stay details'),
          const SizedBox(height: 8),
          InkCard(
            child: Column(
              children: [
                row('Room', hotel['roomName'], icon: Icons.bed_outlined),
                row('Bed', hotel['bedType'], icon: Icons.king_bed_outlined),
                row('Room size', hotel['roomSize'],
                    icon: Icons.square_foot_rounded),
                row('Maximum guests', hotel['maxOccupancy'],
                    icon: Icons.people_outline_rounded),
                row('Board', hotel['boardName'],
                    icon: Icons.restaurant_outlined),
                row('Check-in', stayDate(hotel['checkin'], hotel['checkInTime']),
                    icon: Icons.login_rounded),
                row('Check-out', stayDate(hotel['checkout'], hotel['checkOutTime']),
                    icon: Icons.logout_rounded),
                row(
                    'Price basis',
                    priceBasis == 'stay_total'
                        ? 'Total stay'
                        : priceBasis == 'per_room_night'
                            ? 'Per room/night'
                            : 'Unknown',
                    icon: Icons.calculate_outlined),
                row(
                    'Taxes & fees',
                    fees == 'included' || hotel['taxesAndFeesIncluded'] == true
                        ? 'Included in shown price'
                        : fees == 'excluded'
                            ? 'Excluded from shown price'
                            : 'Not confirmed',
                    icon: Icons.receipt_long_outlined),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Selected room photos'),
          const SizedBox(height: 8),
          if (roomImages.isEmpty)
            const InkCard(
                child: Text('Room photos unavailable from this provider offer.'))
          else
            SizedBox(
              height: 170,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: roomImages.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (_, index) => ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: Image.network(roomImages[index], width: 240, fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => Container(width: 240, color: InkWashColors.cream,
                          alignment: Alignment.center, child: const Icon(Icons.bed_outlined, size: 40))),
                ),
              ),
            ),
          if (roomAmenities.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Room facilities: ${roomAmenities.join(' • ')}'),
          ],
          const SizedBox(height: 18),
          const TravelPreparationGuide(service: 'Hotel'),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Amenities'),
          const SizedBox(height: 8),
          InkCard(
            child: amenities.isEmpty
                ? const Text(
                    'Amenity information is not provided for this offer.')
                : Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: amenities
                        .map((a) => Chip(
                            avatar: const Icon(
                                Icons.check_circle_outline_rounded,
                                size: 17),
                            label: Text(a)))
                        .toList(),
                  ),
          ),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Cancellation & house rules'),
          const SizedBox(height: 8),
          InkCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                    (cancellation['status'] == 'known' ||
                                hotel['cancellationPolicy'] != null
                            ? (hotel['cancellationPolicy'] ??
                                cancellation['tag'] ??
                                'See offer conditions')
                            : 'Cancellation terms are not confirmed for this offer.')
                        .toString(),
                    style: const TextStyle(fontWeight: FontWeight.w700)),
                if (cancellationDeadline.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text('Free-cancellation deadline: $cancellationDeadline'),
                ],
                if (cancellationPenalties.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text('Penalty details: $cancellationPenalties'),
                ],
                if (rules.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  ...rules.map((r) => Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text('•  '),
                              Expanded(child: Text(r))
                            ]),
                      )),
                ],
              ],
            ),
          ),
          if (hotel['latitude'] != null && hotel['longitude'] != null) ...[
            const SizedBox(height: 18),
            OutlinedButton.icon(
              onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                    content: Text(
                        'Map coordinates: ${hotel['latitude']}, ${hotel['longitude']}')),
              ),
              icon: const Icon(Icons.map_outlined),
              label: const Text('View property location'),
            ),
          ],
          const SizedBox(height: 18),
          InkCard(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.info_outline_rounded,
                    color: InkWashColors.blueGrey),
                const SizedBox(width: 10),
                Expanded(
                    child: Text(
                        'Hotel availability, cancellation deadlines and final conditions should be checked again before completing an external provider booking.',
                        style: const TextStyle(color: InkWashColors.charcoal))),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
