class PackagePricing {
  static Map<String, dynamic>? current(Map<String, dynamic> item,
      {DateTime? now}) {
    final pricing = item['packagePricing'];
    if (pricing is! Map || pricing['base'] is! Map) return null;
    var best = Map<String, dynamic>.from(pricing['base'] as Map);
    final day = (now ?? DateTime.now().toUtc())
        .toUtc()
        .add(const Duration(hours: 8))
        .toIso8601String()
        .substring(0, 10);
    final offers = (pricing['offers'] as List? ?? []).whereType<Map>().toList()
      ..sort((a, b) => '${(a['promotion'] as Map?)?['id'] ?? ''}'
          .compareTo('${(b['promotion'] as Map?)?['id'] ?? ''}'));
    for (final raw in offers) {
      final promotion = raw['promotion'];
      if (promotion is! Map || '${promotion['promoCode'] ?? ''}'.isNotEmpty)
        continue;
      final start = '${promotion['startDate'] ?? ''}',
          end = '${promotion['endDate'] ?? ''}';
      if (DateTime.tryParse(start) == null ||
          DateTime.tryParse(end) == null ||
          day.compareTo(start) < 0 ||
          day.compareTo(end) > 0) continue;
      final amount = num.tryParse('${raw['amountMinor']}'),
          previous = num.tryParse('${best['amountMinor']}');
      if (amount != null && previous != null && amount > 0 && amount < previous)
        best = Map<String, dynamic>.from(raw);
    }
    return best;
  }

  static String label(Map<String, dynamic> item) {
    final quote = current(item);
    final amount = num.tryParse(
        '${quote?['finalPayable'] ?? item['adultPrice'] ?? item['price']}');
    if (amount == null) return '';
    final count = (quote?['participants'] as Map?)?['adults'] ?? 1;
    final basis = item['priceBasis'] == 'per_group'
        ? 'group'
        : count == 1
            ? 'person'
            : '$count adults';
    final original = num.tryParse('${quote?['originalSubtotal']}');
    final savings = num.tryParse('${quote?['promotionDiscount']}') ?? 0;
    final promotion = quote?['promotion'] as Map?;
    final price =
        '${item['currency'] ?? 'MYR'} ${amount.toStringAsFixed(2)} / $basis';
    return savings > 0 && original != null
        ? '$price · was ${original.toStringAsFixed(2)} · ${promotion?['campaignTitle'] ?? 'Automatic offer'} · save ${savings.toStringAsFixed(2)} · until ${promotion?['endDate']} · terms apply'
        : price;
  }
}
