import 'dart:async';

import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'hotel_details_screen.dart';
import 'hotel_trip_attachment.dart';
import '../fr09_payment/payment_screen.dart';

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
  final String? initialDestination;
  final String? initialCheckin;
  final String? initialCheckout;
  final int? initialAdults;
  final int? initialChildren;
  final bool requiresGuestConfirmation;
  final ApiService? api;

  const HotelScreen({
    super.key,
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
  Map<String, dynamic>? lastBooking;
  final Map<String, String> bookingAttemptIds = {};

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
    destination = TextEditingController(
        text: widget.initialDestination?.trim().isNotEmpty == true
            ? widget.initialDestination!.trim()
            : 'George Town, Penang');
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
  }

  @override
  void dispose() {
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

  Future<void> search() async {
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

    setState(() {
      busy = true;
      compareIds.clear();
    });
    try {
      final data = await api.post('/api/fr8/hotels/search', {
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
      setState(() {
        items = data['items'] ??
            (data['result'] is Map ? data['result']['items'] ?? [] : []);
        source = (data['source'] ?? '').toString();
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> details(Map<String, dynamic> hotel) async {
    if (!mounted) return;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => HotelDetailsScreen(
          hotel: hotel,
          onProceed: () {
            Navigator.pop(context);
            prebook(hotel);
          },
        ),
      ),
    );
  }

  Future<Map<String, dynamic>?> chooseItinerary() async {
    final data = await api.get('/api/fr5/itineraries');
    final trips = data['items'] as List? ?? [];
    if (!mounted) return null;
    if (trips.isEmpty) {
      showError(context,
          'Create an itinerary first if you want the hotel cost added to the budget.');
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
            const Text('Add booking to which itinerary?',
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
                subtitle: Text(
                    '${trip['destinationArea'] ?? ''} • Budget RM ${trip['budgetLimit'] ?? 0}'),
                onTap: () => Navigator.pop(context, trip),
              );
            }),
          ],
        ),
      ),
    );
  }

  Future<void> prebook(Map<String, dynamic> hotel) async {
    if (busy) return;
    final offerId = (hotel['offerId'] ?? '').toString();
    if (offerId.isEmpty) {
      showError(
          context, 'This hotel result does not contain a bookable offer ID.');
      return;
    }
    final attemptId = bookingAttemptIds.putIfAbsent(
      offerId,
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
        source: (data['source'] ?? source).toString(),
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
    required String source,
    required String validationId,
  }) async {
    final cur = (acceptedPrebook?['currency'] ?? hotel['currency'] ?? 'MYR')
        .toString();
    final amt = acceptedPrebook?['amount'] ?? hotel['price'] ?? 0;
    final expAt = acceptedPrebook?['expiresAt']?.toString();
    String expNotice = '';
    if (expAt != null && expAt.isNotEmpty) {
      final dt = DateTime.tryParse(expAt);
      if (dt != null) {
        final local = dt.toLocal();
        expNotice =
            'Accepted price valid until ${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
      }
    }

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 0, 18, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Hotel Offer Validated',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
              const SizedBox(height: 6),
              Text('${hotel['name']} • ${hotel['roomName']}'),
              const SizedBox(height: 10),
              InkCard(
                color: InkWashColors.cream,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text('Authoritative total',
                            style: TextStyle(
                                color: InkWashColors.mutedInk, fontSize: 13)),
                        Text('$cur $amt',
                            style: const TextStyle(
                                fontSize: 20, fontWeight: FontWeight.w900)),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Dates: ${checkin.text} → ${checkout.text} • ${rooms.length} room(s)',
                      style: const TextStyle(
                          fontSize: 12, color: InkWashColors.mutedInk),
                    ),
                    if (expNotice.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(expNotice,
                          style: const TextStyle(
                              fontSize: 11,
                              color: InkWashColors.blueGrey,
                              fontWeight: FontWeight.w600)),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 10),
              InkCard(
                color: const Color(0xFFEFF6FF),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.shield_outlined,
                        size: 20, color: InkWashColors.blueGrey),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Stripe Test Mode — No real payment will be charged. This checkout does not confirm a reservation with the hotel.',
                        style: TextStyle(
                            fontSize: 12,
                            color: InkWashColors.ink,
                            height: 1.35),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              if (acceptedPrebookSnapshotId.isEmpty) ...[
                InkCard(
                  color: const Color(0xFFFEF3C7),
                  child: const Row(
                    children: [
                      Icon(Icons.warning_amber_rounded,
                          size: 20, color: Color(0xFFD97706)),
                      SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'An accepted quote snapshot was not received. Please re-validate the quote before opening card checkout.',
                          style: TextStyle(
                              fontSize: 12,
                              color: Color(0xFF92400E),
                              fontWeight: FontWeight.w600),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
              ],
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: () {
                    Navigator.pop(ctx);
                    if (acceptedPrebookSnapshotId.isEmpty) {
                      prebook(hotel);
                      return;
                    }
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => PaymentScreen(
                          quoteType: 'hotel',
                          quoteId: (hotel['quoteId'] ?? '').toString(),
                          offerId: (hotel['offerId'] ?? '').toString(),
                          acceptedPrebookSnapshotId: acceptedPrebookSnapshotId,
                          acceptedPrebook: acceptedPrebook,
                          initialAmount: (amt is num)
                              ? amt.toDouble()
                              : double.tryParse('$amt'),
                          initialBookingReference: acceptedPrebookSnapshotId,
                          hotelBookingAttemptId: attemptId,
                          api: api,
                        ),
                      ),
                    );
                  },
                  icon: Icon(acceptedPrebookSnapshotId.isEmpty
                      ? Icons.refresh_rounded
                      : Icons.payment_rounded),
                  label: Text(acceptedPrebookSnapshotId.isEmpty
                      ? 'Re-validate Quote for Checkout'
                      : 'Pay with Card (Stripe Test)'),
                ),
              ),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: () {
                    Navigator.pop(ctx);
                    completeBooking(hotel, validationId, source, attemptId);
                  },
                  icon: const Icon(Icons.science_outlined),
                  label: const Text('Local Demo Reservation (Offline Sim)'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
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

  Future<void> completeBooking(Map<String, dynamic> hotel, String validationId,
      String prebookSource, String attemptId) async {
    final firstName = TextEditingController(text: 'TravelMate');
    final lastName = TextEditingController(text: 'Traveller');
    final email = TextEditingController(
        text: FirebaseAuth.instance.currentUser?.email ??
            'traveller@example.test');
    bool attachToTrip = true;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Confirm booking'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('${hotel['name']} • ${hotel['roomName']}'),
                const SizedBox(height: 6),
                Text('${hotel['currency'] ?? 'MYR'} ${hotel['price'] ?? 0}',
                    style: const TextStyle(
                        fontWeight: FontWeight.w900, fontSize: 18)),
                const SizedBox(height: 12),
                TextField(
                    controller: firstName,
                    decoration: const InputDecoration(labelText: 'First name')),
                const SizedBox(height: 8),
                TextField(
                    controller: lastName,
                    decoration: const InputDecoration(labelText: 'Last name')),
                const SizedBox(height: 8),
                TextField(
                    controller: email,
                    decoration: const InputDecoration(labelText: 'Email')),
                const SizedBox(height: 6),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: attachToTrip,
                  title: const Text('Add hotel cost to itinerary budget'),
                  onChanged: (v) => setDialogState(() => attachToTrip = v),
                ),
                Text(
                  prebookSource == 'liteapi'
                      ? 'Price checked with LiteAPI. This demo app does not reserve a room.'
                      : 'Sample hotel content. This creates a local demo reservation; no room will be reserved.',
                  style: const TextStyle(
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
                child: const Text('Confirm booking')),
          ],
        ),
      ),
    );
    if (confirmed != true) return;

    Map<String, dynamic>? itinerary;
    if (attachToTrip) {
      itinerary = await chooseItinerary();
      if (!mounted) return;
    }

    setState(() => busy = true);
    try {
      final bookingRequest = <String, dynamic>{
        'hotelBookingAttemptId': attemptId,
        'validationId': validationId,
        'holder': {
          'firstName': firstName.text.trim(),
          'lastName': lastName.text.trim(),
          'email': email.text.trim(),
        },
        'guests': [
          {
            'firstName': firstName.text.trim(),
            'lastName': lastName.text.trim(),
            'email': email.text.trim(),
            'occupancyNumber': 1,
          }
        ],
        'payment': {'method': 'ACC_CREDIT_CARD'},
        'itineraryId': itinerary?['id'],
        'selectedHotel': hotel,
        'roomQuantity': hotel['roomQuantity'] ??
            int.tryParse(roomQuantity.text.trim()) ??
            1,
        'hotelCost': hotel['price'] ?? 0,
      };
      var data = await api.post('/api/fr8/hotels/book', bookingRequest);
      if (!mounted) return;
      setState(() => lastBooking = data['booking'] is Map
          ? Map<String, dynamic>.from(data['booking'] as Map)
          : null);
      if (lastBooking?['bookingStatus'] == 'pending') {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
            'Booking outcome pending verification. The provider request was not submitted again.',
          ),
        ));
        return;
      }
      if (itinerary != null) {
        var attachmentOutcome = hotelTripAttachmentOutcome(
            lastBooking?['itineraryAttachmentStatus']);
        if (attachmentOutcome == HotelTripAttachmentOutcome.unverified) {
          final acknowledge = await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('Compatibility cannot be verified'),
              content: const Text(
                  'This hotel booking was created before Trip compatibility information was recorded. We cannot verify that its dates and destination match your selected Trip.'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('Cancel')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('Add Anyway')),
              ],
            ),
          );
          if (acknowledge == true) {
            data = await api.post('/api/fr8/hotels/book', {
              ...bookingRequest,
              'acknowledgeCompatibilityUnverified': true,
            });
            if (!mounted) return;
            setState(() => lastBooking = data['booking'] is Map
                ? Map<String, dynamic>.from(data['booking'] as Map)
                : lastBooking);
          } else {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
              content: Text('Booking created, but it was not added to the trip.'),
            ));
          }
        }
        attachmentOutcome = hotelTripAttachmentOutcome(
            lastBooking?['itineraryAttachmentStatus']);
        final attachmentError =
            lastBooking?['itineraryAttachmentError']?.toString();
        if (attachmentOutcome == HotelTripAttachmentOutcome.attached) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Hotel booking added to the trip budget.'),
          ));
        } else if (attachmentOutcome == HotelTripAttachmentOutcome.incompatible ||
            attachmentOutcome == HotelTripAttachmentOutcome.failed) {
          final chooseAnotherTrip = await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('Hotel was not added to this trip'),
              content: Text(attachmentError?.isNotEmpty == true
                  ? attachmentError!
                  : 'The hotel booking could not be added to the selected trip.'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('Choose another trip')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('Continue')),
              ],
            ),
          );
          if (chooseAnotherTrip == true) {
            final replacement = await chooseItinerary();
            if (replacement != null) {
              data = await api.post('/api/fr8/hotels/book', {
                ...bookingRequest,
                'itineraryId': replacement['id'],
              });
              if (!mounted) return;
              setState(() => lastBooking = data['booking'] is Map
                  ? Map<String, dynamic>.from(data['booking'] as Map)
                  : lastBooking);
              if (hotelTripAttachmentOutcome(
                      lastBooking?['itineraryAttachmentStatus']) ==
                  HotelTripAttachmentOutcome.attached) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text('Hotel booking added to the trip budget.'),
                ));
              } else {
                showError(context,
                    lastBooking?['itineraryAttachmentError'] ??
                        'The hotel booking was not added to the selected trip.');
              }
            }
          }
        }
      }
      final ref = lastBooking?['bookingReference'] ?? '-';
      final simulated = lastBooking?['isSimulated'] == true;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(simulated
              ? 'Demo booking created: $ref'
              : 'Provider booking created: $ref')));
    } on TimeoutException {
      try {
        final data = await api.get('/api/fr8/bookings/attempts/$attemptId');
        if (mounted && data['booking'] is Map) {
          setState(() =>
              lastBooking = Map<String, dynamic>.from(data['booking'] as Map));
        }
      } catch (_) {
        if (mounted) {
          setState(() => lastBooking = {
                'hotelBookingAttemptId': attemptId,
                'bookingStatus': 'pending',
                'confirmationLabel': 'Verification pending',
              });
        }
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text(
            'The booking outcome is being verified. Retrying will reuse this attempt and will not create a second provider booking.',
          ),
        ));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
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
                  'Search and compare hotel offers, then validate a quote before creating a local demo reservation.'),
          const SizedBox(height: 12),
          TextField(
              controller: destination,
              decoration: const InputDecoration(
                  labelText: 'Destination',
                  prefixIcon: Icon(Icons.location_on_outlined))),
          const SizedBox(height: 9),
          Row(children: [
            Expanded(
              child: TextField(
                controller: checkin,
                readOnly: true,
                onTap: () => pickDate(checkin),
                decoration: const InputDecoration(
                    labelText: 'Check-in',
                    prefixIcon: Icon(Icons.calendar_today_outlined)),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: checkout,
                readOnly: true,
                onTap: () => pickDate(checkout,
                    firstDate:
                        parseDate(checkin.text)?.add(const Duration(days: 1))),
                decoration: const InputDecoration(
                    labelText: 'Check-out',
                    prefixIcon: Icon(Icons.logout_rounded)),
              ),
            ),
          ]),
          if (rooms.length == 1) ...[
            Row(children: [
              Expanded(
                child: TextField(
                  controller: adults,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Adults'),
                  onChanged: (val) {
                    final a = int.tryParse(val) ?? 1;
                    rooms[0].adults = a > 0 ? a : 1;
                    syncTotals(fromAdultsController: true);
                  },
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                  controller: children,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Children'),
                  onChanged: (val) {
                    final c = int.tryParse(val) ?? 0;
                    setRoomChildren(0, c >= 0 ? c : 0,
                        fromChildrenController: true);
                  },
                ),
              ),
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
                        });
                      },
                    ),
                  );
                }),
              ),
            ],
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
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
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
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
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
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
                onSelected: (v) => setState(() => refundableOnly = v)),
            ChoiceChip(
                selected: sort == 'top',
                label: const Text('Top'),
                onSelected: (_) => setState(() => sort = 'top')),
            ChoiceChip(
                selected: sort == 'price',
                label: const Text('Lowest price'),
                onSelected: (_) => setState(() => sort = 'price')),
            ChoiceChip(
                selected: sort == 'rating',
                label: const Text('Best rating'),
                onSelected: (_) => setState(() => sort = 'rating')),
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
                        lastBooking!['isSimulated'] == true
                            ? 'Latest Demo booking'
                            : 'Latest booking',
                        style: TextStyle(fontWeight: FontWeight.w900)),
                    Text(
                        'Reference: ${lastBooking!['bookingReference'] ?? '-'}'),
                    Text('Status: ${lastBooking!['bookingStatus'] ?? '-'}'),
                    if (lastBooking!['confirmationLabel'] != null)
                      Text('${lastBooking!['confirmationLabel']}'),
                  ]),
            ),
          ],
          const SizedBox(height: 18),
          if (items.isEmpty && !busy)
            const TravelEmptyState(
                icon: Icons.hotel_outlined,
                title: 'Search for a hotel',
                message:
                    'Hotel offers can be compared, prebooked and confirmed through the available booking flow.'),
          ...items.map((raw) {
            final h = Map<String, dynamic>.from(raw as Map);
            final id = idOf(h);
            final selected = compareIds.contains(id);
            return Padding(
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
                        if ((h['mainPhoto'] ?? '').toString().isNotEmpty) ...[
                          const SizedBox(height: 10),
                          ClipRRect(
                            borderRadius: BorderRadius.circular(14),
                            child: Image.network(
                              h['mainPhoto'].toString(),
                              height: 150,
                              width: double.infinity,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => Container(
                                height: 80,
                                color: InkWashColors.cream,
                                alignment: Alignment.center,
                                child: const Text('Hotel photo unavailable'),
                              ),
                            ),
                          ),
                        ],
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
