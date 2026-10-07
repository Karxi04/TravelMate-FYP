import 'package:flutter/material.dart';

import '../../modules/fr02_travel_preference/preferences_screen.dart';
import '../../services/api_service.dart';
import '../../widgets/travel_widgets.dart';
import '../navigation/app_shell.dart';

/// Ensures every newly registered / first-time Traveller completes the travel
/// preference questionnaire before entering the main application.
class TravellerEntryGate extends StatefulWidget {
  final ApiService? api;
  final Widget? home;

  const TravellerEntryGate({super.key, this.api, this.home});

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

  Future<void> _check() async {
    if (!loading) {
      setState(() {
        loading = true;
        error = null;
      });
    }
    try {
      final profileData = await api.get('/api/fr1/me');
      final profile = profileData['profile'];
      if (profile is! Map || profile.isEmpty) {
        throw const ApiException(
          'Your TravelMate profile is not ready. Please retry.',
          404,
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
        body: AppErrorState(
          message: error!,
          retryLabel: 'Retry',
          onRetry: _check,
        ),
      );
    }

    if (!completed) {
      return PreferencesScreen(
        onboarding: true,
        api: api,
        loadExisting: false,
        onCompleted: () {
          if (mounted) setState(() => completed = true);
        },
      );
    }

    return widget.home ?? const AppShell();
  }
}
