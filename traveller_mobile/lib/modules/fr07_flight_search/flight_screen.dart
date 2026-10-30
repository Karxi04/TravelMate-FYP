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
  late final ApiService api;

  List<dynamic> items = [];
  final Set<String> compareIds = {};
  bool busy = false;
  bool roundTrip = false;
  bool nonstopOnly = false;
  String sort = 'top';
  int travelClass = 1;

  String source = '';
  String sourceLabel = '';
  String searchId = '';
  String? retrievedAt;
  String? expiresAt;
  String freshnessStatus = '';
  bool planningOnly = true;
  String quoteCompleteness = '';
  String selectionStage = '';
  bool returnLoading = false;
  String? _quotedCriteria;

  String _criteriaKey() => [from.text.trim().toUpperCase(), to.text.trim().toUpperCase(),
    outbound.text.trim(), if (roundTrip) returnDate.text.trim(), travellers.text.trim(),
    roundTrip, travelClass, nonstopOnly, sort].join('|');

  void _clearResults() {
    items = [];
    compareIds.clear();
    searchId = '';
    source = '';
    sourceLabel = '';
    expiresAt = null;
    _quotedCriteria = null;
  }

  void _invalidateResults() {
    if (_quotedCriteria != null) setState(_clearResults);
  }

  bool _quoteMatchesCriteria() {
    if (_quotedCriteria != null && _quotedCriteria == _criteriaKey()) return true;
    showError(context, 'Search again after changing your flight details.');
    return false;
  }

  String dateText(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  DateTime? parseDate(String value) => DateTime.tryParse(value.trim());

  bool isQuoteExpired() {
    if (expiresAt == null || expiresAt!.isEmpty) return false;
    final exp = DateTime.tryParse(expiresAt!);
    if (exp == null) return false;
    return exp.toUtc().isBefore(DateTime.now().toUtc());
  }

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
    api = widget.api ?? ApiService();
    if ((widget.initialDeparture ?? '').trim().isNotEmpty) {
      from.text = widget.initialDeparture!.trim();
    }
    if ((widget.initialArrival ?? '').trim().isNotEmpty) {
      to.text = widget.initialArrival!.trim();
    }
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
    for (final controller in [from, to, travellers, outbound, returnDate]) {
      controller.addListener(_invalidateResults);
    }
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
    if (cleaned.isEmpty) return cleaned;
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
    final travellerCount = int.tryParse(travellers.text.trim());
    final outboundDate = parseDate(outbound.text);
    final inboundDate = roundTrip ? parseDate(returnDate.text) : null;
    final today = DateTime.now();
    final todayMidnight = DateTime(today.year, today.month, today.day);

    if (departure.length != 3 || arrival.length != 3 || departure == arrival) {
      showError(context,
          'Enter 3-letter airport codes or supported city names (e.g. KUL, PEN, SIN) and ensure departure and arrival airports differ.');
      return;
    }
    if (outboundDate == null || outboundDate.isBefore(todayMidnight)) {
      showError(context, 'Choose a current or future outbound date.');
      return;
    }
    if (roundTrip &&
        (inboundDate == null || inboundDate.isBefore(outboundDate))) {
      showError(context, 'Return date must be on or after the outbound date.');
      return;
    }
    if (travellerCount == null || travellerCount <= 0) {
      showError(
          context, 'Travellers must be a positive whole number (at least 1).');
      return;
    }

    final requestedCriteria = _criteriaKey();
    setState(() {
      busy = true;
      _clearResults();
      returnLoading = false;
    });

    try {
      final query = <String, String>{
        'departure_id': departure,
        'arrival_id': arrival,
        'outbound_date': outbound.text.trim(),
        'currency': 'MYR',
        'traveller_count': travellerCount.toString(),
        'travel_class': travelClass.toString(),
        if (roundTrip) 'return_date': returnDate.text.trim(),
        if (nonstopOnly) 'nonstop': 'true',
        if (sort == 'price') 'sort': 'price_low',
        if (sort == 'duration') 'sort': 'duration',
      };
      final data = await api.get('/api/fr7/flights/search', query);
      if (!mounted) return;
      if (requestedCriteria != _criteriaKey()) return;
      setState(() {
        _quotedCriteria = requestedCriteria;
        items = data['items'] ?? data['best_flights'] ?? [];
        source = (data['source'] ?? '').toString();
        sourceLabel = (data['sourceLabel'] ?? '').toString();
        searchId = (data['searchId'] ?? '').toString();
        retrievedAt = data['retrievedAt']?.toString();
        expiresAt = data['expiresAt']?.toString();
        freshnessStatus = (data['freshnessStatus'] ?? '').toString();
        planningOnly = data['planningOnly'] != false;
        quoteCompleteness = (data['quoteCompleteness'] ?? '').toString();
        selectionStage = (data['selectionStage'] ?? '').toString();
      });
    } on ApiException catch (e) {
      if (mounted) {
        showError(context, e.message.isNotEmpty ? e.message : e.toString());
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String idOf(Map<String, dynamic> item) => (item['optionId'] ??
          item['id'] ??
          '${item['airline']}_${item['flightNumber']}_${item['departureTime']}')
      .toString();

  Future<void> showDetails(Map<String, dynamic> item) async {
    if (!_quoteMatchesCriteria()) return;
    final requestedSearch = searchId;
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
      if (requestedSearch != searchId || !_quoteMatchesCriteria()) return;
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
    } on ApiException catch (e) {
      if (mounted) {
        if (e.code == 'flight_quote_expired') {
          showError(
              context, 'This flight quote has expired. Please search again.');
        } else {
          showError(context, e.message.isNotEmpty ? e.message : e.toString());
        }
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> chooseReturn(Map<String, dynamic> outboundFlight) async {
    if (!_quoteMatchesCriteria()) return;
    if (!roundTrip || searchId.isEmpty) return;
    final outboundSearch = searchId;
    if (isQuoteExpired()) {
      showError(
          context, 'This flight quote has expired. Please search again.');
      return;
    }
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
      if (outboundSearch != searchId || !_quoteMatchesCriteria()) return;
      if (returns.isEmpty) {
        showError(context,
            'No compatible return flight was found. Try another outbound option.');
        return;
      }
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(18, 0, 18, 20),
            child: ListView(
              shrinkWrap: true,
              children: [
                const Text('Choose your return flight',
                    style:
                        TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
                const SizedBox(height: 4),
                Text(
                  'Outbound: ${outboundFlight['airline'] ?? 'Flight'} ${outboundFlight['flightNumber'] ?? ''} (${outboundFlight['departureAirport'] ?? ''} → ${outboundFlight['arrivalAirport'] ?? ''})',
                  style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      color: InkWashColors.blueGrey),
                ),
                const SizedBox(height: 6),
                const Text(
                  'Each return option displays the complete provider round-trip fare.',
                  style:
                      TextStyle(fontSize: 13, color: InkWashColors.mutedInk),
                ),
                const SizedBox(height: 12),
                ...returns.map((item) {
                  final fare = item['price'] ?? item['combinedPrice'];
                  final fareText =
                      fare != null ? 'RM $fare' : 'Price unavailable';
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(16),
                      onTap: () => Navigator.pop(context, item),
                      child: InkCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    '${item['airline'] ?? 'Flight'} ${item['flightNumber'] ?? ''}',
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w800,
                                        fontSize: 16),
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 10, vertical: 4),
                                  decoration: BoxDecoration(
                                    color: InkWashColors.cream,
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Text(
                                    fareText,
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w900,
                                      fontSize: 15,
                                      color: InkWashColors.ink,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${item['departureAirport'] ?? ''} ${item['departureTime'] ?? ''} → ${item['arrivalAirport'] ?? ''} ${item['arrivalTime'] ?? ''}',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${item['durationMinutes'] ?? '-'} min • ${item['stopText'] ?? (item['stops'] == 0 ? 'Nonstop' : '1 stop')} • Total round-trip fare: $fareText',
                              style: const TextStyle(
                                  fontSize: 12, color: InkWashColors.mutedInk),
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                }),
              ],
            ),
          ),
        ),
      );
      if (selected != null) {
        await selectFlight(outboundFlight, returnOption: selected);
      }
    } on ApiException catch (e) {
      if (mounted) {
        if (e.code == 'flight_quote_expired') {
          showError(
              context, 'This flight quote has expired. Please search again.');
        } else {
          showError(context, e.message.isNotEmpty ? e.message : e.toString());
        }
      }
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
                          Text('RM ${f['price']}',
                              style: const TextStyle(
                                  fontSize: 17, fontWeight: FontWeight.w900)),
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

  Future<bool?> _showHardDateConflictDialog(
    BuildContext context, {
    required String code,
    required String message,
    Map<String, dynamic>? tripDates,
    List<dynamic>? flightDates,
    List<dynamic>? conflicts,
  }) async {
    String tripRangeText = '';
    if (tripDates != null) {
      final start = (tripDates['startDate'] ?? '').toString();
      final end = (tripDates['endDate'] ?? '').toString();
      if (start.isNotEmpty && end.isNotEmpty) {
        tripRangeText = '$start to $end';
      } else if (start.isNotEmpty) {
        tripRangeText = start;
      }
    }

    String flightDatesText = '';
    if (flightDates != null && flightDates.isNotEmpty) {
      flightDatesText = flightDates.map((d) => d.toString()).toSet().join(', ');
    }

    return showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        key: const ValueKey('flight-date-conflict-dialog'),
        title: const Row(
          children: [
            Icon(Icons.calendar_today_outlined, color: AppColors.error),
            SizedBox(width: 8),
            Expanded(
              child: Text(
                'Flight Dates Mismatch',
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18),
              ),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'These flights fall outside your selected Trip dates. Choose a Trip with matching dates or update your Trip before adding the flights.',
              style: TextStyle(fontSize: 14),
            ),
            const SizedBox(height: 12),
            if (tripRangeText.isNotEmpty) ...[
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                margin: const EdgeInsets.only(bottom: 6),
                decoration: BoxDecoration(
                  color: AppColors.primarySoft,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Trip Dates',
                        style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            color: AppColors.textSecondary)),
                    Text(tripRangeText,
                        style: const TextStyle(
                            fontSize: 13, fontWeight: FontWeight.w600)),
                  ],
                ),
              ),
            ],
            if (flightDatesText.isNotEmpty) ...[
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                decoration: BoxDecoration(
                  color: AppColors.warningSoft,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Flight Dates',
                        style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            color: AppColors.warning)),
                    Text(flightDatesText,
                        style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: AppColors.textPrimary)),
                  ],
                ),
              ),
            ],
            if (code == 'invalid_trip_dates' || code == 'invalid_flight_dates') ...[
              const SizedBox(height: 8),
              Text(
                message,
                style: const TextStyle(fontSize: 12, color: AppColors.error),
              ),
            ],
          ],
        ),
        actions: [
          TextButton(
            key: const ValueKey('back-to-flight-results-button'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Back to Flight Results'),
          ),
          FilledButton(
            key: const ValueKey('choose-another-trip-button'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Choose Another Trip'),
          ),
        ],
      ),
    );
  }

  Future<void> selectFlight(Map<String, dynamic> flight,
      {Map<String, dynamic>? returnOption}) async {
    if (!_quoteMatchesCriteria()) return;
    if (isQuoteExpired()) {
      showError(
          context, 'This flight quote has expired. Please search again.');
      return;
    }
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
        final double effectivePrice = returnOption != null &&
                returnOption['price'] != null
            ? (double.tryParse('${returnOption['price']}') ?? 0.0)
            : (double.tryParse('${flight['price'] ?? 0}') ?? 0.0);
        final newTrip = await api.post('/api/fr5/itineraries', {
          'title': 'Trip to ${flight['arrivalAirport'] ?? 'Destination'}',
          'startDate': start,
          'endDate': end,
          'travellerCount': int.tryParse(travellers.text.trim()) ?? 1,
          'budgetLimit': effectivePrice > 0 ? effectivePrice * 3 : 1500.0,
          'activities': [],
        });
        final created = newTrip['itinerary'] is Map
            ? Map<String, dynamic>.from(newTrip['itinerary'] as Map)
            : <String, dynamic>{};
        if ((created['id'] ?? '').toString().isNotEmpty) {
          try {
            await api.post('/api/fr7/flights/select', {
              'itineraryId': created['id'],
              'searchId': searchId,
              'optionId': idOf(flight),
              if (returnOption != null) 'returnOptionId': idOf(returnOption),
              'flight': flight,
            });
          } on ApiException catch (error) {
            if (error.code == 'flight_quote_expired') {
              if (mounted) {
                showError(context,
                    'This flight quote has expired. Please search again.');
              }
              return;
            }
            if (error.data['status'] == 'hard_conflict' ||
                error.code == 'flight_trip_date_mismatch' ||
                error.code == 'invalid_trip_dates' ||
                error.code == 'invalid_flight_dates') {
              if (!mounted) return;
              await _showHardDateConflictDialog(
                context,
                code: error.code ?? '',
                message: error.message,
                tripDates: error.data['tripDates'] is Map
                    ? Map<String, dynamic>.from(error.data['tripDates'] as Map)
                    : null,
                flightDates: error.data['flightDates'] is List
                    ? (error.data['flightDates'] as List)
                    : null,
                conflicts: error.data['conflicts'] is List
                    ? (error.data['conflicts'] as List)
                    : null,
              );
              return;
            }
            rethrow;
          }
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
      while (true) {
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
                Text('Selected offer estimate: ${flight['currency'] ?? 'Currency unavailable'} ${returnOption?['combinedPrice'] ?? returnOption?['price'] ?? flight['price'] ?? 'Unavailable'}'),
                Text('${flight['departureAirport'] ?? '-'} → ${flight['arrivalAirport'] ?? '-'}${returnOption == null ? '' : ' · return included'}'),
                const Text('Adding this offer saves a planning estimate, not an airline ticket. Purchase must be arranged outside TravelMate.'),
                const SizedBox(height: 8),
                ...trips.map((raw) {
                  final trip = Map<String, dynamic>.from(raw as Map);
                  final dates = [trip['startDate'], trip['endDate']]
                      .where((d) => d != null && d.toString().isNotEmpty)
                      .join(' to ');
                  final subtitleText = dates.isNotEmpty
                      ? '$dates • Budget RM ${trip['budgetLimit'] ?? 0}'
                      : 'Budget RM ${trip['budgetLimit'] ?? 0}';
                  return ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const CircleAvatar(
                        backgroundColor: InkWashColors.cream,
                        child: Icon(Icons.luggage_outlined,
                            color: InkWashColors.blueGrey)),
                    title: Text((trip['title'] ?? 'Trip').toString()),
                    subtitle: Text(subtitleText),
                    onTap: () => Navigator.pop(context, trip),
                  );
                }),
              ],
            ),
          ),
        );
        if (selected == null) return;
        final request = <String, dynamic>{
          'itineraryId': selected['id'],
          'searchId': searchId,
          'optionId': idOf(flight),
          if (returnOption != null) 'returnOptionId': idOf(returnOption),
          'flight': flight,
        };
        Map<String, dynamic> result;
        try {
          result = await api.post('/api/fr7/flights/select', request);
        } on ApiException catch (error) {
          if (error.code == 'flight_quote_expired') {
            if (mounted) {
              showError(
                  context, 'This flight quote has expired. Please search again.');
            }
            return;
          }
          if (error.data['status'] == 'hard_conflict' ||
              error.code == 'flight_trip_date_mismatch' ||
              error.code == 'invalid_trip_dates' ||
              error.code == 'invalid_flight_dates') {
            if (!mounted) return;
            final chooseAnother = await _showHardDateConflictDialog(
              context,
              code: error.code ?? '',
              message: error.message,
              tripDates: error.data['tripDates'] is Map
                  ? Map<String, dynamic>.from(error.data['tripDates'] as Map)
                  : null,
              flightDates: error.data['flightDates'] is List
                  ? (error.data['flightDates'] as List)
                  : null,
              conflicts: error.data['conflicts'] is List
                  ? (error.data['conflicts'] as List)
                  : null,
            );
            if (chooseAnother == true) {
              continue;
            }
            return;
          }
          if (error.data['status'] != 'conflicts_require_acknowledgement') {
            rethrow;
          }
          final conflicts = (error.data['conflicts'] as List? ?? const [])
              .whereType<Map>()
              .map((item) => item['message']?.toString())
              .whereType<String>()
              .toList();
          if (!mounted) return;
          final acknowledge = await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('Review itinerary timing'),
              content: Text(conflicts.isEmpty
                  ? 'This flight may overlap your saved itinerary activities.'
                  : '${conflicts.join('\n\n')}\n\nYou can keep the flight and review these activities afterwards.'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('Choose another flight')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('Keep flight')),
              ],
            ),
          );
          if (acknowledge != true) return;
          result = await api.post('/api/fr7/flights/select', {
            ...request,
            'acknowledgeConflicts': true,
          });
        }
        if (mounted) {
          final budget = result['budget'] is Map
              ? Map<String, dynamic>.from(result['budget'] as Map)
              : <String, dynamic>{};
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text(
                    'Flight attached to trip plan! Estimated trip total: RM ${budget['total'] ?? '-'}')),
          );
        }
        break;
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
            onSelectionChanged: (value) => setState(() {
              roundTrip = value.first;
              _clearResults();
            }),
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
          Row(children: [
            Expanded(
              child: TextField(
                controller: travellers,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Travellers',
                  prefixIcon: Icon(Icons.people_outline_rounded),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: DropdownButtonFormField<int>(
                initialValue: travelClass,
                decoration: const InputDecoration(
                  labelText: 'Cabin class',
                  prefixIcon: Icon(Icons.airline_seat_recline_normal_rounded),
                ),
                items: const [
                  DropdownMenuItem(value: 1, child: Text('Economy')),
                  DropdownMenuItem(value: 2, child: Text('Premium')),
                  DropdownMenuItem(value: 3, child: Text('Business')),
                  DropdownMenuItem(value: 4, child: Text('First')),
                ],
                onChanged: (val) {
                  if (val != null) setState(() { travelClass = val; _clearResults(); });
                },
              ),
            ),
          ]),
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
                onSelected: (v) => setState(() { nonstopOnly = v; _clearResults(); })),
            ChoiceChip(
                selected: sort == 'top',
                label: const Text('Top'),
                onSelected: (_) => setState(() { sort = 'top'; _clearResults(); })),
            ChoiceChip(
                selected: sort == 'price',
                label: const Text('Lowest price'),
                onSelected: (_) => setState(() { sort = 'price'; _clearResults(); })),
            ChoiceChip(
                selected: sort == 'duration',
                label: const Text('Shortest'),
                onSelected: (_) => setState(() { sort = 'duration'; _clearResults(); })),
          ]),
          const SizedBox(height: 10),
          FilledButton.icon(
              onPressed: busy ? null : search,
              icon: const Icon(Icons.search_rounded),
              label: Text(busy ? 'Searching...' : 'Search flights')),
          if (searchId.isNotEmpty) ...[
            const SizedBox(height: 10),
            if (isQuoteExpired())
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF3CD),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: const Color(0xFFFFEEBA)),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.timer_off_outlined,
                        color: Color(0xFF856404), size: 20),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Flight quote expired. Please search again for current fares.',
                        style: TextStyle(
                            color: Color(0xFF856404),
                            fontWeight: FontWeight.w600,
                            fontSize: 13),
                      ),
                    ),
                  ],
                ),
              )
            else
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: InkWashColors.cream,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: const Color(0xFFE7E7E2)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(
                          source == 'serpapi'
                              ? Icons.cloud_done_outlined
                              : Icons.science_outlined,
                          size: 18,
                          color: InkWashColors.blueGrey,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            source == 'serpapi'
                                ? 'Provider search results • Planning estimate'
                                : 'Explicit sample fixture • Not a current schedule',
                            style: const TextStyle(
                                fontWeight: FontWeight.w800, fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'Flight planning estimate — provider caching may apply. Price and availability are not guaranteed.',
                      style: TextStyle(
                          fontSize: 12, color: InkWashColors.mutedInk),
                    ),
                  ],
                ),
              ),
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
                                text: (item['priceBasis'] ?? '').toString(),
                                icon: Icons.payments_outlined),
                        ]),
                        const SizedBox(height: 10),
                        Row(children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  roundTrip
                                      ? 'From ${item['currency'] ?? 'MYR'} ${item['price'] ?? '-'}'
                                      : '${item['currency'] ?? 'MYR'} ${item['price'] ?? '-'}',
                                  style: const TextStyle(
                                      fontSize: 19,
                                      fontWeight: FontWeight.w900),
                                ),
                                if (roundTrip)
                                  const Text(
                                    'Round-trip estimate • Choose return for final fare',
                                    style: TextStyle(
                                        fontSize: 11,
                                        color: InkWashColors.mutedInk),
                                  ),
                              ],
                            ),
                          ),
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
