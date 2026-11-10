import 'widgets/ink_card.dart';
import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';

import 'services/firebase_startup.dart';
import 'theme/app_theme.dart';
import 'modules/fr01_user_management/login_screen.dart';
import 'modules/fr09_payment/checkout_return_screen.dart';
import 'core/onboarding/traveller_entry_gate.dart';
import 'services/api_service.dart';
import 'widgets/travel_widgets.dart';
import 'services/android_push_service.dart';
import 'modules/traveller_notifications/notification_center.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const TravelMateApp());
}

class TravelMateApp extends StatefulWidget {
  final Future<void> Function()? initialize;
  final FirebaseAuth? auth;

  const TravelMateApp({super.key, this.initialize, this.auth});

  @override
  State<TravelMateApp> createState() => _TravelMateAppState();
}

class _TravelMateAppState extends State<TravelMateApp> {
  late Future<void> initialization;
  FirebaseAuth get auth => widget.auth ?? FirebaseAuth.instance;
  final navigatorKey = GlobalKey<NavigatorState>();
  final checkoutReturnChannel = CheckoutReturnChannel();
  final handledReturnOrders = <String>{};
  CheckoutReturnLink? pendingCheckoutReturn;
  String? pendingNotification;
  final openingNotifications = <String>{};
  bool authOwnerKnown=false;
  String? navigationOwner;

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
    try {
      await AndroidPushService.instance.start((id) {
        pendingNotification=id;
        _openPushIfReady();
      });
    } catch (_) { /* Push availability must not block login or planning. */ }
  }

  Future<void> _openPushIfReady() async {
    final id=pendingNotification;
    if(id==null)return;
    final user=auth.currentUser;
    final navigator=navigatorKey.currentState;
    if(user==null || navigator==null)return;
    pendingNotification=null;
    final openingKey='${user.uid}:$id';
    if(!openingNotifications.add(openingKey))return;
    try {
      final screen=await notificationForTap(id,ApiService(),owner:user.uid,
        currentOwner:() => auth.currentUser?.uid);
      if(mounted && screen!=null && auth.currentUser?.uid==user.uid) {
        AndroidPushService.instance.inboxChanged();
        navigator.push(MaterialPageRoute(builder:(_) => screen));
      }
    } catch (_) {
      if(mounted && auth.currentUser?.uid==user.uid) {
        final context=navigatorKey.currentContext;
        if(context!=null) showError(context,'This update is unavailable. Open Notifications to review the current status.');
      }
    } finally { openingNotifications.remove(openingKey); }
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
      if (auth.currentUser == null) return;
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
      builder: (context, child) => pushTestBuild ? Banner(message:'Push Test Sandbox',location:BannerLocation.topEnd,child:child ?? const SizedBox.shrink()) : child ?? const SizedBox.shrink(),
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
            stream: auth.authStateChanges(),
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Scaffold(
                  body: Center(child: CircularProgressIndicator()),
                );
              }
              final nextOwner=snapshot.data?.uid;
              if(authOwnerKnown && navigationOwner!=nextOwner) {
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if(mounted && auth.currentUser?.uid==nextOwner) {
                    navigatorKey.currentState?.popUntil((route)=>route.isFirst);
                  }
                });
              }
              authOwnerKnown=true;
              navigationOwner=nextOwner;
              if (snapshot.data == null) return const LoginScreen();
              WidgetsBinding.instance
                  .addPostFrameCallback((_) => _openCheckoutReturnIfReady());
              WidgetsBinding.instance.addPostFrameCallback((_) => _openPushIfReady());
              return TravellerEntryGate(key: ValueKey(snapshot.data!.uid));
            },
          );
        },
      ),
    );
  }
}
