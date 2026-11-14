import 'package:flutter/material.dart';
import 'dart:convert';
import 'database_chat_cards.dart';
import '../../widgets/local_place_rating.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../core/navigation/app_shell_navigation.dart';
import '../../core/operator_content/package_details_screen.dart';
import '../../core/operator_content/package_text_block.dart';
import '../fr03_destination_search_information/destination_details_screen.dart';
import '../fr03_destination_search_information/destination_trip_actions.dart';
import '../fr05_smart_itinerary_budget_planner/trips_tab.dart';
import '../fr05_smart_itinerary_budget_planner/packing_trip_selector_screen.dart';
import '../fr06_weather_forecast/weather_screen.dart';
import '../fr07_flight_search/flight_screen.dart';
import '../fr08_hotel_booking/hotel_screen.dart';

class ChatTab extends StatefulWidget {
  final ApiService? api;

  const ChatTab({super.key, this.api});

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  final message = TextEditingController();
  final conversationScroll = ScrollController();
  bool followReply = true;
  String? pendingMessage;

  void _showLatest() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && followReply && conversationScroll.hasClients) {
        conversationScroll.jumpTo(conversationScroll.position.maxScrollExtent);
      }
    });
  }
  final scaffoldKey = GlobalKey<ScaffoldState>();
  late final ApiService api;

  List<dynamic> sessions = [];
  List<dynamic> messages = [];
  String? activeSessionId;
  bool busy = false;
  bool loadingSessions = true;
  String? screenError;
  String? sendError;
  String? failedMessage;
  Map<String, dynamic> planningState = {};
  final Map<String, String> savedPlans = {};
  final Set<String> openingPackageIds = {};
  final Set<String> addingPlaceIds = {};
  String? savingPlanKey;

  String packageId(Map<String, dynamic> package) =>
      (package['packageId'] ?? package['id'] ?? '').toString().trim();

  Future<void> openPackageDetails(Map<String, dynamic> recommendation) async {
    final id = packageId(recommendation);
    if (id.isEmpty || openingPackageIds.isNotEmpty) return;
    openingPackageIds.add(id);
    setState(() {});
    try {
      final authoritative = recommendation['quoteContext'] is Map;
      final data = await api.get(authoritative
          ? '/api/fr11/packages/$id'
          : '/api/public/tourism-packages');
      if (data['ok'] == false)
        throw StateError('Package information is unavailable.');
      final matches = (authoritative
              ? [if (data['package'] is Map) data['package']]
              : (data['items'] as List? ?? const []))
          .whereType<Map>()
          .where((item) => item['id']?.toString() == id)
          .toList();
      if (matches.length != 1) {
        throw const ApiException(
            'This package is no longer available. Please choose another recommendation.',
            404, {});
      }
      if (!mounted) return;
      await Navigator.push(
          context,
          MaterialPageRoute(
              builder: (_) => TourismPackageDetailsScreen(
                  item: Map<String, dynamic>.from(matches.single),
                  api: api,
                  initialAdults:
                      recommendation['quoteContext']?['partyKnown'] == true
                          ? recommendation['quoteContext']['participants']
                              ['adults'] as int?
                          : null,
                  initialChildren:
                      recommendation['quoteContext']?['partyKnown'] == true
                          ? recommendation['quoteContext']['participants']
                              ['children'] as int?
                          : null,
                  initialPromoCode: recommendation['chatQuote']?['promotion']
                      ?['promoCode'] as String?,
                  initialDepartureDate:
                      recommendation['quoteContext']?['dateKnown'] == true
                          ? recommendation['quoteContext']['departureDate']
                              as String?
                          : null)));
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      openingPackageIds.remove(id);
      if (mounted) setState(() {});
    }
  }

  String planKey(Map<String, dynamic> plan) =>
      (plan['draftId'] ?? jsonEncode(plan)).toString();

  bool stalePlan(Map<String, dynamic> plan) {
    if (planningState['dateClarification'] != null) return true;
    final active = planningState['activePlan'];
    if (plan['draftId'] != null &&
        (active is! Map || active['draftId'] != plan['draftId'])) return true;
    if (plan['adjustmentTripId'] != null) return false;
    return planningState['startDate'] != null &&
        (planningState['startDate'] != plan['startDate'] ||
            planningState['endDate'] != plan['endDate']);
  }

  void acceptPlanningState(Map<String, dynamic> session) {
    planningState =
        Map<String, dynamic>.from(session['planningState'] as Map? ?? {});
    final saved = planningState['savedPlans'] as Map? ?? {};
    savedPlans.clear();
    for (final entry in saved.entries) {
      savedPlans[entry.key.toString()] = entry.value.toString();
    }
  }

  void openTrips() {
    if (!AppShellNavigation.select(context, AppShellTab.trips)) {
      Navigator.push(
          context, MaterialPageRoute(builder: (_) => TripsTab(api: api)));
    }
  }

  final suggestions = const [
    'Find a Penang package under RM500',
    'Show my saved trips',
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
    if (busy) return;
    setState(() => busy = true);
    try {
      final data =
          await api.post('/api/fr11/sessions', {'title': 'New travel chat'});
      final session = Map<String, dynamic>.from(data['session'] as Map);
      if (!mounted) return;
      setState(() {
        activeSessionId = session['id'].toString();
        messages = [];
        planningState = {};
        savedPlans.clear();
        sendError = null;
        failedMessage = null;
      });
      await loadSessions(openNewest: false);
      scaffoldKey.currentState?.closeDrawer();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> openSession(String id) async {
    if (busy) return;
    setState(() => busy = true);
    try {
      final data = await api.get('/api/fr11/sessions/$id');
      final session = Map<String, dynamic>.from(data['session'] as Map);
      if (!mounted) return;
      followReply = true;
      setState(() {
        activeSessionId = id;
        messages = session['messages'] as List? ?? [];
        acceptPlanningState(session);
        sendError = null;
        failedMessage = null;
      });
      _showLatest();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> deleteSession(String id) async {
    if (busy) return;
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
    setState(() => busy = true);
    try {
      await api.delete('/api/fr11/sessions/$id');
      if (activeSessionId == id) {
        activeSessionId = null;
        messages = [];
        planningState = {};
        savedPlans.clear();
        sendError = null;
        failedMessage = null;
      }
      await loadSessions(openNewest: false);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> send([String? quickText]) async {
    final text = (quickText ?? message.text).trim();
    if (text.isEmpty || busy) return;

    message.clear();
    followReply = true;
    setState(() {
      busy = true;
      sendError = null;
      failedMessage = text;
      pendingMessage = text;
    });
    _showLatest();
    try {
      final data = await api.post('/api/fr11/chat', {
        'message': text,
        'guidedPlanning': true,
        if (activeSessionId != null) 'sessionId': activeSessionId,
        if (planningState['commerceRevision'] != null)
          'commerceRevision': planningState['commerceRevision'],
      });
      final session = data['session'];
      if (session is Map && mounted) {
        final s = Map<String, dynamic>.from(session);
        setState(() {
          activeSessionId = s['id'].toString();
          messages = s['messages'] as List? ?? [];
          acceptPlanningState(s);
        });
      } else if (data['item'] is Map && mounted) {
        setState(() => messages = [...messages, data['item']]);
      }
      if (mounted && data['session'] is Map) {
        final summary = Map<String, dynamic>.from(data['session'] as Map)
          ..remove('messages');
        setState(() {
          sessions = [summary, ...sessions.where((row) => row is Map && row['id'].toString() != activeSessionId)];
        });
      }
    } catch (error) {
      if (error is ApiException &&
          error.statusCode == 409 &&
          activeSessionId != null) {
        try {
          final current = await api.get('/api/fr11/sessions/$activeSessionId');
          if (mounted && current['session'] is Map) {
            final session = Map<String, dynamic>.from(current['session']);
            setState(() {
              messages = session['messages'] as List? ?? [];
              acceptPlanningState(session);
            });
          }
        } catch (_) {/* Keep the retry message if refreshing also fails. */}
      }
      if (mounted) {
        setState(() {
          sendError = switch (error) {
            ApiException(statusCode: 409) =>
              'This conversation changed. Review the refreshed chat and retry your message.',
            ApiException(statusCode: 502) =>
              'TravelMate Assistant is temporarily unavailable. Your conversation is still here.',
            _ => 'Your message wasn’t sent. Check your connection and try again.',
          };
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          pendingMessage = null;
        });
        _showLatest();
      }
    }
  }

  Future<void> savePlan(Map<String, dynamic> plan) async {
    if (busy ||
        stalePlan(plan) ||
        savedPlans.containsKey(planKey(plan)) ||
        plan['coverageStatus'] == 'partial' ||
        (plan['adjustmentTripId'] == null && (plan['activities'] as List? ?? []).isEmpty)) return;
    setState(() {
      busy = true;
      savingPlanKey = planKey(plan);
    });
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
              title: Text(plan['adjustmentTripId'] == null ? 'Save this trip?' : 'Apply changes to this trip?'),
              content: Text(
                  '${plan['title'] ?? plan['destinationArea']}\n${plan['startDate'] ?? ''} to ${plan['endDate'] ?? ''}\nBudget: MYR ${plan['budgetLimit'] ?? '-'}\nReview the draft before saving. This does not book or pay for anything.'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(dialog, false),
                    child: const Text('Keep editing')),
                FilledButton(
                    onPressed: () => Navigator.pop(dialog, true),
                    child: const Text('Confirm save'))
              ],
            ));
    if (confirmed != true || !mounted) {
      if (mounted)
        setState(() {
          busy = false;
          savingPlanKey = null;
        });
      return;
    }
    try {
      final data = await api.post('/api/fr11/save-plan', {
        'plan': plan,
        'confirmed': true,
        if (activeSessionId != null && plan['draftId'] != null)
          'sessionId': activeSessionId
      });
      if (!mounted) return;
      final trip = data['itinerary'];
      if (data['ok'] == false ||
          trip is! Map ||
          (trip['id'] ?? data['id'] ?? '').toString().isEmpty)
        throw StateError(
            'The backend did not confirm a saved trip. Please retry.');
      setState(() =>
          savedPlans[planKey(plan)] = (trip['id'] ?? data['id']).toString());
      final title = (trip['title'] ?? 'Trip').toString();
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$title saved to Trips.')));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted)
        setState(() {
          busy = false;
          savingPlanKey = null;
        });
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
                      onPressed: busy ? null : newChat,
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
                    onPressed: busy ? null : newChat,
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
                                  enabled: !busy,
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
                                    enabled: !busy,
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

  String destinationId(Map<String, dynamic> item) => (item['destinationId'] ??
          item['place_id'] ??
          item['id'] ??
          item['title'] ??
          '')
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
    final id = destinationId(item);
    if (addingPlaceIds.isNotEmpty) return;
    addingPlaceIds.add(id);
    setState(() {});
    try {
      await addDestinationToTrip(
          context: context,
          api: api,
          destination: item,
          resumeAfterCreation: true);
    } finally {
      addingPlaceIds.remove(id);
      if (mounted) setState(() {});
    }
  }

  Widget _buildThinkingOrError() {
    return AnimatedSwitcher(
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
                  onRetry:
                      failedMessage == null ? null : () => send(failedMessage),
                )
              : const SizedBox.shrink(),
    );
  }

  Widget _buildCuratedPromptCard({
    required IconData icon,
    required String title,
    required String subtitle,
    required String tag,
    required VoidCallback? onTap,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        key: ValueKey('chat-prompt-$title'),
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadii.medium),
        child: InkCard(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(9),
                decoration: BoxDecoration(
                  color: AppColors.primarySoft,
                  borderRadius: BorderRadius.circular(AppRadii.small),
                ),
                child: Icon(icon, size: 20, color: AppColors.primaryStrong),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            title,
                            style: const TextStyle(
                              fontWeight: FontWeight.w700,
                              fontSize: 13.5,
                              color: AppColors.textPrimary,
                            ),
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: AppColors.surfaceElevated,
                            borderRadius: BorderRadius.circular(4),
                            border: Border.all(color: AppColors.divider),
                          ),
                          child: Text(
                            tag,
                            style: const TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w600,
                              color: AppColors.textSecondary,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 6),
              const Icon(
                Icons.arrow_forward_ios_rounded,
                size: 13,
                color: AppColors.disabled,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildMicroToolPill({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: InkWell(
        key: ValueKey('chat-tool-$label'),
        onTap: busy ? null : onTap,
        borderRadius: BorderRadius.circular(AppRadii.small),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(AppRadii.small),
            border: Border.all(color: AppColors.divider),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: AppColors.primary),
              const SizedBox(width: 6),
              Text(
                label,
                style: const TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: AppColors.textPrimary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget packageRecommendationsCard(List<dynamic> rawPackages) {
    final packages = rawPackages
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    if (packages.isEmpty) return const SizedBox.shrink();

    return Container(
      margin: const EdgeInsets.only(top: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: AppColors.primarySoft,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Icon(Icons.card_travel_outlined,
                    size: 14, color: AppColors.primaryStrong),
              ),
              const SizedBox(width: 6),
              const Expanded(
                child: Text(
                  'Recommended Tourism Packages',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 12.5,
                    color: AppColors.primaryStrong,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ...packages.map((pkg) {
            if (pkg['chatQuote'] is Map)
              return DatabasePackageCard(
                  package: pkg,
                  onDetails: openingPackageIds.isEmpty
                      ? () => openPackageDetails(pkg)
                      : null);
            final title =
                (pkg['title'] ?? pkg['packageTitle'] ?? 'Tourism Package')
                    .toString();
            final destination = (pkg['destination'] ??
                    pkg['destinationName'] ??
                    pkg['destinationArea'] ??
                    '')
                .toString();
            final operatorName = (pkg['operatorName'] ?? '').toString();
            final price = pkg['adultPrice'] ?? pkg['price'];
            final currency = (pkg['currency'] ?? 'MYR').toString();
            final durationDays = pkg['durationDays'];
            final durationText = durationDays != null
                ? '$durationDays ${durationDays == 1 ? 'day' : 'days'}'
                : '';

            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: InkCard(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                title,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w800,
                                  fontSize: 14,
                                ),
                              ),
                              if (destination.isNotEmpty) ...[
                                const SizedBox(height: 2),
                                Row(
                                  children: [
                                    const Icon(Icons.location_on_outlined,
                                        size: 13,
                                        color: AppColors.textSecondary),
                                    const SizedBox(width: 3),
                                    Expanded(
                                      child: Text(
                                        destination,
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: AppColors.textSecondary,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ],
                          ),
                        ),
                        if (price != null)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: AppColors.primarySoft,
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              '$currency $price',
                              style: const TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 13,
                                color: AppColors.primaryStrong,
                              ),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      children: [
                        if (durationText.isNotEmpty)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: AppColors.surfaceElevated,
                              borderRadius: BorderRadius.circular(4),
                              border: Border.all(color: AppColors.divider),
                            ),
                            child: Text(
                              durationText,
                              style: const TextStyle(
                                  fontSize: 11, color: AppColors.textSecondary),
                            ),
                          ),
                        if (operatorName.isNotEmpty)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: AppColors.surfaceElevated,
                              borderRadius: BorderRadius.circular(4),
                              border: Border.all(color: AppColors.divider),
                            ),
                            child: Text(
                              'by $operatorName',
                              style: const TextStyle(
                                  fontSize: 11, color: AppColors.textSecondary),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.tonalIcon(
                        key: ValueKey('chat-package-${packageId(pkg)}'),
                        onPressed: packageId(pkg).isEmpty ||
                                openingPackageIds.isNotEmpty
                            ? null
                            : () => openPackageDetails(pkg),
                        icon: const Icon(Icons.arrow_forward_rounded, size: 16),
                        label: Text(openingPackageIds.contains(packageId(pkg))
                            ? 'Opening package…'
                            : 'View Package Details'),
                      ),
                    ),
                  ],
                ),
              ),
            );
          }),
        ],
      ),
    );
  }

  Widget _buildAdvisoryCard(String text) {
    if (text.trim().isEmpty) return const SizedBox.shrink();
    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.warningSoft,
        borderRadius: BorderRadius.circular(AppRadii.small),
        border: Border.all(color: AppColors.warning.withValues(alpha: 0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.info_outline, size: 16, color: AppColors.warning),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontSize: 12, color: InkWashColors.ink),
            ),
          ),
        ],
      ),
    );
  }

  Widget placeSuggestionsCard(List<Map<String, dynamic>> places) {
    return Container(
      margin: const EdgeInsets.only(top: 12),
      child: Column(
        children: places.map((place) {
          final location = (place['address'] ??
                  [place['city'], place['state']].whereType<String>().toSet().join(', '))
              .toString().trim();
          final description = (place['description'] ?? '').toString().trim();
          final duration = durationText(place);
          final matched = (place['matchedInterests'] as List? ?? [])
              .whereType<String>().join(', ');
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: InkCard(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    TravelPlaceImage(
                      place: place, width: 54, height: 54,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    const SizedBox(width: 10),
                    Expanded(child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text((place['title'] ?? place['name'] ?? 'Place').toString(),
                            style: const TextStyle(fontWeight: FontWeight.w800)),
                        if (location.isNotEmpty)
                          Text(location, style: Theme.of(context).textTheme.bodySmall),
                      ],
                    )),
                  ]),
                  const SizedBox(height: 8),
                  if (matched.isNotEmpty) ...[
                    Text(matched,
                        style: const TextStyle(
                            color: AppColors.primaryStrong,
                            fontWeight: FontWeight.w600,
                            fontSize: 12.5)),
                    const SizedBox(height: 4),
                  ],
                  if (description.isNotEmpty && description != location) ...[
                    PackageTextBlock(text: description, collapsedLines: 3),
                    const SizedBox(height: 4),
                  ],
                  if (duration.isNotEmpty) ...[
                    Text('Estimated $duration',
                        style: Theme.of(context)
                            .textTheme
                            .bodySmall
                            ?.copyWith(color: AppColors.textSecondary)),
                    const SizedBox(height: 4),
                  ],
                  LocalPlaceRating(place: place),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    children: [
                      TextButton(
                        key: ValueKey('chat-place-details-${destinationId(place)}'),
                        onPressed: () => Navigator.push(
                            context, MaterialPageRoute(builder: (_) =>
                                DestinationDetailsScreen(initialDestination: place, api: api))),
                        child: const Text('Details'),
                      ),
                      TextButton(
                        key: ValueKey('chat-add-place-${destinationId(place)}'),
                        onPressed: addingPlaceIds.isNotEmpty
                            ? null : () => addPlaceToTrip(place),
                        child: const Text('Add to trip'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget planCard(Map<String, dynamic> plan) {
    final saved = savedPlans.containsKey(planKey(plan));
    final stale = stalePlan(plan);
    final activities = (plan['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final days = <int, List<Map<String, dynamic>>>{};
    final estimate = plan['budgetEstimate'] as Map?;
    final estimatedTotal = estimate?['knownEstimatedSubtotal'] ?? estimate?['total'];
    final start = DateTime.tryParse('${plan['startDate']}');
    final end = DateTime.tryParse('${plan['endDate']}');
    final dayCount =
        start != null && end != null ? end.difference(start).inDays + 1 : 0;
    if (dayCount > 0 && dayCount <= 14) {
      for (var day = 1; day <= dayCount; day++) {
        days[day] = [];
      }
    }
    for (final a in activities) {
      final day = int.tryParse('${a['dayNo']}') ?? 1;
      days.putIfAbsent(day, () => []).add(a);
    }
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(14),
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
                    style: const TextStyle(
                        fontWeight: FontWeight.w900, fontSize: 15)))
          ]),
          const SizedBox(height: 8),
          if (start != null && end != null) ...[
            Text('${MaterialLocalizations.of(context).formatMediumDate(start)} – ${MaterialLocalizations.of(context).formatMediumDate(end)}',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: AppColors.textSecondary)),
            const SizedBox(height: 4),
          ],
          Wrap(spacing: 8, runSpacing: 4, children: [
            if (plan['destinationArea'] != null) Text('${plan['destinationArea']}'),
            if (dayCount > 0) Text('$dayCount ${dayCount == 1 ? 'day' : 'days'}'),
            if ((plan['numberOfTravellers'] ?? plan['travellerCount']) case final num count)
              Text('$count ${count == 1 ? 'traveller' : 'travellers'}'),
          ]),
          if (plan['budgetLimit'] case final num budget)
            Padding(padding: const EdgeInsets.only(top: 6, bottom: 6),
                child: Text('Planning budget · MYR $budget',
                    style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        color: AppColors.primaryStrong))),
          if (estimatedTotal is num)
            Text('Estimated costs so far · MYR ${estimatedTotal.toStringAsFixed(2)}'),
          if (estimate?['overBy'] case final num excess when excess > 0)
            Text('Known estimates exceed the budget by MYR ${excess.toStringAsFixed(2)}.'),
          if (estimate?['incomplete'] == true)
            const Text('Some expenses still need prices.'),
          if ((plan['interests'] ?? plan['requestedInterests']) is List &&
              ((plan['interests'] ?? plan['requestedInterests']) as List)
                  .isNotEmpty) ...[
            Text(
                'Interests: ${((plan['interests'] ?? plan['requestedInterests']) as List).join(', ')}',
                style: const TextStyle(
                    fontSize: 12.5, color: AppColors.textSecondary)),
            const SizedBox(height: 2),
          ],
          if ((plan['travelPace'] ?? plan['pace'] ?? '').toString().isNotEmpty) ...[
            Text('Pace: ${plan['travelPace'] ?? plan['pace']}',
                style: const TextStyle(
                    fontSize: 12.5, color: AppColors.textSecondary)),
            const SizedBox(height: 2),
          ],
          if ((plan['travelPersonality'] ?? '').toString().isNotEmpty)
            Text('Travel style: ${plan['travelPersonality']}',
                style: const TextStyle(
                    fontSize: 12.5, color: AppColors.textSecondary)),
          if (stale)
            Container(
              margin: const EdgeInsets.only(top: 8),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: AppColors.warningSoft,
                borderRadius: BorderRadius.circular(AppRadii.small),
              ),
              child: const Text(
                  'Earlier draft — trip details have changed. Review the current plan before saving.',
                  style: TextStyle(fontSize: 12, color: InkWashColors.ink)),
            ),
          if (plan['coverageStatus'] == 'partial')
            Container(
              margin: const EdgeInsets.only(top: 8),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: AppColors.warningSoft,
                borderRadius: BorderRadius.circular(AppRadii.small),
              ),
              child: const Text(
                  'Incomplete preview — more verified activities are needed before saving.',
                  style: TextStyle(fontSize: 12, color: InkWashColors.ink)),
            ),
          const SizedBox(height: 10),
          ...days.entries.map((entry) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: ExpansionTile(
                  key: PageStorageKey('chat-${planKey(plan)}-day-${entry.key}'),
                  tilePadding: EdgeInsets.zero,
                  initiallyExpanded: entry.key == 1,
                  title: Text(
                      'Day ${entry.key}${start == null ? '' : ' — ${start.add(Duration(days: entry.key - 1)).toIso8601String().substring(0, 10)}'}',
                      style: const TextStyle(fontWeight: FontWeight.w900)),
                  children: [
                    if (entry.value.isEmpty)
                      const Padding(
                        padding: EdgeInsets.only(bottom: 6),
                        child: Text(
                            'No verified activities scheduled for this day.'),
                      ),
                    ...entry.value.map((a) {
                      final activity = Map<String, dynamic>.from(a as Map);
                      final duration = durationText(activity);
                      final address = (activity['address'] ?? '').toString().trim();
                      final verifiedHours = activity['openingHoursVerifiedAt'] != null &&
                              (activity['openingHoursSourceUrl'] ?? '').toString().isNotEmpty &&
                              activity['openingHours'] is String
                          ? (activity['openingHours'] as String).trim()
                          : '';
                      final cost = activity['effectiveCost'] ?? activity['estimatedCost'];
                      final priced = activity['pricingUnit'] != null &&
                          activity['pricingUnit'] != 'unknown' &&
                          activity['costProvenance'] != null &&
                          activity['costProvenance'] != 'unverified';
                      final notes = (activity['scheduleNotes'] as List? ?? [])
                          .take(1)
                          .join(' ');
                      return Container(
                        margin: const EdgeInsets.only(bottom: 12),
                        padding: const EdgeInsets.only(left: 10),
                        decoration: const BoxDecoration(
                            border: Border(left: BorderSide(color: AppColors.primary, width: 2))),
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(timeText(activity),
                                  style: Theme.of(context)
                                      .textTheme
                                      .labelMedium
                                      ?.copyWith(
                                          color: AppColors.primaryStrong)),
                              const SizedBox(height: 2),
                              Text('${activity['activityName'] ?? ''}',
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w700,
                                      fontSize: 13.5)),
                              if (address.isNotEmpty) Text(address),
                              if (verifiedHours.isNotEmpty) Text('Hours · $verifiedHours'),
                              Text(priced && cost is num
                                  ? 'Activity estimate · MYR ${cost.toStringAsFixed(2)}'
                                  : 'Activity price unverified'),
                              if (duration.isNotEmpty) ...[
                                const SizedBox(height: 2),
                                Text(duration,
                                    style: Theme.of(context)
                                        .textTheme
                                        .bodySmall
                                        ?.copyWith(
                                            color: AppColors.textSecondary)),
                              ],
                              if ((activity['description'] ?? '')
                                  .toString()
                                  .isNotEmpty) ...[
                                const SizedBox(height: 4),
                                PackageTextBlock(
                                    text: activity['description'].toString(),
                                    collapsedLines: 3),
                              ],
                              if (notes.isNotEmpty) ...[
                                const SizedBox(height: 3),
                                Text(notes,
                                    style: Theme.of(context)
                                        .textTheme
                                        .bodySmall
                                        ?.copyWith(
                                            color: AppColors.textSecondary)),
                              ],
                            ]),
                      );
                    }),
                  ],
                ),
              )),
          const SizedBox(height: 6),
          SizedBox(
              width: double.infinity,
              child: FilledButton.tonalIcon(
                  onPressed: saved
                      ? openTrips
                      : busy ||
                              stale ||
                              (plan['adjustmentTripId'] == null && activities.isEmpty) ||
                              plan['coverageStatus'] == 'partial'
                          ? null
                          : () => savePlan(plan),
                  icon: const Icon(Icons.bookmark_add_outlined),
                  label: Text(saved
                      ? 'Open saved trip in Trips'
                      : savingPlanKey == planKey(plan)
                          ? 'Save pending…'
                          : plan['adjustmentTripId'] == null
                              ? 'Save plan to Trips'
                              : 'Apply changes'))),
          if (!saved && !stale && plan['adjustmentTripId'] == null) ...[
            const SizedBox(height: 6),
            SizedBox(
              width: double.infinity,
              child: TextButton.icon(
                onPressed: busy ? null : () => send('Regenerate itinerary'),
                icon: const Icon(Icons.refresh),
                label: const Text('Regenerate'),
              ),
            ),
          ],
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
    conversationScroll.dispose();
    message.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      key: scaffoldKey,
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
              onPressed: busy ? null : newChat,
              icon: const Icon(Icons.add_comment_outlined),
              tooltip: 'New chat')
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: NotificationListener<ScrollUpdateNotification>(
              onNotification: (notification) {
                if (notification.dragDetails != null) {
                  followReply = notification.metrics.extentAfter < 80;
                }
                return false;
              },
              child: ListView(
              key: const ValueKey('assistant-conversation-scroll'),
              controller: conversationScroll,
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
              children: [
                if (loadingSessions)
                  const AppLoadingState(message: 'Loading your chats…')
                else if (screenError != null)
                  AppErrorState(
                    message: screenError!,
                    onRetry: loadSessions,
                  )
                else if (messages.isEmpty && pendingMessage == null && sendError == null) ...[
                  InkCard(
                    color: InkWashColors.cream,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Container(
                          padding: const EdgeInsets.all(AppSpacing.xs),
                          decoration: BoxDecoration(
                            color: AppColors.primarySoft,
                            borderRadius: BorderRadius.circular(AppRadii.small),
                          ),
                          child: const Icon(Icons.auto_awesome_rounded,
                              color: InkWashColors.blueGrey, size: 28),
                        ),
                        const SizedBox(height: 9),
                        const Text('How can I help with your trip?',
                            style: TextStyle(
                                fontSize: 20, fontWeight: FontWeight.w900)),
                        const SizedBox(height: 5),
                        const Text(
                            'Ask for ideas, itinerary changes, budget help or weather-friendly alternatives.',
                            style: TextStyle(
                                fontSize: 13,
                                color: AppColors.textSecondary,
                                height: 1.4)),
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
                  const Text(
                    'Curated planning prompts',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 8),
                  _buildCuratedPromptCard(
                    icon: Icons.explore_outlined,
                    title: 'Plan a 3-day cultural trip',
                    subtitle: 'Heritage sites, local street food & temples',
                    tag: 'Itinerary',
                    onTap:
                        busy ? null : () => send('Plan a 3-day cultural trip'),
                  ),
                  _buildCuratedPromptCard(
                    icon: Icons.account_balance_wallet_outlined,
                    title: 'Vacation on RM1,500 budget',
                    subtitle: 'Smart budget breakdown for your trip',
                    tag: 'Budget',
                    onTap:
                        busy ? null : () => send('Vacation on RM1,500 budget'),
                  ),
                  _buildCuratedPromptCard(
                    icon: Icons.umbrella_outlined,
                    title: 'What should I do if it rains?',
                    subtitle: 'Museums, aquariums & indoor experiences',
                    tag: 'Weather',
                    onTap: busy
                        ? null
                        : () => send('What should I do if it rains?'),
                  ),
                  _buildCuratedPromptCard(
                    icon: Icons.tune_rounded,
                    title: 'Adjust my itinerary',
                    subtitle: 'Pace changes, rest days & relaxed flow',
                    tag: 'Planning',
                    onTap: busy ? null : () => send('Adjust my itinerary'),
                  ),
                  const SizedBox(height: 14),
                  const Text(
                    'Travel tools',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 8),
                  SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      children: [
                        _buildMicroToolPill(
                          icon: Icons.flight_takeoff_rounded,
                          label: 'Flights',
                          onTap: () => Navigator.push(
                              context,
                              MaterialPageRoute(
                                  builder: (_) => FlightScreen(api: api))),
                        ),
                        _buildMicroToolPill(
                          icon: Icons.hotel_rounded,
                          label: 'Hotels',
                          onTap: () => Navigator.push(
                              context,
                              MaterialPageRoute(
                                  builder: (_) => HotelScreen(api: api))),
                        ),
                        _buildMicroToolPill(
                          icon: Icons.checklist_rounded,
                          label: 'Packing',
                          onTap: () => Navigator.push(
                              context,
                              MaterialPageRoute(
                                  builder: (_) =>
                                      PackingTripSelectorScreen(api: api))),
                        ),
                        _buildMicroToolPill(
                          icon: Icons.cloud_outlined,
                          label: 'Weather',
                          onTap: () => Navigator.push(
                              context,
                              MaterialPageRoute(
                                  builder: (_) => WeatherScreen(api: api))),
                        ),
                        _buildMicroToolPill(
                          icon: Icons.luggage_outlined,
                          label: 'Trips',
                          onTap: openTrips,
                        ),
                      ],
                    ),
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
                    final rawPackages = item['packages'] ??
                        (item['package'] != null ? [item['package']] : null);
                    final packages = rawPackages is List
                        ? rawPackages
                            .whereType<Map>()
                            .map((e) => Map<String, dynamic>.from(e))
                            .toList()
                        : <Map<String, dynamic>>[];
                    final advisory =
                        (item['weatherAdvice'] ?? item['advisory'] ?? '')
                            .toString();
                    final replies = identical(raw, messages.last) &&
                            item['suggestedReplies'] is List
                        ? (item['suggestedReplies'] as List)
                            .whereType<String>()
                            .where((text) => text.trim().isNotEmpty)
                            .take(6)
                            .toList()
                        : <String>[];

                    return [
                      Align(
                        alignment: Alignment.centerRight,
                        child: Semantics(
                          label: 'Your message',
                          child: Container(
                            margin: const EdgeInsets.only(bottom: 10, left: 48),
                            padding: const EdgeInsets.symmetric(
                                horizontal: 14, vertical: 10),
                            decoration: BoxDecoration(
                              color: InkWashColors.blueGrey,
                              borderRadius: const BorderRadius.only(
                                topLeft: Radius.circular(18),
                                topRight: Radius.circular(4),
                                bottomLeft: Radius.circular(18),
                                bottomRight: Radius.circular(18),
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color: Colors.black.withValues(alpha: 0.04),
                                  blurRadius: 4,
                                  offset: const Offset(0, 1),
                                ),
                              ],
                            ),
                            child: Text(
                              (item['message'] ?? '').toString(),
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 14,
                                height: 1.45,
                              ),
                            ),
                          ),
                        ),
                      ),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Semantics(
                          label: 'TravelMate response',
                          child: Container(
                            margin:
                                const EdgeInsets.only(bottom: 16, right: 12),
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: Colors.white,
                              borderRadius: const BorderRadius.only(
                                topLeft: Radius.circular(4),
                                topRight: Radius.circular(18),
                                bottomLeft: Radius.circular(18),
                                bottomRight: Radius.circular(18),
                              ),
                              border:
                                  Border.all(color: const Color(0xFFE3E3DE)),
                              boxShadow: [
                                BoxShadow(
                                  color: Colors.black.withValues(alpha: 0.03),
                                  blurRadius: 6,
                                  offset: const Offset(0, 2),
                                ),
                              ],
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Container(
                                      padding: const EdgeInsets.all(3),
                                      decoration: BoxDecoration(
                                        color: AppColors.primarySoft,
                                        borderRadius: BorderRadius.circular(6),
                                      ),
                                      child: const Icon(
                                        Icons.auto_awesome,
                                        size: 13,
                                        color: AppColors.primary,
                                      ),
                                    ),
                                    const SizedBox(width: 6),
                                    const Expanded(
                                      child: Text(
                                        'TravelMate Assistant',
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: TextStyle(
                                          fontSize: 11,
                                          fontWeight: FontWeight.w700,
                                          color: AppColors.primaryStrong,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                PackageTextBlock(
                                  text: (item['reply'] ?? '').toString(),
                                  collapsedLines: 8,
                                  expandLabel: 'Read full reply',
                                  style: const TextStyle(
                                    fontSize: 14,
                                    height: 1.5,
                                    color: AppColors.textPrimary,
                                  ),
                                ),
                                if (replies.isNotEmpty) ...[
                                  const SizedBox(height: 10),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 4,
                                    children: [
                                      for (final text in replies)
                                        ActionChip(
                                          label: Text(text),
                                          onPressed: busy ? null : () => send(text),
                                        ),
                                    ],
                                  ),
                                ],
                                if (placeSuggestions.isNotEmpty)
                                  placeSuggestionsCard(placeSuggestions),
                                if (plan is Map)
                                  planCard(Map<String, dynamic>.from(plan)),
                                if (packages.isNotEmpty)
                                  packageRecommendationsCard(packages),
                                if (advisory.isNotEmpty)
                                  _buildAdvisoryCard(advisory),
                                if (item['ownedTrips'] is List ||
                                    item['ownedOrders'] is List) ...[
                                  const SizedBox(height: 8),
                                  OwnedChatRecords(
                                      item: item, onTrips: openTrips),
                                ],
                                if (item['priceNotice'] != null)
                                  _buildAdvisoryCard(
                                      item['priceNotice'].toString()),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ];
                  }),
                if (pendingMessage != null)
                  Align(
                    alignment: Alignment.centerRight,
                    child: Chip(label: Text(pendingMessage!)),
                  ),
                _buildThinkingOrError(),
              ],
            ),
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
