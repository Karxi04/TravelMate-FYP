import 'package:flutter/material.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_auth/firebase_auth.dart';

import 'firebase_options.dart';
import 'theme/app_theme.dart';
import 'modules/fr01_user_management/login_screen.dart';
import 'core/onboarding/traveller_entry_gate.dart';
import 'services/api_service.dart';
import 'widgets/travel_widgets.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const TravelMateApp());
}

class TravelMateApp extends StatefulWidget {
  final Future<void> Function()? initialize;

  const TravelMateApp({super.key, this.initialize});

  @override
  State<TravelMateApp> createState() => _TravelMateAppState();
}

class _TravelMateAppState extends State<TravelMateApp> {
  late Future<void> initialization;

  @override
  void initState() {
    super.initState();
    initialization = _initialize();
  }

  Future<void> _initialize() async {
    if (!ApiService.forceStandalone) {
      ApiService.setBaseUrl(ApiService.baseUrl);
    }
    await (widget.initialize ??
        () => Firebase.initializeApp(
              options: DefaultFirebaseOptions.currentPlatform,
            ))();
  }

  void _retryInitialization() => setState(() => initialization = _initialize());

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'TravelMate',
      theme: buildInkWashTheme(),
      home: FutureBuilder<void>(
        future: initialization,
        builder: (context, startup) {
          if (startup.connectionState != ConnectionState.done) {
            return const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            );
          }
          if (startup.hasError) {
            return Scaffold(
              body: AppErrorState(
                message:
                    'TravelMate could not start. Check the app configuration and try again.',
                retryLabel: 'Retry',
                onRetry: _retryInitialization,
              ),
            );
          }
          return StreamBuilder<User?>(
            stream: FirebaseAuth.instance.authStateChanges(),
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Scaffold(
                  body: Center(child: CircularProgressIndicator()),
                );
              }
              if (snapshot.data == null) return const LoginScreen();
              return const TravellerEntryGate();
            },
          );
        },
      ),
    );
  }
}
