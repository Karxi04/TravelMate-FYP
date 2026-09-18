import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'shared_firestore_service.dart';
import 'standalone_api_service.dart';

class ApiService {
  /// Leave API_BASE_URL empty for standalone mode.
  /// Set a public HTTPS backend URL at build time to use the Flask API:
  /// flutter build apk --dart-define=API_BASE_URL=https://your-backend.example.com
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: '',
  );

  static const bool forceStandalone = bool.fromEnvironment(
    'STANDALONE_MODE',
    defaultValue: false,
  );

  final StandaloneApiService _standalone = StandaloneApiService();
  final SharedFirestoreService _shared = SharedFirestoreService();

  bool get isStandalone => forceStandalone || baseUrl.trim().isEmpty;

  Future<Map<String, String>> _headers() async {
    final token = await FirebaseAuth.instance.currentUser?.getIdToken();
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  bool _isReviewDetailsPath(String path) =>
      path.startsWith('/api/fr3/destinations/') && path.endsWith('/ratings-reviews');

  String _destinationIdFromReviewPath(String path) {
    final raw = path.substring(
      '/api/fr3/destinations/'.length,
      path.length - '/ratings-reviews'.length,
    );
    return Uri.decodeComponent(raw);
  }

  Future<dynamic> _sharedGet(String path) async {
    if (path == '/api/public/tourism-packages') {
      return {'ok': true, 'items': await _shared.approvedPackages(), 'source': 'firestore'};
    }
    if (path == '/api/public/promotional-campaigns') {
      return {'ok': true, 'items': await _shared.approvedCampaigns(), 'source': 'firestore'};
    }
    if (path == '/api/fr10/feedback') {
      return {'ok': true, 'items': await _shared.ownReviews(), 'source': 'firestore'};
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
          'rating': average == null ? null : double.parse(average.toStringAsFixed(1)),
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
    if (isStandalone && (path.startsWith('/api/public/') || path == '/api/fr10/feedback' || _isReviewDetailsPath(path))) {
      return _sharedGet(path);
    }
    if (isStandalone) return _standalone.get(path, query);
    try {
      final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
      debugPrint('GET  → $uri');
      final response = await http
          .get(uri, headers: await _headers())
          .timeout(const Duration(seconds: 25));
      return _decode(response);
    } catch (e) {
      debugPrint('Cloud GET failed: $e');
      // Shared data must remain shared even when the backend is temporarily down.
      if (path.startsWith('/api/public/') || path == '/api/fr10/feedback' || _isReviewDetailsPath(path)) {
        return _sharedGet(path);
      }
      return _standalone.get(path, query);
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
      return _standalone.post(path, {...payload, 'sharedFeedback': sharedFeedback});
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
          .timeout(const Duration(seconds: 35));
      return _decode(response);
    } catch (e) {
      debugPrint('Cloud POST failed: $e');
      if (path == '/api/fr10/feedback') {
        final result = await _shared.createReview(payload);
        return {'ok': true, 'id': result['id'], 'feedback': result};
      }
      if (path == '/api/fr4/recommendations/generate') {
        final sharedFeedback = await _shared.visibleReviews();
        return _standalone.post(path, {...payload, 'sharedFeedback': sharedFeedback});
      }
      return _standalone.post(path, body);
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
          .timeout(const Duration(seconds: 25));
      return _decode(response);
    } catch (e) {
      debugPrint('Cloud PUT failed: $e');
      if (path.startsWith('/api/fr10/feedback/')) {
        final id = path.split('/').last;
        return {'ok': true, 'feedback': await _shared.updateReview(id, payload)};
      }
      return _standalone.put(path, body);
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
          .timeout(const Duration(seconds: 25));
      return _decode(response);
    } catch (e) {
      debugPrint('Cloud DELETE failed: $e');
      if (path.startsWith('/api/fr10/feedback/')) {
        final id = path.split('/').last;
        await _shared.deleteReview(id);
        return {'ok': true};
      }
      return _standalone.delete(path);
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
      throw Exception(message);
    }
    return data;
  }
}
