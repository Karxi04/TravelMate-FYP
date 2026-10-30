import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class FlightDetailsScreen extends StatelessWidget {
  final Map<String, dynamic> flight;
  final VoidCallback? onSelect;

  const FlightDetailsScreen({
    super.key,
    required this.flight,
    this.onSelect,
  });

  static String? formatCabinClass(dynamic val) {
    if (val == null) return null;
    if (val == 1 || val == '1' || val == 'Economy') return 'Economy';
    if (val == 2 || val == '2' || val == 'Premium' || val == 'Premium Economy') {
      return 'Premium Economy';
    }
    if (val == 3 || val == '3' || val == 'Business') return 'Business';
    if (val == 4 || val == '4' || val == 'First' || val == 'First Class') {
      return 'First Class';
    }
    if (val is String && val.trim().isNotEmpty) return val.trim();
    return null;
  }

  Widget detailRow(String label, dynamic value, {IconData? icon}) {
    final text = (value ?? '').toString().trim();
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
              width: 118,
              child: Text(label,
                  style: const TextStyle(color: InkWashColors.mutedInk))),
          Expanded(
              child: Text(text.isEmpty ? 'Not provided' : text,
                  style: const TextStyle(fontWeight: FontWeight.w700))),
        ],
      ),
    );
  }

  Widget segmentCard(Map<String, dynamic> segment, int index) {
    final departure =
        '${segment['departureAirportCode'] ?? segment['departureAirport'] ?? '-'} ${segment['departureTime'] ?? ''}'
            .trim();
    final arrival =
        '${segment['arrivalAirportCode'] ?? segment['arrivalAirport'] ?? '-'} ${segment['arrivalTime'] ?? ''}'
            .trim();
    final aircraft = segment['aircraft'] ?? segment['airplane'];
    final cabin = formatCabinClass(segment['travelClass'] ?? segment['cabinClass']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: InkCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Segment ${index + 1}',
              style: const TextStyle(fontWeight: FontWeight.w900)),
          const SizedBox(height: 4),
          Text('$departure → $arrival',
              style: const TextStyle(fontWeight: FontWeight.w700)),
          detailRow('Airline',
              '${segment['airline'] ?? '-'} ${segment['flightNumber'] ?? ''}'),
          if ((segment['departureDate'] ?? '').toString().isNotEmpty)
            detailRow('Local dates',
                '${segment['departureDate']} → ${segment['arrivalDate'] ?? ''}'),
          if (aircraft != null) detailRow('Aircraft', aircraft),
          if (cabin != null) detailRow('Cabin', cabin),
          detailRow(
              'Duration',
              segment['durationMinutes'] == null
                  ? null
                  : '${segment['durationMinutes']} min'),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final duration = '${flight['durationMinutes'] ?? '-'} min';
    final bool isPendingReturn =
        flight['quoteCompleteness'] == 'return_selection_pending';
    return Scaffold(
      appBar: AppBar(title: const Text('Flight details')),
      bottomNavigationBar: onSelect == null ? null : SafeArea(
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
                    Text(
                      isPendingReturn ? 'Outbound fare estimate' : 'Total fare',
                      style: const TextStyle(
                          color: InkWashColors.mutedInk, fontSize: 12),
                    ),
                    Text(
                        '${flight['currency'] ?? 'MYR'} ${flight['price'] ?? '-'}',
                        style: const TextStyle(
                            fontSize: 21, fontWeight: FontWeight.w900)),
                  ],
                ),
              ),
              FilledButton.icon(
                  onPressed: onSelect,
                  icon: Icon(isPendingReturn
                      ? Icons.sync_alt_rounded
                      : Icons.add_road_rounded),
                  label: Text(isPendingReturn
                      ? 'Choose return flight'
                      : 'Select flight')),
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
                Text(
                    '${flight['airline'] ?? 'Airline'} ${flight['flightNumber'] ?? ''}',
                    style: const TextStyle(
                        fontSize: 22, fontWeight: FontWeight.w900)),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                          Text((flight['departureTime'] ?? '').toString(),
                              style: const TextStyle(
                                  fontSize: 24, fontWeight: FontWeight.w900)),
                          Text((flight['departureAirport'] ?? '').toString(),
                              style: const TextStyle(
                                  color: InkWashColors.mutedInk))
                        ])),
                    Expanded(
                        child: Column(children: [
                      const Icon(Icons.flight_takeoff_rounded,
                          color: InkWashColors.blueGrey),
                      Text(duration, style: const TextStyle(fontSize: 12)),
                      Text((flight['stopText'] ?? '').toString(),
                          style: const TextStyle(
                              fontSize: 12, color: InkWashColors.mutedInk))
                    ])),
                    Expanded(
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                          Text((flight['arrivalTime'] ?? '').toString(),
                              style: const TextStyle(
                                  fontSize: 24, fontWeight: FontWeight.w900)),
                          Text((flight['arrivalAirport'] ?? '').toString(),
                              style: const TextStyle(
                                  color: InkWashColors.mutedInk))
                        ])),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          InkCard(
            color: InkWashColors.cream,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.info_outline_rounded,
                    color: InkWashColors.blueGrey, size: 20),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Text(
                        'Flight planning estimate — provider caching may apply.',
                        style: TextStyle(
                            fontWeight: FontWeight.w800, fontSize: 13),
                      ),
                      SizedBox(height: 3),
                      Text(
                        'Price and availability are not guaranteed. TravelMate supports flight planning estimates, but cannot issue airline tickets or reserve seats.',
                        style: TextStyle(
                            fontSize: 12, color: InkWashColors.mutedInk),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const TravelPreparationGuide(service: 'Flight'),
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Flight information'),
          const SizedBox(height: 8),
          InkCard(
            child: Column(
              children: [
                detailRow('Outbound date', flight['outboundDate'],
                    icon: Icons.calendar_today_outlined),
                if ((flight['returnDate'] ?? '').toString().isNotEmpty)
                  detailRow('Return date', flight['returnDate'],
                      icon: Icons.event_repeat_outlined),
                detailRow(
                    'Cabin class',
                    formatCabinClass(flight['cabinClass'] ??
                        flight['requestedTravelClass'] ??
                        flight['travelClass']),
                    icon: Icons.airline_seat_recline_normal_rounded),
                detailRow('Aircraft', flight['aircraft'] ?? flight['airplane'],
                    icon: Icons.flight_rounded),
                detailRow('Departure terminal', flight['departureTerminal'],
                    icon: Icons.airport_shuttle_outlined),
                detailRow('Arrival terminal', flight['arrivalTerminal'],
                    icon: Icons.location_on_outlined),
              ],
            ),
          ),
          if ((flight['priceBasis'] ?? '').toString().isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                  'Price basis: ${flight['priceBasis']} • planning reference only',
                  style: const TextStyle(color: InkWashColors.mutedInk)),
            ),
          detailRow('Travellers', flight['travellerCount'],
              icon: Icons.people_outline_rounded),
          if (isPendingReturn)
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: Text(
                  'Outbound candidate only. Choose a compatible return leg before selecting this trip.',
                  style: TextStyle(color: InkWashColors.mutedInk)),
            ),
          ...((flight['outboundSegments'] as List? ?? [])
              .whereType<Map>()
              .toList()
              .asMap()
              .entries
              .map((entry) => segmentCard(
                  Map<String, dynamic>.from(entry.value), entry.key))),
          if ((flight['returnSegments'] as List? ?? []).isNotEmpty) ...[
            const TravelSectionHeader(title: 'Return segments'),
            ...((flight['returnSegments'] as List? ?? [])
                .whereType<Map>()
                .toList()
                .asMap()
                .entries
                .map((entry) => segmentCard(
                    Map<String, dynamic>.from(entry.value), entry.key))),
          ],
          const SizedBox(height: 18),
          const TravelSectionHeader(title: 'Baggage & fare conditions'),
          const SizedBox(height: 8),
          InkCard(
            child: Column(
              children: [
                detailRow('Cabin baggage', flight['cabinBaggage'],
                    icon: Icons.work_outline_rounded),
                detailRow('Checked baggage', flight['checkedBaggage'],
                    icon: Icons.luggage_outlined),
                detailRow('Fare', flight['fareConditions'],
                    icon: Icons.confirmation_number_outlined),
                detailRow('Changes', flight['changePolicy'],
                    icon: Icons.sync_alt_rounded),
                detailRow('Refund', flight['refundPolicy'],
                    icon: Icons.currency_exchange_rounded),
                detailRow('Meal', flight['meal'],
                    icon: Icons.restaurant_outlined),
              ],
            ),
          ),
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
                        'Fare, baggage and operational details should be rechecked before a final external booking because provider conditions can change.',
                        style: const TextStyle(color: InkWashColors.charcoal))),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
