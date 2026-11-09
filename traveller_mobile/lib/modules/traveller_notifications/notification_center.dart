import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import '../../services/android_push_service.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/travel_widgets.dart';
import '../../widgets/ink_card.dart';
import '../fr09_payment/payment_history_screen.dart';
import '../fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import '../fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import '../fr05_smart_itinerary_budget_planner/packing_checklist_screen.dart';

const notificationPath = '/api/traveller/notifications';

Widget? notificationDestination(Map target, ApiService api) {
  final id = '${target['tripId'] ?? ''}';
  if (target['screen'] == 'payments') return PaymentHistoryScreen(api: api, focusOrderId:'${target['orderId'] ?? ''}');
  if (id.isEmpty || id.contains('/')) return null;
  return switch (target['screen']) {
    'package_trip' => PackageTripDetailsScreen(tripId: id, api: api),
    'trip' => TripDetailsScreen(tripId: id, api: api),
    'packing' => PackingChecklistScreen(tripId: id, api: api),
    _ => null,
  };
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
    load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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

class _NotificationCenterScreenState extends State<NotificationCenterScreen> {
  List<Map<String, dynamic>> items = [];
  bool busy = true;
  String? error;
  String notice = '';
  final pending = <String>{};
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = await widget.api.get(notificationPath);
      if (mounted)
        setState(() {
          items = (data['items'] as List? ?? [])
              .whereType<Map>()
              .map(Map<String, dynamic>.from)
              .toList();
          notice = '${data['notice'] ?? ''}';
        });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
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
      if (mounted) showError(context, e);
      return false;
    } finally {
      if (mounted) setState(() => pending.remove(id));
    }
  }

  String timestamp(dynamic raw) {
    final date = DateTime.tryParse('$raw');
    return date == null
        ? 'Time unavailable'
        : date
            .toLocal()
            .toIso8601String()
            .replaceFirst('T', ' ')
            .substring(0, 16);
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
                  const Text(
                'Inbox checked when you open or refresh TravelMate. Android push also requires permission and a configured backend.'),
                  if (AndroidPushService.instance.supported)
                    TextButton.icon(icon:const Icon(Icons.notifications_active_outlined),label:const Text('Android notification settings'),onPressed:() async {
                      final enable=await showDialog<bool>(context:context,builder:(dialogContext) => AlertDialog(
                        title:const Text('Android notifications'),content:const Text('Allow TravelMate to notify you about recorded payments, package updates and upcoming trips. You can keep using the inbox and planning if you decline. If Android already denied permission, enable it in system app settings.'),
                        actions:[TextButton(onPressed:() => Navigator.pop(dialogContext,false),child:const Text('Not now')),TextButton(onPressed:() => Navigator.pop(dialogContext,true),child:const Text('Continue'))]));
                      if(enable!=true)return;
                      try { await AndroidPushService.instance.synchronize(FirebaseAuth.instance.currentUser?.uid,requestPermission:true); }
                      catch(e) { if(context.mounted)showError(context,'Android push could not be enabled. Your inbox is still available.'); }
                    }),
                  if (notice.isNotEmpty)
                    Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: Text(notice)),
                  if (busy) const Center(child: CircularProgressIndicator()),
                  if (error != null)
                    AppErrorState(message: error!, onRetry: load),
                  if (!busy && error == null && items.isEmpty)
                    const Padding(
                        padding: EdgeInsets.all(24),
                        child: Text('No notifications yet.')),
                  for (final item in items)
                    Card(
                        child: ListTile(
                      leading: Icon(switch (item['category']) {
                        'payment' => Icons.receipt_long_outlined,
                        'arrangements_ready' => Icons.task_alt,
                        'upcoming_trip' => Icons.calendar_month_outlined,
                        'packing' => Icons.backpack_outlined,
                        'weather' => Icons.cloud_outlined,
                        _ => Icons.notifications_outlined
                      }),
                      title: Text('${item['title'] ?? 'Notification'}',
                          style: TextStyle(
                              fontWeight: item['read'] == true
                                  ? FontWeight.normal
                                  : FontWeight.bold)),
                      subtitle: Text(
                          '${item['message'] ?? ''}\n${item['sourceLabel'] == null ? '' : '${item['sourceLabel']}\n'}${timestamp(item['createdAt'])}'),
                      trailing: IconButton(
                          tooltip: item['read'] == true
                              ? 'Mark unread'
                              : 'Mark read',
                          onPressed: pending.contains('${item['id']}')
                              ? null
                              : () => mark(item, item['read'] != true),
                          icon: Icon(item['read'] == true
                              ? Icons.mark_email_read_outlined
                              : Icons.mark_email_unread_outlined)),
                      onTap: () async {
                        final screen = notificationDestination(
                            item['target'] as Map? ?? {}, widget.api);
                        if (screen == null) {
                          showError(context,
                              'This notification has no supported destination.');
                          return;
                        }
                        if (item['read'] != true && !await mark(item, true))
                          return;
                        if (context.mounted)
                          await Navigator.push(context,
                              MaterialPageRoute(builder: (_) => screen));
                      },
                    )),
                ])),
      );
}
