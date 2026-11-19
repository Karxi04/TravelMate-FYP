import 'dart:math';
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

class RequestTimeouts {
  static const ordinaryRead = Duration(seconds: 25);
  static const ordinaryWrite = Duration(seconds: 35);
  static const longProviderRead = Duration(seconds: 70);
  static const providerMutation = Duration(seconds: 90);
  static const personalisedGeneration = Duration(seconds: 65);
  // Up to three sequential 40s Maps searches, plus bounded read/ranking/write headroom.
  static const recommendationGeneration = Duration(seconds: 150);
  // Observed discovery chat turns took 80–90s, followed by a successful saved reply.
  static const chatGeneration = Duration(seconds: 120);

  static Duration forGet(String path) {
    if (path.startsWith('/api/fr9/orders/') && path.endsWith('/reconcile')) {
      return providerMutation;
    }
    if (path == '/api/fr8/places/search' ||
        path == '/api/fr3/destinations/search' ||
        path == '/api/fr7/flights/search') {
      return longProviderRead;
    }
    return ordinaryRead;
  }

  static Duration forPost(String path) {
    if (path == '/api/fr11/chat') return chatGeneration;
    if (path == '/api/fr4/recommendations/generate') return recommendationGeneration;
    if (path.endsWith('/lower-cost-alternatives')) return providerMutation;
    if (path == '/api/fr7/flights/returns') return longProviderRead;
    if (path == '/api/fr5/personalised-trips/generate') {
      return personalisedGeneration;
    }
    if (path == '/api/fr8/hotels/search' || path == '/api/fr8/hotels/prebook') {
      return path.endsWith('/search') ? longProviderRead : providerMutation;
    }
    if (path == '/api/fr8/hotels/book' ||
        path.startsWith('/api/fr9/payments') ||
        path == '/api/fr9/checkout/session') {
      return providerMutation;
    }
    return ordinaryWrite;
  }
}

String newTransactionAttemptId(String prefix) {
  final random = Random.secure();
  final token = List.generate(
    18,
    (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();
  return '${prefix}_$token';
}

class TransactionAttemptLifecycle {
  final String prefix;
  final String Function(String prefix) _generator;
  String? _current;

  TransactionAttemptLifecycle(
    this.prefix, {
    String Function(String prefix)? generator,
  }) : _generator = generator ?? newTransactionAttemptId;

  String get currentOrCreate => _current ??= _generator(prefix);
  String? get current => _current;

  String retainForReconciliation() => currentOrCreate;

  void startNewAttempt() {
    _current = null;
  }
}

class CheckoutAttemptStore {
  String _key(String scope) =>
      'travelmate_checkout_attempt_${scope.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_')}';

  Future<String> loadOrCreate(String scope) async {
    final preferences = await SharedPreferences.getInstance();
    final key = _key(scope);
    final existing = preferences.getString(key);
    if (existing != null && existing.isNotEmpty) return existing;
    final created = newTransactionAttemptId('order');
    await preferences.setString(key, created);
    return created;
  }

  Future<void> clear(String scope) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_key(scope));
  }
}

/// Owner-scoped recovery identity; contains no authentication tokens.
class ItineraryGenerationStore {
  static String key(String owner) => 'travelmate_planning_${Uri.encodeComponent(owner)}';
  static Future<Map<String, dynamic>?> read(String owner) async {
    if (owner.isEmpty) return null;
    final raw = (await SharedPreferences.getInstance()).getString(key(owner));
    if (raw == null) return null;
    final value = jsonDecode(raw);
    return value is Map ? Map<String, dynamic>.from(value) : null;
  }
  static Future<void> save(String owner, Map<String, dynamic> payload) async {
    if (owner.isEmpty) return;
    final saved = await (await SharedPreferences.getInstance()).setString(key(owner), jsonEncode(payload));
    if (!saved) throw StateError('Could not retain trip recovery information. Please try again.');
  }
  static Future<void> clear(String owner) async {
    if (owner.isNotEmpty) await (await SharedPreferences.getInstance()).remove(key(owner));
  }
}
