import 'dart:math';

class RequestTimeouts {
  static const ordinaryRead = Duration(seconds: 25);
  static const ordinaryWrite = Duration(seconds: 35);
  static const longProviderRead = Duration(seconds: 70);
  static const providerMutation = Duration(seconds: 90);
  static const personalisedGeneration = Duration(seconds: 65);

  static Duration forGet(String path) {
    if (path == '/api/fr8/places/search' ||
        path == '/api/fr3/destinations/search' ||
        path == '/api/fr7/flights/search') {
      return longProviderRead;
    }
    return ordinaryRead;
  }

  static Duration forPost(String path) {
    if (path == '/api/fr5/personalised-trips/generate') {
      return personalisedGeneration;
    }
    if (path == '/api/fr8/hotels/search' || path == '/api/fr8/hotels/prebook') {
      return path.endsWith('/search') ? longProviderRead : providerMutation;
    }
    if (path == '/api/fr8/hotels/book' ||
        path.startsWith('/api/fr9/payments')) {
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
