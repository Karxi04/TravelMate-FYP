import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class CarRentalScreen extends StatefulWidget {
  final String? initialPickupLocation;
  final String? initialPickupDate;
  final String? initialDropoffDate;

  const CarRentalScreen({
    super.key,
    this.initialPickupLocation,
    this.initialPickupDate,
    this.initialDropoffDate,
  });

  @override
  State<CarRentalScreen> createState() => _CarRentalScreenState();
}

class _CarRentalScreenState extends State<CarRentalScreen> {
  late final TextEditingController pickupLocation;
  late final TextEditingController pickupDate;
  late final TextEditingController dropoffDate;
  final driverCount = TextEditingController(text: '1');
  final api = ApiService();

  List<dynamic> items = [];
  bool busy = false;
  String vehicleType = 'All';
  String source = '';

  String dateText(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  DateTime? parseDate(String value) => DateTime.tryParse(value.trim());

  Future<void> pickDate(TextEditingController controller,
      {DateTime? firstDate}) async {
    final today = DateTime.now();
    final minimum = firstDate ?? DateTime(today.year, today.month, today.day);
    final parsed = parseDate(controller.text);
    final initial =
        parsed != null && !parsed.isBefore(minimum) ? parsed : minimum;
    final picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: minimum,
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (picked != null) setState(() => controller.text = dateText(picked));
  }

  @override
  void initState() {
    super.initState();
    final start = DateTime.now().add(const Duration(days: 30));
    pickupLocation = TextEditingController(
        text: widget.initialPickupLocation?.trim().isNotEmpty == true
            ? widget.initialPickupLocation!.trim()
            : 'George Town, Penang');
    pickupDate = TextEditingController(
        text: widget.initialPickupDate?.trim().isNotEmpty == true
            ? widget.initialPickupDate!.trim()
            : dateText(start));
    dropoffDate = TextEditingController(
        text: widget.initialDropoffDate?.trim().isNotEmpty == true
            ? widget.initialDropoffDate!.trim()
            : dateText(start.add(const Duration(days: 2))));
  }

  @override
  void dispose() {
    pickupLocation.dispose();
    pickupDate.dispose();
    dropoffDate.dispose();
    driverCount.dispose();
    super.dispose();
  }

  Future<void> search() async {
    final pickup = parseDate(pickupDate.text);
    final dropoff = parseDate(dropoffDate.text);
    final drivers = int.tryParse(driverCount.text.trim()) ?? 0;
    if (pickupLocation.text.trim().isEmpty) {
      showError(context, 'Enter a pickup location.');
      return;
    }
    if (pickup == null || dropoff == null || dropoff.isBefore(pickup)) {
      showError(context, 'Choose a valid pickup and drop-off date range.');
      return;
    }
    if (drivers <= 0) {
      showError(context, 'Drivers must be at least 1.');
      return;
    }
    setState(() => busy = true);
    try {
      final data = await api.post('/api/fr8/car-rentals/search', {
        'pickupLocation': pickupLocation.text.trim(),
        'dropoffLocation': pickupLocation.text.trim(),
        'pickupDate': pickupDate.text.trim(),
        'dropoffDate': dropoffDate.text.trim(),
        'driverCount': drivers,
        'vehicleType': vehicleType,
      });
      if (!mounted) return;
      setState(() {
        items = data['items'] ?? [];
        source = (data['source'] ?? '').toString();
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<Map<String, dynamic>?> chooseItinerary() async {
    final data = await api.get('/api/fr5/itineraries');
    final trips = data['items'] as List? ?? [];
    if (!mounted) return null;
    if (trips.isEmpty) {
      showError(context, 'Create an itinerary in Trips first.');
      return null;
    }
    return showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(18, 0, 18, 20),
          children: [
            const Text('Attach car rental to itinerary',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
            const SizedBox(height: 8),
            ...trips.map((raw) {
              final trip = Map<String, dynamic>.from(raw as Map);
              return ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const CircleAvatar(
                    backgroundColor: InkWashColors.cream,
                    child: Icon(Icons.luggage_outlined,
                        color: InkWashColors.blueGrey)),
                title: Text((trip['title'] ?? 'Trip').toString()),
                subtitle: Text((trip['destinationArea'] ?? '').toString()),
                onTap: () => Navigator.pop(context, trip),
              );
            }),
          ],
        ),
      ),
    );
  }

  Future<void> selectRental(Map<String, dynamic> rental) async {
    try {
      final trip = await chooseItinerary();
      if (trip == null) return;
      final data = await api.post('/api/fr8/car-rentals/select', {
        'itineraryId': trip['id'],
        'rental': rental,
      });
      if (!mounted) return;
      final budget = data['budget'] is Map
          ? Map<String, dynamic>.from(data['budget'] as Map)
          : <String, dynamic>{};
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(
            'Car rental selected. New estimated trip total: RM ${budget['total'] ?? '-'}'),
      ));
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Car rentals')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
        children: [
          const TravelSectionHeader(
            title: 'Search car rentals',
            subtitle:
                'Compare simulated vehicle options and attach the selected rental cost to an itinerary.',
          ),
          const SizedBox(height: 12),
          TextField(
            controller: pickupLocation,
            decoration: const InputDecoration(
                labelText: 'Pickup location',
                prefixIcon: Icon(Icons.location_on_outlined)),
          ),
          const SizedBox(height: 9),
          Row(children: [
            Expanded(
              child: TextField(
                controller: pickupDate,
                readOnly: true,
                onTap: () => pickDate(pickupDate),
                decoration: const InputDecoration(
                    labelText: 'Pickup date',
                    prefixIcon: Icon(Icons.calendar_today_outlined)),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: dropoffDate,
                readOnly: true,
                onTap: () => pickDate(dropoffDate,
                    firstDate: parseDate(pickupDate.text)),
                decoration: const InputDecoration(
                    labelText: 'Drop-off date',
                    prefixIcon: Icon(Icons.event_available_outlined)),
              ),
            ),
          ]),
          const SizedBox(height: 9),
          TextField(
            controller: driverCount,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
                labelText: 'Drivers',
                prefixIcon: Icon(Icons.person_outline_rounded)),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: ['All', 'Compact', 'Sedan', 'MPV']
                .map((type) => ChoiceChip(
                      selected: vehicleType == type,
                      label: Text(type),
                      onSelected: (_) => setState(() => vehicleType = type),
                    ))
                .toList(),
          ),
          const SizedBox(height: 10),
          FilledButton.icon(
            onPressed: busy ? null : search,
            icon: const Icon(Icons.search_rounded),
            label: Text(busy ? 'Searching...' : 'Search car rentals'),
          ),
          if (source.isNotEmpty) ...[
            const SizedBox(height: 10),
            TravelStatusPill(
                text: 'SIMULATED RENTAL OPTIONS', icon: Icons.science_outlined),
          ],
          const SizedBox(height: 18),
          if (items.isEmpty && !busy)
            const TravelEmptyState(
              icon: Icons.directions_car_outlined,
              title: 'Search for a rental car',
              message:
                  'Vehicle options can be selected and added into your itinerary budget.',
            ),
          ...items.map((raw) {
            final item = Map<String, dynamic>.from(raw as Map);
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: InkCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text((item['vehicleName'] ?? 'Vehicle').toString(),
                        style: const TextStyle(
                            fontSize: 18, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 5),
                    Text(
                        '${item['vehicleType']} - ${item['seats']} seats - ${item['bags']} bags',
                        style: const TextStyle(color: InkWashColors.mutedInk)),
                    const SizedBox(height: 8),
                    Wrap(spacing: 7, runSpacing: 7, children: [
                      TravelStatusPill(
                          text: '${item['rentalDays']} day(s)',
                          icon: Icons.date_range_outlined),
                      TravelStatusPill(
                          text: item['transmission'].toString(),
                          icon: Icons.settings_outlined),
                      TravelStatusPill(
                          text: item['fuelPolicy'].toString(),
                          icon: Icons.local_gas_station_outlined),
                    ]),
                    const SizedBox(height: 10),
                    Row(children: [
                      Expanded(
                        child: Text(
                          '${item['currency'] ?? 'MYR'} ${item['totalPrice'] ?? '-'}',
                          style: const TextStyle(
                              fontSize: 20, fontWeight: FontWeight.w900),
                        ),
                      ),
                      FilledButton.tonal(
                        onPressed: () => selectRental(item),
                        child: const Text('Select'),
                      ),
                    ]),
                  ],
                ),
              ),
            );
          }),
        ],
      ),
    );
  }
}
