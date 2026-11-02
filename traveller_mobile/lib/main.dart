import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';

import 'services/firebase_startup.dart';
import 'theme/app_theme.dart';
import 'modules/fr01_user_management/login_screen.dart';
import 'modules/fr09_payment/checkout_return_screen.dart';
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
  final navigatorKey = GlobalKey<NavigatorState>();
  final checkoutReturnChannel = CheckoutReturnChannel();
  final handledReturnOrders = <String>{};
  CheckoutReturnLink? pendingCheckoutReturn;

  @override
  void initState() {
    super.initState();
    initialization = _initialize();
    checkoutReturnChannel.listen(_queueCheckoutReturn);
    Future.microtask(() async {
      try {
        final link = await checkoutReturnChannel.initialLink();
        if (link != null) _queueCheckoutReturn(link);
      } catch (_) {}
    });
  }

  @override
  void dispose() {
    checkoutReturnChannel.dispose();
    super.dispose();
  }

  Future<void> _initialize() async {
    if (!ApiService.forceStandalone) {
      ApiService.setBaseUrl(ApiService.baseUrl);
    }
    await (widget.initialize ?? initializeTravelMateFirebase)();
  }

  void _retryInitialization() => setState(() => initialization = _initialize());

  Future<void> _queueCheckoutReturn(CheckoutReturnLink link) async {
    if (handledReturnOrders.contains(link.orderId)) return;
    pendingCheckoutReturn = link;
    try {
      await initialization;
    } catch (_) {
      return;
    }
    _openCheckoutReturnIfReady();
  }

  void _openCheckoutReturnIfReady() {
    final link = pendingCheckoutReturn;
    if (link == null || handledReturnOrders.contains(link.orderId)) return;
    try {
      if (FirebaseAuth.instance.currentUser == null) return;
    } catch (_) {
      return;
    }
    final navigator = navigatorKey.currentState;
    if (navigator == null) {
      WidgetsBinding.instance
          .addPostFrameCallback((_) => _openCheckoutReturnIfReady());
      return;
    }
    pendingCheckoutReturn = null;
    handledReturnOrders.add(link.orderId);
    navigator.push(MaterialPageRoute(
      builder: (_) => CheckoutReturnScreen(link: link),
    ));
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navigatorKey,
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
                message: useFirebaseEmulator
                    ? 'Emulator startup stopped: ${startup.error}'
                    : 'TravelMate could not start. Check the app configuration and try again.',
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
              WidgetsBinding.instance
                  .addPostFrameCallback((_) => _openCheckoutReturnIfReady());
              return const TravellerEntryGate();
            },
          );
        },
      ),
    );
  }
}
