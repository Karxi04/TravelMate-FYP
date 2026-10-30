import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';

class FlightReplacementSheet extends StatelessWidget {
  final Map<String, dynamic> currentFlight;
  final Map<String, dynamic> newFlight;
  final Map<String, dynamic>? returnOption;
  final Map<String, dynamic>? trip;

  const FlightReplacementSheet({
    super.key,
    required this.currentFlight,
    required this.newFlight,
    this.returnOption,
    this.trip,
  });

  static Future<bool?> show({
    required BuildContext context,
    required Map<String, dynamic> currentFlight,
    required Map<String, dynamic> newFlight,
    Map<String, dynamic>? returnOption,
    Map<String, dynamic>? trip,
  }) {
    return showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => FlightReplacementSheet(
        currentFlight: currentFlight,
        newFlight: newFlight,
        returnOption: returnOption,
        trip: trip,
      ),
    );
  }

  double _parseFare(dynamic val) {
    if (val == null) return 0.0;
    if (val is num) return val.toDouble();
    return double.tryParse(val.toString().replaceAll(RegExp(r'[^0-9.]'), '')) ??
        0.0;
  }

  @override
  Widget build(BuildContext context) {
    final currentFare = _parseFare(currentFlight['price'] ?? trip?['flightCost']);
    final newFare = returnOption != null
        ? _parseFare(returnOption!['combinedPrice'] ??
            returnOption!['price'] ??
            newFlight['price'])
        : _parseFare(newFlight['price']);
    final fareDiff = newFare - currentFare;

    final String tripTitle = (trip?['title'] ?? 'Trip').toString();
    final String tripDates = [trip?['startDate'], trip?['endDate']]
        .where((d) => d != null && d.toString().isNotEmpty)
        .join(' to ');

    final double screenHeight = MediaQuery.of(context).size.height;

    return Container(
      constraints: BoxConstraints(
        maxHeight: screenHeight * 0.9,
      ),
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Header
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 16, 12),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Replace Flight',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          tripDates.isNotEmpty
                              ? '$tripTitle ($tripDates)'
                              : tripTitle,
                          style: const TextStyle(
                            fontSize: 12,
                            color: InkWashColors.mutedInk,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close_rounded),
                    onPressed: () => Navigator.pop(context, false),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),

            // Scrollable Content
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
                children: [
                  // Comparison Cards
                  const Text(
                    'Flight Comparison',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 10),

                  // Current Flight Card
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF8FAFC),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: const Color(0xFFE2E8F0)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: const Color(0xFFE2E8F0),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: const Text(
                                'CURRENT',
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.w800,
                                  color: Color(0xFF475569),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              '${currentFlight['airline'] ?? 'Airline'} ${currentFlight['flightNumber'] ?? ''}',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w700),
                            ),
                            const Spacer(),
                            Text(
                              'RM ${currentFare.toStringAsFixed(2)}',
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 14,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Route: ${currentFlight['departureAirport'] ?? '-'} → ${currentFlight['arrivalAirport'] ?? '-'}',
                          style: const TextStyle(
                              fontSize: 12, color: InkWashColors.mutedInk),
                        ),
                        Text(
                          'Timing: ${currentFlight['departureTime'] ?? '-'} to ${currentFlight['arrivalTime'] ?? '-'}',
                          style: const TextStyle(
                              fontSize: 12, color: InkWashColors.mutedInk),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 8),
                  const Center(
                    child: Icon(Icons.arrow_downward_rounded,
                        size: 20, color: InkWashColors.blueGrey),
                  ),
                  const SizedBox(height: 8),

                  // New Flight Card
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.primarySoft,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                          color: AppColors.primary.withValues(alpha: 0.3)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: AppColors.primary,
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: const Text(
                                'NEW SELECTION',
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.w800,
                                  color: Colors.white,
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              '${newFlight['airline'] ?? 'Airline'} ${newFlight['flightNumber'] ?? ''}',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w700),
                            ),
                            const Spacer(),
                            Text(
                              'RM ${newFare.toStringAsFixed(2)}',
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 14,
                                color: AppColors.primary,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Route: ${newFlight['departureAirport'] ?? '-'} → ${newFlight['arrivalAirport'] ?? '-'}${returnOption != null ? ' (Return included)' : ''}',
                          style: const TextStyle(
                              fontSize: 12, color: InkWashColors.mutedInk),
                        ),
                        Text(
                          'Timing: ${newFlight['departureTime'] ?? '-'} to ${newFlight['arrivalTime'] ?? '-'}',
                          style: const TextStyle(
                              fontSize: 12, color: InkWashColors.mutedInk),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 12),

                  // Fare Difference Row
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF1F5F9),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          'Fare Difference:',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        Text(
                          '${fareDiff >= 0 ? '+' : '-'} RM ${fareDiff.abs().toStringAsFixed(2)}',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w900,
                            color: fareDiff > 0
                                ? AppColors.warning
                                : AppColors.success,
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 18),

                  // Impact Details
                  const Text(
                    'Schedule & Budget Impact',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: InkWashColors.cream,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: const Color(0xFFE2E8F0)),
                    ),
                    child: const Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '• Transport budget allocation will be updated with the new flight price.',
                          style: TextStyle(fontSize: 12, height: 1.4),
                        ),
                        SizedBox(height: 4),
                        Text(
                          '• Hotel and car rental plans remain untouched.',
                          style: TextStyle(fontSize: 12, height: 1.4),
                        ),
                        SizedBox(height: 4),
                        Text(
                          '• Planned activities on travel dates may require adjustment to fit the new flight schedule.',
                          style: TextStyle(fontSize: 12, height: 1.4),
                        ),
                        SizedBox(height: 4),
                        Text(
                          '• Manually protected activities will stay protected.',
                          style: TextStyle(fontSize: 12, height: 1.4),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 12),
                  const Text(
                    'Planning estimate only • No airline ticket issued',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 11,
                      color: InkWashColors.mutedInk,
                      fontStyle: FontStyle.italic,
                    ),
                  ),
                ],
              ),
            ),

            // Action Buttons
            Container(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              decoration: const BoxDecoration(
                color: Colors.white,
                border: Border(top: BorderSide(color: Color(0xFFE2E8F0))),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      key: const ValueKey('flight-replacement-cancel-btn'),
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Keep Current Flight'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton(
                      key: const ValueKey('flight-replacement-confirm-btn'),
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Confirm Replacement'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
