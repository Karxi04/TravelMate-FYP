import '../../widgets/ink_card.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../modules/fr02_travel_preference/preferences_screen.dart';
import '../../modules/traveller_notifications/android_notification_permission.dart';
import '../../services/api_service.dart';
import '../../services/android_push_service.dart';
import '../../widgets/travel_widgets.dart';
import '../navigation/app_shell.dart';

/// Ensures every newly registered / first-time Traveller completes the travel
/// preference questionnaire before entering the main application.
class TravellerEntryGate extends StatefulWidget {
  final ApiService? api;
  final Widget? home;
  final String? candidateName;
  final Duration pollDelay;

  const TravellerEntryGate({
    super.key,
    this.api,
    this.home,
    this.candidateName,
    this.pollDelay = const Duration(milliseconds: 400),
  });

  @override
  State<TravellerEntryGate> createState() => _TravellerEntryGateState();
}

class _TravellerEntryGateState extends State<TravellerEntryGate> {
  late final ApiService api;
  bool loading = true;
  bool completed = false;
  String? error;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    _check();
  }

  String _resolveCandidateName() {
    final explicit = widget.candidateName?.trim();
    if (explicit != null && explicit.isNotEmpty) {
      return explicit;
    }
    try {
      final user = FirebaseAuth.instance.currentUser;
      if (user != null) {
        final displayName = user.displayName?.trim();
        if (displayName != null && displayName.isNotEmpty) {
          return displayName;
        }
        final emailPrefix = user.email?.split('@').first.trim();
        if (emailPrefix != null && emailPrefix.isNotEmpty) {
          return emailPrefix;
        }
      }
    } catch (_) {}
    return 'Traveller';
  }

  Future<void> _signOut() async {
    try {
      await AndroidPushService.instance.beforeLogout();
      await FirebaseAuth.instance.signOut();
    } catch (_) {
      if (mounted) showError(context, 'Connect to TravelMate and retry signing out so Android notifications can be disabled.');
    }
  }

  Future<void> _check() async {
    if (!loading) {
      setState(() {
        loading = true;
        error = null;
      });
    }
    try {
      var profileData = await api.get('/api/fr1/me');
      var profile = profileData is Map ? profileData['profile'] : null;

      // When a new user registers, the auth listener dispatches before
      // the profile POST completes. Poll briefly to allow in-flight
      // registration or token propagation to finish cleanly.
      if (profile is! Map || profile.isEmpty) {
        for (var attempt = 0;
            attempt < 3 && (profile is! Map || profile.isEmpty);
            attempt++) {
          if (widget.pollDelay > Duration.zero) {
            await Future<void>.delayed(
              Duration(
                milliseconds: widget.pollDelay.inMilliseconds * (attempt + 1),
              ),
            );
          }
          if (!mounted) return;
          try {
            profileData = await api.get('/api/fr1/me');
            profile = profileData is Map ? profileData['profile'] : null;
          } catch (_) {
            // Transient read errors during registration polling are ignored.
          }
        }
      }

      // If the profile is still missing after polling, provision/self-heal it
      // using the authenticated Firebase user details.
      if (profile is! Map || profile.isEmpty) {
        final candidateName = _resolveCandidateName();
        final created = await api.post(
          '/api/fr1/profile',
          {'role': 'traveller', 'name': candidateName},
        );
        if (created is Map && created['profile'] is Map) {
          profile = created['profile'];
        } else {
          profileData = await api.get('/api/fr1/me');
          profile = profileData is Map ? profileData['profile'] : null;
        }
      }

      if (profile is! Map || profile.isEmpty) {
        throw const ApiException(
          'Your TravelMate profile is not ready. Please retry.',
          404,
          <String, dynamic>{},
        );
      }

      if (profile['role'] != null && profile['role'] != 'traveller') {
        throw const ApiException(
          'This account is not a Traveller account.',
          403,
          <String, dynamic>{},
        );
      }

      final data = await api.get('/api/fr2/preferences');
      final prefs = data['preferences'];
      if (!mounted) return;
      setState(() {
        completed = prefs is Map && prefs.isNotEmpty;
        loading = false;
        error = null;
      });
    } catch (failure) {
      if (!mounted) return;
      setState(() {
        loading = false;
        error = userFacingApiError(failure);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    if (error != null) {
      return Scaffold(
        body: SafeArea(
          child: Column(
            children: [
              Expanded(
                child: Center(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(24),
                    child: AppErrorState(
                      message: error!,
                      retryLabel: 'Retry',
                      onRetry: _check,
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(bottom: 24),
                child: TextButton.icon(
                  onPressed: _signOut,
                  icon: const Icon(Icons.arrow_back_rounded, size: 18),
                  label: const Text('Back to Sign In'),
                ),
              ),
            ],
          ),
        ),
      );
    }

    return AndroidNotificationPermission(
      child: completed
          ? widget.home ?? const AppShell()
          : PreferencesScreen(
              onboarding: true,
              api: api,
              loadExisting: false,
              onCompleted: () {
                if (mounted) setState(() => completed = true);
              },
            ),
    );
  }
}
