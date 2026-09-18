import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class TourismPackageDetailsScreen extends StatelessWidget {
  final Map<String, dynamic> item;
  final VoidCallback? onAddToTrip;

  const TourismPackageDetailsScreen({super.key, required this.item, this.onAddToTrip});

  List<String> _list(dynamic value) {
    if (value is List) return value.map((e) => e.toString()).where((e) => e.trim().isNotEmpty).toList();
    return value.toString().split(RegExp(r'\r?\n|,')).map((e) => e.trim()).where((e) => e.isNotEmpty).toList();
  }

  Widget _bullets(String title, dynamic value, IconData icon) {
    final items = _list(value ?? '');
    if (items.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
        const SizedBox(height: 8),
        ...items.map((x) => Padding(
          padding: const EdgeInsets.only(bottom: 7),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(icon, size: 18, color: InkWashColors.blueGrey),
            const SizedBox(width: 8),
            Expanded(child: Text(x)),
          ]),
        )),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final campaigns = (item['activeCampaigns'] as List? ?? []).whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Tourism package')),
      bottomNavigationBar: onAddToTrip == null ? null : SafeArea(
        minimum: const EdgeInsets.all(14),
        child: FilledButton.icon(onPressed: onAddToTrip, icon: const Icon(Icons.add_location_alt_outlined), label: const Text('Add package to trip')),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
        children: [
          TravelPlaceImage(place: {
            'title': item['packageTitle'] ?? item['destinationName'] ?? 'Tourism package',
            'imageUrl': item['imageUrl'] ?? item['bannerImageUrl'] ?? '',
            'category': 'Tourism package',
          }, height: 230, width: double.infinity, borderRadius: BorderRadius.circular(22)),
          const SizedBox(height: 16),
          const TravelStatusPill(text: 'APPROVED TOURISM PACKAGE', icon: Icons.verified_outlined),
          const SizedBox(height: 10),
          Text((item['packageTitle'] ?? 'Tourism package').toString(), style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900)),
          const SizedBox(height: 5),
          Text((item['destinationName'] ?? '').toString(), style: const TextStyle(color: InkWashColors.mutedInk, fontSize: 15)),
          const SizedBox(height: 12),
          Wrap(spacing: 8, runSpacing: 8, children: [
            TravelStatusPill(text: 'RM ${item['price'] ?? 0}', icon: Icons.payments_outlined),
            if ((item['durationDays'] ?? '').toString().isNotEmpty) TravelStatusPill(text: '${item['durationDays']} day(s)', icon: Icons.calendar_today_outlined),
            if ((item['maxTravellers'] ?? '').toString().isNotEmpty) TravelStatusPill(text: 'Up to ${item['maxTravellers']}', icon: Icons.group_outlined),
          ]),
          const SizedBox(height: 18),
          InkCard(color: InkWashColors.cream, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Package overview', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
            const SizedBox(height: 7),
            Text((item['description'] ?? 'Package information provided by the Tourism Operator.').toString()),
          ])),
          const SizedBox(height: 18),
          if (campaigns.isNotEmpty) ...[
            const Text('Current promotion', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
            const SizedBox(height: 8),
            ...campaigns.map((c) => Padding(
              padding: const EdgeInsets.only(bottom: 9),
              child: InkCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text((c['campaignTitle'] ?? 'Promotion').toString(), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
                if ((c['description'] ?? '').toString().isNotEmpty) ...[const SizedBox(height: 5), Text(c['description'].toString())],
                if ((c['promoCode'] ?? '').toString().isNotEmpty) ...[const SizedBox(height: 7), TravelStatusPill(text: 'Code ${c['promoCode']}', icon: Icons.local_offer_outlined)],
              ])),
            )),
            const SizedBox(height: 9),
          ],
          _bullets('Highlights', item['highlights'], Icons.place_outlined),
          _bullets('What is included', item['inclusions'], Icons.check_circle_outline),
          _bullets('Not included', item['exclusions'], Icons.remove_circle_outline),
          InkCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Package information', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
            const SizedBox(height: 10),
            if ((item['validFrom'] ?? '').toString().isNotEmpty || (item['validUntil'] ?? '').toString().isNotEmpty)
              Text('Valid: ${item['validFrom'] ?? '-'} to ${item['validUntil'] ?? '-'}'),
            if ((item['meetingPoint'] ?? '').toString().isNotEmpty) Text('Meeting point: ${item['meetingPoint']}'),
            if ((item['operatorName'] ?? '').toString().isNotEmpty) Text('Tourism Operator: ${item['operatorName']}'),
            if ((item['operatorPhone'] ?? '').toString().isNotEmpty) Text('Contact: ${item['operatorPhone']}'),
          ])),
        ],
      ),
    );
  }
}
