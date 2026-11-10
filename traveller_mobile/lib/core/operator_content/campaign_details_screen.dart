import '../utils/package_pricing.dart';
import 'package:flutter/material.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class CampaignDetailsScreen extends StatelessWidget {
  final Map<String, dynamic> item;
  const CampaignDetailsScreen({super.key, required this.item});

  @override
  Widget build(BuildContext context) {
    final discount = (item['discountValue'] ?? '').toString();
    final type = (item['discountType'] ?? '').toString();
    return Scaffold(
      appBar: AppBar(title: const Text('Promotion details')),
      body: ListView(padding: const EdgeInsets.fromLTRB(18, 8, 18, 28), children: [
        TravelPlaceImage(place: {
          'title': item['campaignTitle'] ?? item['packageTitle'] ?? 'Travel promotion',
          'imageUrl': item['bannerImageUrl'] ?? item['packageImageUrl'] ?? '',
          'category': 'Promotion',
        }, height: 220, width: double.infinity, borderRadius: BorderRadius.circular(22)),
        const SizedBox(height: 16),
        const TravelStatusPill(text: 'APPROVED PROMOTION', icon: Icons.local_offer_outlined),
        const SizedBox(height: 10),
        Text((item['campaignTitle'] ?? 'Travel promotion').toString(), style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w900)),
        if ((item['packageTitle'] ?? '').toString().isNotEmpty) Text('For ${item['packageTitle']}', style: const TextStyle(color: InkWashColors.mutedInk)),
        const SizedBox(height: 15),
        InkCard(color: InkWashColors.cream, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (['percentage','fixed'].contains(type) && (num.tryParse(discount) ?? 0) > 0) Text(type == 'percentage' ? '$discount% off' : 'Save RM $discount', style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900)),
          if ((item['promoCode'] ?? '').toString().isNotEmpty) ...[const SizedBox(height: 7), SelectableText('Promo code: ${item['promoCode']}', style: const TextStyle(fontWeight: FontWeight.w800))],
          if (['percentage','fixed'].contains(type) && (item['promoCode'] ?? '').toString().trim().isEmpty && (num.tryParse(discount) ?? 0) > 0) const Text('Applied automatically to eligible package bookings. Best single offer; no stacking.'),
          const SizedBox(height: 8),
          Text((item['description'] ?? '').toString()),
        ])),
        if (item['packagePricing'] is Map) Padding(padding: const EdgeInsets.only(top: 12), child: Text(PackagePricing.label({...item, 'currency': 'MYR', 'priceBasis': (item['packagePricing']['base'] as Map?)?['priceBasis']}))),
        const SizedBox(height: 16),
        InkCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Promotion period', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
          const SizedBox(height: 7),
          Text('${item['startDate'] ?? '-'} to ${item['endDate'] ?? '-'}'),
          if ((item['operatorName'] ?? '').toString().isNotEmpty) ...[const SizedBox(height: 8), Text('By ${item['operatorName']}')],
        ])),
        if ((item['termsConditions'] ?? '').toString().isNotEmpty) ...[
          const SizedBox(height: 16),
          InkCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Terms & conditions', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
            const SizedBox(height: 7),
            Text(item['termsConditions'].toString()),
          ])),
        ],
      ]),
    );
  }
}
