import 'package:flutter/material.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../core/operator_content/package_text_block.dart';

/// Values are backend quotes; this widget never computes payable amounts.
class DatabasePackageCard extends StatelessWidget {
  final Map<String, dynamic> package;
  final VoidCallback? onDetails;
  const DatabasePackageCard({super.key, required this.package, this.onDetails});
  String money(dynamic value) =>
      value is num ? value.toStringAsFixed(2) : 'Unavailable';
  @override
  Widget build(BuildContext context) {
    final quote = package['chatQuote'] as Map? ?? {};
    final conditions = package['quoteContext'] as Map? ?? {};
    final party = conditions['participants'] as Map? ?? {};
    final offer = quote['promotion'] as Map? ?? {};
    final services = package['serviceInclusions'] as Map? ?? {};
    final image =
        (package['heroImage'] ?? package['imageUrl'] ?? '').toString();
    final discounted =
        quote['promotionDiscount'] is num && quote['promotionDiscount'] > 0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkCard(
          padding: const EdgeInsets.all(14),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (image.startsWith('https://') || image.startsWith('http://')) ...[
              ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: Image.network(image,
                      height: 120,
                      width: double.infinity,
                      fit: BoxFit.cover,
                      errorBuilder: (context, error, stack) =>
                          const SizedBox.shrink())),
              const SizedBox(height: 10),
            ],
            Text((package['title'] ?? package['packageTitle'] ?? '').toString(),
                style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                    height: 1.3)),
            const SizedBox(height: 3),
            Text(
                '${package['destination'] ?? package['destinationArea'] ?? ''} · ${package['durationDays'] ?? '?'} days',
                style: const TextStyle(
                    fontSize: 13, color: AppColors.textSecondary)),
            const SizedBox(height: 2),
            Text(
                'by ${package['operatorName'] ?? 'Operator information unavailable'}',
                style: const TextStyle(
                    fontSize: 12.5, color: AppColors.textSecondary)),
            const SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppColors.surfaceElevated,
                borderRadius: BorderRadius.circular(AppRadii.small),
                border: Border.all(color: AppColors.divider),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                      conditions['isReference'] == true
                          ? 'Reference party total'
                          : 'Quoted party total',
                      style: const TextStyle(
                          fontWeight: FontWeight.w700, fontSize: 13)),
                  const SizedBox(height: 2),
                  if (discounted)
                    Text('MYR ${money(quote['originalSubtotal'])}',
                        style: const TextStyle(
                            decoration: TextDecoration.lineThrough,
                            fontSize: 13,
                            color: AppColors.textSecondary)),
                  Text('MYR ${money(quote['finalPayable'])}',
                      style: const TextStyle(
                          fontWeight: FontWeight.w800,
                          color: AppColors.primaryStrong,
                          fontSize: 18)),
                  const SizedBox(height: 4),
                  Text(
                      '${party['adults'] ?? '?'} adults · ${party['children'] ?? '?'} children · ${quote['priceBasis'] == 'per_group' ? 'per-group price' : 'adult/child pricing'}',
                      style: const TextStyle(
                          fontSize: 12.5, color: AppColors.textSecondary)),
                  const SizedBox(height: 2),
                  Text(
                      '${conditions['dateKnown'] == true ? 'Requested departure' : 'Reference departure'}: ${conditions['departureDate'] ?? 'Not specified'}',
                      style: const TextStyle(
                          fontSize: 12.5, color: AppColors.textSecondary)),
                  if (conditions['partyKnown'] != true) ...[
                    const SizedBox(height: 4),
                    const Text(
                        'Tell me your adult/child counts for a specific quote.',
                        style: TextStyle(
                            fontSize: 12.5, color: AppColors.primaryStrong)),
                  ],
                ],
              ),
            ),
            if (discounted) ...[
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppColors.primarySoft,
                  borderRadius: BorderRadius.circular(AppRadii.small),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                        '${offer['campaignTitle'] ?? 'Offer'} · Save MYR ${money(quote['promotionDiscount'])}',
                        style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 13,
                            color: AppColors.primaryStrong)),
                    const SizedBox(height: 2),
                    Text(
                        'Offer valid ${offer['startDate'] ?? '?'} to ${offer['endDate'] ?? '?'}',
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.textSecondary)),
                    if ((offer['promoCode'] ?? '').toString().isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text('Explicit coupon: ${offer['promoCode']}',
                          style: const TextStyle(
                              fontSize: 12, fontWeight: FontWeight.w600)),
                    ],
                    if ((offer['termsConditions'] ?? '')
                        .toString()
                        .isNotEmpty) ...[
                      const SizedBox(height: 4),
                      PackageTextBlock(
                        text: offer['termsConditions'].toString(),
                        expandLabel: 'Read full offer terms',
                        style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.textSecondary,
                            height: 1.4),
                      ),
                    ],
                  ],
                ),
              ),
            ],
            const SizedBox(height: 8),
            Text(
                quote['taxIncluded'] == true
                    ? 'Declared taxes/fees included'
                    : 'Taxes/fees: ${quote['taxNotes'] ?? 'Review full terms'}',
                style: const TextStyle(
                    fontSize: 12.5, color: AppColors.textSecondary)),
            const SizedBox(height: 2),
            Text(
                'Party limits: ${package['minimumTravellers'] ?? 1}–${package['maximumTravellers'] ?? 'not specified'}',
                style: const TextStyle(
                    fontSize: 12.5, color: AppColors.textSecondary)),
            if (package['inclusions'] case final List inclusions
                when inclusions.isNotEmpty) ...[
              const SizedBox(height: 8),
              PackageTextBlock(
                text: inclusions.map((line) => '• $line').join('\n'),
                expandLabel: 'Read all listed inclusions',
              ),
            ],
            if (package['inclusionsTruncated'] == true ||
                conditions['termsTruncated'] == true) ...[
              const SizedBox(height: 4),
              const Text(
                  'Open details for all inclusions and complete terms.',
                  style: TextStyle(
                      fontSize: 12, color: AppColors.textSecondary)),
            ],
            const SizedBox(height: 8),
            for (final entry in const {
              'accommodation': 'Accommodation',
              'transport': 'Transportation',
              'guideActivities': 'Guide / activities'
            }.entries)
              Padding(
                padding: const EdgeInsets.only(bottom: 3),
                child: Text(
                    '${entry.value}: ${services[entry.key] == true ? 'Included' : services[entry.key] == false ? 'Not included' : 'Unknown — review brochure'}',
                    style: const TextStyle(
                        fontSize: 12.5, color: AppColors.textSecondary)),
              ),
            if (conditions['quotedAt'] != null) ...[
              const SizedBox(height: 6),
              Text('Quote recorded: ${conditions['quotedAt']}',
                  style: const TextStyle(
                      fontSize: 12, color: AppColors.textSecondary)),
            ],
            const SizedBox(height: 6),
            const Text(
                'Published package. Prices and eligibility refresh at checkout. No reservation or supplier confirmation is implied.',
                style: TextStyle(
                    fontSize: 11.5,
                    color: AppColors.textSecondary,
                    height: 1.4)),
            const SizedBox(height: 10),
            SizedBox(
                width: double.infinity,
                child: FilledButton.tonalIcon(
                    key: ValueKey('chat-package-${package['id']}'),
                    onPressed: onDetails,
                    icon: const Icon(Icons.arrow_forward_rounded, size: 16),
                    label: const Text('View Package Details'))),
          ])),
    );
  }
}

class OwnedChatRecords extends StatelessWidget {
  final Map item;
  final VoidCallback onTrips;
  const OwnedChatRecords(
      {super.key, required this.item, required this.onTrips});
  @override
  Widget build(BuildContext context) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final trip in (item['ownedTrips'] as List? ?? []).whereType<Map>())
          ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(
                  (trip['title'] ?? trip['destinationArea'] ?? 'Saved trip')
                      .toString(),
                  style: const TextStyle(fontWeight: FontWeight.w700)),
              subtitle: Text(
                  '${trip['startDate'] ?? 'Date unavailable'} to ${trip['endDate'] ?? 'Date unavailable'}')),
        if ((item['ownedTrips'] as List? ?? []).isNotEmpty) ...[
          TextButton(onPressed: onTrips, child: const Text('Open Saved Trips')),
          const SizedBox(height: 6),
        ],
        for (final order
            in (item['ownedOrders'] as List? ?? []).whereType<Map>())
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: InkCard(
                padding: const EdgeInsets.all(12),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text((order['title'] ?? 'Package purchase').toString(),
                          style: const TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 14)),
                      const SizedBox(height: 4),
                      Text('Order: ${order['orderId']}',
                          style: const TextStyle(
                              fontSize: 12.5, color: AppColors.textSecondary)),
                      const SizedBox(height: 2),
                      Text(
                          'Payment: ${order['paymentStatus'] ?? 'Unknown'} · ${order['currency'] ?? ''} ${order['amount'] ?? 'Unavailable'}',
                          style: const TextStyle(
                              fontSize: 13, fontWeight: FontWeight.w600)),
                      const SizedBox(height: 6),
                      for (final entry in const {
                        'travellerTrip': 'Trip',
                        'operatorReadiness': 'Operator readiness',
                        'supplierArrangements': 'Supplier arrangements'
                      }.entries)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 2),
                          child: Text(
                              '${entry.value}: ${(order['statusOverview'] as Map?)?[entry.key]?['label'] ?? 'Unavailable'}',
                              style: const TextStyle(fontSize: 12.5)),
                        ),
                      const SizedBox(height: 6),
                      const Text(
                          'Recorded arrangements are not independent supplier confirmation.',
                          style: TextStyle(
                              fontSize: 11.5,
                              color: AppColors.textSecondary,
                              height: 1.35)),
                    ])),
          ),
      ]);
}
