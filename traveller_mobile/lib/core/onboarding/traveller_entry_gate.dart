import 'package:flutter/material.dart';

import '../../modules/fr02_travel_preference/preferences_screen.dart';
import '../../services/api_service.dart';
import '../navigation/app_shell.dart';

/// Ensures every newly registered / first-time Traveller completes the travel
/// preference questionnaire before entering the main application.
class TravellerEntryGate extends StatefulWidget {
  const TravellerEntryGate({super.key});

  @override
  State<TravellerEntryGate> createState() => _TravellerEntryGateState();
}

class _TravellerEntryGateState extends State<TravellerEntryGate> {
  final ApiService api = ApiService();
  bool loading = true;
  bool completed = false;

  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    try {
      final data = await api.get('/api/fr2/preferences');
      final prefs = data['preferences'];
      if (!mounted) return;
      setState(() {
        completed = prefs is Map && prefs.isNotEmpty;
        loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        completed = false;
        loading = false;
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

    if (!completed) {
      return PreferencesScreen(
        onboarding: true,
        onCompleted: () {
          if (mounted) setState(() => completed = true);
        },
      );
    }

    return const AppShell();
  }
}
