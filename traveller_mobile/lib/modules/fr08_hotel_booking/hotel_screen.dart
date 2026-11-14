import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'hotel_details_screen.dart';
import 'room_offer_photo.dart';
import 'hotel_trip_attachment.dart';
import '../fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import '../fr09_payment/payment_history_screen.dart';
import '../fr09_payment/payment_screen.dart';
import '../fr09_payment/payment_status.dart';

class RoomOccupancyConfig {
  int adults;
  List<int?> childAges;

  RoomOccupancyConfig({
    this.adults = 2,
    List<int?>? childAges,
  }) : childAges = childAges ?? [];

  Map<String, dynamic> toJson() {
    final ages = childAges.whereType<int>().toList();
    return {
      'adults': adults,
      if (ages.isNotEmpty) 'children': ages,
    };
  }

  RoomOccupancyConfig clone() => RoomOccupancyConfig(
        adults: adults,
        childAges: List<int?>.from(childAges),
      );
}

class HotelScreen extends StatefulWidget {
  final String? targetTripId;
  final String? initialDestination;
  final String? initialCheckin;
  final String? initialCheckout;
  final int? initialAdults;
  final int? initialChildren;
  final bool requiresGuestConfirmation;
  final ApiService? api;

  const HotelScreen({
    super.key,
    this.targetTripId,
    this.initialDestination,
    this.initialCheckin,
    this.initialCheckout,
    this.initialAdults,
    this.initialChildren,
    this.requiresGuestConfirmation = false,
    this.api,
  });

  @override
  State<HotelScreen> createState() => _HotelScreenState();
}

class _HotelScreenState extends State<HotelScreen> {
  final hotelName = TextEditingController();
  int? nextHotelOffset;
  late final TextEditingController destination;
  late final TextEditingController checkin;
  late final TextEditingController checkout;
  late final TextEditingController adults;
  late final TextEditingController children;
  final roomQuantity = TextEditingController(text: '1');
  late final ApiService api;
  late final List<RoomOccupancyConfig> rooms;

  List<dynamic> items = [];
  final Set<String> compareIds = {};
  bool busy = false;
  bool refundableOnly = false;
  String sort = 'top';
  String source = '';
  bool hasSearched = false;
  String lastSearchedDestination = '';
  bool sampleContentLimited = false;
  Map<String, dynamic>? lastBooking;
  final Map<String, String> bookingAttemptIds = {};
  final Map<String, int> _selectedOfferIndexByProperty = {};
  String? _quotedCriteria;

  List<Map<String, dynamic>> get _groupedHotels {
    if (items.isEmpty) return const [];
    final Map<String, Map<String, dynamic>> groups = {};
    for (final raw in items) {
      if (raw is! Map) continue;
      final item = Map<String, dynamic>.from(raw);
      final hotelId = (item['hotelId'] ?? '').toString().trim();
      final id = (item['id'] ?? '').toString().trim();
      final offerId = (item['offerId'] ?? '').toString().trim();
      final name = (item['name'] ?? '').toString().trim();
      final address = (item['address'] ?? '').toString().trim();

      String key;
      if (hotelId.isNotEmpty) {
        key = hotelId;
      } else if (id.isNotEmpty && id != offerId) {
        key = id;
      } else if (name.isNotEmpty) {
        key = address.isNotEmpty ? '${name}_$address' : name;
      } else {
        key = 'prop_${item.hashCode}';
      }

      if (!groups.containsKey(key)) {
        groups[key] = {
          'propertyKey': key,
          'offers': <Map<String, dynamic>>[item],
        };
      } else {
        final offerList = groups[key]!['offers'] as List<Map<String, dynamic>>;
        if (offerId.isEmpty || !offerList.any((o) => (o['offerId'] ?? '').toString() == offerId)) {
          offerList.add(item);
        }
      }
    }
    return groups.values.toList();
  }

  String _resolveHotelPhoto(Map<String, dynamic> h) {
    final direct = (h['mainPhoto'] ?? h['main_photo'] ?? h['thumbnailUrl'] ?? h['thumbnail'] ?? '').toString().trim();
    if (direct.startsWith('http://') || direct.startsWith('https://')) {
      return direct;
    }
    for (final key in ['imageUrls', 'images', 'photos', 'roomImageUrls']) {
      final list = h[key];
      if (list is List && list.isNotEmpty) {
        for (final entry in list) {
          final u = (entry is Map ? (entry['url'] ?? entry['image']) : entry)?.toString().trim() ?? '';
          if (u.startsWith('http://') || u.startsWith('https://')) return u;
        }
      }
    }
    return '';
  }

  String _criteriaKey() => jsonEncode([hotelName.text.trim(), destination.text.trim(), checkin.text.trim(),
    checkout.text.trim(), adults.text.trim(), children.text.trim(),
    rooms.map((room) => [room.adults, room.childAges]).toList(), refundableOnly, sort]);

  void _clearResults() {
    nextHotelOffset = null;
    items = [];
    compareIds.clear();
    source = '';
    sampleContentLimited = false;
    _quotedCriteria = null;
    _selectedOfferIndexByProperty.clear();
  }

  void _invalidateResults() {
    if (_quotedCriteria != null) setState(_clearResults);
  }

  bool _quoteMatchesCriteria() {
    if (_quotedCriteria != null && _quotedCriteria == _criteriaKey()) return true;
    showError(context, 'Search again after changing your hotel dates or guests.');
    return false;
  }

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

  void syncTotals({bool fromAdultsController = false, bool fromChildrenController = false}) {
    int totalAdults = 0;
    int totalChildren = 0;
    for (final r in rooms) {
      totalAdults += r.adults;
      totalChildren += r.childAges.length;
    }
    if (!fromAdultsController) {
      adults.text = '$totalAdults';
    }
    if (!fromChildrenController) {
      children.text = '$totalChildren';
    }
    roomQuantity.text = '${rooms.length}';
    _invalidateResults();
    setState(() {});
  }

  void addRoom() {
    rooms.add(RoomOccupancyConfig(adults: 2, childAges: []));
    syncTotals();
  }

  void removeRoom(int index) {
    if (rooms.length > 1 && index < rooms.length) {
      rooms.removeAt(index);
      syncTotals();
    }
  }

  void setRoomAdults(int roomIndex, int count) {
    if (roomIndex < rooms.length && count >= 1) {
      rooms[roomIndex].adults = count;
      syncTotals();
    }
  }

  void setRoomChildren(int roomIndex, int count, {bool fromChildrenController = false}) {
    if (roomIndex < rooms.length && count >= 0) {
      final currentList = rooms[roomIndex].childAges;
      if (count > currentList.length) {
        currentList.addAll(List.generate(count - currentList.length, (_) => null));
      } else if (count < currentList.length) {
        rooms[roomIndex].childAges = currentList.sublist(0, count);
      }
      syncTotals(fromChildrenController: fromChildrenController);
    }
  }

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    final start = DateTime.now().add(const Duration(days: 30));
    final initialDest = widget.initialDestination?.trim();
    destination = TextEditingController(
        text: initialDest != null && initialDest.isNotEmpty
            ? initialDest
            : '');
    checkin = TextEditingController(
        text: widget.initialCheckin?.trim().isNotEmpty == true
            ? widget.initialCheckin!.trim()
            : dateText(start));
    checkout = TextEditingController(
        text: widget.initialCheckout?.trim().isNotEmpty == true
            ? widget.initialCheckout!.trim()
            : dateText(start.add(const Duration(days: 2))));
    adults = TextEditingController(
        text: widget.requiresGuestConfirmation && widget.initialAdults == null
            ? ''
            : '${widget.initialAdults ?? 2}');
    children = TextEditingController(text: '${widget.initialChildren ?? 0}');

    final initialAdultCount =
        widget.requiresGuestConfirmation && widget.initialAdults == null
            ? 2
            : (widget.initialAdults ?? 2);
    final initialChildCount = widget.initialChildren ?? 0;
    rooms = [
      RoomOccupancyConfig(
        adults: initialAdultCount,
        childAges: List.generate(initialChildCount, (_) => null),
      ),
    ];
    for (final controller in [destination, checkin, checkout, adults, children]) {
      controller.addListener(_invalidateResults);
    }
    hotelName.addListener(_invalidateResults);
  }

  @override
  void dispose() {
    hotelName.dispose();
    destination.dispose();
    checkin.dispose();
    checkout.dispose();
    adults.dispose();
    children.dispose();
    roomQuantity.dispose();
    super.dispose();
  }

  String idOf(Map<String, dynamic> item) =>
      (item['offerId'] ?? item['hotelId'] ?? item['name'] ?? '').toString();

  Future<void> search({bool loadMore = false}) async {
    if (busy) return;
    final checkinDate = parseDate(checkin.text);
    final checkoutDate = parseDate(checkout.text);
    if (destination.text.trim().isEmpty) {
      showError(context, 'Enter a destination.');
      return;
    }
    if (checkinDate == null || checkoutDate == null) {
      showError(context, 'Choose valid hotel dates.');
      return;
    }
    if (!checkoutDate.isAfter(checkinDate)) {
      showError(context, 'Check-out must be after check-in.');
      return;
    }
    if (widget.requiresGuestConfirmation && adults.text.trim().isEmpty) {
      showError(context,
          'Confirm the number of adults before searching for this Trip.');
      return;
    }
    final adultCount = int.tryParse(adults.text.trim()) ?? 0;
    final childCount = int.tryParse(children.text.trim()) ?? -1;
    final roomCount = rooms.length;
    if (adultCount <= 0) {
      showError(context, 'Adults must be at least 1.');
      return;
    }
    if (childCount < 0) {
      showError(context, 'Children cannot be negative.');
      return;
    }
    if (roomCount <= 0) {
      showError(context, 'Rooms must be at least 1.');
      return;
    }

    int sumAdults = 0;
    int sumChildren = 0;
    for (int i = 0; i < rooms.length; i++) {
      final r = rooms[i];
      if (r.adults < 1) {
        showError(context, 'Room ${i + 1} must have at least 1 adult.');
        return;
      }
      sumAdults += r.adults;
      sumChildren += r.childAges.length;
      for (int k = 0; k < r.childAges.length; k++) {
        final age = r.childAges[k];
        if (age == null || age < 0 || age > 17) {
          showError(context,
              'Please specify an age for Child ${k + 1} in Room ${i + 1} (0–17 years).');
          return;
        }
      }
    }
    if (sumAdults != adultCount || sumChildren != childCount) {
      showError(context, 'Total guests must match room allocations.');
      return;
    }

    final requestedCriteria = _criteriaKey();
    final previous = loadMore ? List<dynamic>.from(items) : <dynamic>[];
    final offset = loadMore ? nextHotelOffset : 0;
    if (offset == null) return;
    setState(() {
      busy = true;
      if (!loadMore) _clearResults();
      hasSearched = true;
      lastSearchedDestination = destination.text.trim();
    });
    try {
      final data = await api.post('/api/fr8/hotels/search', {
        if (hotelName.text.trim().isNotEmpty) 'hotelName': hotelName.text.trim(),
        'offset': offset, 'limit': 50,
        'destination': destination.text.trim(),
        'aiSearch': destination.text.trim(),
        'checkin': checkin.text.trim(),
        'checkout': checkout.text.trim(),
        'adults': adultCount,
        'children': childCount,
        'roomQuantity': roomCount,
        'occupancies': rooms.map((r) => r.toJson()).toList(),
        'currency': 'MYR',
        'guestNationality': 'MY',
        'refundable': refundableOnly,
        if (sort == 'price') 'sort': 'price_low',
        if (sort == 'rating') 'sort': 'rating',
      });
      if (!mounted) return;
      if (requestedCriteria != _criteriaKey()) return;
      setState(() {
        _quotedCriteria = requestedCriteria;
        final incoming = data['items'] ?? (data['result'] is Map ? data['result']['items'] ?? [] : []);
        final unique = <String, dynamic>{};
        for (final raw in [...previous, ...incoming as List]) {
          final item = Map<String, dynamic>.from(raw as Map);
          unique['${item['hotelId']}_${item['offerId']}'] = item;
        }
        items = unique.values.toList();
        nextHotelOffset = data['nextOffset'] as int?;
        source = (data['source'] ?? '').toString();
        sampleContentLimited = data['sampleContentLimited'] == true;
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> details(Map<String, dynamic> hotel) async {
    if (!mounted) return;
    if (!_quoteMatchesCriteria()) return;
    final propKey = (hotel['hotelId'] ?? hotel['id'] ?? hotel['name'] ?? '').toString().trim();
    Map<String, dynamic> activeOffer = Map<String, dynamic>.from(hotel);
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => HotelDetailsScreen(
          hotel: activeOffer,
          onOfferSelected: (newOffer) {
            activeOffer = Map<String, dynamic>.from(newOffer);
            final allOffers = (activeOffer['_allOffers'] as List?)?.whereType<Map<String, dynamic>>().toList() ?? [];
            final newIdx = allOffers.indexWhere((o) => o['offerId'] == activeOffer['offerId']);
            if (newIdx != -1 && propKey.isNotEmpty) {
              setState(() {
                _selectedOfferIndexByProperty[propKey] = newIdx;
              });
            }
          },
          onProceed: () {
            Navigator.pop(context);
            prebook(activeOffer);
          },
        ),
      ),
    );
  }

  bool _compatibleTrip(Map trip, Map stay) {
    if (trip['packageTrip'] == true || trip['tripType'] == 'package') return false;
    final checkIn = DateTime.tryParse('${stay['checkin'] ?? ''}');
    final checkOut = DateTime.tryParse('${stay['checkout'] ?? ''}');
    final start = DateTime.tryParse('${trip['startDate'] ?? ''}');
    final end = DateTime.tryParse('${trip['endDate'] ?? ''}');
    return checkIn != null && checkOut != null && start != null && end != null &&
        !checkIn.isBefore(start) && checkIn.isBefore(checkOut) && !checkOut.isAfter(end);
  }

  Future<Map<String, dynamic>?> chooseItinerary({Map<String, dynamic>? stay}) async {
    if (widget.targetTripId != null) {
      final data = await api.get('/api/fr5/itineraries/${Uri.encodeComponent(widget.targetTripId!)}');
      return Map<String, dynamic>.from(data['itinerary'] as Map);
    }
    final data = stay != null && stay['id'] != null && !api.isStandalone
        ? await api.get('/api/fr8/hotels/compatible-trips', {'acceptedPrebookSnapshotId': '${stay['id']}'})
        : await api.get('/api/fr5/itineraries');
    final trips = (data['items'] as List? ?? []).whereType<Map>()
        .where((trip) => stay == null || _compatibleTrip(trip, stay)).toList();
    if (!mounted) return null;
    if (trips.isEmpty) {
      final create = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('No compatible trips'),
          content: const Text('Choose a saved trip in the hotel destination that covers the whole stay, or plan a new trip.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Plan a trip')),
          ],
        ),
      );
      if (mounted && create == true) {
        await Navigator.push<void>(context, MaterialPageRoute(
          builder: (_) => PersonalizedPlanningScreen(api: api),
        ));
      }
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
            const Text('Add hotel details to which Trip?',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
            const SizedBox(height: 8),
            ...trips.map((raw) {
              final trip = Map<String, dynamic>.from(raw);
              return ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const CircleAvatar(
                    backgroundColor: InkWashColors.cream,
                    child: Icon(Icons.luggage_outlined,
                        color: InkWashColors.blueGrey)),
                title: Text((trip['title'] ?? 'Trip').toString()),
                subtitle: Text(
                    '${trip['destinationArea'] ?? ''} • Budget RM ${trip['budgetLimit'] ?? 0}'),
                onTap: () async {
                  if (stay == null) {
                    Navigator.pop(context, trip);
                    return;
                  }
                  final confirmed = await showDialog<bool>(
                    context: context,
                    builder: (ctx) => AlertDialog(
                      title: const Text('Add hotel to this trip?'),
                      content: Text((trip['title'] ?? 'Trip').toString()),
                      actions: [
                        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
                        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Add to Trip')),
                      ],
                    ),
                  );
                  if (context.mounted && confirmed == true) Navigator.pop(context, trip);
                },
              );
            }),
          ],
        ),
      ),
    );
  }

  Future<void> prebook(Map<String, dynamic> hotel) async {
    if (busy) return;
    if (!_quoteMatchesCriteria()) return;
    final requestedCriteria = _quotedCriteria;
    final offerId = (hotel['offerId'] ?? '').toString();
    if (offerId.isEmpty) {
      showError(
          context, 'This hotel result does not contain a bookable offer ID.');
      return;
    }
    final attemptId = bookingAttemptIds.putIfAbsent(
      '${hotel['quoteId']}|$offerId',
      () => newTransactionAttemptId('hotel'),
    );
    setState(() => busy = true);
    try {
      final request = <String, dynamic>{
        'offerId': offerId,
        'quoteId': hotel['quoteId'],
        'hotelBookingAttemptId': attemptId,
      };
      late Map<String, dynamic> data;
      try {
        data = Map<String, dynamic>.from(
            await api.post('/api/fr8/hotels/prebook', request));
      } on ApiException catch (error) {
        if (error.data['status'] == 'quote_expired') {
          if (!mounted) return;
          await showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              title: const Text('Quote Expired'),
              content: const Text(
                  'This hotel quote has expired. Please refresh search results to view current rates and availability.'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text('Cancel')),
                FilledButton(
                  onPressed: () {
                    Navigator.pop(ctx);
                    search();
                  },
                  child: const Text('Refresh Search'),
                ),
              ],
            ),
          );
          return;
        }
        if (error.data['status'] != 'reprice_required') rethrow;
        final latest = error.data['validatedOffer'] is Map
            ? Map<String, dynamic>.from(error.data['validatedOffer'] as Map)
            : <String, dynamic>{};
        final oldPrice = hotel['price'] ?? '-';
        final newPrice = latest['price'] ?? '-';
        final curr = latest['currency'] ?? hotel['currency'] ?? 'MYR';
        if (!mounted) rethrow;
        final accepted = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Price or terms updated'),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                      'The provider updated the price or terms for this offer:'),
                  const SizedBox(height: 8),
                  Text('Previous rate: $curr $oldPrice',
                      style: const TextStyle(
                          decoration: TextDecoration.lineThrough,
                          color: InkWashColors.mutedInk)),
                  Text('Updated rate: $curr $newPrice',
                      style: const TextStyle(
                          fontWeight: FontWeight.w900,
                          fontSize: 18,
                          color: InkWashColors.ink)),
                  const SizedBox(height: 10),
                  const Text(
                    'Provider rates and terms may change prior to checkout. Review the updated terms before accepting.',
                    style: TextStyle(
                        fontSize: 12, color: InkWashColors.mutedInk),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Accept updated price')),
            ],
          ),
        );
        if (accepted != true) return;
        request['acceptedQuoteVersion'] = error.data['quoteVersion'];
        data = Map<String, dynamic>.from(
            await api.post('/api/fr8/hotels/prebook', request));
      }
      if (!mounted || requestedCriteria != _criteriaKey() || requestedCriteria != _quotedCriteria) return;
      if (data['status'] == 'pending') {
        if (!mounted) return;
        setState(() => lastBooking = {
              'hotelBookingAttemptId': attemptId,
              'bookingStatus': 'pending',
              'confirmationLabel': 'Verification pending',
            });
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
            'The prebook outcome is being verified and was not submitted again.',
          ),
        ));
        return;
      }
      final result = data['result'] is Map
          ? Map<String, dynamic>.from(data['result'] as Map)
          : <String, dynamic>{};
      final acceptedPrebook = data['acceptedPrebook'] is Map
          ? Map<String, dynamic>.from(data['acceptedPrebook'] as Map)
          : null;
      final acceptedExpiry = DateTime.tryParse('${acceptedPrebook?['expiresAt'] ?? ''}');
      if (acceptedPrebook?['status'] == 'expired' ||
          (acceptedExpiry != null && !acceptedExpiry.isAfter(DateTime.now()))) {
        showError(context, 'This accepted hotel price has expired. Search again.');
        return;
      }
      final acceptedPrebookSnapshotId = (acceptedPrebook?['id'] ??
              data['acceptedPrebookSnapshotId'] ??
              data['acceptedPrebookId'] ??
              result['acceptedPrebookSnapshotId'] ??
              '')
          .toString();
      final validationId = (result['validationId'] ??
              result['prebookId'] ??
              acceptedPrebookSnapshotId)
          .toString();
      if (validationId.isEmpty) {
        throw Exception(
            'The hotel offer could not be validated. Search again.');
      }
      if (!mounted) return;
      setState(() => busy = false);
      final resultOffer = result['validatedOffer'] is Map
          ? Map<String, dynamic>.from(result['validatedOffer'] as Map)
          : result;
      final mergedHotel = {...hotel, ...resultOffer};
      if (acceptedPrebook != null && acceptedPrebook['amount'] != null) {
        mergedHotel['price'] = acceptedPrebook['amount'];
        mergedHotel['currency'] =
            acceptedPrebook['currency'] ?? mergedHotel['currency'];
      }

      await _showPrebookOutcomeSheet(
        hotel: mergedHotel,
        acceptedPrebook: acceptedPrebook,
        acceptedPrebookSnapshotId: acceptedPrebookSnapshotId,
        attemptId: attemptId,
        validationId: validationId,
      );
    } on TimeoutException {
      if (!mounted) return;
      setState(() => lastBooking = {
            'hotelBookingAttemptId': attemptId,
            'bookingStatus': 'pending',
            'confirmationLabel': 'Verification pending',
          });
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text(
          'The prebook request may still be completing. TravelMate will retain this booking attempt instead of creating another.',
        ),
      ));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _showPrebookOutcomeSheet({
    required Map<String, dynamic> hotel,
    required Map<String, dynamic>? acceptedPrebook,
    required String acceptedPrebookSnapshotId,
    required String attemptId,
    required String validationId,
  }) async {
    final canPay = acceptedPrebook?['checkoutEligible'] != false &&
        (await loadHostedCheckoutCapabilities(api)).contains('hotel');
    if (!mounted) return;
    final currency = acceptedPrebook?['currency'] ?? hotel['currency'] ?? 'Unknown currency';
    final amount = acceptedPrebook?['amount'] ?? hotel['price'];
    final action = await showModalBottomSheet<bool>(
      context: context, showDragHandle: true, isScrollControlled: true,
      builder: (ctx) => SafeArea(child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(18, 0, 18, 24),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Hotel Offer Validated', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
            const SizedBox(height: 8),
            Text('${hotel['name']} • ${hotel['roomName']}'),
            Text('Selected stay total: $currency ${amount ?? 'Unavailable'}'),
            Text('Dates: ${acceptedPrebook?['checkin'] ?? checkin.text} → ${acceptedPrebook?['checkout'] ?? checkout.text} • ${acceptedPrebook?['roomQuantity'] ?? rooms.length} room(s)'),
            if (acceptedPrebook?['expiresAt'] != null)
              _buildQuoteFreshnessPill('${acceptedPrebook!['expiresAt']}'),
            const SizedBox(height: 12),
            const Text('Adding this selection updates the trip estimate. It does not reserve a room or take payment.'),
            if (acceptedPrebookSnapshotId.isEmpty)
              const Text('Please validate this offer again before saving.'),
            FilledButton.icon(
              onPressed: () => Navigator.pop(ctx, true),
              icon: Icon(acceptedPrebookSnapshotId.isEmpty ? Icons.refresh_rounded : Icons.bookmark_add_outlined),
              label: Text(acceptedPrebookSnapshotId.isEmpty ? 'Re-validate Quote' : 'Add to Trip'),
            ),
          ],
        ),
      )),
    );
    if (!mounted || action != true) return;
    if (acceptedPrebookSnapshotId.isEmpty) {
      await prebook(hotel);
      return;
    }
    if (busy) return;
    setState(() => busy = true);
    try {
      final trip = await chooseItinerary(stay: acceptedPrebook);
      if (!mounted || trip == null) return;
      final tripId = (trip['id'] ?? '').toString();
      if (tripId.isEmpty) throw StateError('Select a saved trip.');
      final data = await api.post('/api/fr8/hotels/book', {
        'hotelBookingAttemptId': attemptId,
        'validationId': validationId,
        'saveDetailsOnly': true,
        'itineraryId': tripId,
      });
      if (!mounted) return;
      final booking = data['booking'] as Map?;
      if (hotelTripAttachmentOutcome(booking?['itineraryAttachmentStatus']) !=
          HotelTripAttachmentOutcome.attached) {
        showError(context, booking?['itineraryAttachmentError'] ??
            'The hotel could not be added. Check the saved trip before trying again.');
        return;
      }
      setState(() => lastBooking = Map<String, dynamic>.from(booking!));
      ApiService.tripChanges.value++;
      if (!canPay) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Hotel selection added to the trip budget.'),
        ));
        return;
      }
      final pay = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Hotel added to trip'),
          content: Text('${trip['title'] ?? 'Trip'} • $currency ${amount ?? 'Unavailable'}\n\n$academicPaymentDisclosure'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Done')),
            FilledButton(
              key: const ValueKey('hotel-continue-payment'),
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Continue to Payment'),
            ),
          ],
        ),
      );
      if (!mounted || pay != true) return;
      await Navigator.push<void>(context, MaterialPageRoute(builder: (_) => PaymentScreen(
        api: api, quoteType: 'hotel', itineraryId: tripId,
        quoteId: (acceptedPrebook?['quoteId'] ?? hotel['quoteId'] ?? '').toString(),
        offerId: (acceptedPrebook?['offerId'] ?? hotel['offerId'] ?? '').toString(),
        acceptedPrebookSnapshotId: acceptedPrebookSnapshotId,
        acceptedPrebook: acceptedPrebook,
        hotelBookingAttemptId: attemptId,
        initialAmount: double.tryParse('$amount'),
        initialBookingReference: [
          hotel['name'] ?? 'Hotel',
          if (hotel['roomName'] != null) hotel['roomName'],
        ].join(' - '),
      )));
    } on TimeoutException {
      if (mounted) showError(context, 'The hotel selection may have been saved. Reopen the trip to check before retrying.');
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Widget _buildQuoteFreshnessPill(String expiresAtStr) {
    final dt = DateTime.tryParse(expiresAtStr);
    if (dt == null) return const SizedBox.shrink();
    final local = dt.toLocal();
    final isExpired = DateTime.now().isAfter(local);
    final timeStr =
        '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
    return TravelStatusPill(
      text: isExpired ? 'Quote expired' : 'Quote valid until $timeStr',
      icon: isExpired ? Icons.timer_off_outlined : Icons.timer_outlined,
    );
  }

  Future<void> compare() async {
    final selected = items
        .where((raw) =>
            compareIds.contains(idOf(Map<String, dynamic>.from(raw as Map))))
        .map((raw) => Map<String, dynamic>.from(raw as Map))
        .toList();
    if (selected.length < 2) {
      showError(context, 'Select at least two hotel offers to compare.');
      return;
    }
    try {
      final data =
          await api.post('/api/fr8/hotels/compare', {'items': selected});
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
              const Text('Hotel comparison',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
              const SizedBox(height: 10),
              ...compared.asMap().entries.map((entry) {
                final h = Map<String, dynamic>.from(entry.value as Map);
                return Padding(
                  padding: const EdgeInsets.only(bottom: 9),
                  child: InkCard(
                    color: entry.key == 0 ? InkWashColors.cream : null,
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                              '${entry.key == 0 ? 'Best value • ' : ''}${h['name']}',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w900)),
                          Text(
                              '${h['roomName']} • Rating ${h['rating']} • ${h['refundable'] == true ? 'Refundable' : 'Non-refundable'}'),
                          Text('${h['currency'] ?? 'MYR'} ${h['price']}',
                              style: const TextStyle(
                                  fontWeight: FontWeight.w900, fontSize: 18)),
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

  Widget _responsiveFields(List<Widget> fields) => LayoutBuilder(builder: (context, constraints) {
    if (constraints.maxWidth < 520) {
      return Column(children: fields.map((field) => Padding(
        padding: const EdgeInsets.only(bottom: 12), child: field)).toList());
    }
    return Row(children: fields.map((field) => Expanded(child: Padding(
      padding: const EdgeInsets.only(right: 8, bottom: 12), child: field))).toList());
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Hotels'),
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
              title: 'Search bookable hotel offers',
              subtitle:
                  'Search and compare hotel offers, check availability and view property details.'),
          const SizedBox(height: 12),
          TextField(
              controller: destination,
              decoration: const InputDecoration(
                  labelText: 'Destination',
                  hintText: 'City or destination in Malaysia',
                  prefixIcon: Icon(Icons.location_on_outlined))),
          const SizedBox(height: 6),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                'Penang',
                'Kuala Lumpur',
                'Melaka',
                'Kota Kinabalu',
                'Kuching',
                'Langkawi',
              ].map((city) {
                final isSelected =
                    destination.text.trim().toLowerCase() == city.toLowerCase();
                return Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ActionChip(
                    label: Text(city,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight:
                              isSelected ? FontWeight.bold : FontWeight.normal,
                        )),
                    onPressed: () {
                      setState(() {
                        destination.text = city;
                      });
                    },
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 9),
          TextField(controller: hotelName, decoration: const InputDecoration(
            labelText: 'Hotel name (optional)', hintText: 'Find a hotel within this destination',
            prefixIcon: Icon(Icons.hotel_outlined))),
          const SizedBox(height: 12),
          _responsiveFields([
            TextField(controller: checkin, readOnly: true, onTap: () => pickDate(checkin),
              decoration: const InputDecoration(labelText: 'Check-in', prefixIcon: Icon(Icons.login_rounded))),
            TextField(controller: checkout, readOnly: true,
              onTap: () => pickDate(checkout, firstDate: parseDate(checkin.text)?.add(const Duration(days: 1))),
              decoration: const InputDecoration(labelText: 'Check-out', prefixIcon: Icon(Icons.logout_rounded))),
          ]),
          if (rooms.length == 1) ...[
            _responsiveFields([
              TextField(controller: adults, keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Adults'),
                onChanged: (val) {
                  final a = int.tryParse(val) ?? 1;
                  rooms[0].adults = a > 0 ? a : 1;
                  syncTotals(fromAdultsController: true);
                }),
              TextField(controller: children, keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Children'),
                onChanged: (val) {
                  final c = int.tryParse(val) ?? 0;
                  setRoomChildren(0, c >= 0 ? c : 0, fromChildrenController: true);
                }),
            ]),
            const SizedBox(height: 6),
            Text(
                widget.requiresGuestConfirmation
                    ? 'This Trip only stores a total traveller count. Confirm adults and children before searching.'
                    : 'Guest ages are not inferred from a Trip total. Confirm adults and children before searching.',
                style: const TextStyle(
                    color: InkWashColors.mutedInk, fontSize: 12)),
            if (rooms[0].childAges.isNotEmpty) ...[
              const SizedBox(height: 8),
              const Text('Child ages (required for hotel rates):',
                  style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: InkWashColors.blueGrey)),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: List.generate(rooms[0].childAges.length, (childIdx) {
                  return SizedBox(
                    width: 160,
                    child: DropdownButtonFormField<int>(
                      isExpanded: true,
                      initialValue: rooms[0].childAges[childIdx],
                      decoration: InputDecoration(
                        labelText: 'Child ${childIdx + 1} age',
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 8),
                      ),
                      hint: const Text('Select age *',
                          overflow: TextOverflow.ellipsis),
                      items: List.generate(
                          18,
                          (age) => DropdownMenuItem(
                                value: age,
                                child: Text(age == 0 ? '< 1 yr' : '$age yrs'),
                              )),
                      onChanged: (val) {
                        setState(() {
                          rooms[0].childAges[childIdx] = val;
                          _clearResults();
                        });
                      },
                    ),
                  );
                }),
              ),
            ],
            const SizedBox(height: 8),
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  '1 Room · ${rooms[0].adults} Adult${rooms[0].adults != 1 ? 's' : ''}${rooms[0].childAges.isNotEmpty ? ' · ${rooms[0].childAges.length} Child${rooms[0].childAges.length != 1 ? 'ren' : ''}' : ''}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w700, color: InkWashColors.ink),
                ),
                TextButton.icon(
                  onPressed: addRoom,
                  icon: const Icon(Icons.add_rounded, size: 18),
                  label: const Text('Add Room'),
                ),
              ],
            ),
          ] else ...[
            InkCard(
              color: InkWashColors.cream,
              child: Wrap(
                alignment: WrapAlignment.spaceBetween,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    '${rooms.length} Rooms · ${rooms.fold<int>(0, (sum, r) => sum + r.adults)} Adults${rooms.fold<int>(0, (sum, r) => sum + r.childAges.length) > 0 ? ' · ${rooms.fold<int>(0, (sum, r) => sum + r.childAges.length)} Child${rooms.fold<int>(0, (sum, r) => sum + r.childAges.length) != 1 ? 'ren' : ''}' : ''}',
                    style: const TextStyle(
                        fontWeight: FontWeight.w800, fontSize: 14),
                  ),
                  TextButton.icon(
                    onPressed: addRoom,
                    icon: const Icon(Icons.add_rounded, size: 18),
                    label: const Text('Add Room'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            for (int i = 0; i < rooms.length; i++) ...[
              InkCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      alignment: WrapAlignment.spaceBetween,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 8,
                      children: [
                        Text('Room ${i + 1}',
                            style: const TextStyle(
                                fontWeight: FontWeight.w900, fontSize: 16)),
                        if (rooms.length > 1)
                          TextButton.icon(
                            onPressed: () => removeRoom(i),
                            icon: const Icon(Icons.remove_circle_outline,
                                size: 18, color: AppColors.error),
                            label: const Text('Remove Room',
                                style:
                                    TextStyle(color: AppColors.error)),
                          ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text('Adults',
                                  style: TextStyle(
                                      fontSize: 12,
                                      color: InkWashColors.mutedInk)),
                              const SizedBox(height: 4),
                              Row(
                                children: [
                                  IconButton.outlined(
                                    visualDensity: VisualDensity.compact,
                                    icon: const Icon(Icons.remove, size: 16),
                                    onPressed: rooms[i].adults > 1
                                        ? () => setRoomAdults(
                                            i, rooms[i].adults - 1)
                                        : null,
                                  ),
                                  Padding(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 10),
                                    child: Text('${rooms[i].adults}',
                                        style: const TextStyle(
                                            fontWeight: FontWeight.w800,
                                            fontSize: 16)),
                                  ),
                                  IconButton.outlined(
                                    visualDensity: VisualDensity.compact,
                                    icon: const Icon(Icons.add, size: 16),
                                    onPressed: () => setRoomAdults(
                                        i, rooms[i].adults + 1),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text('Children',
                                  style: TextStyle(
                                      fontSize: 12,
                                      color: InkWashColors.mutedInk)),
                              const SizedBox(height: 4),
                              Row(
                                children: [
                                  IconButton.outlined(
                                    visualDensity: VisualDensity.compact,
                                    icon: const Icon(Icons.remove, size: 16),
                                    onPressed: rooms[i].childAges.isNotEmpty
                                        ? () => setRoomChildren(
                                            i, rooms[i].childAges.length - 1)
                                        : null,
                                  ),
                                  Padding(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 10),
                                    child: Text(
                                        '${rooms[i].childAges.length}',
                                        style: const TextStyle(
                                            fontWeight: FontWeight.w800,
                                            fontSize: 16)),
                                  ),
                                  IconButton.outlined(
                                    visualDensity: VisualDensity.compact,
                                    icon: const Icon(Icons.add, size: 16),
                                    onPressed: () => setRoomChildren(
                                        i, rooms[i].childAges.length + 1),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    if (rooms[i].childAges.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      const Text('Child ages (required for hotel rates):',
                          style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: InkWashColors.blueGrey)),
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: List.generate(rooms[i].childAges.length,
                            (childIdx) {
                          return SizedBox(
                            width: 160,
                            child: DropdownButtonFormField<int>(
                              key: ValueKey('room_${i}_child_$childIdx'),
                              isExpanded: true,
                              initialValue: rooms[i].childAges[childIdx],
                              decoration: InputDecoration(
                                labelText: 'Room ${i + 1} Child ${childIdx + 1} age',
                                contentPadding: const EdgeInsets.symmetric(
                                    horizontal: 10, vertical: 8),
                              ),
                              hint: const Text('Select age *',
                                  overflow: TextOverflow.ellipsis),
                              items: List.generate(
                                  18,
                                  (age) => DropdownMenuItem(
                                        value: age,
                                        child: Text(
                                            age == 0 ? '< 1 yr' : '$age yrs'),
                                      )),
                              onChanged: (val) {
                                setState(() {
                                  rooms[i].childAges[childIdx] = val;
                                  _clearResults();
                                });
                              },
                            ),
                          );
                        }),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 8),
            ],
          ],
          const SizedBox(height: 9),
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilterChip(
                selected: refundableOnly,
                label: const Text('Refundable'),
                onSelected: (v) => setState(() { refundableOnly = v; _clearResults(); })),
            ChoiceChip(
                selected: sort == 'top',
                label: const Text('Top'),
                onSelected: (_) => setState(() { sort = 'top'; _clearResults(); })),
            ChoiceChip(
                selected: sort == 'price',
                label: const Text('Lowest price'),
                onSelected: (_) => setState(() { sort = 'price'; _clearResults(); })),
            ChoiceChip(
                selected: sort == 'rating',
                label: const Text('Best rating'),
                onSelected: (_) => setState(() { sort = 'rating'; _clearResults(); })),
          ]),
          const SizedBox(height: 10),
          FilledButton.icon(
              onPressed: busy ? null : search,
              icon: const Icon(Icons.search_rounded),
              label: Text(busy ? 'Searching...' : 'Search hotels')),
          if (source.isNotEmpty) ...[
            const SizedBox(height: 10),
            TravelStatusPill(
                text: source == 'liteapi'
                    ? 'PRICE CHECKED WITH LITEAPI'
                    : 'SAMPLE HOTEL CONTENT',
                icon: source == 'liteapi'
                    ? Icons.cloud_done_outlined
                    : Icons.science_outlined),
          ],
          if (lastBooking != null) ...[
            const SizedBox(height: 12),
            InkCard(
              color: InkWashColors.cream,
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                        lastBooking!['bookingStatus'] == 'pending'
                            ? 'Hotel Details Pending'
                            : lastBooking!['bookingStatus'] == 'failed'
                                ? 'Hotel Details Not Saved'
                                : 'Hotel Details Saved',
                        style: TextStyle(fontWeight: FontWeight.w900)),
                    Text(
                        'TravelMate record: ${lastBooking!['id'] ?? '-'}'),
                    Text('Room reservation: not confirmed'),
                    TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute(
                      builder: (_) => TravelRecordsScreen(api: api))), child: const Text('View Travel Records')),
                  ]),
            ),
          ],
          const SizedBox(height: 18),
          if (items.isEmpty && !busy)
            TravelEmptyState(
              icon: hasSearched ? Icons.location_city_outlined : Icons.hotel_outlined,
              title: hasSearched
                  ? 'No hotel offers in ${lastSearchedDestination.isNotEmpty ? lastSearchedDestination : "this destination"}'
                  : 'Search for a hotel',
              message: hasSearched
                  ? (sampleContentLimited
                      ? 'No sample hotel offers match "$lastSearchedDestination". Sample catalog coverage is limited for this location; sample properties are available in Penang.'
                      : 'No hotel offers match "$lastSearchedDestination" for the selected dates and guest count. Try adjusting your dates or destination.')
                  : 'Compare hotel offers and save stay details for your Trip. A saved record is not a room reservation.',
            ),
          if (nextHotelOffset != null) OutlinedButton.icon(
            onPressed: busy ? null : () => search(loadMore: true),
            icon: const Icon(Icons.search), label: const Text('Search next hotel page')),
          ..._groupedHotels.map((group) {
            final propertyKey = (group['propertyKey'] ?? '').toString();
            final offers = (group['offers'] as List<Map<String, dynamic>>?) ?? const [];
            if (offers.isEmpty) return const SizedBox.shrink();

            final selectedIdx = (_selectedOfferIndexByProperty[propertyKey] ?? 0).clamp(0, offers.length - 1);
            final h = Map<String, dynamic>.from(offers[selectedIdx]);
            h['_allOffers'] = offers;
            final id = idOf(h);
            final selected = compareIds.contains(id);
            final photoUrl = _resolveHotelPhoto(h);
            final hasValidPhoto = photoUrl.isNotEmpty;

            return Padding(
              key: ValueKey('hotel-card-$propertyKey'),
              padding: const EdgeInsets.only(bottom: 10),
              child: InkWell(
                borderRadius: BorderRadius.circular(20),
                onTap: () => details(h),
                child: InkCard(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Expanded(
                              child: Text((h['name'] ?? 'Hotel').toString(),
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
                                  })),
                        ]),
                        const SizedBox(height: 10),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(14),
                          child: hasValidPhoto
                              ? Image.network(
                                  photoUrl,
                                  height: 150,
                                  width: double.infinity,
                                  fit: BoxFit.cover,
                                  loadingBuilder: (ctx, child, progress) {
                                    if (progress == null) return child;
                                    return Container(
                                      height: 150,
                                      width: double.infinity,
                                      color: InkWashColors.cream,
                                      alignment: Alignment.center,
                                      child: const SizedBox(
                                        width: 24,
                                        height: 24,
                                        child: CircularProgressIndicator(strokeWidth: 2),
                                      ),
                                    );
                                  },
                                  errorBuilder: (_, __, ___) => Container(
                                    height: 120,
                                    width: double.infinity,
                                    color: InkWashColors.cream,
                                    alignment: Alignment.center,
                                    child: const Column(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        Icon(Icons.hotel_outlined, size: 36, color: InkWashColors.blueGrey),
                                        SizedBox(height: 4),
                                        Text('Hotel photo unavailable',
                                            style: TextStyle(fontSize: 12, color: InkWashColors.mutedInk)),
                                      ],
                                    ),
                                  ),
                                )
                              : Container(
                                  height: 100,
                                  width: double.infinity,
                                  decoration: BoxDecoration(
                                    color: InkWashColors.cream,
                                    borderRadius: BorderRadius.circular(14),
                                  ),
                                  alignment: Alignment.center,
                                  child: const Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Icons.hotel_outlined, size: 36, color: InkWashColors.blueGrey),
                                      SizedBox(height: 4),
                                      Text('Hotel photo unavailable',
                                          style: TextStyle(fontSize: 12, color: InkWashColors.mutedInk)),
                                    ],
                                  ),
                                ),
                        ),
                        const SizedBox(height: 8),
                        Text((h['address'] ?? '').toString(),
                            style:
                                const TextStyle(color: InkWashColors.mutedInk)),
                        if ((h['demoDisclosure'] ?? '').toString().isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 5),
                            child: Text((h['demoDisclosure']).toString(),
                                style: const TextStyle(
                                    color: InkWashColors.mutedInk,
                                    fontSize: 12)),
                          ),
                        const SizedBox(height: 7),
                        Wrap(spacing: 7, runSpacing: 7, children: [
                          TravelStatusPill(
                              text: 'Rating ${h['rating'] ?? '-'}',
                              icon: Icons.star_rounded),
                          TravelStatusPill(
                              text: '${h['stars'] ?? '-'} stars',
                              icon: Icons.hotel_class_outlined),
                          TravelStatusPill(
                              text: h['refundable'] == true
                                  ? 'Refundable'
                                  : 'Non-refundable',
                              icon: Icons.policy_outlined),
                          if (h['quoteExpiresAt'] != null)
                            _buildQuoteFreshnessPill(
                                h['quoteExpiresAt'].toString()),
                        ]),
                        const SizedBox(height: 8),
                        RoomOfferPhoto(offer: h),
                        if (offers.length > 1) ...[
                          const SizedBox(height: 10),
                          Text('${offers.length} Room Options Available:',
                              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: InkWashColors.blueGrey)),
                          const SizedBox(height: 4),
                          Wrap(
                            spacing: 6,
                            runSpacing: 4,
                            children: List.generate(offers.length, (idx) {
                              final off = offers[idx];
                              final isSel = idx == selectedIdx;
                              final rName = (off['roomName'] ?? 'Room ${idx + 1}').toString();
                              final rPrice = off['price'] != null ? ' (MYR ${off['price']})' : '';
                              return ChoiceChip(
                                label: Text('$rName$rPrice',
                                    style: TextStyle(
                                      fontSize: 11,
                                      fontWeight: isSel ? FontWeight.w700 : FontWeight.normal,
                                    )),
                                selected: isSel,
                                onSelected: (val) {
                                  if (val) {
                                    setState(() {
                                      _selectedOfferIndexByProperty[propertyKey] = idx;
                                    });
                                  }
                                },
                              );
                            }),
                          ),
                        ],
                        const SizedBox(height: 8),
                        Text((h['roomName'] ?? 'Available room').toString(),
                            style:
                                const TextStyle(fontWeight: FontWeight.w700)),
                        if ((h['boardName'] ?? '').toString().isNotEmpty)
                          Text((h['boardName']).toString()),
                        const SizedBox(height: 8),
                        Text(
                          '${h['checkin'] ?? ''} → ${h['checkout'] ?? ''} • ${h['roomQuantity'] ?? 1} room(s)',
                          style: const TextStyle(
                              color: InkWashColors.mutedInk, fontSize: 12),
                        ),
                        const SizedBox(height: 8),
                        Row(children: [
                          Expanded(
                              child: Text(
                                  '${h['currency'] ?? 'Unknown'} ${h['price'] ?? '-'}${h['priceBasis'] == 'per_room_night' ? ' / room/night' : h['priceBasis'] == 'stay_total' ? ' total stay' : ''}',
                                  style: const TextStyle(
                                      fontSize: 20,
                                      fontWeight: FontWeight.w900))),
                          OutlinedButton(
                              onPressed: () => details(h),
                              child: const Text('Details')),
                          const SizedBox(width: 6),
                          FilledButton.tonal(
                              onPressed: busy ? null : () => prebook(h),
                              child: const Text('Validate quote')),
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
