import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'shared_firestore_service.dart';
import 'standalone_api_service.dart';
import 'transaction_request.dart';

String resolveApiBaseUrl(
  String configuredUrl, {
  bool release = kReleaseMode,
  bool web = kIsWeb,
  TargetPlatform? platform,
}) {
  final url = configuredUrl.trim().replaceFirst(RegExp(r'/+$'), '');
  if (release) {
    final uri = Uri.tryParse(url);
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        {'localhost', '127.0.0.1', '0.0.0.0', '::1', '10.0.2.2', '10.0.3.2'}
            .contains(uri.host.toLowerCase())) {
      throw StateError(
        'Cloud release requires an explicit HTTPS API_BASE_URL for a reachable '
        'backend. Build with --dart-define=API_BASE_URL=https://YOUR-BACKEND '
        'or explicitly use --dart-define=STANDALONE_MODE=true for the FYP demo.',
      );
    }
  }
  if (url.isNotEmpty) return url;
  if (!web && (platform ?? defaultTargetPlatform) == TargetPlatform.android) {
    return 'http://10.0.2.2:5000';
  }
  return 'http://127.0.0.1:5000';
}

class ApiException implements Exception {
  final String message;
  final int statusCode;
  final Map<String, dynamic> data;

  const ApiException(this.message, this.statusCode, this.data);

  @override
  String toString() => message;
}

class ApiService {
  static String? customBaseUrl;

  /// Local defaults are for debug builds; cloud releases require explicit HTTPS.
  static String get baseUrl {
    const envUrl = String.fromEnvironment('API_BASE_URL', defaultValue: '');
    final override = customBaseUrl?.trim() ?? '';
    return resolveApiBaseUrl(override.isNotEmpty ? override : envUrl);
  }

  static void setBaseUrl(String url) {
    customBaseUrl = url.trim();
  }

  static const bool forceStandalone = bool.fromEnvironment(
    'STANDALONE_MODE',
    defaultValue: false,
  );

  StandaloneApiService? _standaloneService;
  StandaloneApiService get _standalone =>
      _standaloneService ??= StandaloneApiService();
  SharedFirestoreService? _sharedService;
  SharedFirestoreService get _shared =>
      _sharedService ??= SharedFirestoreService();

  /// Standalone mode is only active when explicitly enabled at build time.
  bool get isStandalone => forceStandalone;

  Future<Map<String, String>> _headers() async {
    final token = await FirebaseAuth.instance.currentUser?.getIdToken();
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  bool _isReviewDetailsPath(String path) =>
      path.startsWith('/api/fr3/destinations/') &&
      path.endsWith('/ratings-reviews');

  String _destinationIdFromReviewPath(String path) {
    final raw = path.substring(
      '/api/fr3/destinations/'.length,
      path.length - '/ratings-reviews'.length,
    );
    return Uri.decodeComponent(raw);
  }

  Future<dynamic> _sharedGet(String path) async {
    if (path == '/api/public/tourism-packages') {
      return {
        'ok': true,
        'items': await _shared.approvedPackages(),
        'source': 'firestore'
      };
    }
    if (path == '/api/public/promotional-campaigns') {
      return {
        'ok': true,
        'items': await _shared.approvedCampaigns(),
        'source': 'firestore'
      };
    }
    if (path == '/api/fr10/feedback') {
      return {
        'ok': true,
        'items': await _shared.ownReviews(),
        'source': 'firestore'
      };
    }
    if (_isReviewDetailsPath(path)) {
      final id = _destinationIdFromReviewPath(path);
      final reviews = await _shared.destinationReviews(id);
      final ratings = reviews
          .map((e) => double.tryParse('${e['rating']}'))
          .whereType<double>()
          .toList();
      final average = ratings.isEmpty
          ? null
          : ratings.reduce((a, b) => a + b) / ratings.length;
      return {
        'ok': true,
        'source': 'travelmate_database',
        'result': {
          'rating':
              average == null ? null : double.parse(average.toStringAsFixed(1)),
          'reviews': reviews.length,
          'review_summary': reviews.isEmpty
              ? 'No Traveller reviews have been submitted for this place yet.'
              : 'Ratings and reviews submitted by TravelMate Travellers.',
          'user_reviews': reviews
              .map((e) => {
                    ...e,
                    'username': e['travellerName'] ?? 'Traveller',
                    'description': e['comment'] ?? '',
                    'date': e['updatedAt'] ?? e['submittedAt'] ?? '',
                  })
              .toList(),
        },
      };
    }
    return null;
  }

  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    // Cross-role shared data comes directly from Firebase in standalone mode so
    // Traveller can see Operator/Admin changes without USB or a local Flask server.
    if (isStandalone &&
        (path.startsWith('/api/public/') ||
            path == '/api/fr10/feedback' ||
            _isReviewDetailsPath(path))) {
      return _sharedGet(path);
    }
    if (isStandalone) return _standalone.get(path, query);
    try {
      final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
      debugPrint('GET  → $uri');
      final response = await http
          .get(uri, headers: await _headers())
          .timeout(RequestTimeouts.forGet(path));
      return _decode(response);
    } catch (e) {
      debugPrint('Backend GET failed ($path): $e');
      rethrow;
    }
  }

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    final payload = body ?? <String, dynamic>{};
    if (isStandalone && path == '/api/fr10/feedback') {
      final result = await _shared.createReview(payload);
      return {'ok': true, 'id': result['id'], 'feedback': result};
    }
    if (isStandalone && path == '/api/fr4/recommendations/generate') {
      final sharedFeedback = await _shared.visibleReviews();
      return _standalone
          .post(path, {...payload, 'sharedFeedback': sharedFeedback});
    }
    if (isStandalone) return _standalone.post(path, body);
    try {
      final uri = Uri.parse('$baseUrl$path');
      debugPrint('POST → $uri');
      final response = await http
          .post(
            uri,
            headers: await _headers(),
            body: jsonEncode(payload),
          )
          .timeout(RequestTimeouts.forPost(path));
      return _decode(response);
    } catch (e) {
      debugPrint('Backend POST failed ($path): $e');
      rethrow;
    }
  }

  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    final payload = body ?? <String, dynamic>{};
    if (isStandalone && path.startsWith('/api/fr10/feedback/')) {
      final id = path.split('/').last;
      return {'ok': true, 'feedback': await _shared.updateReview(id, payload)};
    }
    if (isStandalone) return _standalone.put(path, body);
    try {
      final response = await http
          .put(
            Uri.parse('$baseUrl$path'),
            headers: await _headers(),
            body: jsonEncode(payload),
          )
          .timeout(RequestTimeouts.ordinaryRead);
      return _decode(response);
    } catch (e) {
      debugPrint('Backend PUT failed ($path): $e');
      rethrow;
    }
  }

  Future<dynamic> delete(String path) async {
    if (isStandalone && path.startsWith('/api/fr10/feedback/')) {
      final id = path.split('/').last;
      await _shared.deleteReview(id);
      return {'ok': true};
    }
    if (isStandalone) return _standalone.delete(path);
    try {
      final response = await http
          .delete(Uri.parse('$baseUrl$path'), headers: await _headers())
          .timeout(RequestTimeouts.ordinaryRead);
      return _decode(response);
    } catch (e) {
      debugPrint('Backend DELETE failed ($path): $e');
      rethrow;
    }
  }

  dynamic _decode(http.Response response) {
    dynamic data;
    try {
      data = jsonDecode(response.body.isEmpty ? '{}' : response.body);
    } catch (_) {
      data = {'error': response.body};
    }
    if (response.statusCode >= 400) {
      final message = data is Map
          ? (data['error'] ?? 'Request failed (${response.statusCode})')
          : 'Request failed';
      throw ApiException(
        message.toString(),
        response.statusCode,
        data is Map
            ? Map<String, dynamic>.from(data)
            : <String, dynamic>{'error': message},
      );
    }
    return data;
  }
}
