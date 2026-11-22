import 'package:flutter/material.dart';
import '../../services/transaction_request.dart';

/// A local draft editor. Only the parent's existing preview/apply can save a Trip.
class PersonalBlockEditor extends StatefulWidget {
  final Map<String, dynamic>? initial;
  final int dayCount, initialDay;
  final String initialType;
  const PersonalBlockEditor(
      {super.key,
      this.initial,
      required this.dayCount,
      this.initialDay = 1,
      this.initialType = 'rest'});
  @override
  State<PersonalBlockEditor> createState() => _PersonalBlockEditorState();
}

class _PersonalBlockEditorState extends State<PersonalBlockEditor> {
  final form = GlobalKey<FormState>();
  late final TextEditingController title, notes, location, cost, duration;
  late String type, boundary;
  late int day;
  late bool locked;
  String? start, end, timeError;
  @override
  void initState() {
    super.initState();
    final old = widget.initial ?? {};
    title = TextEditingController(text: old['label']?.toString() ?? '');
    notes = TextEditingController(text: old['notes']?.toString() ?? '');
    location = TextEditingController(text: old['location']?.toString() ?? '');
    cost = TextEditingController(text: old['estimatedCost']?.toString() ?? '');
    duration = TextEditingController(text: '${old['durationMinutes'] ?? 60}');
    type = old['type']?.toString() ?? widget.initialType;
    day = old['dayNo'] as int? ?? widget.initialDay;
    boundary = old['boundary']?.toString() ?? contextFor(type);
    locked = old['locked'] != false;
    start = old['startTime'];
    end = old['endTime'];
  }

  String contextFor(String kind) =>
      {'custom', 'hotel_luggage'}.contains(kind) ? 'destination' : 'personal';
  @override
  void dispose() {
    for (final c in [title, notes, location, cost, duration]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> pick(bool first) async {
    final parts = ((first ? start : end) ?? '09:00').split(':');
    final value = await showTimePicker(
        context: context,
        initialTime:
            TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1])));
    if (value != null && mounted)
      setState(() {
        final text =
            '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
        if (first) {
          start = text;
        } else {
          end = text;
        }
        timeError = null;
      });
  }

  void save() {
    final valid = form.currentState!.validate();
    if ((start == null) != (end == null) ||
        start != null && start!.compareTo(end!) >= 0) {
      setState(
          () => timeError = 'Choose both times, with the end after the start.');
      return;
    }
    if (!valid) return;
    final amount = double.tryParse(cost.text.trim());
    Navigator.pop(context, <String, dynamic>{
      'blockId': widget.initial?['blockId'] ??
          newTransactionAttemptId('personal_block'),
      'type': type,
      'label': title.text.trim(),
      'dayNo': day,
      'boundary': boundary,
      'locked': locked,
      if (start != null) 'startTime': start,
      if (end != null) 'endTime': end,
      if (start == null) 'durationMinutes': int.parse(duration.text),
      if (amount != null) 'estimatedCost': amount,
      'location': location.text.trim(),
      'notes': notes.text.trim()
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(
          title: Text(widget.initial == null
              ? 'Add personal block'
              : 'Edit personal block')),
      body: Column(children: [
        Expanded(
            child: Form(
                key: form,
                child: ListView(
                    keyboardDismissBehavior:
                        ScrollViewKeyboardDismissBehavior.onDrag,
                    padding: const EdgeInsets.all(16),
                    children: [
                      Text('Basic details',
                          style: Theme.of(context).textTheme.titleMedium),
                      TextFormField(
                          controller: title,
                          decoration: const InputDecoration(labelText: 'Title'),
                          maxLength: 160,
                          validator: (v) => v == null || v.trim().isEmpty
                              ? 'Give this plan a title.'
                              : null),
                      DropdownButtonFormField<String>(
                          initialValue: type,
                          isExpanded: true,
                          itemHeight: null,
                          decoration: const InputDecoration(labelText: 'Type'),
                          items: const {
                            'rest': 'Rest',
                            'meal': 'Meal',
                            'hotel_luggage': 'Hotel / luggage',
                            'free_time': 'Free time',
                            'transfer': 'Personal transport',
                            'custom': 'Custom activity'
                          }
                              .entries
                              .map((e) => DropdownMenuItem(
                                  value: e.key, child: Text(e.value)))
                              .toList(),
                          onChanged: (value) => setState(() {
                                type = value!;
                                boundary = contextFor(type);
                              })),
                      DropdownButtonFormField<int>(
                          initialValue: day,
                          isExpanded: true,
                          itemHeight: null,
                          decoration:
                              const InputDecoration(labelText: 'Trip day'),
                          items: [
                            for (var n = 1; n <= widget.dayCount; n++)
                              DropdownMenuItem(value: n, child: Text('Day $n'))
                          ],
                          onChanged: (v) => setState(() => day = v!)),
                      const SizedBox(height: 20),
                      Text('Time',
                          style: Theme.of(context).textTheme.titleMedium),
                      Wrap(spacing: 8, runSpacing: 8, children: [
                        OutlinedButton(
                            onPressed: () => pick(true),
                            child: Text('Start: ${start ?? 'Choose time'}')),
                        OutlinedButton(
                            onPressed: () => pick(false),
                            child: Text('End: ${end ?? 'Choose time'}')),
                        TextButton(
                            onPressed: () => setState(() {
                                  start = null;
                                  end = null;
                                  timeError = null;
                                }),
                            child: const Text('Leave unscheduled'))
                      ]),
                      if (timeError != null)
                        Text(timeError!,
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error)),
                      if (start == null && end == null) ...[
                        TextFormField(
                            controller: duration,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                                labelText: 'Duration estimate (minutes)'),
                            validator: (v) {
                              final n = int.tryParse(v ?? '');
                              return n == null || n < 1 || n > 1440
                                  ? 'Choose 1–1440 minutes.'
                                  : null;
                            }),
                        const Text(
                            'An unscheduled plan does not reserve an exact time slot.')
                      ],
                      const SizedBox(height: 16),
                      ExpansionTile(
                          title: const Text('Optional details'),
                          children: [
                            TextFormField(
                                controller: location,
                                decoration: const InputDecoration(
                                    labelText: 'Location'),
                                maxLength: 300),
                            TextFormField(
                                controller: notes,
                                decoration:
                                    const InputDecoration(labelText: 'Notes'),
                                maxLength: 1000,
                                maxLines: 3),
                            TextFormField(
                                controller: cost,
                                keyboardType:
                                    const TextInputType.numberWithOptions(
                                        decimal: true),
                                decoration: const InputDecoration(
                                    labelText: 'Estimated cost (RM) — Optional',
                                    helperText: 'Blank means cost unknown.'),
                                validator: (v) {
                                  if (v == null || v.trim().isEmpty)
                                    return null;
                                  final n = double.tryParse(v);
                                  return n == null ||
                                          !n.isFinite ||
                                          n < 0 ||
                                          n > 1000000
                                      ? 'Enter a non-negative estimate up to RM1,000,000.'
                                      : null;
                                }),
                            const Text(
                                'This is a personal estimate, not a booking or payment. Do not repeat a hotel or flight amount already in Budget.'),
                            SwitchListTile(
                                contentPadding: EdgeInsets.zero,
                                value: locked,
                                onChanged: (v) => setState(() => locked = v),
                                title: const Text('Keep this block fixed')),
                            DropdownButtonFormField<String>(
                                initialValue: boundary,
                                isExpanded: true,
                                itemHeight: null,
                                decoration: const InputDecoration(
                                    labelText: 'Planning context'),
                                items: const [
                                  DropdownMenuItem(
                                      value: 'destination',
                                      child:
                                          Text('Sightseeing / at destination')),
                                  DropdownMenuItem(
                                      value: 'personal',
                                      child:
                                          Text('Personal arrangement / travel'))
                                ],
                                onChanged: (v) =>
                                    setState(() => boundary = v!)),
                            const Text(
                                'Destination plans respect arrival and departure travel bounds. Personal arrangements are unverified notes and do not extend sightseeing time.')
                          ]),
                      const SizedBox(height: 16),
                    ]))),
        SafeArea(
            top: false,
            child: Padding(
                padding: const EdgeInsets.all(12),
                child: Wrap(
                    spacing: 12,
                    runSpacing: 8,
                    alignment: WrapAlignment.end,
                    children: [
                      TextButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('Cancel')),
                      FilledButton(
                          onPressed: save,
                          child: Text(widget.initial == null
                              ? 'Add to preview'
                              : 'Save changes')),
                    ]))),
      ]));
}
