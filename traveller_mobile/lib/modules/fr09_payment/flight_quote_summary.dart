import 'package:flutter/material.dart';

class FlightQuoteSummary extends StatelessWidget {
  final Map<String, dynamic> quote;
  const FlightQuoteSummary({super.key, required this.quote});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${quote['currency']} ${quote['price']}'),
          Text('Adults: ${quote['travellerCount']}'),
          const Text(
              'One adult: provider ticket price for all outbound segments, counted once.'),
          Text('Originally retrieved: ${quote['retrievedAt']}'),
          Text('Quote expires: ${quote['expiresAt']}'),
          const Text('Segment times are local airport times.'),
          if (quote['feeDisclosure'] != null)
            Text(quote['feeDisclosure'].toString()),
          for (final direction in const {
            'outboundSegments': 'Outbound',
            'returnSegments': 'Return'
          }.entries)
            if ((quote[direction.key] as List? ?? []).isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(direction.value,
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              for (final segment
                  in (quote[direction.key] as List).whereType<Map>()) ...[
                Text('${segment['airline']} ${segment['flightNumber']}'),
                Text(
                    '${segment['departureAirportCode']} ${segment['departureDate']} ${segment['departureTime']} → ${segment['arrivalAirportCode']} ${segment['arrivalDate']} ${segment['arrivalTime']}'),
                if (segment['travelClass'] != null)
                  Text('Cabin: ${segment['travelClass']}'),
              ],
            ],
          const SizedBox(height: 12),
          const Text('Stripe test payment.'),
          const Text('TravelMate demo order.'),
          const Text('No flight has been booked or ticketed.'),
        ],
      );
}
