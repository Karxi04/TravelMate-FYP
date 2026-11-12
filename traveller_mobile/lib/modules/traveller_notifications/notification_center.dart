import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import '../../services/android_push_service.dart';
import '../../services/trip_reminders.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/travel_widgets.dart';
import '../../widgets/ink_card.dart' show showError;
import '../fr09_payment/payment_history_screen.dart';
import '../fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import '../fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import '../fr05_smart_itinerary_budget_planner/packing_checklist_screen.dart';

const notificationPath = '/api/traveller/notifications';

Widget? notificationDestination(Map target, ApiService api) {
  final id = '${target['tripId'] ?? ''}';
  if (target['screen'] == 'payments' && !validTargetId('${target['orderId'] ?? ''}')) return null;
  if (target['screen'] == 'payments') return PaymentHistoryScreen(api: api, focusOrderId:'${target['orderId'] ?? ''}');
  if (!validTargetId(id)) return null;
  return switch (target['screen']) {
    'package_trip' => PackageTripDetailsScreen(tripId: id, api: api),
    'trip' => TripDetailsScreen(tripId: id, api: api),
    'packing' => PackingChecklistScreen(tripId: id, api: api),
    _ => null,
  };
}

bool validTargetId(String id) => id.length <= 200 &&
    RegExp(r'^[A-Za-z0-9_-][A-Za-z0-9_:.-]*$').hasMatch(id);

/// Resolve the opaque push ID through authenticated backend data, never payload URLs.
Future<Widget?> notificationForTap(String id, ApiService api,
    {required String owner, required String? Function() currentOwner}) async {
  if (!AndroidPushService.validId(id) || currentOwner() != owner) return null;
  final local = await localReminderTarget(id, owner, api, currentOwner);
  if (local != null && currentOwner() == owner) return notificationDestination(local, api);
  final data=await api.get('$notificationPath/$id');
  if (currentOwner()!=owner) return null;
  final item=data['item'];
  if (data['ok']==false || item is! Map || item['id']!=id || item['travellerId']!=owner || item['target'] is! Map) {
    throw const ApiException('This update is unavailable for the current account.',404,{});
  }
  final screen=notificationDestination(item['target'] as Map,api);
  if (screen==null) throw const ApiException('This update has no supported destination.',404,{});
  if (item['read']!=true) {
    final changed=await api.patch('$notificationPath/$id',{'read':true});
    if (changed['ok']==false) throw const ApiException('The update could not be marked read. Please retry.',503,{});
  }
  return currentOwner()==owner ? screen : null;
}

class NotificationBell extends StatefulWidget {
  final ApiService api;
  final int refreshToken;
  const NotificationBell({super.key, required this.api, this.refreshToken = 0});
  @override
  State<NotificationBell> createState() => _NotificationBellState();
}

class _NotificationBellState extends State<NotificationBell>
    with WidgetsBindingObserver {
  int unread = 0;
  int version = 0;
  bool failed = false;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    AndroidPushService.instance.notificationsChanged.addListener(load);
    load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    AndroidPushService.instance.notificationsChanged.removeListener(load);
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant NotificationBell oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.refreshToken != widget.refreshToken ||
        oldWidget.api != widget.api) load();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) load();
  }

  Future<void> load() async {
    final current = ++version;
    try {
      final data = await widget.api.get(notificationPath);
      if (mounted && current == version)
        setState(() {
          unread = (data['unreadCount'] as num?)?.toInt() ?? 0;
          failed = false;
        });
    } catch (_) {
      if (mounted && current == version) setState(() => failed = true);
    }
  }

  @override
  Widget build(BuildContext context) => IconButton(
      tooltip: failed
          ? 'Notifications unavailable — open to retry'
          : 'Notifications, $unread unread',
      icon: Badge(
          isLabelVisible: unread > 0,
          label: Text('$unread'),
          child: const Icon(Icons.notifications_outlined)),
      onPressed: () async {
        await Navigator.push(
            context,
            MaterialPageRoute(
                builder: (_) => NotificationCenterScreen(api: widget.api)));
        if (mounted) await load();
      });
}

class NotificationCenterScreen extends StatefulWidget {
  final ApiService api;
  const NotificationCenterScreen({super.key, required this.api});
  @override
  State<NotificationCenterScreen> createState() =>
      _NotificationCenterScreenState();
}

class _NotificationCenterScreenState extends State<NotificationCenterScreen> with WidgetsBindingObserver {
  List<Map<String, dynamic>> items = [];
  bool busy = true;
  int loadVersion = 0;
  String? error;
  final pending = <String>{};
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    AndroidPushService.instance.notificationsChanged.addListener(load);
    load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    AndroidPushService.instance.notificationsChanged.removeListener(load);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) load();
  }

  Future<void> load() async {
    if (!mounted) return;
    final request=++loadVersion;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = await widget.api.get(notificationPath);
      if (mounted && request==loadVersion)
        setState(() {
          items = (data['items'] as List? ?? [])
              .whereType<Map>()
              .map(Map<String, dynamic>.from)
              .toList();
        });
    } catch (e) {
      if (kDebugMode) debugPrint('Notification inbox refresh: ${e.runtimeType}');
      if (mounted && request==loadVersion) {
        setState(() => error = 'Notifications are unavailable. Please try again.');
      }
    } finally {
      if (mounted && request==loadVersion) setState(() => busy = false);
    }
  }

  Future<bool> mark(Map item, bool read) async {
    final id = '${item['id']}';
    if (pending.contains(id)) return false;
    setState(() => pending.add(id));
    try {
      await widget.api.patch(
          '$notificationPath/${Uri.encodeComponent(id)}', {'read': read});
      if (mounted) setState(() => item['read'] = read);
      return true;
    } catch (e) {
      if (kDebugMode) debugPrint('Notification read state: ${e.runtimeType}');
      if (mounted) showError(context, 'Could not update this notification. Please try again.');
      return false;
    } finally {
      if (mounted) setState(() => pending.remove(id));
    }
  }

  String timestamp(BuildContext context, Map<String, dynamic> item) {
    final instant = DateTime.tryParse('${item['occurredAt']}') ??
        DateTime.tryParse('${item['createdAt']}');
    if (instant == null) return 'Time unavailable';
    final malaysia = instant.toUtc().add(const Duration(hours: 8));
    final localizations = MaterialLocalizations.of(context);
    final date = '${malaysia.day} ${localizations.formatMonthYear(malaysia)}';
    final time = localizations.formatTimeOfDay(TimeOfDay.fromDateTime(malaysia));
    return '$date · $time MYT';
  }

  Widget notificationCard(Map<String, dynamic> item) {
    final read = item['read'] == true;
    final colors = Theme.of(context).colorScheme;
    final typography = Theme.of(context).textTheme;
    final category = item['category'];
    final icon = switch (category) {
      'payment' => Icons.receipt_long_outlined,
      'arrangements_ready' => Icons.task_alt,
      'package_booking' => Icons.card_travel_outlined,
      'arrangements_update' => Icons.assignment_turned_in_outlined,
      'booking_attention' => Icons.info_outline,
      'upcoming_trip' => Icons.calendar_month_outlined,
      'packing' => Icons.backpack_outlined,
      'weather' => Icons.cloud_outlined,
      _ => Icons.notifications_outlined
    };
    final target = item['target'] as Map? ?? {};
    var source = '${item['sourceLabel'] ?? ''}';
    if (category == 'payment') {
      // Older inbox responses appended the order reference to this label.
      final reference = 'Order ${target['orderId'] ?? ''}';
      if (source == reference) {
        source = '';
      } else if (source.endsWith(' · $reference')) {
        source = source.substring(0, source.length - reference.length - 3);
      }
    }
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      color: read ? colors.surface : AppColors.primarySoft,
      child: InkWell(
        customBorder: const RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(16))),
        onTap: () async {
          final screen = notificationDestination(target, widget.api);
          if (screen == null) {
            showError(context, 'This notification has no supported destination.');
            return;
          }
          if (!read && !await mark(item, true)) return;
          if (context.mounted) {
            await Navigator.push(
                context, MaterialPageRoute(builder: (_) => screen));
          }
        },
        child: Padding(
          padding: const EdgeInsets.all(15),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Icon(icon, size: 20, color: colors.primary),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${item['title'] ?? 'Notification'}',
                        style: typography.titleSmall?.copyWith(
                            fontWeight: read ? FontWeight.w600 : FontWeight.w800)),
                    const SizedBox(height: 5),
                    Text('${item['message'] ?? ''}',
                        style: typography.bodyMedium?.copyWith(height: 1.4)),
                    if (source.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(source, style: typography.bodySmall),
                    ],
                    const SizedBox(height: 8),
                    Text(timestamp(context, item),
                        style: typography.bodySmall
                            ?.copyWith(color: colors.onSurfaceVariant)),
                  ],
                ),
              ),
              IconButton(
                tooltip: read ? 'Mark unread' : 'Mark read',
                onPressed: pending.contains('${item['id']}')
                    ? null
                    : () => mark(item, !read),
                color: colors.onSurfaceVariant,
                iconSize: 17,
                icon: Icon(read ? Icons.done_all : Icons.mark_email_unread_outlined),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Notifications')),
        body: RefreshIndicator(
            onRefresh: load,
            child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: AppSpacing.page,
                children: [
                  if (busy) const Center(child: CircularProgressIndicator()),
                  if (error != null)
                    AppErrorState(message: error!, onRetry: load),
                  if (!busy && error == null && items.isEmpty)
                    const Padding(
                        padding: EdgeInsets.all(24),
                        child: Text('No notifications yet.')),
                  for (final item in items) notificationCard(item),
                ])),
      );
}
