import 'dart:async';
import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'shared_firestore_service.dart';
import 'review_contract.dart';
import 'standalone_api_service.dart';
import 'transaction_request.dart';

const backendConnectionMessage =
    "We couldn't connect to TravelMate. Check your connection and try again.";
const backendUnavailableMessage = 'TravelMate is temporarily unavailable. Please try again.';

bool isBackendConnectionFailure(Object error) =>
    error is TimeoutException || error is http.ClientException;

String userFacingApiError(Object error) {
  if (isBackendConnectionFailure(error)) return backendConnectionMessage;
  if (error is ApiException) return error.statusCode >= 500 ? backendUnavailableMessage : error.message;
  return 'Something went wrong. Please try again.';
}

String resolveApiBaseUrl(
  String configuredUrl, {
  bool release = kReleaseMode,
  bool web = kIsWeb,
  TargetPlatform? platform,
  bool localDemo = const bool.fromEnvironment('LOCAL_DEMO'),
}) {
  final url = configuredUrl.trim().replaceFirst(RegExp(r'/+$'), '');
  final uri = Uri.tryParse(url);
  if (localDemo &&
      (uri == null ||
          uri.scheme != 'http' ||
          uri.host.isEmpty ||
          !_isPrivateLanIpv4(uri.host))) {
    throw StateError(
      'LOCAL_DEMO requires an explicit http:// private-LAN IPv4 API_BASE_URL.',
    );
  }
  if (release) {
    if (uri == null ||
        localDemo ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        _isUnsafeReleaseHost(uri.host)) {
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

bool _isPrivateLanIpv4(String host) {
  final octets = host.split('.').map(int.tryParse).toList();
  if (octets.length != 4 || octets.any((part) => part == null)) return false;
  final values = octets.cast<int>();
  if (values.any((part) => part < 0 || part > 255)) return false;
  return values[0] == 10 ||
      (values[0] == 172 && values[1] >= 16 && values[1] <= 31) ||
      (values[0] == 192 && values[1] == 168);
}

bool _isUnsafeReleaseHost(String host) {
  final normalized = host.toLowerCase();
  if ({'localhost', '127.0.0.1', '0.0.0.0', '::1', '10.0.2.2', '10.0.3.2'}
          .contains(normalized) ||
      normalized.endsWith('.local')) {
    return true;
  }
  final octets = normalized.split('.').map(int.tryParse).toList();
  if (octets.length != 4 || octets.any((part) => part == null)) return false;
  final values = octets.cast<int>();
  return values.any((part) => part < 0 || part > 255) ||
      values[0] == 10 ||
      values[0] == 127 ||
      (values[0] == 169 && values[1] == 254) ||
      (values[0] == 172 && values[1] >= 16 && values[1] <= 31) ||
      (values[0] == 192 && values[1] == 168);
}

class ApiException implements Exception {
  final String message;
  final int statusCode;
  final Map<String, dynamic> data;

  const ApiException(this.message, this.statusCode, this.data);

  String? get code => data['code']?.toString();
  String? get status => data['status']?.toString();
  Map<String, dynamic>? get tripDates => data['tripDates'] is Map
      ? Map<String, dynamic>.from(data['tripDates'] as Map)
      : null;
  List<dynamic>? get flightDates =>
      data['flightDates'] is List ? (data['flightDates'] as List) : null;
  List<dynamic>? get conflicts =>
      data['conflicts'] is List ? (data['conflicts'] as List) : null;
  int? get currentRevision => data['currentRevision'] is int
      ? data['currentRevision'] as int
      : int.tryParse(data['currentRevision']?.toString() ?? '');

  @override
  String toString() => message;
}

class ApiService {
  static String? customBaseUrl;
  static final tripChanges = ValueNotifier<int>(0);

  static dynamic decodeMutationResponse(String path, http.Response response) {
    final result = decodeResponse(response);
    if (result is Map && result['ok'] != false &&
        (path.startsWith('/api/fr5/') || path.startsWith('/api/fr15/'))) {
      tripChanges.value++;
    }
    return result;
  }

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
    if (path == '/api/fr3/local-ratings') {
      final groups = <String, List<num>>{};
      for (final review in await _shared.visibleReviews()) {
        final id = ReviewContract.destinationId('${review['destinationId'] ?? ''}');
        final rating = ReviewContract.approvedRating(review);
        if (id.isNotEmpty && rating != null) {
          groups.putIfAbsent(id, () => []).add(rating);
        }
      }
      return {'ok':true, 'items':groups.map((id, values) => MapEntry(id, {
        'rating':double.parse((values.reduce((a,b) => a+b)/values.length).toStringAsFixed(1)), 'reviews':values.length}))};
    }
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
          .map(ReviewContract.approvedRating)
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
              ? 'No TravelMate reviews yet.'
              : 'Ratings and reviews submitted by TravelMate Travellers.',
          'user_reviews': reviews
              .map((e) => {
                    ...e,
                    'username': e['username'] ?? e['travellerName'] ?? 'Traveller',
                    'description': e['description'] ?? e['comment'] ?? '',
                    'date': e['date'] ?? e['updatedAt'] ?? e['submittedAt'] ?? '',
                  })
              .toList(),
        },
      };
    }
    return null;
  }

  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (isStandalone && path.contains('/packing-checklist')) {
      throw const ApiException(
        'Smart Packing Checklist requires an active TravelMate backend connection.',
        503,
        {'error': 'Standalone mode does not support packing checklists.'},
      );
    }
    // Cross-role shared data comes directly from Firebase in standalone mode so
    // Traveller can see Operator/Admin changes without USB or a local Flask server.
    if (isStandalone &&
        (path == '/api/fr3/local-ratings' || path.startsWith('/api/public/') ||
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
      final result = decodeResponse(response);
      if (path.startsWith('/api/fr9/orders/') && path.endsWith('/reconcile') && result is Map && result['ok'] != false) {
        tripChanges.value++;
      }
      return result;
    } catch (e) {
      debugPrint('Backend GET failed ($path): $e');
      rethrow;
    }
  }

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (isStandalone && path.contains('/packing-checklist')) {
      throw const ApiException(
        'Smart Packing Checklist requires an active TravelMate backend connection.',
        503,
        {'error': 'Standalone mode does not support packing checklists.'},
      );
    }
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
      return decodeMutationResponse(path, response);
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
      return decodeMutationResponse(path, response);
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
      return decodeMutationResponse(path, response);
    } catch (e) {
      debugPrint('Backend DELETE failed ($path): $e');
      rethrow;
    }
  }

  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) async {
    final payload = body ?? <String, dynamic>{};
    if (isStandalone) {
      if (path.startsWith('/api/traveller/notifications/')) return _standalone.put(path,payload);
      if (path.contains('/packing-checklist')) {
        throw const ApiException(
          'Smart Packing Checklist requires an active TravelMate backend connection.',
          503,
          {'error': 'Standalone mode does not support packing checklists.'},
        );
      }
      throw UnimplementedError('Standalone mode does not support PATCH requests');
    }
    try {
      final uri = Uri.parse('$baseUrl$path');
      debugPrint('PATCH → $uri');
      final response = await http
          .patch(
            uri,
            headers: await _headers(),
            body: jsonEncode(payload),
          )
          .timeout(RequestTimeouts.ordinaryRead);
      return decodeMutationResponse(path, response);
    } catch (e) {
      debugPrint('Backend PATCH failed ($path): $e');
      rethrow;
    }
  }

  static dynamic decodeResponse(http.Response response) {
    dynamic data;
    try {
      data = jsonDecode(response.body.isEmpty ? '{}' : response.body);
    } catch (_) {
      throw ApiException(backendUnavailableMessage,response.statusCode >= 400 ? response.statusCode : 502,
          {'code':'invalid_server_response'});
    }
    if (response.statusCode >= 400) {
      final rawMessage = data is Map
          ? (data['error'] ?? 'Request failed (${response.statusCode})')
          : 'Request failed';
      final message = response.statusCode >= 500 || RegExp(r'<(?:!doctype|html|head|body)\b',caseSensitive:false).hasMatch('$rawMessage')
          ? backendUnavailableMessage : rawMessage.toString();
      throw ApiException(
        message,
        response.statusCode,
        data is Map
            ? {...Map<String, dynamic>.from(data),'error':message}
            : <String, dynamic>{'error': message},
      );
    }
    return data;
  }
}
