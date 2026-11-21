import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/transaction_request.dart';
import '../../theme/app_theme.dart';
import 'flight_adjustment_preview_sheet.dart';

class PlanningSettingsSheet extends StatefulWidget {
  final Map<String, dynamic> trip;
  final ApiService api;
  final String? initialBlockType;
  final int initialDay;
  const PlanningSettingsSheet(
      {super.key,
      required this.trip,
      required this.api,
      this.initialBlockType,
      this.initialDay = 1});

  static Future<Map<String, dynamic>?> show(
          BuildContext context, ApiService api, Map<String, dynamic> trip,
          {String? initialBlockType, int initialDay = 1}) =>
      showModalBottomSheet<Map<String, dynamic>>(
          context: context,
          isScrollControlled: true,
          useSafeArea: true,
          builder: (_) => PlanningSettingsSheet(
              trip: trip,
              api: api,
              initialBlockType: initialBlockType,
              initialDay: initialDay));

  @override
  State<PlanningSettingsSheet> createState() => _PlanningSettingsSheetState();
}

class _PlanningSettingsSheetState extends State<PlanningSettingsSheet> {
  late String mode, arrival, departure;
  late String travelMode;
  String? arrivalStart, departureEnd;
  late Map<String, dynamic> transport;
  late List<Map<String, dynamic>> days, blocks;
  late TextEditingController buffer;
  bool busy = false;
  bool preferencesTouched = false, blocksTouched = false;
  bool travelTouched = false;
  String? error;
  int get count =>
      DateTime.parse(widget.trip['endDate'].toString().substring(0, 10))
          .difference(DateTime.parse(
              widget.trip['startDate'].toString().substring(0, 10)))
          .inDays +
      1;
  Map<String, dynamic> map(dynamic value) =>
      value is Map ? Map<String, dynamic>.from(value) : {};
  List<Map<String, dynamic>> rows(dynamic value) =>
      value is List ? value.whereType<Map>().map(map).toList() : [];
  @override
  void initState() {
    super.initState();
    final prefs = map(widget.trip['travelDayPreferences']);
    mode = widget.trip['planningMode']?.toString() ?? 'smart';
    travelMode = widget.trip['travelMode']?.toString() ?? 'undecided';
    arrival = map(prefs['arrival'])['choice']?.toString() ?? 'practical';
    departure = map(prefs['departure'])['choice']?.toString() ?? 'keep';
    arrivalStart = map(prefs['arrival'])['startTime'];
    departureEnd = map(prefs['departure'])['endTime'];
    transport = map(prefs['transport']);
    buffer = TextEditingController(text: '${transport['bufferMinutes'] ?? 0}');
    days = rows(prefs['days']);
    blocks = rows(
        widget.trip['planningBlocks'] ?? widget.trip['planningPersonalBlocks']);
    if (widget.initialBlockType != null)
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) editBlock();
      });
  }

  @override
  void dispose() {
    buffer.dispose();
    super.dispose();
  }

  String clock(TimeOfDay value) =>
      '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
  Future<String?> pick(String? value) async {
    final parts = (value ?? '09:00').split(':');
    final result = await showTimePicker(
        context: context,
        initialTime: TimeOfDay(
            hour: int.tryParse(parts.first) ?? 9,
            minute: int.tryParse(parts.last) ?? 0));
    return result == null ? null : clock(result);
  }

  Widget timeButton(String label, String? value, ValueChanged<String> set) =>
      OutlinedButton(
          onPressed: busy
              ? null
              : () async {
                  final result = await pick(value);
                  if (result != null && mounted)
                    setState(() {
                      preferencesTouched = true;
                      set(result);
                    });
                },
          child: Text('$label: ${value ?? 'Choose time'}'));
  Future<void> transportDate(String key) async {
    final start =
        DateTime.parse(widget.trip['startDate'].toString().substring(0, 10));
    final end =
        DateTime.parse(widget.trip['endDate'].toString().substring(0, 10));
    final result = await showDatePicker(
        context: context,
        initialDate:
            DateTime.tryParse(transport[key]?.toString() ?? '') ?? start,
        firstDate: start,
        lastDate: end);
    if (result != null && mounted)
      setState(() {
        preferencesTouched = true;
        transport[key] = result.toIso8601String().substring(0, 10);
      });
  }

  Map<String, dynamic> blockPayload(Map<String, dynamic> block) => {
        for (final key in [
          'blockId',
          'type',
          'label',
          'dayNo',
          'startTime',
          'endTime',
          'durationMinutes',
          'location',
          'notes',
          'locked',
          'estimatedCost',
          'boundary'
        ])
          if (block[key] != null) key: block[key]
      };

  Future<void> editBlock([int? index]) async {
    final old = index == null ? <String, dynamic>{} : blocks[index];
    final title = TextEditingController(text: old['label']?.toString() ?? '');
    final notes = TextEditingController(text: old['notes']?.toString() ?? '');
    final location =
        TextEditingController(text: old['location']?.toString() ?? '');
    final cost =
        TextEditingController(text: old['estimatedCost']?.toString() ?? '');
    final duration =
        TextEditingController(text: '${old['durationMinutes'] ?? 60}');
    var day = old['dayNo'] as int? ?? widget.initialDay;
    var kind = old['type']?.toString() ?? widget.initialBlockType ?? 'rest';
    var boundary = old['boundary']?.toString() ??
        ({'custom', 'hotel_luggage'}.contains(kind)
            ? 'destination'
            : 'personal');
    String? start = old['startTime'], end = old['endTime'];
    var locked = old['locked'] != false;
    String? failure;
    final result = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (dialogContext) => StatefulBuilder(
            builder: (context, update) => AlertDialog(
                    title: Text(index == null
                        ? 'Add personal block'
                        : 'Edit personal block'),
                    scrollable: true,
                    content: SizedBox(
                        width: 420,
                        child:
                            Column(mainAxisSize: MainAxisSize.min, children: [
                          TextField(
                              controller: title,
                              decoration:
                                  const InputDecoration(labelText: 'Title'),
                              maxLength: 160),
                          DropdownButtonFormField<String>(
                              initialValue: kind,
                              isExpanded: true,
                              itemHeight: null,
                              decoration:
                                  const InputDecoration(labelText: 'Type'),
                              items: const {
                                'rest': 'Rest',
                                'meal': 'Meal break',
                                'hotel_luggage': 'Hotel / luggage time',
                                'free_time': 'Free time',
                                'transfer': 'Personal transfer',
                                'custom': 'Custom activity'
                              }
                                  .entries
                                  .map((e) => DropdownMenuItem(
                                      value: e.key, child: Text(e.value)))
                                  .toList(),
                              onChanged: (v) => update(() {
                                    kind = v!;
                                    boundary = {'custom', 'hotel_luggage'}
                                            .contains(kind)
                                        ? 'destination'
                                        : 'personal';
                                  })),
                          DropdownButtonFormField<int>(
                              initialValue: day,
                              isExpanded: true,
                              itemHeight: null,
                              decoration:
                                  const InputDecoration(labelText: 'Trip day'),
                              items: [
                                for (var n = 1; n <= count; n++)
                                  DropdownMenuItem(
                                      value: n, child: Text('Day $n'))
                              ],
                              onChanged: (v) => update(() => day = v!)),
                          DropdownButtonFormField<String>(
                              initialValue: boundary,
                              isExpanded: true,
                              itemHeight: null,
                              decoration: const InputDecoration(
                                  labelText: 'Time context'),
                              items: const [
                                DropdownMenuItem(
                                    value: 'destination',
                                    child: Text(
                                        'At destination: apply travel bounds')),
                                DropdownMenuItem(
                                    value: 'personal',
                                    child: Text(
                                        'Personal / travel plan: unverified timing'))
                              ],
                              onChanged: (v) => update(() => boundary = v!)),
                          Wrap(spacing: 8, runSpacing: 8, children: [
                            OutlinedButton(
                                onPressed: () async {
                                  final v = await pick(start);
                                  if (v != null) update(() => start = v);
                                },
                                child: Text('Start: ${start ?? 'Optional'}')),
                            OutlinedButton(
                                onPressed: () async {
                                  final v = await pick(end);
                                  if (v != null) update(() => end = v);
                                },
                                child: Text('End: ${end ?? 'Optional'}')),
                            TextButton(
                                onPressed: () => update(() {
                                      start = null;
                                      end = null;
                                    }),
                                child: const Text('Leave unscheduled')),
                          ]),
                          if (start == null && end == null)
                            TextField(
                                controller: duration,
                                keyboardType: TextInputType.number,
                                decoration: const InputDecoration(
                                    labelText: 'Duration estimate (minutes)')),
                          TextField(
                              controller: location,
                              decoration: const InputDecoration(
                                  labelText: 'Location (optional)'),
                              maxLength: 300),
                          TextField(
                              controller: notes,
                              decoration: const InputDecoration(
                                  labelText: 'Notes (optional)'),
                              maxLines: 3,
                              maxLength: 1000),
                          TextField(
                              controller: cost,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                  labelText:
                                      'Additional personal estimate (MYR)',
                                  helperText:
                                      'Optional. Blank means cost unknown.')),
                          const Text(
                              'This does not book a hotel or transfer. Do not repeat a hotel or flight amount already in your Budget. Untimed blocks do not reserve a time slot.'),
                          SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              value: locked,
                              onChanged: (v) => update(() => locked = v),
                              title: const Text('Keep this block fixed')),
                          if (failure != null)
                            Text(failure!,
                                style: const TextStyle(color: AppColors.error)),
                        ])),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(dialogContext),
                          child: const Text('Cancel')),
                      FilledButton(
                          onPressed: () {
                            final amount = double.tryParse(cost.text),
                                minutes = int.tryParse(duration.text);
                            if (title.text.trim().isEmpty ||
                                cost.text.trim().isNotEmpty &&
                                    (amount == null ||
                                        !amount.isFinite ||
                                        amount < 0) ||
                                (start == null) != (end == null) ||
                                start != null && start!.compareTo(end!) >= 0 ||
                                start == null &&
                                    (minutes == null || minutes < 1)) {
                              update(() => failure =
                                  'Enter a title, valid time range or duration, and non-negative cost.');
                              return;
                            }
                            Navigator.pop(dialogContext, {
                              'blockId': old['blockId'] ??
                                  newTransactionAttemptId('personal_block'),
                              'type': kind,
                              'label': title.text.trim(),
                              'dayNo': day,
                              if (start != null) 'startTime': start,
                              if (end != null) 'endTime': end,
                              if (start == null) 'durationMinutes': minutes,
                              'location': location.text.trim(),
                              'notes': notes.text.trim(),
                              'locked': locked,
                              if (amount != null) 'estimatedCost': amount,
                              'boundary': boundary
                            });
                          },
                          child: const Text('Keep in preview'))
                    ])));
    if (result != null && mounted)
      setState(() {
        blocksTouched = true;
        if (index == null) {
          blocks.add(result);
        } else {
          blocks[index] = result;
        }
      });
    // Dialog route removal may animate while its text fields are still mounted.
    await Future<void>.delayed(const Duration(milliseconds: 300));
    for (final controller in [title, notes, location, cost, duration])
      controller.dispose();
  }

  Future<void> preview() async {
    final minutes = int.tryParse(buffer.text);
    if (minutes == null || minutes < 0 || minutes > 720) {
      setState(() => error = 'Choose a buffer of 0–720 minutes.');
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    final preferences = <String, dynamic>{
      'arrival': {
        'choice': arrival,
        if (arrivalStart != null && {'rest', 'custom'}.contains(arrival))
          'startTime': arrivalStart
      },
      'departure': {
        'choice': departure,
        if (departureEnd != null && departure == 'custom')
          'endTime': departureEnd
      },
      'days': days,
      'transport': {...transport, 'bufferMinutes': minutes},
    };
    final result = await FlightAdjustmentPreviewSheet.show(
        context: context,
        api: widget.api,
        tripId: '${widget.trip['id']}',
        trip: widget.trip,
        title: 'Review planning changes',
        previewRequest: {
          'planningChanges': {
            'planningMode': mode,
            if (travelTouched) 'travelMode': travelMode,
            if (preferencesTouched) 'travelDayPreferences': preferences,
            if (blocksTouched)
              'planningBlocks': blocks.map(blockPayload).toList()
          },
          'action': 'settings',
          if (widget.trip['itineraryRevision'] is int)
            'expectedItineraryRevision': widget.trip['itineraryRevision']
        });
    if (!mounted) return;
    setState(() => busy = false);
    if (result?['itinerary'] is Map)
      Navigator.pop(context, Map<String, dynamic>.from(result!['itinerary']));
  }

  @override
  Widget build(BuildContext context) {
    final flight = map(widget.trip['selectedFlight']);
    final outbound = rows(flight['outboundSegments']),
        returns = rows(flight['returnSegments']);
    final assumptions = map(widget.trip['planningAssumptions']);
    final available = map(map(widget.trip['planningAvailability'])['days']);
    final arrivalDay = map(available[outbound.isNotEmpty
        ? outbound.last['arrivalDate']
        : transport['arrivalDate']]);
    final departureDay = map(available[returns.isNotEmpty
        ? returns.first['departureDate']
        : transport['departureDate']]);
    String minutes(int value) =>
        '${(value ~/ 60).toString().padLeft(2, '0')}:${(value % 60).toString().padLeft(2, '0')}';
    return SizedBox(
        height: MediaQuery.sizeOf(context).height * .92,
        child: Column(children: [
          Padding(
              padding: const EdgeInsets.all(12),
              child: Row(children: [
                const Expanded(
                    child: Text('Planning settings',
                        style: TextStyle(
                            fontSize: 20, fontWeight: FontWeight.w700))),
                TextButton(
                    onPressed: busy ? null : () => Navigator.pop(context),
                    child: const Text('Not now'))
              ])),
          Expanded(
              child: ListView(
                  padding: EdgeInsets.fromLTRB(
                      16, 0, 16, MediaQuery.viewInsetsOf(context).bottom + 24),
                  children: [
                DropdownButtonFormField<String>(
                    initialValue: mode,
                    isExpanded: true,
                    itemHeight: null,
                    decoration:
                        const InputDecoration(labelText: 'Planning style'),
                    items: const {
                      'smart': 'Smart Planning',
                      'manual': 'Manual Planning',
                      'assisted': 'Assisted Planning'
                    }
                        .entries
                        .map((e) => DropdownMenuItem(
                            value: e.key, child: Text(e.value)))
                        .toList(),
                    onChanged: busy ? null : (v) => setState(() => mode = v!)),
                if (widget.trip['planningMode'] == null)
                  const Text(
                      'This older trip has no saved planning style. It changes only when you apply a preview.'),
                if (flight.isEmpty)
                  DropdownButtonFormField<String>(
                      initialValue: travelMode,
                      isExpanded: true,
                      itemHeight: null,
                      decoration: const InputDecoration(
                          labelText: 'Travel arrangements'),
                      items: const {
                        'undecided': 'Undecided',
                        'flight': 'Flight (optional selection)',
                        'own_vehicle': 'Self-drive',
                        'public_transport': 'Bus / train (self-arranged)',
                        'other': 'Other arrangements'
                      }
                          .entries
                          .map((e) => DropdownMenuItem(
                              value: e.key, child: Text(e.value)))
                          .toList(),
                      onChanged: busy
                          ? null
                          : (v) => setState(() {
                                travelMode = v!;
                                travelTouched = true;
                              })),
                const SizedBox(height: 16),
                if (outbound.isNotEmpty)
                  Text(
                      'Arrival: ${outbound.last['arrivalAirportCode'] ?? 'Airport'} · ${outbound.last['arrivalDate'] ?? 'Date unavailable'} ${outbound.last['arrivalTime'] ?? 'Time unavailable'}'),
                if (returns.isNotEmpty)
                  Text(
                      'Departure: ${returns.first['departureAirportCode'] ?? 'Airport'} · ${returns.first['departureDate'] ?? 'Date unavailable'} ${returns.first['departureTime'] ?? 'Time unavailable'}'),
                if (flight.isNotEmpty)
                  Text(assumptions.isNotEmpty
                      ? 'Planning buffers: clearance ${assumptions['arrivalClearanceMinutes']} min + arrival transfer ${assumptions['arrivalTransferMinutes']} min; departure transfer ${assumptions['departureTransferMinutes']} min + check-in ${assumptions['departureCheckinMinutes']} min. Estimates, not airline requirements.'
                      : 'Review the configured airport buffers in the preview. They are planning estimates, not airline requirements.'),
                if (arrivalDay['earliestStartMinutes'] is int)
                  Text((arrivalDay['earliestStartMinutes'] as int) >= 1440
                      ? 'Arrival and travel buffers leave no sightseeing time that day.'
                      : 'Saved arrival travel bound: sightseeing from ${minutes(arrivalDay['earliestStartMinutes'])} at the earliest.'),
                if (departureDay['latestEndMinutes'] is int)
                  Text((departureDay['latestEndMinutes'] as int) <= 0
                      ? 'No sightseeing fits on the departure day.'
                      : 'Saved departure travel bound: finish by ${minutes(departureDay['latestEndMinutes'])}.'),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                    initialValue: arrival,
                    isExpanded: true,
                    itemHeight: null,
                    decoration: const InputDecoration(labelText: 'Arrival day'),
                    items: const {
                      'practical': 'Start when practical',
                      'rest': 'Rest / hotel / luggage first',
                      'custom': 'Choose my start time',
                      'none': 'No sightseeing'
                    }
                        .entries
                        .map((e) => DropdownMenuItem(
                            value: e.key, child: Text(e.value)))
                        .toList(),
                    onChanged: busy
                        ? null
                        : (v) => setState(() {
                              preferencesTouched = true;
                              arrival = v!;
                            })),
                if ({'rest', 'custom'}.contains(arrival))
                  timeButton('Sightseeing starts', arrivalStart,
                      (v) => arrivalStart = v),
                DropdownButtonFormField<String>(
                    initialValue: departure,
                    isExpanded: true,
                    itemHeight: null,
                    decoration:
                        const InputDecoration(labelText: 'Departure day'),
                    items: const {
                      'keep': 'Keep activities if they fit',
                      'light': 'Light sightseeing',
                      'custom': 'Choose my finish time',
                      'none': 'No sightseeing'
                    }
                        .entries
                        .map((e) => DropdownMenuItem(
                            value: e.key, child: Text(e.value)))
                        .toList(),
                    onChanged: busy
                        ? null
                        : (v) => setState(() {
                              preferencesTouched = true;
                              departure = v!;
                            })),
                if (departure == 'custom')
                  timeButton('Sightseeing ends', departureEnd,
                      (v) => departureEnd = v),
                if (flight.isEmpty)
                  ExpansionTile(
                      title: const Text('Estimated transport times (optional)'),
                      children: [
                        const Text(
                            'Your estimates are distinct from verified flight data. Leave unset if undecided.'),
                        for (final kind in ['arrival', 'departure'])
                          Wrap(spacing: 8, runSpacing: 8, children: [
                            OutlinedButton(
                                onPressed: () => transportDate('${kind}Date'),
                                child: Text(
                                    '$kind date: ${transport['${kind}Date'] ?? 'Optional'}')),
                            timeButton('$kind time', transport['${kind}Time'],
                                (v) => transport['${kind}Time'] = v),
                            TextButton(
                                onPressed: () => setState(() {
                                      preferencesTouched = true;
                                      transport.remove('${kind}Date');
                                      transport.remove('${kind}Time');
                                    }),
                                child: const Text('Clear')),
                          ]),
                        TextField(
                            controller: buffer,
                            onChanged: (_) => preferencesTouched = true,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                                labelText: 'Travel buffer (minutes)')),
                      ]),
                ExpansionTile(
                    title: const Text('Daily sightseeing windows'),
                    children: [
                      for (var day = 1; day <= count; day++)
                        Builder(builder: (context) {
                          final override = days
                              .where((row) => row['dayNo'] == day)
                              .firstOrNull;
                          void change(Map<String, dynamic> update) {
                            preferencesTouched = true;
                            days.removeWhere((row) => row['dayNo'] == day);
                            days.add({
                              'dayNo': day,
                              'startTime': '09:00',
                              'endTime': '18:00',
                              ...?override,
                              ...update
                            });
                          }

                          return Padding(
                              padding: const EdgeInsets.only(bottom: 12),
                              child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.stretch,
                                  children: [
                                    Text(
                                        'Day $day · ${override == null ? 'Travel-pace defaults' : 'Custom window'}'),
                                    SwitchListTile(
                                        contentPadding: EdgeInsets.zero,
                                        title: const Text('Rest day'),
                                        value: override?['restDay'] == true,
                                        onChanged: busy
                                            ? null
                                            : (v) => setState(
                                                () => change({'restDay': v}))),
                                    if (override?['restDay'] != true)
                                      Wrap(
                                          spacing: 8,
                                          runSpacing: 8,
                                          children: [
                                            timeButton(
                                                'Start',
                                                override?['startTime'],
                                                (v) =>
                                                    change({'startTime': v})),
                                            timeButton(
                                                'End',
                                                override?['endTime'],
                                                (v) => change({'endTime': v})),
                                          ]),
                                    Wrap(spacing: 8, runSpacing: 8, children: [
                                      TextButton(
                                          onPressed: () => setState(() {
                                                preferencesTouched = true;
                                                days.removeWhere((row) =>
                                                    row['dayNo'] == day);
                                              }),
                                          child: const Text('Use default')),
                                      if (count > 2 && override != null)
                                        TextButton(
                                            onPressed: () => setState(() {
                                                  preferencesTouched = true;
                                                  for (var n = 2;
                                                      n < count;
                                                      n++) {
                                                    days.removeWhere((row) =>
                                                        row['dayNo'] == n);
                                                    days.add({
                                                      ...override,
                                                      'dayNo': n
                                                    });
                                                  }
                                                }),
                                            child: const Text(
                                                'Apply to middle days')),
                                    ]),
                                  ]));
                        }),
                    ]),
                ExpansionTile(
                    title: Text('Personal planning blocks (${blocks.length})'),
                    initiallyExpanded: blocks.isNotEmpty,
                    children: [
                      for (var index = 0; index < blocks.length; index++)
                        ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text('${blocks[index]['label']}'),
                            subtitle: Text(
                                'Day ${blocks[index]['dayNo']} · ${blocks[index]['startTime'] ?? 'Unscheduled'} ${blocks[index]['endTime'] ?? ''}'),
                            onTap: () => editBlock(index),
                            trailing: IconButton(
                                tooltip: 'Remove personal block',
                                icon: const Icon(Icons.delete_outline),
                                onPressed: () => setState(() {
                                      blocksTouched = true;
                                      blocks.removeAt(index);
                                    }))),
                      OutlinedButton.icon(
                          onPressed: busy ? null : () => editBlock(),
                          icon: const Icon(Icons.add),
                          label: const Text('Add personal block')),
                    ]),
                const Text(
                    'No saved activities or arrangements change until you review and apply. Fixed visits and paid arrangements stay protected.'),
                if (error != null)
                  Text(error!, style: const TextStyle(color: AppColors.error)),
                const SizedBox(height: 12),
                FilledButton(
                    onPressed: busy ? null : preview,
                    child: const Text('Preview planning changes')),
              ])),
        ]));
  }
}
