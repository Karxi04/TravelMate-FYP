import 'dart:async';

import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'hotel_details_screen.dart';
import '../fr09_payment/payment_screen.dart';

class HotelScreen extends StatefulWidget {
  final String? initialDestination;
  final String? initialCheckin;
  final String? initialCheckout;

  const HotelScreen({
    super.key,
    this.initialDestination,
    this.initialCheckin,
    this.initialCheckout,
  });

  @override
  State<HotelScreen> createState() => _HotelScreenState();
}

class _HotelScreenState extends State<HotelScreen> {
  late final TextEditingController destination;
  late final TextEditingController checkin;
  late final TextEditingController checkout;
  final adults = TextEditingController(text: '2');
  final roomQuantity = TextEditingController(text: '1');
  final api = ApiService();

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

  @override
  void initState() {
    super.initState();
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
  }

  @override
  void dispose() {
    destination.dispose();
    checkin.dispose();
    checkout.dispose();
    adults.dispose();
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
    final adultCount = int.tryParse(adults.text.trim()) ?? 0;
    final roomCount = int.tryParse(roomQuantity.text.trim()) ?? 0;
    if (adultCount <= 0) {
      showError(context, 'Adults must be at least 1.');
      return;
    }
    if (roomCount <= 0) {
      showError(context, 'Rooms must be at least 1.');
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
        'roomQuantity': roomCount,
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
        if (error.data['status'] != 'reprice_required') rethrow;
        final latest = error.data['validatedOffer'] is Map
            ? Map<String, dynamic>.from(error.data['validatedOffer'] as Map)
            : <String, dynamic>{};
        if (!mounted) rethrow;
        final accepted = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Offer updated'),
            content: Text(
                'The validated price or cancellation terms changed to ${latest['currency'] ?? 'MYR'} ${latest['price'] ?? '-'} . Review the latest offer before continuing.'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Accept latest offer')),
            ],
          ),
        );
        if (accepted != true) rethrow;
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
      final result = Map<String, dynamic>.from(data['result'] as Map);
      final prebookId = (result['prebookId'] ?? result['id'] ?? '').toString();
      if (prebookId.isEmpty)
        throw Exception('Provider did not return a prebook ID.');
      if (!mounted) return;
      setState(() => busy = false);
      final resultOffer = result['validatedOffer'] is Map
          ? Map<String, dynamic>.from(result['validatedOffer'] as Map)
          : result;
      await completeBooking({...hotel, ...resultOffer},
          prebookId, (data['source'] ?? source).toString(), attemptId);
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

  Future<void> completeBooking(Map<String, dynamic> hotel, String prebookId,
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
                      ? 'This uses the configured LiteAPI/Nuitée booking flow.'
                      : 'This creates a Demo booking with a simulated confirmation. It is not an external hotel reservation.',
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
      final data = await api.post('/api/fr8/hotels/book', {
        'hotelBookingAttemptId': attemptId,
        'prebookId': prebookId,
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
      });
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
      final ref = lastBooking?['bookingReference'] ?? '-';
      final simulated = lastBooking?['isSimulated'] == true;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(simulated
              ? 'Demo booking created: $ref'
              : 'Provider booking created: $ref')));
      final proceed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Proceed to card payment?'),
          content: Text(
              '${simulated ? 'Demo booking' : 'Booking'} $ref is ready. Continue to the card-payment process for ${hotel['currency'] ?? 'MYR'} ${hotel['price'] ?? 0}?'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Later')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Continue to payment')),
          ],
        ),
      );
      if (proceed == true && mounted) {
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => PaymentScreen(
              initialBookingReference: ref.toString(),
              initialAmount: double.tryParse('${hotel['price']}'),
            ),
          ),
        );
      }
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
                  'Search, compare, prebook and confirm hotel offers. Live provider results are used when configured.'),
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
          const SizedBox(height: 9),
          TextField(
              controller: adults,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Adults')),
          const SizedBox(height: 9),
          TextField(
              controller: roomQuantity,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: 'Rooms',
                  prefixIcon: Icon(Icons.meeting_room_outlined))),
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
                    ? 'LIVE LITEAPI / NUITÉE OFFERS'
                    : 'AVAILABLE HOTEL OFFERS',
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
                        Text((h['address'] ?? '').toString(),
                            style:
                                const TextStyle(color: InkWashColors.mutedInk)),
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
                        ]),
                        const SizedBox(height: 8),
                        Text((h['roomName'] ?? 'Available room').toString(),
                            style:
                                const TextStyle(fontWeight: FontWeight.w700)),
                        if ((h['boardName'] ?? '').toString().isNotEmpty)
                          Text((h['boardName']).toString()),
                        const SizedBox(height: 8),
                        Row(children: [
                          Expanded(
                              child: Text(
                                  '${h['currency'] ?? 'MYR'} ${h['price'] ?? '-'}',
                                  style: const TextStyle(
                                      fontSize: 20,
                                      fontWeight: FontWeight.w900))),
                          OutlinedButton(
                              onPressed: () => details(h),
                              child: const Text('Details')),
                          const SizedBox(width: 6),
                          FilledButton.tonal(
                              onPressed: busy ? null : () => prebook(h),
                              child: const Text('Prebook')),
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
