import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import 'personal_block_editor.dart';
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

  Widget transportEstimate(String kind, String title) {
    final date = transport['${kind}Date'];
    final time = transport['${kind}Time'];
    Widget control(String field, Object? value, VoidCallback onPressed) =>
        OutlinedButton(
            key: ValueKey('transport-$kind-$field'),
            onPressed: busy ? null : onPressed,
            child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Column(children: [
                  Text('$title $field'),
                  Text(value?.toString() ?? 'Choose $field'),
                ])));
    final controls = [
      control('date', date, () => transportDate('${kind}Date')),
      control('time', time, () async {
        final value = await pick(time?.toString());
        if (value != null && mounted) {
          setState(() {
            preferencesTouched = true;
            transport['${kind}Time'] = value;
          });
        }
      }),
    ];
    return Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child:
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(title, style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          LayoutBuilder(builder: (context, constraints) {
            if (constraints.maxWidth < 340 ||
                MediaQuery.textScalerOf(context).scale(14) > 18) {
              return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    controls[0],
                    const SizedBox(height: 8),
                    controls[1],
                  ]);
            }
            return Row(children: [
              Expanded(child: controls[0]),
              const SizedBox(width: 12),
              Expanded(child: controls[1])
            ]);
          }),
          Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                  key: ValueKey('clear-$kind-estimate'),
                  onPressed: busy || date == null && time == null
                      ? null
                      : () => setState(() {
                            preferencesTouched = true;
                            transport.remove('${kind}Date');
                            transport.remove('${kind}Time');
                          }),
                  child: Text('Clear ${kind.toLowerCase()} estimate'))),
        ]));
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
    final result = await Navigator.push<Map<String, dynamic>>(
        context,
        MaterialPageRoute(
            fullscreenDialog: true,
            builder: (_) => PersonalBlockEditor(
                initial: index == null ? null : blocks[index],
                dayCount: count,
                initialDay: widget.initialDay,
                initialType: widget.initialBlockType ?? 'rest')));
    if (result != null && mounted)
      setState(() {
        blocksTouched = true;
        if (index == null) {
          blocks.add(result);
        } else {
          blocks[index] = result;
        }
      });
  }

  String dayLabel(int day) {
    final date =
        DateTime.parse(widget.trip['startDate'].toString().substring(0, 10))
            .add(Duration(days: day - 1));
    final flight = map(widget.trip['selectedFlight']);
    final outbound = rows(flight['outboundSegments']),
        returns = rows(flight['returnSegments']);
    String datePart(dynamic value) =>
        value.toString().split('T').first.split(' ').first;
    final arrivalDate = datePart(
        (outbound.isEmpty ? null : outbound.last['arrivalDate']) ??
            transport['arrivalDate'] ??
            widget.trip['startDate']);
    final departureDate = datePart(
        (returns.isEmpty ? null : returns.first['departureDate']) ??
            transport['departureDate'] ??
            widget.trip['endDate']);
    final dayDate = date.toIso8601String().substring(0, 10);
    final role = dayDate == arrivalDate && dayDate == departureDate
        ? 'Arrival / departure day'
        : dayDate == arrivalDate
            ? 'Arrival day'
            : dayDate == departureDate
                ? 'Departure day'
                : dayDate.compareTo(arrivalDate) < 0 ||
                        dayDate.compareTo(departureDate) > 0
                    ? 'Travel day'
                    : 'Full day';
    return 'Day $day · ${MaterialLocalizations.of(context).formatMediumDate(date)} ${date.year} · $role';
  }

  Future<void> bulkHours() async {
    final selected = <int>{for (var n = 2; n < count; n++) n};
    var start = '09:00', end = '18:00';
    String? failure;
    final result = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (c) => StatefulBuilder(
            builder: (c, update) => AlertDialog(
                  title: const Text('Set hours for multiple days'),
                  scrollable: true,
                  content: SizedBox(
                      width: 420,
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                        Wrap(spacing: 8, runSpacing: 8, children: [
                          TextButton(
                              onPressed: () => update(() {
                                    selected.clear();
                                    selected.addAll(
                                        [for (var n = 2; n < count; n++) n]);
                                  }),
                              child: const Text('Select all middle days')),
                          TextButton(
                              onPressed: () => update(selected.clear),
                              child: const Text('Clear selection'))
                        ]),
                        for (var n = 1; n <= count; n++)
                          CheckboxListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(dayLabel(n)),
                              value: selected.contains(n),
                              onChanged: (v) => update(() {
                                    if (v == true) {
                                      selected.add(n);
                                    } else {
                                      selected.remove(n);
                                    }
                                  })),
                        Wrap(spacing: 8, runSpacing: 8, children: [
                          OutlinedButton(
                              onPressed: () async {
                                final v = await pick(start);
                                if (v != null) update(() => start = v);
                              },
                              child: Text('Start: $start')),
                          OutlinedButton(
                              onPressed: () async {
                                final v = await pick(end);
                                if (v != null) update(() => end = v);
                              },
                              child: Text('End: $end'))
                        ]),
                        Text(
                            'Days ${selected.toList()..sort()} will use $start–$end for sightseeing. Unselected days stay unchanged. Travel bounds still apply.'),
                        if (failure != null)
                          Text(failure!,
                              style: const TextStyle(color: AppColors.error)),
                      ])),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(c),
                        child: const Text('Cancel')),
                    FilledButton(
                        onPressed: () {
                          if (selected.isEmpty || start.compareTo(end) >= 0) {
                            update(() => failure =
                                'Choose days and a valid time range.');
                            return;
                          }
                          Navigator.pop(c, {
                            'days': selected.toList(),
                            'startTime': start,
                            'endTime': end
                          });
                        },
                        child: const Text('Apply to draft'))
                  ],
                )));
    if (result != null && mounted)
      setState(() {
        preferencesTouched = true;
        for (final day in result['days'] as List) {
          days.removeWhere((row) => row['dayNo'] == day);
          days.add({
            'dayNo': day,
            'startTime': result['startTime'],
            'endTime': result['endTime'],
            'restDay': false
          });
        }
      });
  }

  Future<void> preview() async {
    final minutes = int.tryParse(buffer.text);
    if (minutes == null || minutes < 0 || minutes > 720) {
      setState(() => error = 'Enter extra travel time from 0 to 720 minutes.');
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
    final keyboard = MediaQuery.viewInsetsOf(context).bottom;
    return Padding(
        padding: EdgeInsets.only(bottom: keyboard),
        child: SizedBox(
            height: (MediaQuery.sizeOf(context).height - keyboard) * .92,
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
                      keyboardDismissBehavior:
                          ScrollViewKeyboardDismissBehavior.onDrag,
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
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
                        onChanged:
                            busy ? null : (v) => setState(() => mode = v!)),
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
                    Text('Arrival and departure preferences',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                        initialValue: arrival,
                        isExpanded: true,
                        itemHeight: null,
                        decoration:
                            const InputDecoration(labelText: 'Arrival day'),
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
                    const SizedBox(height: 16),
                    ExpansionTile(
                        key: const ValueKey('planning-travel-schedule'),
                        title: const Text('Travel schedule'),
                        subtitle: Text(flight.isEmpty
                            ? 'Optional transport estimates'
                            : 'Selected flight times'),
                        initiallyExpanded: flight.isNotEmpty,
                        childrenPadding: const EdgeInsets.fromLTRB(8, 8, 8, 16),
                        expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          if (flight.isNotEmpty) ...[
                            if (outbound.isNotEmpty)
                              Text(
                                  'Arrival: ${outbound.last['arrivalAirportCode'] ?? 'Airport'} · ${outbound.last['arrivalDate'] ?? 'Date unavailable'} ${outbound.last['arrivalTime'] ?? 'Time unavailable'}'),
                            if (returns.isNotEmpty)
                              Text(
                                  'Departure: ${returns.first['departureAirportCode'] ?? 'Airport'} · ${returns.first['departureDate'] ?? 'Date unavailable'} ${returns.first['departureTime'] ?? 'Time unavailable'}'),
                            ExpansionTile(
                              title: const Text('Airport time allowances'),
                              children: [
                                Text(assumptions.isNotEmpty
                                    ? 'Clearance: ${assumptions['arrivalClearanceMinutes']} min. Arrival transfer: ${assumptions['arrivalTransferMinutes']} min. Departure transfer: ${assumptions['departureTransferMinutes']} min. Check-in: ${assumptions['departureCheckinMinutes']} min. Planning estimates, not airline requirements.'
                                    : 'Review the airport allowances in the preview. These are planning estimates, not airline requirements.')
                              ],
                            ),
                            if (arrivalDay['earliestStartMinutes'] is int)
                              Text((arrivalDay['earliestStartMinutes']
                                          as int) >=
                                      1440
                                  ? 'Arrival and travel buffers leave no sightseeing time that day.'
                                  : 'Saved arrival travel bound: sightseeing from ${minutes(arrivalDay['earliestStartMinutes'])} at the earliest.'),
                            if (departureDay['latestEndMinutes'] is int)
                              Text((departureDay['latestEndMinutes'] as int) <=
                                      0
                                  ? 'No sightseeing fits on the departure day.'
                                  : 'Saved departure travel bound: finish by ${minutes(departureDay['latestEndMinutes'])}.'),
                          ] else ...[
                            const Text(
                                'Optional estimates, not confirmed transport. Leave unset if undecided.'),
                            const SizedBox(height: 16),
                            transportEstimate('arrival', 'Arrival'),
                            transportEstimate('departure', 'Departure'),
                            const SizedBox(height: 8),
                            TextField(
                                key: const ValueKey('extra-travel-time'),
                                controller: buffer,
                                onChanged: (_) => preferencesTouched = true,
                                keyboardType: TextInputType.number,
                                decoration: const InputDecoration(
                                    labelText: 'Extra travel time (minutes)',
                                    helperText:
                                        'Optional time for stops or transfers. This is an estimate.',
                                    helperMaxLines: 3)),
                          ],
                        ]),
                    ExpansionTile(
                        title: const Text('Daily sightseeing windows'),
                        children: [
                          TextButton(
                              onPressed: busy ? null : bulkHours,
                              child: const Text('Set hours for multiple days')),
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
                                  key: ValueKey('planning-day-$day'),
                                  padding: const EdgeInsets.only(bottom: 12),
                                  child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.stretch,
                                      children: [
                                        Text(
                                            '${dayLabel(day)} · ${override == null ? 'Travel-pace defaults' : 'Custom window'}'),
                                        SwitchListTile(
                                            key: ValueKey('rest-day-$day'),
                                            contentPadding: EdgeInsets.zero,
                                            title: const Text('Rest day'),
                                            value: override?['restDay'] == true,
                                            onChanged: busy
                                                ? null
                                                : (v) => setState(() =>
                                                    change({'restDay': v}))),
                                        if (override?['restDay'] != true)
                                          Wrap(
                                              spacing: 8,
                                              runSpacing: 8,
                                              children: [
                                                timeButton(
                                                    'Start',
                                                    override?['startTime'],
                                                    (v) => change(
                                                        {'startTime': v})),
                                                timeButton(
                                                    'End',
                                                    override?['endTime'],
                                                    (v) =>
                                                        change({'endTime': v})),
                                              ]),
                                        Wrap(
                                            spacing: 8,
                                            runSpacing: 8,
                                            children: [
                                              TextButton(
                                                  onPressed: () => setState(() {
                                                        preferencesTouched =
                                                            true;
                                                        days.removeWhere(
                                                            (row) =>
                                                                row['dayNo'] ==
                                                                day);
                                                      }),
                                                  child: const Text(
                                                      'Use default')),
                                            ]),
                                      ]));
                            }),
                        ]),
                    ExpansionTile(
                        title:
                            Text('Personal planning blocks (${blocks.length})'),
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
                      Text(error!,
                          style: const TextStyle(color: AppColors.error)),
                    const SizedBox(height: 12),
                    FilledButton(
                        onPressed: busy ? null : preview,
                        child: const Text('Preview planning changes')),
                  ])),
            ])));
  }
}
