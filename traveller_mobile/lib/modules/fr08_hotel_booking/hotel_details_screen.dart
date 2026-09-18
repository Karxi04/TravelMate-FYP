import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class HotelDetailsScreen extends StatelessWidget {
  final Map<String, dynamic> hotel;
  final VoidCallback onProceed;

  const HotelDetailsScreen({
    super.key,
    required this.hotel,
    required this.onProceed,
  });

  Widget row(String label, dynamic value, {IconData? icon}) {
    final text = (value ?? '').toString();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 19, color: InkWashColors.blueGrey),
            const SizedBox(width: 9),
          ],
          SizedBox(width: 110, child: Text(label, style: const TextStyle(color: InkWashColors.mutedInk))),
          Expanded(child: Text(text.isEmpty ? 'Not provided' : text, style: const TextStyle(fontWeight: FontWeight.w700))),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final amenities = (hotel['amenities'] as List? ?? []).map((e) => e.toString()).toList();
    final rules = (hotel['houseRules'] as List? ?? []).map((e) => e.toString()).toList();

    return Scaffold(
      appBar: AppBar(title: const Text('Hotel details')),
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
          decoration: const BoxDecoration(color: Colors.white, border: Border(top: BorderSide(color: Color(0xFFE7E7E2)))),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Stay price', style: TextStyle(color: InkWashColors.mutedInk, fontSize: 12)),
                    Text('${hotel['currency'] ?? 'MYR'} ${hotel['price'] ?? '-'}', style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w900)),
                  ],
                ),
              ),
              FilledButton.icon(onPressed: onProceed, icon: const Icon(Icons.hotel_class_outlined), label: const Text('Continue')),
            ],
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 100),
        children: [
          InkCard(
            color: InkWashColors.cream,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text((hotel['name'] ?? 'Hotel').toString(), style: const TextStyle(fontSize: 23, fontWeight: FontWeight.w900)),
                const SizedBox(height: 5),
                Text((hotel['address'] ?? '').toString(), style: const TextStyle(color: InkWashColors.mutedInk)),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    TravelStatusPill(text: 'Rating ${hotel['rating'] ?? '-'}', icon: Icons.star_rounded),
                    TravelStatusPill(text: '${hotel['stars'] ?? '-'} stars', icon: Icons.hotel_class_outlined),
                    TravelStatusPill(text: hotel['refundable'] == true ? 'Refundable' : 'Non-refundable', icon: Icons.policy_outlined),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'About this stay'),
          const SizedBox(height: 8),
          InkCard(child: Text((hotel['description'] ?? 'Hotel information is available for the selected offer.').toString())),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Room & stay details'),
          const SizedBox(height: 8),
          InkCard(
            child: Column(
              children: [
                row('Room', hotel['roomName'], icon: Icons.bed_outlined),
                row('Bed', hotel['bedType'], icon: Icons.king_bed_outlined),
                row('Room size', hotel['roomSize'], icon: Icons.square_foot_rounded),
                row('Board', hotel['boardName'], icon: Icons.restaurant_outlined),
                row('Check-in', '${hotel['checkin'] ?? ''} • ${hotel['checkInTime'] ?? ''}', icon: Icons.login_rounded),
                row('Check-out', '${hotel['checkout'] ?? ''} • ${hotel['checkOutTime'] ?? ''}', icon: Icons.logout_rounded),
                row('Taxes & fees', hotel['taxesAndFeesIncluded'] == true ? 'Included in shown price' : 'Check final offer', icon: Icons.receipt_long_outlined),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Amenities'),
          const SizedBox(height: 8),
          InkCard(
            child: amenities.isEmpty
                ? const Text('Amenity information is not provided for this offer.')
                : Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: amenities.map((a) => Chip(avatar: const Icon(Icons.check_circle_outline_rounded, size: 17), label: Text(a))).toList(),
                  ),
          ),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Cancellation & house rules'),
          const SizedBox(height: 8),
          InkCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text((hotel['cancellationPolicy'] ?? 'Check the selected offer conditions before confirming.').toString(), style: const TextStyle(fontWeight: FontWeight.w700)),
                if (rules.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  ...rules.map((r) => Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [const Text('•  '), Expanded(child: Text(r))]),
                      )),
                ],
              ],
            ),
          ),
          const SizedBox(height: 18),
          InkCard(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.info_outline_rounded, color: InkWashColors.blueGrey),
                const SizedBox(width: 10),
                Expanded(child: Text('Hotel availability, cancellation deadlines and final conditions should be checked again before completing an external provider booking.', style: const TextStyle(color: InkWashColors.charcoal))),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
