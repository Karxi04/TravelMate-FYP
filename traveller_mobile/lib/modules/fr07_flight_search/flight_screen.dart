import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'flight_details_screen.dart';

class FlightScreen extends StatefulWidget {
  final String? initialOutboundDate;
  final String? initialReturnDate;
  final String? initialDeparture;
  final String? initialArrival;
  final ApiService? api;

  const FlightScreen({
    super.key,
    this.initialOutboundDate,
    this.initialReturnDate,
    this.initialDeparture,
    this.initialArrival,
    this.api,
  });

  @override
  State<FlightScreen> createState() => _FlightScreenState();
}

class _FlightScreenState extends State<FlightScreen> {
  final from = TextEditingController(text: 'KUL');
  final to = TextEditingController(text: 'PEN');
  final travellers = TextEditingController(text: '1');
  late final TextEditingController outbound;
  late final TextEditingController returnDate;
  late final api = widget.api ?? ApiService();

  List<dynamic> items = [];
  final Set<String> compareIds = {};
  bool busy = false;
  bool roundTrip = false;
  bool nonstopOnly = false;
  String sort = 'top';
  String source = '';
  String searchId = '';
  bool returnLoading = false;

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
    if (picked != null) {
      setState(() => controller.text = dateText(picked));
    }
  }

  @override
  void initState() {
    super.initState();
    if ((widget.initialDeparture ?? '').trim().isNotEmpty)
      from.text = widget.initialDeparture!.trim();
    if ((widget.initialArrival ?? '').trim().isNotEmpty)
      to.text = widget.initialArrival!.trim();
    final start = DateTime.now().add(const Duration(days: 30));
    outbound = TextEditingController(
        text: widget.initialOutboundDate?.trim().isNotEmpty == true
            ? widget.initialOutboundDate!.trim()
            : dateText(start));
    returnDate = TextEditingController(
        text: widget.initialReturnDate?.trim().isNotEmpty == true
            ? widget.initialReturnDate!.trim()
            : dateText(start.add(const Duration(days: 3))));
    roundTrip = widget.initialReturnDate?.trim().isNotEmpty == true;
  }

  @override
  void dispose() {
    from.dispose();
    to.dispose();
    travellers.dispose();
    outbound.dispose();
    returnDate.dispose();
    super.dispose();
  }

  static const Map<String, String> cityToIata = {
    'KUALA LUMPUR': 'KUL',
    'KL': 'KUL',
    'KLIA': 'KUL',
    'PENANG': 'PEN',
    'GEORGETOWN': 'PEN',
    'GEORGE TOWN': 'PEN',
    'SINGAPORE': 'SIN',
    'CHANGI': 'SIN',
    'BANGKOK': 'BKK',
    'SUVARNABHUMI': 'BKK',
    'TOKYO': 'NRT',
    'NARITA': 'NRT',
    'HANEDA': 'HND',
    'SEOUL': 'ICN',
    'INCHEON': 'ICN',
    'HONG KONG': 'HKG',
    'HK': 'HKG',
    'LANGKAWI': 'LGK',
    'KOTA KINABALU': 'BKI',
    'KUCHING': 'KCH',
    'JOHOR BAHRU': 'JHB',
    'JB': 'JHB',
    'IPOH': 'IPH',
    'MELAKA': 'MKZ',
    'MALACCA': 'MKZ',
    'LONDON': 'LHR',
    'HEATHROW': 'LHR',
    'SYDNEY': 'SYD',
    'MELBOURNE': 'MEL',
    'BALI': 'DPS',
    'DENPASAR': 'DPS',
    'JAKARTA': 'CGK',
    'TAIPEI': 'TPE',
    'OSAKA': 'KIX',
    'DUBAI': 'DXB',
  };

  String resolveIata(String input) {
    final cleaned = input.trim().toUpperCase();
    if (cleaned.length == 3 && RegExp(r'^[A-Z]{3}$').hasMatch(cleaned)) {
      return cleaned;
    }
    for (final entry in cityToIata.entries) {
      if (cleaned.contains(entry.key) || entry.key.contains(cleaned)) {
        return entry.value;
      }
    }
    return cleaned;
  }

  Future<void> search() async {
    final departure = resolveIata(from.text);
    final arrival = resolveIata(to.text);
    if (departure.length == 3) from.text = departure;
    if (arrival.length == 3) to.text = arrival;
    final travellerCount = int.tryParse(travellers.text.trim()) ?? 0;
    final outboundDate = parseDate(outbound.text);
    final inboundDate = roundTrip ? parseDate(returnDate.text) : null;
    if (departure.length != 3 || arrival.length != 3 || departure == arrival) {
      showError(context,
          'Enter 3-letter airport codes or supported city names (e.g. KUL, PEN, SIN).');
      return;
    }
    if (outboundDate == null || (roundTrip && inboundDate == null)) {
      showError(context, 'Choose valid flight dates.');
      return;
    }
    if (inboundDate != null && inboundDate.isBefore(outboundDate)) {
      showError(context, 'Return date must be after the outbound date.');
      return;
    }
    if (travellerCount <= 0) {
      showError(context, 'Travellers must be at least 1.');
      return;
    }
    setState(() {
      busy = true;
      compareIds.clear();
      returnLoading = false;
    });
    try {
      final query = <String, String>{
        'departure_id': departure,
        'arrival_id': arrival,
        'outbound_date': outbound.text.trim(),
        'currency': 'MYR',
        'traveller_count': travellerCount.toString(),
        if (roundTrip) 'return_date': returnDate.text.trim(),
        if (nonstopOnly) 'nonstop': 'true',
        if (sort == 'price') 'sort': 'price_low',
        if (sort == 'duration') 'sort': 'duration',
      };
      final data = await api.get('/api/fr7/flights/search', query);
      if (!mounted) return;
      setState(() {
        items = data['items'] ?? data['best_flights'] ?? [];
        source = (data['source'] ?? '').toString();
        searchId = (data['searchId'] ?? '').toString();
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String idOf(Map<String, dynamic> item) => (item['id'] ??
          '${item['airline']}_${item['flightNumber']}_${item['departureTime']}')
      .toString();

  Future<void> showDetails(Map<String, dynamic> item) async {
    try {
      final data = await api.post('/api/fr7/flights/details', {
        'flight': item,
        if (searchId.isNotEmpty) 'searchId': searchId,
        'optionId': idOf(item),
      });
      final flight = data['flight'] is Map
          ? Map<String, dynamic>.from(data['flight'] as Map)
          : Map<String, dynamic>.from(item);
      if (!mounted) return;
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => FlightDetailsScreen(
            flight: flight,
            onSelect: () {
              Navigator.pop(context);
              roundTrip ? chooseReturn(flight) : selectFlight(flight);
            },
          ),
        ),
      );
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> chooseReturn(Map<String, dynamic> outboundFlight) async {
    if (!roundTrip || searchId.isEmpty) return;
    setState(() => returnLoading = true);
    try {
      final data = await api.post('/api/fr7/flights/returns', {
        'searchId': searchId,
        'optionId': idOf(outboundFlight),
      });
      final returns = (data['items'] as List? ?? [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
      if (!mounted) return;
      if (returns.isEmpty) {
        showError(context,
            'No compatible return flight was found. Try another outbound option.');
        return;
      }
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(18, 0, 18, 20),
            children: [
              const Text('Choose your return flight',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
              const SizedBox(height: 6),
              const Text(
                  'Return flights remain useful planning references. Their combined price basis is not established, so round-trip Checkout stays blocked.'),
              const SizedBox(height: 10),
              ...returns.map((item) => ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(
                        '${item['airline'] ?? 'Flight'} ${item['flightNumber'] ?? ''}'),
                    subtitle: Text(
                        '${item['departureAirport'] ?? ''} ${item['departureTime'] ?? ''} → ${item['arrivalAirport'] ?? ''} ${item['arrivalTime'] ?? ''}'),
                    trailing: const Icon(Icons.arrow_forward_rounded),
                    onTap: () => Navigator.pop(context, item),
                  )),
            ],
          ),
        ),
      );
      if (selected != null)
        await selectFlight(outboundFlight, returnOptionId: idOf(selected));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => returnLoading = false);
    }
  }

  Future<void> compare() async {
    final selected = items
        .where((raw) =>
            compareIds.contains(idOf(Map<String, dynamic>.from(raw as Map))))
        .map((raw) => Map<String, dynamic>.from(raw as Map))
        .toList();
    if (selected.length < 2) {
      showError(context, 'Select at least two flights to compare.');
      return;
    }
    try {
      final data =
          await api.post('/api/fr7/flights/compare', {'items': selected});
      final compared = data['items'] as List? ?? selected;
      if (!mounted) return;
      showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        builder: (context) => DraggableScrollableSheet(
          expand: false,
          initialChildSize: .65,
          maxChildSize: .9,
          builder: (context, controller) => ListView(
            controller: controller,
            padding: const EdgeInsets.fromLTRB(18, 0, 18, 24),
            children: [
              const Text('Flight comparison',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
              const SizedBox(height: 10),
              ...compared.asMap().entries.map((entry) {
                final f = Map<String, dynamic>.from(entry.value as Map);
                return Padding(
                  padding: const EdgeInsets.only(bottom: 9),
                  child: InkCard(
                    color: entry.key == 0 ? InkWashColors.cream : null,
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                              '${entry.key == 0 ? 'Best value • ' : ''}${f['airline']} ${f['flightNumber']}',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w900)),
                          Text(
                              '${f['departureTime']} → ${f['arrivalTime']} • ${f['durationMinutes']} min • ${f['stopText']}'),
                          Text('${f['currency'] ?? 'MYR'} ${f['price']}',
                              style: const TextStyle(
                                  fontSize: 17, fontWeight: FontWeight.w900)),
                          Text(f['checkoutEligible'] == true
                              ? 'Single-adult one-way ticket reference; extras may apply.'
                              : 'Indicative price only; excluded from budget and Checkout.'),
                        ]),
                  ),
                );
              }),
            ],
          ),
        ),
      );
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> selectFlight(Map<String, dynamic> flight,
      {String? returnOptionId}) async {
    try {
      final data = await api.get('/api/fr5/itineraries');
      final trips = data['items'] as List? ?? [];
      if (!mounted) return;
      if (trips.isEmpty) {
        final createNow = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Create Itinerary for Flight?'),
            content: Text(
                'No active itineraries were found. Would you like to create a new itinerary to ${flight['arrivalAirport'] ?? 'your destination'} with this flight attached?'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Create Itinerary')),
            ],
          ),
        );
        if (createNow != true) return;
        final start = flight['outboundDate'] ??
            dateText(DateTime.now().add(const Duration(days: 14)));
        final end = flight['returnDate'] ?? start;
        final price = double.tryParse('${flight['price'] ?? 0}') ?? 0.0;
        final newTrip = await api.post('/api/fr5/itineraries', {
          'title': 'Trip to ${flight['arrivalAirport'] ?? 'Destination'}',
          'destinationArea': flight['arrivalAirport'] ?? to.text.trim(),
          'startDate': start,
          'endDate': end,
          'travellerCount': int.tryParse(travellers.text.trim()) ?? 1,
          'budgetLimit': price > 0 ? price * 3 : 1500.0,
          'activities': [],
        });
        final created = newTrip['itinerary'] is Map
            ? Map<String, dynamic>.from(newTrip['itinerary'] as Map)
            : <String, dynamic>{};
        if ((created['id'] ?? '').toString().isNotEmpty) {
          await api.post('/api/fr7/flights/select', {
            'itineraryId': created['id'],
            'searchId': searchId,
            'optionId': idOf(flight),
            if (returnOptionId != null) 'returnOptionId': returnOptionId,
            'flight': flight,
          });
        }
        if (mounted) {
          final tripTitle = newTrip['itinerary']?['title'] ?? 'New trip';
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content:
                    Text('Created "$tripTitle" with this flight attached!')),
          );
        }
        return;
      }
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(18, 0, 18, 20),
            children: [
              const Text('Attach flight to itinerary',
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
                  subtitle: Text('Budget RM ${trip['budgetLimit'] ?? 0}'),
                  onTap: () => Navigator.pop(context, trip),
                );
              }),
            ],
          ),
        ),
      );
      if (selected == null) return;
      final result = await api.post('/api/fr7/flights/select', {
        'itineraryId': selected['id'],
        'searchId': searchId,
        'optionId': idOf(flight),
        if (returnOptionId != null) 'returnOptionId': returnOptionId,
        'flight': flight,
      });
      if (mounted) {
        final budget = result['budget'] is Map
            ? Map<String, dynamic>.from(result['budget'] as Map)
            : <String, dynamic>{};
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text(
                  'Flight selected. New estimated trip total: RM ${budget['total'] ?? '-'}')),
        );
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Flights'),
        actions: [
          if (compareIds.length >= 2)
            TextButton.icon(
                onPressed: compare,
                icon: const Icon(Icons.compare_arrows_rounded),
                label: Text('Compare ${compareIds.length}')),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 6, 18, 28),
        children: [
          const TravelSectionHeader(
              title: 'Search & compare flights',
              subtitle:
                  'Search and compare available flight options. Live provider results are used when the cloud service is configured.'),
          const SizedBox(height: 12),
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(
                  value: false,
                  label: Text('One way'),
                  icon: Icon(Icons.arrow_forward_rounded)),
              ButtonSegment(
                  value: true,
                  label: Text('Round trip'),
                  icon: Icon(Icons.sync_alt_rounded))
            ],
            selected: {roundTrip},
            onSelectionChanged: (value) =>
                setState(() => roundTrip = value.first),
          ),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
                child: TextField(
                    controller: from,
                    textCapitalization: TextCapitalization.characters,
                    decoration: const InputDecoration(
                        labelText: 'From', hintText: 'KUL'))),
            const Padding(
                padding: EdgeInsets.symmetric(horizontal: 5),
                child: Icon(Icons.arrow_forward_rounded)),
            Expanded(
                child: TextField(
                    controller: to,
                    textCapitalization: TextCapitalization.characters,
                    decoration: const InputDecoration(
                        labelText: 'To', hintText: 'PEN'))),
          ]),
          const SizedBox(height: 9),
          TextField(
            controller: travellers,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Adults',
              prefixIcon: Icon(Icons.people_outline_rounded),
            ),
          ),
          const SizedBox(height: 9),
          Row(children: [
            Expanded(
              child: TextField(
                controller: outbound,
                readOnly: true,
                onTap: () => pickDate(outbound),
                decoration: const InputDecoration(
                    labelText: 'Outbound date',
                    prefixIcon: Icon(Icons.calendar_today_outlined)),
              ),
            ),
            if (roundTrip) ...[
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                  controller: returnDate,
                  readOnly: true,
                  onTap: () =>
                      pickDate(returnDate, firstDate: parseDate(outbound.text)),
                  decoration: const InputDecoration(
                      labelText: 'Return date',
                      prefixIcon: Icon(Icons.event_repeat_outlined)),
                ),
              ),
            ],
          ]),
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilterChip(
                selected: nonstopOnly,
                label: const Text('Nonstop only'),
                avatar: const Icon(Icons.flight_rounded, size: 17),
                onSelected: (v) => setState(() => nonstopOnly = v)),
            ChoiceChip(
                selected: sort == 'top',
                label: const Text('Top'),
                onSelected: (_) => setState(() => sort = 'top')),
            ChoiceChip(
                selected: sort == 'price',
                label: const Text('Lowest price'),
                onSelected: (_) => setState(() => sort = 'price')),
            ChoiceChip(
                selected: sort == 'duration',
                label: const Text('Shortest'),
                onSelected: (_) => setState(() => sort = 'duration')),
          ]),
          const SizedBox(height: 10),
          FilledButton.icon(
              onPressed: busy ? null : search,
              icon: const Icon(Icons.search_rounded),
              label: Text(busy ? 'Searching...' : 'Search flights')),
          if (source.isNotEmpty) ...[
            const SizedBox(height: 10),
            TravelStatusPill(
                text: source == 'serpapi'
                    ? 'PROVIDER RESULTS • PLANNING REFERENCE'
                    : 'EXPLICIT SAMPLE FIXTURE • NOT A CURRENT SCHEDULE',
                icon: source == 'serpapi'
                    ? Icons.cloud_done_outlined
                    : Icons.science_outlined),
          ],
          const SizedBox(height: 18),
          if (items.isEmpty && !busy)
            const TravelEmptyState(
                icon: Icons.flight_takeoff_rounded,
                title: 'Search for a flight',
                message:
                    'Results can be viewed, compared and attached to your itinerary budget.'),
          ...items.map((raw) {
            final item = Map<String, dynamic>.from(raw as Map);
            final id = idOf(item);
            final selected = compareIds.contains(id);
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: InkWell(
                borderRadius: BorderRadius.circular(20),
                onTap: () => showDetails(item),
                child: InkCard(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Expanded(
                              child: Text(
                                  '${item['airline'] ?? 'Flight'} ${item['flightNumber'] ?? ''}',
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w900,
                                      fontSize: 17))),
                          Checkbox(
                            value: selected,
                            onChanged: (v) => setState(() {
                              if (v == true) {
                                compareIds.add(id);
                              } else {
                                compareIds.remove(id);
                              }
                            }),
                          ),
                        ]),
                        Text(
                            '${item['departureAirport'] ?? ''} ${item['departureTime'] ?? ''}  →  ${item['arrivalAirport'] ?? ''} ${item['arrivalTime'] ?? ''}',
                            style:
                                const TextStyle(fontWeight: FontWeight.w700)),
                        const SizedBox(height: 7),
                        Wrap(spacing: 7, runSpacing: 7, children: [
                          TravelStatusPill(
                              text: '${item['durationMinutes'] ?? '-'} min',
                              icon: Icons.schedule_outlined),
                          TravelStatusPill(
                              text: (item['stopText'] ?? '-').toString(),
                              icon: Icons.alt_route_rounded),
                          TravelStatusPill(
                              text:
                                  '${item['travellerCount'] ?? travellers.text} traveller(s)',
                              icon: Icons.people_outline_rounded),
                          if ((item['priceBasis'] ?? '').toString().isNotEmpty)
                            TravelStatusPill(
                                text: item['checkoutEligible'] == true
                                    ? 'Single-adult one-way ticket reference'
                                    : 'Indicative price; excluded from budget and Checkout',
                                icon: Icons.payments_outlined),
                        ]),
                        const SizedBox(height: 10),
                        Row(children: [
                          Expanded(
                              child: Text(
                                  '${item['currency'] ?? 'MYR'} ${item['price'] ?? '-'}',
                                  style: const TextStyle(
                                      fontSize: 20,
                                      fontWeight: FontWeight.w900))),
                          OutlinedButton(
                              onPressed: () => showDetails(item),
                              child: const Text('Details')),
                          const SizedBox(width: 6),
                          FilledButton.tonal(
                              onPressed: returnLoading
                                  ? null
                                  : () => roundTrip
                                      ? chooseReturn(item)
                                      : selectFlight(item),
                              child:
                                  Text(roundTrip ? 'Choose return' : 'Select')),
                        ]),
                      ]),
                ),
              ),
            );
          }),
        ],
      ),
    );
  }
}
