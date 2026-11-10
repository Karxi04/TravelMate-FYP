import 'package:flutter/material.dart';
import '../../services/android_push_service.dart';
import '../../widgets/ink_card.dart';

class AndroidNotificationSettings extends StatefulWidget {
  final AndroidPushService? push;
  const AndroidNotificationSettings({super.key, this.push});
  @override
  State<AndroidNotificationSettings> createState() =>
      _AndroidNotificationSettingsState();
}

class _AndroidNotificationSettingsState
    extends State<AndroidNotificationSettings> with WidgetsBindingObserver {
  late final AndroidPushService push;
  bool busy = true, authorized = false, channelEnabled = false;
  String? checkError;
  bool explaining = false;
  @override
  void initState() {
    super.initState();
    push = widget.push ?? AndroidPushService.instance;
    WidgetsBinding.instance.addObserver(this);
    push.registrationChanges.addListener(changed);
    WidgetsBinding.instance.addPostFrameCallback((_) => prepare());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    push.registrationChanges.removeListener(changed);
    super.dispose();
  }

  void changed() {
    if (mounted) setState(() {});
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && !busy)
      refresh(retryRegistration: true);
  }

  Future<void> prepare() async {
    await refresh(retryRegistration: true);
    if (!mounted || !push.supported || checkError != null) return;
    try {
      if (await push.claimPermissionExplanation() && mounted) await enable();
    } catch (_) {
      if (mounted)
        setState(() => checkError =
            'Android notification status could not be checked. Your inbox is still available.');
    }
  }

  Future<void> refresh({bool retryRegistration = false}) async {
    if (!mounted) return;
    setState(() {
      busy = true;
      checkError = null;
    });
    try {
      if (push.supported) {
        final allowed = await push.platform.authorizationGranted();
        final display = allowed && await push.platform.permission();
        if (retryRegistration && display && push.uid != null) {
          try {
            await push.synchronize(push.uid);
          } catch (_) {/* Show registrationProblem below. */}
        }
        if (mounted)
          setState(() {
            authorized = allowed;
            channelEnabled = display;
          });
      }
    } catch (_) {
      if (mounted)
        checkError =
            'Android notification status could not be checked. Your inbox is still available.';
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> enable() async {
    if (busy || explaining || !push.supported || push.uid == null) return;
    explaining = true;
    try {
      final owner = push.uid;
      // Already-granted permission needs registration, never another OS prompt.
      if (await push.platform.authorizationGranted()) {
        await refresh(retryRegistration: true);
        return;
      }
      if (!mounted) return;
      final allow = await showDialog<bool>(
          context: context,
          builder: (dialog) => AlertDialog(
                  title: const Text('Allow Android alerts?'),
                  content: const Text(
                      'TravelMate can show Android alerts for recorded payments, package updates and upcoming trips while you are away from the app. Your inbox and travel planning still work if you decline.'),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(dialog, false),
                        child: const Text('Not now')),
                    FilledButton(
                        onPressed: () => Navigator.pop(dialog, true),
                        child: const Text('Allow alerts'))
                  ]));
      if (allow != true || !mounted || push.uid != owner) return;
      setState(() => busy = true);
      try {
        await push.synchronize(owner, requestPermission: true);
      } catch (_) {/* Show the verified registration failure. */}
      if (mounted) await refresh();
    } catch (_) {
      if (mounted)
        setState(() => checkError =
            'Android notification status could not be checked. Your inbox is still available.');
    } finally {
      explaining = false;
    }
  }

  String get description {
    if (!push.supported)
      return push.unavailableReason ??
          'System alerts are unavailable in this build.';
    if (checkError != null) return checkError!;
    if (push.uid == null)
      return 'Sign in to enable Android alerts for your account.';
    if (!authorized)
      return 'Android notification permission is not allowed. Enable alerts below, then choose Allow in the Android prompt. If Android no longer prompts, use Android settings.';
    if (!channelEnabled)
      return 'Android permission is allowed, but the TravelMate notification channel is disabled. Review Android settings.';
    if (push.registrationProblem != null) return push.registrationProblem!;
    if (!push.registered)
      return 'Android permission is allowed, but device registration is not confirmed. Retry registration. A configured push backend is also required.';
    return 'Android permission is allowed and this device is registered. This does not confirm FCM delivery; alerts also require an active, configured push dispatcher.';
  }

  @override
  Widget build(BuildContext context) => InkCard(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Android system notifications',
            style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        Text(description),
        if (push.supported)
          Text(push.tripReminders.problem ??
              'Trip reminders: 9:00 AM Malaysia time on the day before the saved start date. Open Trips after changes made on another device to refresh this phone.'),
        if (busy && push.supported) const LinearProgressIndicator(),
        if (push.supported && !busy && push.uid != null) ...[
          if (!authorized)
            FilledButton(
                onPressed: enable, child: const Text('Enable Android alerts')),
          if (authorized && channelEnabled && !push.registered)
            FilledButton(
                onPressed: () => refresh(retryRegistration: true),
                child: const Text('Retry device registration')),
          TextButton(
              onPressed: () async {
                try {
                  await push.openSettings();
                } catch (_) {
                  if (context.mounted)
                    showError(context, 'Android settings could not be opened.');
                }
              },
              child: const Text('Open Android settings')),
          if (checkError != null)
            TextButton(
                onPressed: () => refresh(retryRegistration: true),
                child: const Text('Retry check')),
        ],
      ]));
}
