import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../services/android_push_service.dart';

class AndroidNotificationPermission extends StatefulWidget {
  final AndroidPushService? push;
  final Widget child;

  const AndroidNotificationPermission(
      {super.key, this.push, required this.child});

  @override
  State<AndroidNotificationPermission> createState() =>
      _AndroidNotificationPermissionState();
}

class _AndroidNotificationPermissionState
    extends State<AndroidNotificationPermission> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _offerPermission());
  }

  Future<void> _offerPermission() async {
    if (!mounted) return;
    final push = widget.push ?? AndroidPushService.instance;
    final owner = push.uid;
    if (owner == null) return;
    try {
      if (!await push.claimPermissionExplanation() ||
          !mounted ||
          push.uid != owner) return;
      final allow = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
          title: const Text('Allow notifications?'),
          content: const Text(
              'Get alerts for payments, booking updates and upcoming trips.'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialog, false),
              child: const Text('Not Now'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialog, true),
              child: const Text('Allow'),
            ),
          ],
        ),
      );
      if (allow == true && mounted && push.uid == owner) {
        await push.synchronize(owner, requestPermission: true);
      }
    } catch (error) {
      if (kDebugMode)
        debugPrint('Android notification setup: ${error.runtimeType}');
    }
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
