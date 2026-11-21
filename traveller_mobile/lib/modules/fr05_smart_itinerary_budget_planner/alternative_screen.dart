import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../widgets/ink_card.dart';
import 'budget_service.dart';
import 'budget_replan_screen.dart';
import 'models/budget_model.dart';
import '../fr08_hotel_booking/hotel_screen.dart';

class AlternativeScreen extends StatefulWidget {
  final BudgetModel budget;
  final double userBudget;
  final String? tripId;
  final ApiService? api;
  final ValueChanged<Map<String, dynamic>>? onApplied;

  const AlternativeScreen({
    super.key,
    required this.budget,
    required this.userBudget,
    this.tripId,
    this.api,
    this.onApplied,
  });

  @override
  State<AlternativeScreen> createState() => _AlternativeScreenState();
}

class _AlternativeScreenState extends State<AlternativeScreen> {
  late ApiService api;
  int _loadVersion = 0;
  bool checkingPrices = false;
  bool applying = false;
  String? discovering;
  final searchMessages = <String, String>{};
  final searchRetryAt = <String, DateTime>{};
  List<Map<String, dynamic>> planning = [];
  List<Map<String, dynamic>> flightTimingPreviews = [];
  bool optionsChanged = false;
  String? stateVersion;
  List<Map<String, dynamic>> alternatives = [];
  Map<String, dynamic>? budget;
  Map<String, dynamic>? replanOptions;
  String? loadError;
  bool busy = false;
  Map<String,dynamic> flightComparison = {}, hotelComparison = {};
  Map categoryRejections = {};
  bool includeLowerCabins=false;
  int? comparisonCabin;
  static const cabins={1:'Economy',2:'Premium Economy',3:'Business',4:'First'};
  Map<String,dynamic> get cabinRequest => {'cabinComparison':includeLowerCabins ? 'include_lower':'same_cabin',
    if(includeLowerCabins && comparisonCabin!=null) 'comparisonCabin':comparisonCabin};

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(load);
  }

  @override
  void didUpdateWidget(covariant AlternativeScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.tripId != widget.tripId || oldWidget.api != widget.api) {
      api = widget.api ?? ApiService();
      stateVersion = null;
      budget = null;
      replanOptions = null;
      optionsChanged = false;
      applying = false;
      discovering = null;
      includeLowerCabins=false;comparisonCabin=null;
      flightComparison={};hotelComparison={};categoryRejections={};
      searchMessages.clear();
      searchRetryAt.clear();
      load();
    }
  }

  void _setTripState(Map data) {
    if(data['categoryRejectionCounts'] is Map) categoryRejections=data['categoryRejectionCounts'];
    if(data['flightComparison'] is Map) flightComparison=Map<String,dynamic>.from(data['flightComparison']);
    if(data['hotelComparison'] is Map) hotelComparison=Map<String,dynamic>.from(data['hotelComparison']);
    if (data['planningAlternatives'] is List) {
      planning = (data['planningAlternatives'] as List)
          .whereType<Map>()
          .map((row) => Map<String, dynamic>.from(row))
          .toList();
    }
    budget = data['budget'] is Map
        ? Map<String, dynamic>.from(data['budget'])
        : null;
    replanOptions = data['budgetReplanOptions'] is Map
        ? Map<String, dynamic>.from(data['budgetReplanOptions'])
        : null;
    stateVersion = data['stateVersion'] as String?;
  }

  Future<void> load() async {
    if (!mounted || applying) return;
    final version = ++_loadVersion;
    final tripId = widget.tripId;
    bool current() => mounted && version == _loadVersion;
    if ((tripId ?? '').isEmpty) {
      final local = BudgetService().generateAlternatives(widget.budget);
      setState(() {
        alternatives = local
            .map((item) => {
                  'title': item['title'],
                  'description': item['description'],
                  'alternativeType': item['type'] ?? 'strategy',
                  'isAdvisory': item['isAdvisory'] ?? true,
                  'canApply': item['canApply'] ?? false,
                })
            .toList();
      });
      return;
    }
    final hadPrices = alternatives.isNotEmpty;
    setState(() {
      for (final category in searchRetryAt.keys.toList()) {
        if (!searchRetryAt[category]!.isAfter(DateTime.now().toUtc())) {
          searchRetryAt.remove(category);
          searchMessages.remove(category);
        }
      }
      busy = true;
      checkingPrices = true;
      loadError = null;
      alternatives = [];
      planning = [];
      flightTimingPreviews = [];
    });
    final before = stateVersion;
    var loadedTrip = false;
    try {
      final data = await api.get('/api/fr5/itineraries/$tripId/budget-replan');
      if (!current()) return;
      if (data is Map && data['ok'] == true && data['stateVersion'] is String) {
        loadedTrip = true;
        setState(() {
          _setTripState(data);
          optionsChanged = before != null && before != stateVersion;
          busy = false;
        });
      }
    } catch (_) {
      // An older Backend can still return the complete state from the POST.
    }
    if (!current()) return;
    if (loadedTrip && !_overBudget) {
      setState(() => checkingPrices = false);
      return;
    }
    try {
      final data = await api
          .post('/api/fr5/itineraries/$tripId/lower-cost-alternatives',cabinRequest);
      if (!current()) return;
      if (data is! Map || data['ok'] == false) {
        throw StateError('Alternatives could not be refreshed.');
      }
      setState(() {
        flightTimingPreviews = (data['flightTimingPreviews'] as List? ?? [])
            .whereType<Map>()
            .map((row) => Map<String, dynamic>.from(row))
            .toList();
        alternatives = (data['alternatives'] as List? ?? [])
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
        if (!loadedTrip || data['stateVersion'] is String) {
          _setTripState(data);
          optionsChanged = before != null && before != stateVersion;
        }
        optionsChanged = optionsChanged || (hadPrices && alternatives.isEmpty);
      });
    } catch (e) {
      if (current())
        setState(() {
          loadError = userFacingApiError(e);
          if (!loadedTrip) replanOptions = null;
        });
    } finally {
      if (current())
        setState(() {
          busy = false;
          checkingPrices = false;
        });
    }
  }

  Future<void> openReplan() async {
    final options = replanOptions;
    final tripId = widget.tripId;
    if (options == null || tripId == null || applying) return;
    // The preview owns its options/revision. Keep the existing lookup for returning after Cancel.
    final updated = await Navigator.push<Map<String, dynamic>>(
        context,
        MaterialPageRoute(
            builder: (context) => BudgetReplanScreen(
                api: api,
                tripId: tripId,
                options: options,
                stateVersion: stateVersion)));
    if (!mounted || widget.tripId != tripId || updated == null) return;
    if (updated['id'] == tripId) widget.onApplied?.call(updated);
    await load();
  }

  bool get _overBudget {
    final total = budget?['total'] ?? widget.budget.totalCost;
    final limit = budget?['limit'] ?? widget.userBudget;
    return total is num && limit is num && limit > 0 && total > limit;
  }

  String money(Object? value) =>
      value is num ? value.toStringAsFixed(2) : 'Unavailable';

  Future<void> previewPlanning(Map<String, dynamic> item) async {
    if (applying || discovering != null || widget.tripId == null) return;
    setState(() => applying = true);
    final version = _loadVersion;
    final path = '/api/fr5/itineraries/' + widget.tripId! + '/budget-replan';
    final command = <String, dynamic>{
      'changes': item['changes'],
      'stateVersion': stateVersion
    };
    var refresh = false;
    try {
      final preview = await api.post('$path/preview', command);
      if (!mounted || version != _loadVersion) return;
      final accepted = await confirmPreview(item, preview);
      if (!mounted || accepted != true || version != _loadVersion) return;
      final saved = await api.post('$path/apply', {
        ...command,
        'confirmed': true,
        'previewToken': preview['previewToken']
      });
      if (!mounted || version != _loadVersion) return;
      final trip = saved['itinerary'];
      if (trip is! Map || trip['id'] != widget.tripId)
        throw StateError('The trip update could not be confirmed.');
      if (!mounted) return;
      widget.onApplied?.call(Map<String, dynamic>.from(trip));
      refresh = true;
    } catch (error) {
      if (mounted && version == _loadVersion) showError(context, error);
      refresh = error is ApiException && error.statusCode == 409;
    } finally {
      if (mounted && version == _loadVersion) setState(() => applying = false);
    }
    if (refresh && mounted && version == _loadVersion) await load();
  }

  Future<bool?> confirmPreview(Map<String, dynamic> item, dynamic preview) {
    final before = preview['before'] as Map? ?? {};
    final after = preview['budget'] as Map? ?? {};
    return showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: Text((item['title'] ?? 'Review alternative').toString()),
              scrollable: true,
              content: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if(item['alternativeType']=='flight' || item['alternativeType']=='hotel')
                      ...selectionDetails(item),
                    Text('Original known estimate: RM ' +
                        money(before['total'])),
                    Text(
                        'Proposed known estimate: RM ' + money(after['total'])),
                    Text('Estimated planning reduction: RM ' +
                        money(preview['estimatedReduction'])),
                    Text('Remaining over budget: RM ' +
                        money(after['overBy'] ?? 0)),
                    if ((after['pendingExpenseCategories'] as List? ?? [])
                        .isNotEmpty)
                      const Text(
                          'Important costs remain unpriced; this does not establish full-trip affordability.'),
                    for (final change
                        in (preview['itineraryChanges'] as List? ?? [])
                            .whereType<Map>())
                      Text((change['activityName'] ?? 'Visit').toString() +
                          ' — ' +
                          (change['kind'] ?? 'review').toString() +
                          (change['to'] is Map
                              ? ' ' +
                                  (change['to']['scheduledStartTime'] ?? '')
                                      .toString()
                              : '')),
                    const Text(
                        'This changes your saved plan only. It does not book, cancel or refund a supplier arrangement.'),
                    for (final day in (preview['dailySchedule'] as List? ?? [])
                        .whereType<Map>()) ...[
                      Text('Day ' + day['dayNo'].toString()),
                      for (final row in (day['activities'] as List? ?? [])
                          .whereType<Map>())
                        Text((row['scheduledStartTime'] ?? '').toString() +
                            ' ' +
                            (row['activityName'] ?? '').toString()),
                    ],
                  ]),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('Cancel')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('Confirm change')),
              ],
            ));
  }

  String noOffer(String category) => category == 'hotel'
      ? 'No verified cheaper hotel is currently available for this stay.'
      : 'No verified cheaper flight is currently available.';

  String searchBlocked(String category) => category == 'hotel'
      ? 'Hotel search has not run. Review the selected stay, total price and room details in Hotels first. Paid or pending stays cannot be replaced.'
      : 'Flight search has not run. Review the selected route, dates, passengers and cabin first. Paid or booked flights cannot be replaced.';

  String searchLimitMessage(String category, DateTime? retry) {
    final label = category == 'hotel' ? 'Hotel' : 'Flight';
    if (retry == null)
      return '$label search limit reached. Please try again later.';
    final malaysia = retry.toUtc().add(const Duration(hours: 8));
    return '$label search limit reached. Try again at ' +
        malaysia.toIso8601String().substring(0, 16).replaceFirst('T', ' ') +
        ' MYT.';
  }

  Future<void> discover(String category) async {
    if (discovering != null ||
        applying ||
        widget.tripId == null ||
        stateVersion == null) return;
    final tripId = widget.tripId!;
    final state = stateVersion;
    final version = _loadVersion;
    setState(() => discovering = category);
    try {
      final accepted = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
                title: Text(category == 'flight'
                    ? 'Find cheaper flights?'
                    : 'Find cheaper hotels?'),
                content: Text(category == 'flight'
                    ? 'Search matching fares using up to 2 provider requests. This may use API quota. Quote records may be saved; your trip and bookings stay unchanged until you confirm a replacement.'
                    : 'Search matching stays using 1 provider rates request. This may use API quota. A rate is not a reservation. Your trip stays unchanged until you confirm a replacement.'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Cancel')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Search now')),
                ],
              ));
      if (!mounted ||
          accepted != true ||
          version != _loadVersion ||
          widget.tripId != tripId) return;
      setState(() {
        searchMessages.remove(category);
        searchRetryAt.remove(category);
      });
      final result = await api.post(
          '/api/fr5/itineraries/$tripId/lower-cost-alternatives/discover', {
        'category': category,
        'providerSearchConfirmed': true,
        'searchRequestId': newTransactionAttemptId('budget_search'),
        if(category=='flight') ...cabinRequest,
        'stateVersion': state
      });
      if (!mounted || version != _loadVersion) return;
      final search = result['search'] as Map? ?? {};
      final status = search['status'];
      final retry = DateTime.tryParse(search['retryAt']?.toString() ?? '');
      final message = switch (status) {
        'completed' => 'Checking returned offers…',
        'pending' =>
          'Search is still processing. Refresh saved results before trying again.',
        'quota_limited' => searchLimitMessage(category, retry),
        'retry_available' =>
          'Search limit has reset. You can start a new search.',
        'needs_review' => searchBlocked(category),
        'unavailable' => switch (search['failureCode']) {
            'provider_timeout' =>
              'The provider search timed out. No result was confirmed; refresh saved results before trying again.',
            'provider_rate_limited' =>
              'The provider search limit was reached. Please try again later.',
            _ =>
              'The provider could not complete the search. No result was confirmed.',
          },
        _ =>
          'Provider search is unavailable. Your local planning options remain available.',
      };
      setState(() {
        searchMessages[category] = message;
        if (status == 'quota_limited' && retry != null)
          searchRetryAt[category] = retry;
      });
      await load();
      if (mounted && widget.tripId == tripId && status == 'completed') {
        final available = alternatives.any((item) =>
            item['alternativeType'] == category && _canApplyItem(item));
        setState(() => searchMessages[category] = available
            ? 'Verified cheaper offers are ready to preview.'
            : loadError != null
                ? 'Search finished, but saved offers could not be loaded. Refresh saved results.'
                : (status == 'completed' &&
                        (search['requestsAttempted'] as num? ?? 0) == 0)
                    ? searchBlocked(category)
                    : category == 'flight' && flightTimingPreviews.isNotEmpty
                        ? 'Cheaper flights need a timing review before they can be used.'
                        : noOffer(category));
      }
    } catch (error) {
      if (mounted && version == _loadVersion) {
        setState(() => searchMessages[category] = error is ApiException &&
                error.statusCode == 429
            ? searchLimitMessage(category, null)
            : error is ApiException && error.statusCode == 409
                ? error.code == 'STALE_ALTERNATIVE'
                    ? 'This trip changed. Refresh alternatives before searching again.'
                    : userFacingApiError(error)
                : 'Search could not be confirmed. Refresh saved results before trying again.');
      }
    } finally {
      if (mounted && widget.tripId == tripId)
        setState(() => discovering = null);
    }
  }

  Future<void> openHotels() async {
    final criteria=hotelComparison['searchCriteria'] as Map? ?? {};
    await Navigator.push(context,MaterialPageRoute(builder:(_)=>HotelScreen(api:api,targetTripId:widget.tripId,
      initialDestination:criteria['destination']?.toString(),initialCheckin:criteria['checkin']?.toString(),
      initialCheckout:criteria['checkout']?.toString(),initialAdults:criteria['adults'] as int?,
      initialChildren:criteria['children'] is num ? (criteria['children'] as num).toInt():null,
      initialOccupancies:(criteria['occupancies'] as List?)?.whereType<Map>().map((r)=>Map<String,dynamic>.from(r)).toList())));
    if(mounted) await load();
  }

  List<Widget> flightDetails(String label,Map flight) => [
    if(flight.isNotEmpty) Text('$label flight: ${flight['airline'] ?? 'Airline not supplied'}'),
    for(final leg in ['outboundSegments','returnSegments'])
      for(final segment in (flight[leg] as List? ?? []).whereType<Map>())
        Text('${segment['departureAirportCode'] ?? ''} ${segment['departureDate'] ?? ''} ${segment['departureTime'] ?? ''}'
             ' → ${segment['arrivalAirportCode'] ?? ''} ${segment['arrivalTime'] ?? ''}'),
    if(flight['durationMinutes']!=null) Text('$label duration: ${flight['durationMinutes']} minutes'),
    if(flight['stops']!=null) Text('$label stops: ${flight['stops']}'),
    if(flight['baggage']!=null) Text('Baggage: ${flight['baggage']}'),
    if(flight.isNotEmpty && flight['baggage']==null) const Text('Baggage and fare conditions: not supplied; verify with the airline.'),
  ];

  List<Widget> selectionDetails(Map item) {
    final data=item['data'] is Map ? item['data'] as Map : <String,dynamic>{};
    final original=item['originalSelection'] is Map ? item['originalSelection'] as Map : <String,dynamic>{};
    if(item['alternativeType']=='flight') {
      final cabin=data['cabin'] as Map? ?? {};
      return [
        if(cabin.isNotEmpty) Text('${cabin['cabinDowngrade']==true ? 'Cabin downgrade' : 'Same cabin'}: '
          '${cabins[cabin['originalCabin']]} → ${cabins[cabin['comparisonCabin']]}'),
        ...flightDetails('Original',original),...flightDetails('Proposed',data),
        Text(item['comparisonStatus']=='requires_schedule_adjustment' ? 'Requires Schedule Adjustment':'Ready to Preview'),
      ];
    }
    if(item['alternativeType']=='hotel') {
      final criteria=data['comparisonCriteria'] as Map? ?? data['stayCriteria'] as Map? ?? {};
      return [Text('Original stay: ${original['name'] ?? 'Selected hotel'}'),
        Text('Proposed stay: ${data['name'] ?? 'Hotel'} · ${data['roomName'] ?? 'Room details unavailable'}'),
        Text('${criteria['checkin'] ?? ''} – ${criteria['checkout'] ?? ''} · ${criteria['roomQuantity'] ?? '?'} room(s)'),
        Text('Adults: ${criteria['adults'] ?? '?'} · Children: ${criteria['children'] ?? 0}'),
        const Text('Selected planning quote — not paid or a confirmed reservation.')];
    }
    return [];
  }

  Widget discoveryCard(String category) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: InkCard(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(category == 'flight' ? 'Flights' : 'Hotels',
              style: const TextStyle(fontWeight: FontWeight.w700)),
          const Text('Look for a cheaper comparable planning quote.'),
          if(category=='flight') ...[
            Text('Original cabin: ${cabins[flightComparison['originalCabin']] ?? 'Not established'}'),
            Text(includeLowerCabins ? 'Comparison: Include Lower Cabin Classes · ${cabins[comparisonCabin] ?? ''}' : 'Comparison: Same Cabin Class'),
            if((flightComparison['originalCabin'] as num? ?? 1)>1) SwitchListTile(contentPadding:EdgeInsets.zero,
              title:const Text('Include lower cabin classes'),subtitle:const Text('Choose one cabin per search. No silent downgrade.'),
              value:includeLowerCabins,onChanged:discovering!=null || applying ? null : (value){
                setState((){includeLowerCabins=value;comparisonCabin=value ? 1:null;searchMessages.remove('flight');});load();}),
            if(includeLowerCabins) DropdownButtonFormField<int>(initialValue:comparisonCabin,isExpanded:true,
              decoration:const InputDecoration(labelText:'Cabin to compare'),
              items:[for(final cabin in cabins.entries) if(cabin.key <= (flightComparison['originalCabin'] as num? ?? 1))
                DropdownMenuItem(value:cabin.key,child:Text(cabin.value))],
              onChanged:discovering!=null || applying ? null : (value){setState(()=>comparisonCabin=value);load();}),
          ],
          for(final reason in ((category=='hotel' ? hotelComparison:flightComparison)['reasons'] as List? ?? [])) Text('$reason'),
          if(category=='hotel' && hotelComparison['nextAction']=='search_hotels') TextButton(
            onPressed:applying || discovering!=null ? null : openHotels,child:const Text('Review selected stay in Hotels')),
          if (searchMessages[category] != null) Text(searchMessages[category]!),
          OutlinedButton(
              onPressed: discovering != null || applying || stateVersion == null ||
                  (category=='hotel' ? hotelComparison:flightComparison)['status']=='needs_review'
                  ? null
                  : () => discover(category),
              child: Text(discovering == category
                  ? 'Searching…'
                  : category == 'flight'
                      ? 'Find cheaper flights'
                      : 'Find cheaper hotels')),
        ])),
      );

  Widget timingReviewCard(Map<String, dynamic> preview) => Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: InkCard(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${preview['title'] ?? 'Requires Schedule Adjustment'}',
            style: TextStyle(fontWeight: FontWeight.w700)),
        Text('MYR ' +
            money(preview['currentCost']) +
            ' → MYR ' +
            money(preview['proposedCost'])),
        Text((preview['reason'] ?? 'The flights conflict with planned visits.')
            .toString()),
        for(final entry in {'Original':preview['originalFlight'],'Proposed':preview['proposedFlight']}.entries)
          ...flightDetails(entry.key,entry.value is Map ? entry.value as Map : {}),
        TextButton(
            onPressed: () => showDialog<void>(
                context: context,
                builder: (context) => AlertDialog(
                        title: const Text('Review flight timing'),
                        scrollable: true,
                        content: Column(
                            mainAxisSize: MainAxisSize.min,
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text((preview['reason'] ?? '').toString()),
                              for (final change
                                  in (preview['itineraryChanges'] as List? ??
                                          [])
                                      .whereType<Map>())
                                Text((change['activityName'] ?? 'Visit')
                                        .toString() +
                                    ' — ' +
                                    (change['kind'] ?? 'review').toString() +
                                    (change['to'] is Map
                                        ? ' ' +
                                            (change['to'][
                                                        'scheduledStartTime'] ??
                                                    '')
                                                .toString()
                                        : '')),
                              const Text(
                                  'This flight cannot be applied while visits conflict. Choose different flight times or review your trip dates. Your trip is unchanged.'),
                            ]),
                        actions: [
                          TextButton(
                              onPressed: () => Navigator.pop(context),
                              child: const Text('Close'))
                        ])),
            child: const Text('Review timing')),
      ])));

  double? _extractSavings(Map<String, dynamic> item) {
    final raw = item['estimatedSavings'] ?? item['saving'];
    if (raw == null) return null;
    if (raw is num) return raw > 0 ? raw.toDouble() : null;
    final parsed = double.tryParse(raw.toString());
    return (parsed != null && parsed > 0) ? parsed : null;
  }

  bool _canApplyItem(Map<String, dynamic> item) =>
      (widget.tripId ?? '').isNotEmpty &&
      item['canApply'] == true &&
      item['isAdvisory'] != true &&
      item['stateVersion'] is String &&
      _extractSavings(item) != null;

  Future<void> applyAlternative(Map<String, dynamic> item) async {
    if (busy || applying || discovering != null || !_canApplyItem(item)) return;
    final tripId = widget.tripId;
    final version = _loadVersion;
    setState(() => applying = true);
    dynamic preview;
    try {
      preview = await api.post(
          '/api/fr5/itineraries/$tripId/lower-cost-alternatives/preview',
          {'alternative': item});
    } catch (error) {
      if (mounted) {
        setState(() => applying = false);
        showError(context, error);
      }
      return;
    }
    if (!mounted || version != _loadVersion) return;
    final confirmed = await confirmPreview(item, preview);
    if (mounted) setState(() => applying = false);
    if (!mounted || confirmed != true || busy || version != _loadVersion)
      return;
    setState(() => applying = true);
    var refresh = false;
    try {
      final data = await api.post(
        '/api/fr5/itineraries/$tripId/lower-cost-alternatives/apply',
        {'alternative': item},
      );
      if (!mounted || version != _loadVersion) return;
      final updated = data['itinerary'];
      if (updated is! Map || updated['id'] != widget.tripId) {
        throw StateError('The trip update could not be confirmed.');
      }
      widget.onApplied?.call(Map<String, dynamic>.from(updated));
      setState(() {
        if (data['planningAlternatives'] is List) {
          planning = (data['planningAlternatives'] as List)
              .whereType<Map>()
              .map((row) => Map<String, dynamic>.from(row))
              .toList();
        }
        budget = data['budget'] is Map
            ? Map<String, dynamic>.from(data['budget'] as Map)
            : budget;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Lower-cost alternative applied.')),
      );
      refresh = true;
    } catch (e) {
      if (!mounted || version != _loadVersion) return;
      showError(context, e);
      refresh = e is ApiException && e.statusCode == 409;
    } finally {
      if (mounted && version == _loadVersion) setState(() => applying = false);
    }
    if (refresh && mounted && version == _loadVersion) await load();
  }

  Widget optionCard(Map<String, dynamic> item, {bool local = false}) {
    final canApply = local || _canApplyItem(item);
    final saving = _extractSavings(item);
    final before = item['currentEstimatedCost'];
    final after = item['replacementEstimatedCost'];
    final remaining = item['remainingOverBy'];
    return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: InkCard(
            child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
                (item['category'] ??
                        item['alternativeType'] ??
                        'Planning advice')
                    .toString(),
                style: Theme.of(context).textTheme.labelLarge),
            Text((item['title'] ?? 'Lower-cost option').toString(),
                style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text((item['description'] ?? '').toString()),
            if(item['alternativeType']=='flight' || item['alternativeType']=='hotel') ...[
              if(item['data'] is Map && item['data']['cabin'] is Map && item['data']['cabin']['cabinDowngrade']==true)
                Text('Cabin downgrade: ${cabins[item['data']['cabin']['originalCabin']]} → ${cabins[item['data']['cabin']['comparisonCabin']]}'),
              ExpansionTile(title:Text(item['alternativeType']=='flight' ? 'Compare flight details':'Compare stay details'),
                children:selectionDetails(item)),
            ],
            if (item['data'] is Map && item['alternativeType'] == 'hotel')
              Text(((item['data']['roomName'] ?? '')).toString() +
                  ' · ' +
                  ((item['data']['address'] ?? '')).toString()),
            if (before is num && after is num)
              Text('RM ' + money(before) + ' → RM ' + money(after)),
            if (saving != null && canApply)
              Text('Estimated reduction: RM ' + money(saving)),
            if (remaining is num)
              Text('Remaining over budget: RM ' + money(remaining)),
            if (item['source'] != null)
              Text('Source: ' + item['source'].toString(),
                  style: Theme.of(context).textTheme.bodySmall),
            if (!canApply) const Text('Advisory guidance'),
            if (canApply)
              Align(
                  alignment: Alignment.centerRight,
                  child: FilledButton.tonal(
                    onPressed: applying || discovering != null
                        ? null
                        : () => local
                            ? previewPlanning(item)
                            : applyAlternative(item),
                    child: Text(item['comparisonStatus']=='requires_schedule_adjustment' ? 'Review schedule':'Preview'),
                  )),
          ],
        )));
  }

  List<Widget> comparisonResults(String kind) {
    final rows=alternatives.where((row)=>row['alternativeType']==kind).toList();
    final ready=rows.where((row)=>row['comparisonStatus']!='requires_schedule_adjustment').toList();
    final changes=rows.where((row)=>row['comparisonStatus']=='requires_schedule_adjustment').toList();
    final rejected=categoryRejections[kind] as Map? ?? {};
    return [
      if(ready.isNotEmpty) const Text('Ready to Preview',style:TextStyle(fontWeight:FontWeight.w700)),
      for(final row in ready) optionCard(row),
      if(changes.isNotEmpty || kind=='flight' && flightTimingPreviews.isNotEmpty)
        const Text('Requires Schedule Adjustment',style:TextStyle(fontWeight:FontWeight.w700)),
      for(final row in changes) optionCard(row),
      if(kind=='flight') for(final row in flightTimingPreviews) timingReviewCard(row),
      if(rejected.isNotEmpty) ExpansionTile(title:const Text('Unavailable options · details'),
        children:[for(final entry in rejected.entries) ListTile(title:Text('${entry.key}'),trailing:Text('${entry.value}'))]),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final total = budget?['total'] ?? widget.budget.totalCost;
    final limit = budget?['limit'] ?? widget.userBudget;
    final pending = (budget?['pendingExpenseCategories'] as List? ??
        widget.budget.pendingExpenseCategories);
    return Scaffold(
      appBar: AppBar(title: const Text('Lower-Cost Alternatives')),
      body: RefreshIndicator(
          onRefresh: load,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
            children: [
              InkCard(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    const Text('Budget overview',style:TextStyle(fontWeight:FontWeight.w700)),
                    Text('Budget: RM ' + money(limit)),
                    Text('Known estimate: RM ' + money(total)),
                    if (_overBudget)
                      Text('Over budget: RM ' +
                          money((total as num) - (limit as num))),
                    if (!_overBudget && !busy)
                      const Text(
                          'Your known estimate does not exceed the budget.'),
                    if (pending.isNotEmpty)
                      Text('Unpriced: ${pending.join(', ')}. The known subtotal does not establish full-trip affordability.'),
                  ])),
              const SizedBox(height: 16),
              if (_overBudget) ...[
                const Text('Available ways to save',
                    style:
                        TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                const SizedBox(height: 12),
                const Text('Flight comparison',style:TextStyle(fontSize:18,fontWeight:FontWeight.w700)),
                if (!api.isStandalone &&
                    (widget.tripId ?? '').isNotEmpty &&
                    (budget?['flight'] as num? ?? widget.budget.flight) > 0)
                  discoveryCard('flight'),
                ...comparisonResults('flight'),
                const SizedBox(height:16),
                const Text('Hotel comparison',style:TextStyle(fontSize:18,fontWeight:FontWeight.w700)),
                if (!api.isStandalone &&
                    (widget.tripId ?? '').isNotEmpty &&
                    (budget?['hotel'] as num? ?? widget.budget.accommodation) >
                        0)
                  discoveryCard('hotel'),
                ...comparisonResults('hotel'),
                const SizedBox(height:16),
                const Text('Other budget adjustments',style:TextStyle(fontSize:18,fontWeight:FontWeight.w700)),
                for (final item in planning) optionCard(item, local: true),
                for (final item in alternatives.where((row)=>!['flight','hotel'].contains(row['alternativeType']))) optionCard(item),
                if (replanOptions != null)
                  FilledButton(
                      onPressed: applying ? null : openReplan,
                      child: const Text('Review budget options')),
                if (optionsChanged)
                  const Text(
                      'Options have been refreshed for this trip. Earlier options may no longer apply.'),
                if (checkingPrices)
                  const Padding(
                      padding: EdgeInsets.all(12),
                      child: LinearProgressIndicator()),
                if (loadError != null) ...[
                  const Text(
                      'Replacement prices are unavailable. You can still review available planning changes.'),
                  TextButton(onPressed: load, child: const Text('Try again')),
                ],
                if (!checkingPrices && alternatives.isEmpty)
                  const Text(
                      'No saved replacement quotes are available to preview. Use the search buttons to check current offers.'),
                if (!checkingPrices &&
                    planning.isEmpty &&
                    replanOptions == null)
                  const Text('No eligible planning reductions are available.'),
              ],
            ],
          )),
    );
  }
}
