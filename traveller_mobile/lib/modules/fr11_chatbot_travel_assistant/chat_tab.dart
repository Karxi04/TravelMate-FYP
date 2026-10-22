import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../core/navigation/app_shell_navigation.dart';
import '../fr03_destination_search_information/destination_details_screen.dart';
import '../fr05_smart_itinerary_budget_planner/trips_tab.dart';

class ChatTab extends StatefulWidget {
  final ApiService? api;

  const ChatTab({super.key, this.api});

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  final message = TextEditingController();
  late final ApiService api;

  List<dynamic> sessions = [];
  List<dynamic> messages = [];
  String? activeSessionId;
  bool busy = false;
  bool loadingSessions = true;
  String? screenError;
  String? sendError;
  String? failedMessage;

  final suggestions = const [
    'Plan things to do',
    'Adjust my itinerary',
    'Help with my budget',
    'What should I do if it rains?',
  ];

  Future<void> loadSessions({bool openNewest = true}) async {
    if (mounted) {
      setState(() {
        loadingSessions = true;
        screenError = null;
      });
    }
    try {
      final data = await api.get('/api/fr11/sessions');
      final list = data['items'] as List? ?? [];
      if (!mounted) return;
      setState(() => sessions = list);
      if (activeSessionId == null && list.isNotEmpty && openNewest) {
        final first = Map<String, dynamic>.from(list.first as Map);
        await openSession(first['id'].toString());
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          screenError = 'We couldn’t load your previous chats. Try again.';
        });
      }
    } finally {
      if (mounted) setState(() => loadingSessions = false);
    }
  }

  Future<void> newChat() async {
    try {
      final data =
          await api.post('/api/fr11/sessions', {'title': 'New travel chat'});
      final session = Map<String, dynamic>.from(data['session'] as Map);
      if (!mounted) return;
      setState(() {
        activeSessionId = session['id'].toString();
        messages = [];
      });
      await loadSessions(openNewest: false);
      if (mounted && Navigator.canPop(context)) Navigator.pop(context);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> openSession(String id) async {
    try {
      final data = await api.get('/api/fr11/sessions/$id');
      final session = Map<String, dynamic>.from(data['session'] as Map);
      if (!mounted) return;
      setState(() {
        activeSessionId = id;
        messages = session['messages'] as List? ?? [];
      });
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> deleteSession(String id) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.delete_outline_rounded, color: AppColors.error),
        title: const Text('Delete this chat?'),
        content: const Text(
          'This removes the conversation from your chat history.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Keep chat'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.error),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Delete chat'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await api.delete('/api/fr11/sessions/$id');
      if (activeSessionId == id) {
        activeSessionId = null;
        messages = [];
      }
      await loadSessions();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> send([String? quickText]) async {
    final text = (quickText ?? message.text).trim();
    if (text.isEmpty || busy) return;

    message.clear();
    setState(() {
      busy = true;
      sendError = null;
      failedMessage = text;
    });
    try {
      final data = await api.post('/api/fr11/chat', {
        'message': text,
        if (activeSessionId != null) 'sessionId': activeSessionId,
      });
      final session = data['session'];
      if (session is Map && mounted) {
        final s = Map<String, dynamic>.from(session);
        setState(() {
          activeSessionId = s['id'].toString();
          messages = s['messages'] as List? ?? [];
        });
      }
      await loadSessions(openNewest: false);
    } catch (_) {
      if (mounted) {
        setState(() {
          sendError =
              'Your message wasn’t sent. Check your connection and try again.';
        });
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> savePlan(Map<String, dynamic> plan) async {
    try {
      final data = await api.post('/api/fr11/save-plan', {'plan': plan});
      if (!mounted) return;
      final trip = data['itinerary'];
      final title = trip is Map ? (trip['title'] ?? 'Trip').toString() : 'Trip';
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$title saved to Trips.')));
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  String sessionTitle() {
    if (activeSessionId == null) return 'Travel Assistant';
    for (final raw in sessions) {
      final s = Map<String, dynamic>.from(raw as Map);
      if (s['id'].toString() == activeSessionId)
        return (s['title'] ?? 'Travel Assistant').toString();
    }
    return 'Travel Assistant';
  }

  Widget historyDrawer() {
    return Drawer(
      child: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
              child: Row(
                children: [
                  const Expanded(
                      child: Text('TravelMate chats',
                          style: TextStyle(
                              fontSize: 21, fontWeight: FontWeight.w900))),
                  IconButton(
                      onPressed: newChat,
                      icon: const Icon(Icons.add_comment_outlined),
                      tooltip: 'New chat'),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                    onPressed: newChat,
                    icon: const Icon(Icons.add_rounded),
                    label: const Text('New chat')),
              ),
            ),
            const SizedBox(height: 10),
            const Divider(height: 1),
            Expanded(
              child: loadingSessions
                  ? const AppLoadingState(message: 'Loading your chats…')
                  : screenError != null
                      ? AppErrorState(
                          message: screenError!, onRetry: loadSessions)
                      : sessions.isEmpty
                          ? const Center(
                              child: Padding(
                                  padding: EdgeInsets.all(24),
                                  child: Text(
                                      'Your previous travel chats will appear here.',
                                      textAlign: TextAlign.center,
                                      style: TextStyle(
                                          color: InkWashColors.mutedInk))))
                          : ListView.builder(
                              padding: const EdgeInsets.symmetric(vertical: 8),
                              itemCount: sessions.length,
                              itemBuilder: (context, index) {
                                final s = Map<String, dynamic>.from(
                                    sessions[index] as Map);
                                final selected =
                                    s['id'].toString() == activeSessionId;
                                return ListTile(
                                  selected: selected,
                                  leading: Icon(selected
                                      ? Icons.chat_bubble_rounded
                                      : Icons.chat_bubble_outline_rounded),
                                  title: Text(
                                      (s['title'] ?? 'Travel chat').toString(),
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis),
                                  subtitle: Text(
                                      (s['updatedAt'] ?? '')
                                          .toString()
                                          .split('T')
                                          .first,
                                      style: const TextStyle(fontSize: 11)),
                                  trailing: PopupMenuButton<String>(
                                    onSelected: (value) {
                                      if (value == 'delete')
                                        deleteSession(s['id'].toString());
                                    },
                                    itemBuilder: (_) => const [
                                      PopupMenuItem(
                                          value: 'delete',
                                          child: Text('Delete chat'))
                                    ],
                                  ),
                                  onTap: () async {
                                    Navigator.pop(context);
                                    await openSession(s['id'].toString());
                                  },
                                );
                              },
                            ),
            ),
          ],
        ),
      ),
    );
  }

  String destinationId(Map<String, dynamic> item) =>
      (item['destinationId'] ?? item['place_id'] ?? item['title'] ?? '')
          .toString();

  String dayText(Map<String, dynamic> activity, dynamic fallbackDay) {
    final label = (activity['dayLabel'] ?? '').toString();
    if (label.isNotEmpty) return label;
    final date = (activity['dayDate'] ?? '').toString();
    return date.isNotEmpty ? 'Day $fallbackDay - $date' : 'Day $fallbackDay';
  }

  String timeText(Map<String, dynamic> activity) {
    final range = (activity['timeRangeLabel'] ?? '').toString();
    if (range.isNotEmpty) return range;
    final slot = (activity['timeSlot'] ?? '').toString();
    return slot.isNotEmpty ? slot : 'Time not arranged';
  }

  String durationText(Map<String, dynamic> activity) {
    final minutes = int.tryParse(
          '${activity['recommendedDurationMinutes'] ?? activity['durationMinutes'] ?? 0}',
        ) ??
        0;
    final buffer = int.tryParse('${activity['travelBufferMinutes'] ?? 0}') ?? 0;
    final parts = <String>[];
    if (minutes > 0) parts.add('$minutes min visit');
    if (buffer > 0) parts.add('$buffer min travel buffer');
    return parts.join(' + ');
  }

  Future<void> addPlaceToTrip(Map<String, dynamic> item) async {
    try {
      final data = await api.get('/api/fr5/itineraries');
      final trips = data['items'] as List? ?? [];
      if (!mounted) return;
      if (trips.isEmpty) {
        final go = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Create a trip first'),
            content: const Text(
                'Create a trip, then add this place from the assistant.'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Go to Trips')),
            ],
          ),
        );
        if (go == true && mounted) {
          final switched =
              AppShellNavigation.select(context, AppShellTab.trips);
          if (!switched) {
            Navigator.push(
                context, MaterialPageRoute(builder: (_) => const TripsTab()));
          }
        }
        return;
      }
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(18, 0, 18, 22),
            children: [
              const Text('Add to which trip?',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
              const SizedBox(height: 8),
              ...trips.map((raw) {
                final trip = Map<String, dynamic>.from(raw as Map);
                return ListTile(
                  leading: const CircleAvatar(
                      backgroundColor: InkWashColors.cream,
                      child: Icon(Icons.luggage_outlined)),
                  title: Text((trip['title'] ?? 'Trip').toString()),
                  subtitle: Text((trip['destinationArea'] ?? '').toString()),
                  onTap: () => Navigator.pop(context, trip),
                );
              }),
            ],
          ),
        ),
      );
      if (selected == null) return;
      await api.post('/api/fr5/itineraries/${selected['id']}/activities', {
        'activityName': item['title'] ?? item['name'] ?? 'Place',
        'destinationId': destinationId(item),
        'address': item['address'] ?? '',
        'estimatedCost': item['estimatedCost'] ?? 0,
        'gps_coordinates':
            item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
        'type': item['type'] ?? item['category'] ?? '',
        'category': item['category'] ?? item['type'] ?? '',
        'description': item['description'] ?? '',
        'indoor': item['indoor'] ?? false,
        'openingHours': item['openingHours'] ?? '',
        'recommendedDurationMinutes': item['recommendedDurationMinutes'] ?? 90,
        'dayNo': 1,
      });
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Added to ${selected['title'] ?? 'trip'}')));
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Widget placeSuggestionsCard(List<Map<String, dynamic>> places) {
    return Container(
      margin: const EdgeInsets.only(top: 12),
      child: Column(
        children: places.map((place) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: InkCard(
              padding: EdgeInsets.zero,
              child: Row(
                children: [
                  TravelPlaceImage(
                    place: place,
                    width: 90,
                    height: 100,
                    borderRadius: const BorderRadius.horizontal(
                        left: Radius.circular(20)),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 9),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                              (place['title'] ?? place['name'] ?? 'Place')
                                  .toString(),
                              style:
                                  const TextStyle(fontWeight: FontWeight.w900)),
                          const SizedBox(height: 2),
                          Text((place['address'] ?? '').toString(),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  fontSize: 11, color: InkWashColors.mutedInk)),
                          const SizedBox(height: 5),
                          Text(
                              '★ ${place['rating'] ?? '-'} • ${place['category'] ?? place['type'] ?? ''}',
                              style: const TextStyle(fontSize: 11)),
                          const SizedBox(height: 6),
                          Wrap(
                            spacing: 6,
                            children: [
                              TextButton(
                                onPressed: () => Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                        builder: (_) =>
                                            DestinationDetailsScreen(
                                                initialDestination: place))),
                                child: const Text('Details'),
                              ),
                              TextButton(
                                  onPressed: () => addPlaceToTrip(place),
                                  child: const Text('Add to trip')),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(width: 6),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget planCard(Map<String, dynamic> plan) {
    final activities = (plan['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final days = <int, List<Map<String, dynamic>>>{};
    for (final a in activities) {
      final day = int.tryParse('${a['dayNo']}') ?? 1;
      days.putIfAbsent(day, () => []).add(a);
    }
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
          color: InkWashColors.cream,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: const Color(0xFFE2E2D0))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Icon(Icons.route_rounded, color: InkWashColors.blueGrey),
            const SizedBox(width: 7),
            Expanded(
                child: Text((plan['title'] ?? 'Trip plan').toString(),
                    style: const TextStyle(fontWeight: FontWeight.w900)))
          ]),
          const SizedBox(height: 7),
          Text(
              '${plan['startDate'] ?? ''} → ${plan['endDate'] ?? ''} • Budget RM ${plan['budgetLimit'] ?? 0}',
              style:
                  const TextStyle(fontSize: 12, color: InkWashColors.mutedInk)),
          const SizedBox(height: 9),
          ...days.entries.map((entry) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                        dayText(
                            Map<String, dynamic>.from(entry.value.first as Map),
                            entry.key),
                        style: const TextStyle(fontWeight: FontWeight.w900)),
                    ...entry.value.map((a) {
                      final activity = Map<String, dynamic>.from(a as Map);
                      final duration = durationText(activity);
                      final notes = (activity['scheduleNotes'] as List? ?? [])
                          .take(1)
                          .join(' ');
                      return Padding(
                        padding: const EdgeInsets.only(top: 3),
                        child: Text(
                          '• ${timeText(activity)}  ${activity['activityName'] ?? ''}${duration.isNotEmpty ? ' • $duration' : ''}${notes.isNotEmpty ? ' • $notes' : ''}',
                          style: const TextStyle(fontSize: 12),
                        ),
                      );
                    }),
                  ],
                ),
              )),
          const SizedBox(height: 5),
          SizedBox(
              width: double.infinity,
              child: FilledButton.tonalIcon(
                  onPressed: () => savePlan(plan),
                  icon: const Icon(Icons.bookmark_add_outlined),
                  label: const Text('Save plan to Trips'))),
        ],
      ),
    );
  }

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(loadSessions);
  }

  @override
  void dispose() {
    message.dispose();
    super.dispose();
  }

  bool usesSavedGuidance(Map<String, dynamic> item) {
    final source = (item['source'] ?? '').toString().toLowerCase();
    return {
      'fallback',
      'cache',
      'cached',
      'local',
      'standalone',
      'travelmate-assistant',
    }.contains(source);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      drawer: historyDrawer(),
      appBar: AppBar(
        title: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('TravelMate Assistant'),
            Text('How can I help with your trip?',
                style: TextStyle(
                    fontSize: 11,
                    color: InkWashColors.mutedInk,
                    fontWeight: FontWeight.w500)),
          ],
        ),
        actions: [
          IconButton(
              onPressed: newChat,
              icon: const Icon(Icons.add_comment_outlined),
              tooltip: 'New chat')
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
              children: [
                if (loadingSessions)
                  const AppLoadingState(message: 'Loading your chats…')
                else if (screenError != null)
                  AppErrorState(
                    message: screenError!,
                    onRetry: loadSessions,
                  )
                else if (messages.isEmpty) ...[
                  InkCard(
                    color: InkWashColors.cream,
                    child: const Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(Icons.auto_awesome_rounded,
                            color: InkWashColors.blueGrey, size: 31),
                        SizedBox(height: 9),
                        Text('How can I help with your trip?',
                            style: TextStyle(
                                fontSize: 20, fontWeight: FontWeight.w900)),
                        SizedBox(height: 5),
                        Text(
                            'Ask for ideas, itinerary changes, budget help or weather-friendly alternatives.'),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: suggestions
                        .map((item) => ActionChip(
                            label: Text(item),
                            onPressed: busy ? null : () => send(item)))
                        .toList(),
                  ),
                  const SizedBox(height: 16),
                ],
                if (!loadingSessions && screenError == null)
                  ...messages.expand((raw) {
                    final item = Map<String, dynamic>.from(raw as Map);
                    final plan = item['tripPlan'];
                    final placeSuggestions =
                        (item['placeSuggestions'] as List? ?? [])
                            .whereType<Map>()
                            .map((e) => Map<String, dynamic>.from(e))
                            .toList();
                    return [
                      Align(
                        alignment: Alignment.centerRight,
                        child: Semantics(
                          label: 'Your message',
                          child: Container(
                            margin: const EdgeInsets.only(bottom: 8, left: 52),
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                                color: InkWashColors.blueGrey,
                                borderRadius: BorderRadius.circular(17)),
                            child: Text((item['message'] ?? '').toString(),
                                style: const TextStyle(color: Colors.white)),
                          ),
                        ),
                      ),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Semantics(
                          label: 'TravelMate response',
                          child: Container(
                            margin:
                                const EdgeInsets.only(bottom: 14, right: 28),
                            padding: const EdgeInsets.all(13),
                            decoration: BoxDecoration(
                                color: Colors.white,
                                borderRadius: BorderRadius.circular(17),
                                border:
                                    Border.all(color: const Color(0xFFE3E3DE))),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text((item['reply'] ?? '').toString()),
                                if (usesSavedGuidance(item)) ...[
                                  const SizedBox(height: 10),
                                  const StatusChip(
                                    text: 'Using saved travel guidance',
                                    icon: Icons.offline_bolt_outlined,
                                    tone: AppStatusTone.warning,
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    'Check live details before making bookings.',
                                    style: Theme.of(context)
                                        .textTheme
                                        .bodySmall
                                        ?.copyWith(
                                          color: AppColors.textSecondary,
                                        ),
                                  ),
                                ],
                                if (placeSuggestions.isNotEmpty)
                                  placeSuggestionsCard(placeSuggestions),
                                if (plan is Map)
                                  planCard(Map<String, dynamic>.from(plan)),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ];
                  }),
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 180),
                  child: busy
                      ? const Align(
                          key: ValueKey('assistant-thinking'),
                          alignment: Alignment.centerLeft,
                          child: Padding(
                            padding: EdgeInsets.symmetric(vertical: 12),
                            child: StatusChip(
                              text: 'TravelMate is thinking…',
                              icon: Icons.auto_awesome_outlined,
                              tone: AppStatusTone.info,
                            ),
                          ),
                        )
                      : sendError != null
                          ? AppErrorState(
                              key: const ValueKey('assistant-send-error'),
                              title: 'Message not sent',
                              message: sendError!,
                              retryLabel: 'Retry message',
                              onRetry: failedMessage == null
                                  ? null
                                  : () => send(failedMessage),
                            )
                          : const SizedBox.shrink(),
                ),
              ],
            ),
          ),
          SafeArea(
            top: false,
            child: Container(
              padding: const EdgeInsets.all(10),
              decoration: const BoxDecoration(
                  color: Colors.white,
                  border: Border(top: BorderSide(color: Color(0xFFE7E7E2)))),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: TextField(
                      controller: message,
                      minLines: 1,
                      maxLines: 5,
                      onSubmitted: (_) => send(),
                      decoration: const InputDecoration(
                          hintText: 'Ask about your trip…',
                          prefixIcon: Icon(Icons.chat_bubble_outline_rounded)),
                    ),
                  ),
                  const SizedBox(width: 8),
                  SizedBox(
                      width: 52,
                      height: 52,
                      child: FilledButton(
                          style:
                              FilledButton.styleFrom(padding: EdgeInsets.zero),
                          onPressed: busy ? null : () => send(),
                          child: const Icon(
                            Icons.arrow_upward_rounded,
                            semanticLabel: 'Send message',
                          ))),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
