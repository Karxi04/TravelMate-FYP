import 'package:flutter/material.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';

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
      padding: const EdgeInsets.only(bottom: 8),
      child: InkCard(
          padding: const EdgeInsets.all(12),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (image.startsWith('https://') || image.startsWith('http://'))
              ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.network(image,
                      height: 120,
                      width: double.infinity,
                      fit: BoxFit.cover,
                      errorBuilder: (context, error, stack) =>
                          const SizedBox.shrink())),
            Text((package['title'] ?? package['packageTitle'] ?? '').toString(),
                style:
                    const TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
            Text(
                '${package['destination'] ?? package['destinationArea'] ?? ''} · ${package['durationDays'] ?? '?'} days'),
            Text(
                'by ${package['operatorName'] ?? 'Operator information unavailable'}'),
            const SizedBox(height: 8),
            Text(
                conditions['isReference'] == true
                    ? 'Reference party total'
                    : 'Quoted party total',
                style: const TextStyle(fontWeight: FontWeight.w700)),
            if (discounted)
              Text('MYR ${money(quote['originalSubtotal'])}',
                  style:
                      const TextStyle(decoration: TextDecoration.lineThrough)),
            Text('MYR ${money(quote['finalPayable'])}',
                style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    color: AppColors.primaryStrong,
                    fontSize: 18)),
            Text(
                '${party['adults'] ?? '?'} adults · ${party['children'] ?? '?'} children · ${quote['priceBasis'] == 'per_group' ? 'per-group price' : 'adult/child pricing'}'),
            Text(
                '${conditions['dateKnown'] == true ? 'Requested departure' : 'Reference departure'}: ${conditions['departureDate'] ?? 'Not specified'}'),
            if (conditions['partyKnown'] != true)
              const Text(
                  'Tell me your adult/child counts for a specific quote.'),
            if (discounted) ...[
              Text(
                  '${offer['campaignTitle'] ?? 'Offer'} · Save MYR ${money(quote['promotionDiscount'])}'),
              Text(
                  'Offer valid ${offer['startDate'] ?? '?'} to ${offer['endDate'] ?? '?'}'),
              if ((offer['promoCode'] ?? '').toString().isNotEmpty)
                Text('Explicit coupon: ${offer['promoCode']}'),
              if ((offer['termsConditions'] ?? '').toString().isNotEmpty)
                Text(offer['termsConditions'].toString()),
            ],
            Text(quote['taxIncluded'] == true
                ? 'Declared taxes/fees included'
                : 'Taxes/fees: ${quote['taxNotes'] ?? 'Review full terms'}'),
            Text(
                'Party limits: ${package['minimumTravellers'] ?? 1}–${package['maximumTravellers'] ?? 'not specified'}'),
            const SizedBox(height: 6),
            for (final line in (package['inclusions'] as List? ?? []))
              Text('• $line'),
            if (package['inclusionsTruncated'] == true ||
                conditions['termsTruncated'] == true)
              const Text('Open details for all inclusions and complete terms.'),
            for (final entry in const {
              'accommodation': 'Accommodation',
              'transport': 'Transportation',
              'guideActivities': 'Guide / activities'
            }.entries)
              Text(
                  '${entry.value}: ${services[entry.key] == true ? 'Included' : services[entry.key] == false ? 'Not included' : 'Unknown — review brochure'}'),
            const SizedBox(height: 6),
            if (conditions['quotedAt'] != null)
              Text('Quote recorded: ${conditions['quotedAt']}'),
            const Text(
                'Published package. Prices and eligibility refresh at checkout. No reservation or supplier confirmation is implied.'),
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
                      .toString()),
              subtitle: Text(
                  '${trip['startDate'] ?? 'Date unavailable'} to ${trip['endDate'] ?? 'Date unavailable'}')),
        if ((item['ownedTrips'] as List? ?? []).isNotEmpty)
          TextButton(onPressed: onTrips, child: const Text('Open Saved Trips')),
        for (final order
            in (item['ownedOrders'] as List? ?? []).whereType<Map>())
          InkCard(
              padding: const EdgeInsets.all(10),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text((order['title'] ?? 'Package purchase').toString(),
                        style: const TextStyle(fontWeight: FontWeight.w700)),
                    Text('Order: ${order['orderId']}'),
                    Text(
                        'Payment: ${order['paymentStatus'] ?? 'Unknown'} · ${order['currency'] ?? ''} ${order['amount'] ?? 'Unavailable'}'),
                    for (final entry in const {
                      'travellerTrip': 'Trip',
                      'operatorReadiness': 'Operator readiness',
                      'supplierArrangements': 'Supplier arrangements'
                    }.entries)
                      Text(
                          '${entry.value}: ${(order['statusOverview'] as Map?)?[entry.key]?['label'] ?? 'Unavailable'}'),
                    const Text(
                        'Recorded arrangements are not independent supplier confirmation.'),
                  ])),
      ]);
}
