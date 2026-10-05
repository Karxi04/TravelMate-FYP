import 'dart:convert';
import 'dart:math';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../core/utils/malaysian_locality.dart';
import '../core/utils/preference_learning.dart';
import '../core/utils/recommendation_taxonomy.dart';
import '../core/utils/constraint_itinerary_planner.dart';

/// Local-first implementation of the same REST contracts used by TravelMate.
///
/// It allows the installed Traveller application to remain usable when a Flask
/// server is not configured. When a cloud backend URL is supplied, ApiService
/// uses the real Flask API instead and keeps this class as an automatic fallback.
class StandaloneApiService {
  final SharedPreferencesAsync _prefs = SharedPreferencesAsync();

  String get _uid => FirebaseAuth.instance.currentUser?.uid ?? 'guest';
  String _key(String name) => 'travelmate_${_uid}_$name';

  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr1/me') return _getProfile();
    if (path == '/api/fr2/preferences') {
      return {'ok': true, 'preferences': await _readMap('preferences')};
    }
    if (path == '/api/fr3/favourites') {
      return {'ok': true, 'items': await _readList('favourites')};
    }
    if (path == '/api/fr3/destinations/search') {
      return _searchDestinations(query ?? const {});
    }
    if (path.startsWith('/api/fr3/destinations/') &&
        path.endsWith('/ratings-reviews')) {
      final id = Uri.decodeComponent(
        path.substring('/api/fr3/destinations/'.length,
            path.length - '/ratings-reviews'.length),
      );
      return _destinationReviews(id);
    }
    if (path.startsWith('/api/fr3/destinations/') && path.endsWith('/nearby')) {
      final id = Uri.decodeComponent(
        path.substring(
          '/api/fr3/destinations/'.length,
          path.length - '/nearby'.length,
        ),
      );
      return _nearbyPlaces(id, query ?? const {});
    }
    if (path.startsWith('/api/fr3/destinations/')) {
      final id = Uri.decodeComponent(
        path.substring('/api/fr3/destinations/'.length),
      );
      return _destinationDetails(id);
    }
    if (path == '/api/fr4/recommendations') {
      final snapshots = await _readList('recommendation_snapshots');
      final generationId = (query?['generationId'] ?? '').trim();
      final destinationArea = (query?['destinationArea'] ?? '').trim();
      Map<String, dynamic>? snapshot;
      for (final candidate in snapshots) {
        final idMatches = generationId.isEmpty ||
            candidate['recommendationGenerationId'].toString() == generationId;
        final areaMatches = destinationArea.isEmpty ||
            _requestedArea(candidate['requestedDestination'].toString()) ==
                _requestedArea(destinationArea);
        if (idMatches && areaMatches) {
          snapshot = candidate;
          break;
        }
      }
      Map<String, dynamic>? safeSnapshot;
      if (snapshot != null) {
        final storedScope = snapshot['canonicalDestinationScope'];
        final scope = storedScope is Map
            ? Map<String, dynamic>.from(storedScope)
            : MalaysianLocality.normalizeScope(
                (snapshot['requestedDestination'] ?? '').toString());
        final safeResults = (snapshot['recommendationResults'] as List? ??
                const [])
            .whereType<Map>()
            .map((item) => MalaysianLocality.validateCandidate(
                Map<String, dynamic>.from(item), scope))
            .where((item) => item['geographicEligibility']?['eligible'] == true)
            .toList();
        safeSnapshot = {...snapshot, 'recommendationResults': safeResults};
      }
      return {
        'ok': true,
        'recommendationGenerationId':
            safeSnapshot?['recommendationGenerationId'] ?? '',
        'recommendation': safeSnapshot ?? <String, dynamic>{},
        'snapshot': safeSnapshot ?? <String, dynamic>{},
        'recommendations':
            safeSnapshot?['recommendationResults'] ?? <Map<String, dynamic>>[],
        'source': safeSnapshot?['source'] ?? '',
        'engine': safeSnapshot?['engine'] ?? _engineInfo,
      };
    }
    if (path == '/api/fr4/preference-feedback') {
      return {
        'ok': true,
        'learning': PreferenceLearning.publicState(
          await _readMap('learned_preference_profile'),
        ),
      };
    }
    if (path == '/api/fr5/itineraries') {
      return {'ok': true, 'items': await _readList('itineraries')};
    }
    if (path.startsWith('/api/fr5/itineraries/') && path.endsWith('/budget')) {
      final id = path.split('/')[4];
      final trip = await _tripById(id);
      return {'ok': true, 'budget': _calculateBudget(trip ?? {})};
    }
    if (path == '/api/fr6/locations/search') {
      return _searchLocation(query?['q'] ?? 'George Town');
    }
    if (path == '/api/fr6/weather') {
      return _weather(query ?? const {});
    }
    if (path == '/api/fr7/flights/search') {
      return _flightSearch(query ?? const {});
    }
    if (path == '/api/fr10/feedback') {
      return {'ok': true, 'items': await _readList('feedback')};
    }
    if (path == '/api/fr11/history') {
      return {'ok': true, 'items': await _readList('chat_history')};
    }
    if (path == '/api/fr11/sessions') {
      return _chatSessions();
    }
    if (path.startsWith('/api/fr11/sessions/')) {
      final id = path.split('/').last;
      return _chatSessionById(id);
    }
    if (path == '/api/fr9/payments') {
      return {'ok': true, 'items': await _readList('payments')};
    }
    throw Exception('This function is not available in standalone mode: $path');
  }

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    final payload = body ?? <String, dynamic>{};

    if (path == '/api/fr1/profile') return _saveProfile(payload);
    if (path == '/api/fr3/favourites') return _saveFavourite(payload);
    if (path == '/api/fr4/recommendations/generate') {
      return _generateRecommendations(payload);
    }
    if (path == '/api/fr4/preference-feedback') {
      return _submitPreferenceFeedback(payload);
    }
    if (path == '/api/fr5/personalised-trips/generate') {
      return _generatePersonalisedTrip(payload);
    }
    if (path == '/api/fr5/itineraries') return _createTrip(payload);
    if (path.startsWith('/api/fr5/itineraries/') &&
        path.endsWith('/activities/rearrange')) {
      final id = path.split('/')[4];
      return _rearrangeActivities(id, payload);
    }
    if (path.startsWith('/api/fr5/itineraries/') &&
        path.endsWith('/activities')) {
      final id = path.split('/')[4];
      return _addActivity(id, payload);
    }
    if (path.startsWith('/api/fr5/itineraries/') &&
        path.endsWith('/lower-cost-alternatives')) {
      final id = path.split('/')[4];
      return _lowerCostAlternatives(id);
    }
    if (path.startsWith('/api/fr5/itineraries/') &&
        path.endsWith('/lower-cost-alternatives/apply')) {
      final id = path.split('/')[4];
      return _applyLowerCostAlternative(id, payload);
    }
    if (path.startsWith('/api/fr5/itineraries/') &&
        path.endsWith('/generate')) {
      final id = path.split('/')[4];
      return _generateAndPlanTrip(id, payload);
    }
    if (path.startsWith('/api/fr5/itineraries/') && path.endsWith('/save')) {
      final id = path.split('/')[4];
      return _saveTrip(id);
    }
    if (path == '/api/fr7/flights/details') {
      return {
        'ok': true,
        'flight': Map<String, dynamic>.from(payload['flight'] ?? {})
      };
    }
    if (path == '/api/fr7/flights/compare') {
      final items = (payload['items'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      items.sort((a, b) {
        final av = (_num(a['price']) * .7) + (_num(a['durationMinutes']) * .3);
        final bv = (_num(b['price']) * .7) + (_num(b['durationMinutes']) * .3);
        return av.compareTo(bv);
      });
      return {'ok': true, 'items': items};
    }
    if (path == '/api/fr7/flights/select') return _selectFlight(payload);
    if (path == '/api/fr8/hotels/search') return _hotelSearch(payload);
    if (path == '/api/fr8/hotels/prebook') return _prebook(payload);
    if (path == '/api/fr8/hotels/book') return _bookHotel(payload);
    if (path == '/api/fr8/car-rentals/search') return _carRentalSearch(payload);
    if (path == '/api/fr8/car-rentals/select') return _selectCarRental(payload);
    if (path == '/api/fr8/hotels/compare') {
      final items = (payload['items'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      items.sort((a, b) {
        final av = _num(a['price']) - _num(a['rating']) * 10;
        final bv = _num(b['price']) - _num(b['rating']) * 10;
        return av.compareTo(bv);
      });
      return {'ok': true, 'items': items};
    }
    if (path == '/api/fr9/payments/process') {
      return _recordPayment(payload);
    }
    if (path.startsWith('/api/fr9/payments/') && path.endsWith('/retry')) {
      return _updatePaymentStatus(path.split('/')[4], 'successful');
    }
    if (path.startsWith('/api/fr9/payments/') && path.endsWith('/cancel')) {
      return _updatePaymentStatus(path.split('/')[4], 'cancelled');
    }
    if (path == '/api/fr10/feedback') return _createFeedback(payload);
    if (path == '/api/fr11/sessions') return _createChatSession(payload);
    if (path == '/api/fr11/save-plan') return _saveChatPlan(payload);
    if (path == '/api/fr11/chat') return _chat(payload);

    throw Exception('This function is not available in standalone mode: $path');
  }

  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    final payload = body ?? <String, dynamic>{};
    if (path == '/api/fr1/me') return _updateProfile(payload);
    if (path == '/api/fr2/preferences') return _savePreferences(payload);
    if (path.startsWith('/api/fr5/itineraries/') &&
        path.contains('/activities/')) {
      final parts = path.split('/');
      return _updateActivity(parts[4], parts.last, payload);
    }
    if (path.startsWith('/api/fr5/itineraries/') &&
        path.split('/').length == 5) {
      final id = path.split('/').last;
      return _updateTrip(id, payload);
    }
    if (path.startsWith('/api/fr10/feedback/')) {
      final id = path.split('/').last;
      final items = await _readList('feedback');
      final index = items.indexWhere((e) => e['id'].toString() == id);
      if (index >= 0) {
        items[index] = {...items[index], ...payload, 'updatedAt': _now()};
        await _writeList('feedback', items);
        return {'ok': true, 'feedback': items[index]};
      }
      throw Exception('Feedback not found.');
    }
    throw Exception('This function is not available in standalone mode: $path');
  }

  Future<dynamic> delete(String path) async {
    if (path == '/api/fr4/preference-feedback') {
      return _resetPreferenceFeedback();
    }
    if (path.startsWith('/api/fr11/sessions/')) {
      final id = path.split('/').last;
      final sessions = await _readList('chat_sessions');
      sessions.removeWhere((e) => e['id'].toString() == id);
      await _writeList('chat_sessions', sessions);
      return {'ok': true};
    }
    if (path == '/api/fr11/history') {
      await _writeList('chat_history', []);
      return {'ok': true};
    }
    if (path.startsWith('/api/fr3/favourites/')) {
      final id = Uri.decodeComponent(path.split('/').last);
      final items = await _readList('favourites');
      items.removeWhere((e) =>
          (e['id'] ?? e['destinationId'] ?? e['place_id'] ?? '').toString() ==
          id);
      await _writeList('favourites', items);
      return {'ok': true};
    }
    if (path.startsWith('/api/fr10/feedback/')) {
      final id = path.split('/').last;
      final items = await _readList('feedback');
      items.removeWhere((e) => e['id'].toString() == id);
      await _writeList('feedback', items);
      return {'ok': true};
    }
    if (path.startsWith('/api/fr5/itineraries/') &&
        path.contains('/activities/')) {
      final parts = path.split('/');
      final tripId = parts[4];
      final activityId = parts.last;
      return _removeActivity(tripId, activityId);
    }
    if (path.startsWith('/api/fr5/itineraries/')) {
      final id = path.split('/').last;
      final trips = await _readList('itineraries');
      trips.removeWhere((e) => e['id'].toString() == id);
      await _writeList('itineraries', trips);
      return {'ok': true};
    }
    throw Exception('This function is not available in standalone mode: $path');
  }

  // ------------------------------------------------------------------
  // Persistent local data
  // ------------------------------------------------------------------

  Future<Map<String, dynamic>?> _readMap(String name) async {
    final raw = await _prefs.getString(_key(name));
    if (raw == null || raw.trim().isEmpty) return null;
    final value = jsonDecode(raw);
    return value is Map ? Map<String, dynamic>.from(value) : null;
  }

  Future<void> _writeMap(String name, Map<String, dynamic> value) =>
      _prefs.setString(_key(name), jsonEncode(value));

  Future<List<Map<String, dynamic>>> _readList(String name) async {
    final raw = await _prefs.getString(_key(name));
    if (raw == null || raw.trim().isEmpty) return [];
    final value = jsonDecode(raw);
    if (value is! List) return [];
    return value
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
  }

  Future<void> _writeList(String name, List<Map<String, dynamic>> value) =>
      _prefs.setString(_key(name), jsonEncode(value));

  Future<dynamic> _getProfile() async {
    var profile = await _readMap('profile');
    final user = FirebaseAuth.instance.currentUser;
    if (profile == null && user != null) {
      profile = {
        'uid': user.uid,
        'email': user.email ?? '',
        'name': user.displayName?.trim().isNotEmpty == true
            ? user.displayName
            : (user.email?.split('@').first ?? 'Traveller'),
        'phoneNo': '',
        'preferredLanguage': 'English',
        'role': 'traveller',
        'status': 'active',
        'createdAt': _now(),
        'updatedAt': _now(),
      };
      await _writeMap('profile', profile);
    }
    return {'ok': true, 'profile': profile};
  }

  Future<dynamic> _saveProfile(Map<String, dynamic> payload) async {
    final current =
        (await _getProfile())['profile'] as Map<String, dynamic>? ?? {};
    final user = FirebaseAuth.instance.currentUser;
    final profile = <String, dynamic>{
      ...current,
      ...payload,
      'uid': user?.uid ?? _uid,
      'email': user?.email ?? current['email'] ?? '',
      'role': 'traveller',
      'status': current['status'] ?? 'active',
      'createdAt': current['createdAt'] ?? _now(),
      'updatedAt': _now(),
    };
    await _writeMap('profile', profile);
    return {'ok': true, 'profile': profile};
  }

  Future<dynamic> _updateProfile(Map<String, dynamic> payload) =>
      _saveProfile(payload);

  Future<dynamic> _savePreferences(Map<String, dynamic> payload) async {
    final version = _now();
    final profile = <String, dynamic>{
      ...payload,
      'travellerId': _uid,
      'homepageCategories': _homepageCategories(payload),
      'preferenceProfileVersion': version,
      'updatedAt': version,
    };
    await _writeMap('preferences', profile);
    return {'ok': true, 'preferences': profile};
  }

  List<String> _homepageCategories(Map<String, dynamic> p) {
    final values = <String>{};
    for (final x in (p['interests'] as List? ?? [])) {
      values.add(x.toString());
    }
    if ((p['travelType'] ?? '').toString().isNotEmpty) {
      values.add(p['travelType'].toString());
    }
    return values.take(6).toList();
  }

  // ------------------------------------------------------------------
  // Destinations and recommendations
  // ------------------------------------------------------------------

  String _requestedArea(String value) {
    return MalaysianLocality.normalizeScope(value)['scopeKey'].toString();
  }

  bool _matchesRequestedArea(Map<String, dynamic> item, String destination) {
    final scope = MalaysianLocality.normalizeScope(destination);
    final validated = MalaysianLocality.validateCandidate(item, scope);
    return validated['geographicEligibility']?['eligible'] == true;
  }

  static Map<String, dynamic> _catalogPlace({
    required String id,
    required String title,
    required String address,
    required String category,
    required String type,
    required double rating,
    required int reviews,
    required String description,
    required String hours,
    required double cost,
    required bool indoor,
    required double lat,
    required double lon,
    required List<String> interests,
    required List<String> keywords,
    String budgetLevel = 'Moderate',
    int popularity = 80,
  }) {
    final daily = <String, String>{
      'Monday': hours,
      'Tuesday': hours,
      'Wednesday': hours,
      'Thursday': hours,
      'Friday': hours,
      'Saturday': hours,
      'Sunday': hours,
    };
    return {
      'destinationId': id,
      'place_id': id,
      'title': title,
      'name': title,
      'address': address,
      'category': category,
      'type': type,
      'rating': rating,
      'reviews': reviews,
      'description': description,
      'openingHours': hours,
      'weeklyHours': daily,
      'admission': cost <= 0
          ? 'No admission fee for general access.'
          : 'Estimated visit cost RM ${cost.toStringAsFixed(0)}; individual purchases or tickets may vary.',
      'bestTime':
          indoor ? 'Late morning or afternoon' : 'Morning or late afternoon',
      'visitTips': [
        'Check the latest operating information before travelling.',
        'Allow extra time during weekends and public holidays.',
        if (!indoor)
          'Check the weather before outdoor activities.'
        else
          'Suitable for indoor planning when the weather is poor.',
      ],
      'facilities': indoor
          ? ['Restrooms', 'Nearby food options', 'Indoor visitor area']
          : ['Nearby food options', 'Public access', 'Restrooms nearby'],
      'estimatedCost': cost,
      'recommendedDurationMinutes': indoor ? 120 : 150,
      'indoor': indoor,
      'gps_coordinates': {'latitude': lat, 'longitude': lon},
      'interests': interests,
      'keywords': keywords,
      'budgetLevel': budgetLevel,
      'pace': ['Relaxed', 'Moderate', 'Packed'],
      'purpose': ['Holiday', 'Solo travel', 'Family trip', 'Educational trip'],
      'personality': ['Explorer', 'Planner', 'Social', 'Balanced', 'Relaxed'],
      'popularity': popularity,
    };
  }

  static final List<Map<String, dynamic>> _destinations = [
    {
      'destinationId': 'penang_georgetown',
      'place_id': 'penang_georgetown',
      'title': 'George Town UNESCO Heritage Area',
      'name': 'George Town UNESCO Heritage Area',
      'address': 'George Town, Penang, Malaysia',
      'category': 'Heritage',
      'type': 'Culture',
      'rating': 4.8,
      'reviews': 14820,
      'description':
          'Historic streets, clan houses, temples, murals and multicultural heritage in central George Town.',
      'openingHours': 'Open public heritage streets throughout the day',
      'weeklyHours': {
        'Monday': 'Open all day',
        'Tuesday': 'Open all day',
        'Wednesday': 'Open all day',
        'Thursday': 'Open all day',
        'Friday': 'Open all day',
        'Saturday': 'Open all day',
        'Sunday': 'Open all day'
      },
      'admission':
          'Public streets are free; individual attractions may charge admission.',
      'bestTime': 'Morning or late afternoon',
      'visitTips': [
        'Wear comfortable walking shoes',
        'Plan museum stops during hotter hours',
        'Keep some time for street food'
      ],
      'facilities': [
        'Restaurants nearby',
        'Public transport nearby',
        'Convenience stores',
        'Tourist information points'
      ],
      'website': '',
      'phone': '',
      'estimatedCost': 20.0,
      'recommendedDurationMinutes': 180,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.4141, 'longitude': 100.3288},
      'interests': [
        'Culture',
        'Heritage',
        'Photography',
        'Food',
        'History',
        'Architecture'
      ],
      'keywords': [
        'george town',
        'georgetown',
        'unesco',
        'street art',
        'murals',
        'heritage',
        'old town',
        'history',
        'culture'
      ],
      'budgetLevel': 'Budget',
      'pace': ['Relaxed', 'Moderate', 'Packed'],
      'purpose': ['Holiday', 'Solo travel', 'Family trip', 'Educational trip'],
      'personality': ['Explorer', 'Planner', 'Social', 'Balanced'],
      'popularity': 98,
    },
    {
      'destinationId': 'penang_hill',
      'place_id': 'penang_hill',
      'title': 'Penang Hill',
      'name': 'Penang Hill',
      'address': 'Bukit Bendera, Penang, Malaysia',
      'category': 'Nature',
      'type': 'Nature',
      'rating': 4.6,
      'reviews': 32100,
      'description':
          'Hilltop viewpoints, cooler weather, walking trails and panoramic views over Penang Island.',
      'openingHours': 'Daily, with attraction hours varying by facility',
      'weeklyHours': {
        'Monday': '06:30–23:00',
        'Tuesday': '06:30–23:00',
        'Wednesday': '06:30–23:00',
        'Thursday': '06:30–23:00',
        'Friday': '06:30–23:00',
        'Saturday': '06:30–23:00',
        'Sunday': '06:30–23:00'
      },
      'admission':
          'Access to the hill area is free; funicular and paid attractions have separate fares.',
      'bestTime': 'Early morning or sunset',
      'visitTips': [
        'Check weather before going',
        'Bring a light jacket',
        'Allow extra time during weekends'
      ],
      'facilities': [
        'Food outlets',
        'Restrooms',
        'Viewing decks',
        'Prayer room',
        'Shuttle/funicular access'
      ],
      'estimatedCost': 30.0,
      'recommendedDurationMinutes': 180,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.4085, 'longitude': 100.2770},
      'interests': ['Nature', 'Photography', 'Adventure', 'Scenery', 'Hiking'],
      'keywords': [
        'penang hill',
        'bukit bendera',
        'funicular',
        'viewpoint',
        'mountain',
        'hiking',
        'sunset',
        'nature'
      ],
      'budgetLevel': 'Moderate',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Family trip', 'Solo travel'],
      'personality': ['Explorer', 'Relaxed', 'Balanced'],
      'popularity': 95,
    },
    {
      'destinationId': 'peranakan_mansion',
      'place_id': 'peranakan_mansion',
      'title': 'Pinang Peranakan Mansion',
      'name': 'Pinang Peranakan Mansion',
      'address': 'Church Street, George Town, Penang',
      'category': 'Heritage',
      'type': 'Museum',
      'rating': 4.5,
      'reviews': 9200,
      'description':
          'A richly restored mansion presenting Peranakan architecture, antiques and cultural history.',
      'openingHours': 'Daily during daytime visiting hours',
      'weeklyHours': {
        'Monday': '09:30–17:00',
        'Tuesday': '09:30–17:00',
        'Wednesday': '09:30–17:00',
        'Thursday': '09:30–17:00',
        'Friday': '09:30–17:00',
        'Saturday': '09:30–17:00',
        'Sunday': '09:30–17:00'
      },
      'admission': 'Admission ticket required.',
      'bestTime': 'Late morning or early afternoon',
      'visitTips': [
        'Allow at least 1–2 hours',
        'Photography rules may vary by area',
        'Combine with nearby heritage streets'
      ],
      'facilities': ['Guided-tour information', 'Souvenir area', 'Restrooms'],
      'estimatedCost': 25.0,
      'recommendedDurationMinutes': 90,
      'indoor': true,
      'gps_coordinates': {'latitude': 5.4176, 'longitude': 100.3413},
      'interests': [
        'Culture',
        'Heritage',
        'Photography',
        'History',
        'Architecture'
      ],
      'keywords': [
        'peranakan',
        'baba nyonya',
        'mansion',
        'museum',
        'heritage',
        'architecture',
        'antiques'
      ],
      'budgetLevel': 'Moderate',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Educational trip', 'Family trip'],
      'personality': ['Planner', 'Relaxed', 'Balanced'],
      'popularity': 88,
    },
    {
      'destinationId': 'penang_food_trail',
      'place_id': 'penang_food_trail',
      'title': 'George Town Food Trail',
      'name': 'George Town Food Trail',
      'address': 'George Town, Penang',
      'category': 'Food',
      'type': 'Food',
      'rating': 4.7,
      'reviews': 12400,
      'description':
          'Explore hawker centres and local dishes such as char koay teow, laksa, cendol and nasi kandar.',
      'openingHours': 'Individual food outlets have different operating hours',
      'weeklyHours': {
        'Monday': '07:00–23:00 (varies)',
        'Tuesday': '07:00–23:00 (varies)',
        'Wednesday': '07:00–23:00 (varies)',
        'Thursday': '07:00–23:00 (varies)',
        'Friday': '07:00–23:00 (varies)',
        'Saturday': '07:00–23:00 (varies)',
        'Sunday': '07:00–23:00 (varies)'
      },
      'admission': 'No admission fee; pay for food ordered.',
      'bestTime': 'Breakfast, lunch or evening',
      'visitTips': [
        'Carry small cash amounts',
        'Try several smaller portions',
        'Check individual stall closing days'
      ],
      'facilities': [
        'Food courts',
        'Seating varies by venue',
        'Public transport nearby'
      ],
      'estimatedCost': 45.0,
      'recommendedDurationMinutes': 150,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.4164, 'longitude': 100.3327},
      'interests': ['Food', 'Culture', 'Social', 'Local experience'],
      'keywords': [
        'food',
        'hawker',
        'char koay teow',
        'laksa',
        'cendol',
        'nasi kandar',
        'street food',
        'eat'
      ],
      'budgetLevel': 'Budget',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Solo travel', 'Family trip'],
      'personality': ['Social', 'Explorer', 'Balanced'],
      'popularity': 96,
    },
    {
      'destinationId': 'kek_lok_si',
      'place_id': 'kek_lok_si',
      'title': 'Kek Lok Si Temple',
      'name': 'Kek Lok Si Temple',
      'address': 'Air Itam, Penang, Malaysia',
      'category': 'Culture',
      'type': 'Temple',
      'rating': 4.6,
      'reviews': 18000,
      'description':
          'A major Buddhist temple complex known for its architecture, hillside setting and cultural significance.',
      'openingHours': 'Daily during daytime visiting hours',
      'weeklyHours': {
        'Monday': '08:30–17:30',
        'Tuesday': '08:30–17:30',
        'Wednesday': '08:30–17:30',
        'Thursday': '08:30–17:30',
        'Friday': '08:30–17:30',
        'Saturday': '08:30–17:30',
        'Sunday': '08:30–17:30'
      },
      'admission':
          'Main temple access is generally free; selected areas/services may charge.',
      'bestTime': 'Morning',
      'visitTips': [
        'Dress respectfully',
        'Expect stairs and slopes',
        'Combine with Air Itam food stops'
      ],
      'facilities': ['Restrooms', 'Food nearby', 'Parking nearby', 'Shops'],
      'estimatedCost': 15.0,
      'recommendedDurationMinutes': 120,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.3992, 'longitude': 100.2735},
      'interests': [
        'Culture',
        'Heritage',
        'Photography',
        'Religion',
        'Architecture'
      ],
      'keywords': [
        'kek lok si',
        'temple',
        'buddhist',
        'air itam',
        'culture',
        'heritage',
        'architecture'
      ],
      'budgetLevel': 'Budget',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Family trip', 'Educational trip'],
      'personality': ['Explorer', 'Planner', 'Balanced'],
      'popularity': 93,
    },
    {
      'destinationId': 'entopia',
      'place_id': 'entopia',
      'title': 'Entopia by Penang Butterfly Farm',
      'name': 'Entopia by Penang Butterfly Farm',
      'address': 'Teluk Bahang, Penang, Malaysia',
      'category': 'Nature',
      'type': 'Attraction',
      'rating': 4.5,
      'reviews': 7800,
      'description':
          'A family-friendly nature attraction featuring butterflies, insects and immersive indoor exhibits.',
      'openingHours': 'Daily during daytime visiting hours',
      'weeklyHours': {
        'Monday': '09:00–17:00',
        'Tuesday': '09:00–17:00',
        'Wednesday': '09:00–17:00',
        'Thursday': '09:00–17:00',
        'Friday': '09:00–17:00',
        'Saturday': '09:00–17:00',
        'Sunday': '09:00–17:00'
      },
      'admission': 'Admission ticket required.',
      'bestTime': 'Morning or early afternoon',
      'visitTips': [
        'Allow 2–3 hours',
        'Good option for rainy weather',
        'Suitable for families'
      ],
      'facilities': ['Indoor exhibits', 'Cafe', 'Restrooms', 'Gift shop'],
      'estimatedCost': 75.0,
      'recommendedDurationMinutes': 150,
      'indoor': true,
      'gps_coordinates': {'latitude': 5.4498, 'longitude': 100.2151},
      'interests': ['Nature', 'Photography', 'Family', 'Wildlife', 'Education'],
      'keywords': [
        'entopia',
        'butterfly',
        'insect',
        'nature',
        'family',
        'teluk bahang',
        'indoor'
      ],
      'budgetLevel': 'Premium',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Family trip', 'Holiday', 'Educational trip'],
      'personality': ['Relaxed', 'Planner', 'Balanced'],
      'popularity': 84,
    },
    {
      'destinationId': 'batu_ferringhi',
      'place_id': 'batu_ferringhi',
      'title': 'Batu Ferringhi Beach',
      'name': 'Batu Ferringhi Beach',
      'address': 'Batu Ferringhi, Penang, Malaysia',
      'category': 'Leisure',
      'type': 'Beach',
      'rating': 4.3,
      'reviews': 11000,
      'description':
          'Beach area popular for sunset views, seaside activities and evening markets.',
      'openingHours': 'Public beach accessible daily',
      'weeklyHours': {
        'Monday': 'Open all day',
        'Tuesday': 'Open all day',
        'Wednesday': 'Open all day',
        'Thursday': 'Open all day',
        'Friday': 'Open all day',
        'Saturday': 'Open all day',
        'Sunday': 'Open all day'
      },
      'admission': 'Public beach access is free.',
      'bestTime': 'Late afternoon and sunset',
      'visitTips': [
        'Check sea and weather conditions',
        'Bring sun protection',
        'Night market activity varies by day'
      ],
      'facilities': [
        'Food nearby',
        'Water activities',
        'Hotels nearby',
        'Public transport'
      ],
      'estimatedCost': 20.0,
      'recommendedDurationMinutes': 180,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.4720, 'longitude': 100.2450},
      'interests': ['Nature', 'Leisure', 'Adventure', 'Photography', 'Beach'],
      'keywords': [
        'batu ferringhi',
        'beach',
        'sea',
        'sunset',
        'night market',
        'water sport',
        'leisure'
      ],
      'budgetLevel': 'Budget',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Family trip', 'Solo travel'],
      'personality': ['Relaxed', 'Social', 'Explorer'],
      'popularity': 90,
    },
    {
      'destinationId': 'gurney_plaza',
      'place_id': 'gurney_plaza',
      'title': 'Gurney Plaza',
      'name': 'Gurney Plaza',
      'address': 'Gurney Drive, Penang, Malaysia',
      'category': 'Shopping',
      'type': 'Shopping',
      'rating': 4.4,
      'reviews': 15000,
      'description':
          'Major shopping centre with retail, dining, entertainment and indoor facilities.',
      'openingHours': 'Daily shopping-centre hours',
      'weeklyHours': {
        'Monday': '10:00–22:00',
        'Tuesday': '10:00–22:00',
        'Wednesday': '10:00–22:00',
        'Thursday': '10:00–22:00',
        'Friday': '10:00–22:00',
        'Saturday': '10:00–22:00',
        'Sunday': '10:00–22:00'
      },
      'admission': 'Free entry.',
      'bestTime': 'Afternoon or evening',
      'visitTips': [
        'Useful during rainy weather',
        'Combine with Gurney food area',
        'Allow extra time on weekends'
      ],
      'facilities': [
        'Restaurants',
        'Cinema',
        'Restrooms',
        'Parking',
        'Prayer room',
        'ATMs'
      ],
      'estimatedCost': 40.0,
      'recommendedDurationMinutes': 150,
      'indoor': true,
      'gps_coordinates': {'latitude': 5.4380, 'longitude': 100.3100},
      'interests': ['Shopping', 'Food', 'Leisure', 'Family'],
      'keywords': [
        'gurney plaza',
        'shopping',
        'mall',
        'food',
        'cinema',
        'indoor'
      ],
      'budgetLevel': 'Moderate',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Family trip'],
      'personality': ['Social', 'Relaxed', 'Balanced'],
      'popularity': 87,
    },
    {
      'destinationId': 'blue_mansion',
      'place_id': 'blue_mansion',
      'title': 'Cheong Fatt Tze – The Blue Mansion',
      'name': 'Cheong Fatt Tze – The Blue Mansion',
      'address': 'Leith Street, George Town, Penang',
      'category': 'Heritage',
      'type': 'Museum',
      'rating': 4.5,
      'reviews': 6400,
      'description':
          'A distinctive indigo heritage mansion known for architecture, history and guided visits.',
      'openingHours': 'Guided visits and access depend on daily schedule',
      'weeklyHours': {
        'Monday': '11:00–18:00',
        'Tuesday': '11:00–18:00',
        'Wednesday': '11:00–18:00',
        'Thursday': '11:00–18:00',
        'Friday': '11:00–18:00',
        'Saturday': '11:00–18:00',
        'Sunday': '11:00–18:00'
      },
      'admission': 'Ticketed heritage visit.',
      'bestTime': 'Late morning',
      'visitTips': [
        'Check guided-visit times',
        'Reserve time for photography',
        'Combine with nearby George Town streets'
      ],
      'facilities': ['Cafe/restaurant nearby', 'Restrooms', 'Guided visits'],
      'estimatedCost': 30.0,
      'recommendedDurationMinutes': 90,
      'indoor': true,
      'gps_coordinates': {'latitude': 5.4212, 'longitude': 100.3345},
      'interests': [
        'Culture',
        'Heritage',
        'Photography',
        'Architecture',
        'History'
      ],
      'keywords': [
        'blue mansion',
        'cheong fatt tze',
        'heritage',
        'architecture',
        'museum',
        'history'
      ],
      'budgetLevel': 'Moderate',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Educational trip', 'Solo travel'],
      'personality': ['Planner', 'Explorer', 'Balanced'],
      'popularity': 89,
    },
    {
      'destinationId': 'clan_jetties',
      'place_id': 'clan_jetties',
      'title': 'Clan Jetties of Penang',
      'name': 'Clan Jetties of Penang',
      'address': 'Weld Quay, George Town, Penang',
      'category': 'Heritage',
      'type': 'Culture',
      'rating': 4.2,
      'reviews': 9000,
      'description':
          'Historic waterfront settlements on wooden jetties reflecting the heritage of Chinese clan communities.',
      'openingHours': 'Residential area; visit respectfully during daytime',
      'weeklyHours': {
        'Monday': '09:00–21:00',
        'Tuesday': '09:00–21:00',
        'Wednesday': '09:00–21:00',
        'Thursday': '09:00–21:00',
        'Friday': '09:00–21:00',
        'Saturday': '09:00–21:00',
        'Sunday': '09:00–21:00'
      },
      'admission': 'Free entry; some stalls or activities charge separately.',
      'bestTime': 'Morning or late afternoon',
      'visitTips': [
        'Respect residents privacy',
        'Avoid blocking narrow walkways',
        'Good for photography near sunset'
      ],
      'facilities': ['Small shops', 'Food nearby', 'Public transport nearby'],
      'estimatedCost': 10.0,
      'recommendedDurationMinutes': 75,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.4111, 'longitude': 100.3410},
      'interests': ['Culture', 'Heritage', 'Photography', 'Local experience'],
      'keywords': [
        'clan jetties',
        'chew jetty',
        'weld quay',
        'waterfront',
        'heritage',
        'culture'
      ],
      'budgetLevel': 'Budget',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Solo travel', 'Educational trip'],
      'personality': ['Explorer', 'Relaxed', 'Balanced'],
      'popularity': 86,
    },
    {
      'destinationId': 'penang_national_park',
      'place_id': 'penang_national_park',
      'title': 'Penang National Park',
      'name': 'Penang National Park',
      'address': 'Teluk Bahang, Penang, Malaysia',
      'category': 'Nature',
      'type': 'Adventure',
      'rating': 4.5,
      'reviews': 5300,
      'description':
          'Coastal rainforest trails, beaches and nature experiences suited to active travellers.',
      'openingHours': 'Daily daytime access; trail conditions can affect entry',
      'weeklyHours': {
        'Monday': '08:00–17:00',
        'Tuesday': '08:00–17:00',
        'Wednesday': '08:00–17:00',
        'Thursday': '08:00–17:00',
        'Friday': '08:00–17:00',
        'Saturday': '08:00–17:00',
        'Sunday': '08:00–17:00'
      },
      'admission': 'Entry conditions and registration requirements may apply.',
      'bestTime': 'Early morning',
      'visitTips': [
        'Bring water',
        'Wear proper footwear',
        'Avoid long hikes during heavy rain',
        'Check trail status'
      ],
      'facilities': [
        'Registration point',
        'Restrooms near entrance',
        'Boat services nearby'
      ],
      'estimatedCost': 25.0,
      'recommendedDurationMinutes': 240,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.4593, 'longitude': 100.2060},
      'interests': ['Nature', 'Adventure', 'Hiking', 'Photography', 'Wildlife'],
      'keywords': [
        'national park',
        'hiking',
        'trail',
        'monkey beach',
        'nature',
        'forest',
        'adventure'
      ],
      'budgetLevel': 'Budget',
      'pace': ['Moderate', 'Packed'],
      'purpose': ['Holiday', 'Solo travel'],
      'personality': ['Explorer', 'Planner'],
      'popularity': 82,
    },
    {
      'destinationId': 'tropical_spice_garden',
      'place_id': 'tropical_spice_garden',
      'title': 'Tropical Spice Garden',
      'name': 'Tropical Spice Garden',
      'address': 'Teluk Bahang, Penang, Malaysia',
      'category': 'Nature',
      'type': 'Garden',
      'rating': 4.4,
      'reviews': 4100,
      'description':
          'Landscaped tropical garden featuring spices, native plants and guided nature experiences.',
      'openingHours': 'Daily daytime visiting hours',
      'weeklyHours': {
        'Monday': '09:00–16:30',
        'Tuesday': '09:00–16:30',
        'Wednesday': '09:00–16:30',
        'Thursday': '09:00–16:30',
        'Friday': '09:00–16:30',
        'Saturday': '09:00–16:30',
        'Sunday': '09:00–16:30'
      },
      'admission': 'Admission ticket required.',
      'bestTime': 'Morning',
      'visitTips': [
        'Bring insect repellent',
        'Wear walking shoes',
        'Allow time for guided interpretation'
      ],
      'facilities': ['Cafe', 'Shop', 'Restrooms', 'Guided tours'],
      'estimatedCost': 35.0,
      'recommendedDurationMinutes': 120,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.4632, 'longitude': 100.2291},
      'interests': ['Nature', 'Photography', 'Food', 'Education', 'Wellness'],
      'keywords': [
        'spice garden',
        'garden',
        'plants',
        'nature',
        'herbs',
        'tropical',
        'teluk bahang'
      ],
      'budgetLevel': 'Moderate',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Family trip', 'Educational trip'],
      'personality': ['Relaxed', 'Planner', 'Balanced'],
      'popularity': 80,
    },
    {
      'destinationId': 'escape_penang',
      'place_id': 'escape_penang',
      'title': 'ESCAPE Penang',
      'name': 'ESCAPE Penang',
      'address': 'Teluk Bahang, Penang, Malaysia',
      'category': 'Adventure',
      'type': 'Theme Park',
      'rating': 4.6,
      'reviews': 10500,
      'description':
          'Outdoor adventure and water attractions designed for active recreation and family fun.',
      'openingHours': 'Selected operating days and daytime hours',
      'weeklyHours': {
        'Monday': '10:00–18:00',
        'Tuesday': '10:00–18:00',
        'Wednesday': '10:00–18:00',
        'Thursday': '10:00–18:00',
        'Friday': '10:00–18:00',
        'Saturday': '10:00–18:00',
        'Sunday': '10:00–18:00'
      },
      'admission': 'Paid admission required.',
      'bestTime': 'Morning for a full-day visit',
      'visitTips': [
        'Plan most of the day',
        'Bring suitable activity clothing',
        'Check weather and attraction requirements'
      ],
      'facilities': ['Changing areas', 'Food outlets', 'Restrooms', 'Lockers'],
      'estimatedCost': 160.0,
      'recommendedDurationMinutes': 360,
      'indoor': false,
      'gps_coordinates': {'latitude': 5.4518, 'longitude': 100.2144},
      'interests': ['Adventure', 'Family', 'Nature', 'Water activities'],
      'keywords': [
        'escape',
        'theme park',
        'adventure',
        'water park',
        'family',
        'teluk bahang',
        'outdoor'
      ],
      'budgetLevel': 'Premium',
      'pace': ['Packed', 'Moderate'],
      'purpose': ['Family trip', 'Holiday'],
      'personality': ['Explorer', 'Social'],
      'popularity': 91,
    },
    {
      'destinationId': 'wonderfood_museum',
      'place_id': 'wonderfood_museum',
      'title': 'Wonderfood Museum Penang',
      'name': 'Wonderfood Museum Penang',
      'address': 'Beach Street, George Town, Penang',
      'category': 'Food',
      'type': 'Museum',
      'rating': 4.3,
      'reviews': 5100,
      'description':
          'Indoor museum showcasing oversized Malaysian food replicas and cultural food stories.',
      'openingHours': 'Daily daytime visiting hours',
      'weeklyHours': {
        'Monday': '09:00–18:00',
        'Tuesday': '09:00–18:00',
        'Wednesday': '09:00–18:00',
        'Thursday': '09:00–18:00',
        'Friday': '09:00–18:00',
        'Saturday': '09:00–18:00',
        'Sunday': '09:00–18:00'
      },
      'admission': 'Admission ticket required.',
      'bestTime': 'Midday or rainy periods',
      'visitTips': [
        'Good indoor option',
        'Combine with nearby heritage attractions',
        'Allow time for photos'
      ],
      'facilities': ['Air conditioning', 'Restrooms', 'Souvenir area'],
      'estimatedCost': 20.0,
      'recommendedDurationMinutes': 75,
      'indoor': true,
      'gps_coordinates': {'latitude': 5.4150, 'longitude': 100.3410},
      'interests': ['Food', 'Culture', 'Photography', 'Family'],
      'keywords': [
        'wonderfood',
        'food museum',
        'museum',
        'indoor',
        'malaysian food',
        'photo'
      ],
      'budgetLevel': 'Budget',
      'pace': ['Relaxed', 'Moderate'],
      'purpose': ['Holiday', 'Family trip'],
      'personality': ['Social', 'Relaxed', 'Balanced'],
      'popularity': 79,
    },
    {
      'destinationId': 'klcc',
      'place_id': 'klcc',
      'title': 'Petronas Twin Towers & KLCC',
      'name': 'Petronas Twin Towers & KLCC',
      'address': 'Kuala Lumpur City Centre, Malaysia',
      'category': 'City',
      'type': 'Landmark',
      'rating': 4.7,
      'reviews': 82000,
      'description':
          'Iconic Kuala Lumpur landmark surrounded by shopping, dining, parks and city attractions.',
      'openingHours':
          'KLCC precinct accessible daily; individual attractions have separate schedules',
      'weeklyHours': {
        'Monday': '10:00–22:00 (precinct varies)',
        'Tuesday': '10:00–22:00 (precinct varies)',
        'Wednesday': '10:00–22:00 (precinct varies)',
        'Thursday': '10:00–22:00 (precinct varies)',
        'Friday': '10:00–22:00 (precinct varies)',
        'Saturday': '10:00–22:00 (precinct varies)',
        'Sunday': '10:00–22:00 (precinct varies)'
      },
      'admission':
          'KLCC park and mall access are free; observation attractions are ticketed.',
      'bestTime': 'Late afternoon to evening',
      'visitTips': [
        'Book observation tickets early if required',
        'Allow time for park and mall',
        'Good evening photography location'
      ],
      'facilities': [
        'Mall',
        'Restaurants',
        'Park',
        'Transit access',
        'Restrooms'
      ],
      'estimatedCost': 80.0,
      'recommendedDurationMinutes': 180,
      'indoor': false,
      'gps_coordinates': {'latitude': 3.1579, 'longitude': 101.7116},
      'interests': [
        'Photography',
        'Shopping',
        'Culture',
        'City',
        'Architecture'
      ],
      'keywords': [
        'klcc',
        'petronas',
        'twin towers',
        'kuala lumpur',
        'landmark',
        'city',
        'shopping'
      ],
      'budgetLevel': 'Premium',
      'pace': ['Relaxed', 'Moderate', 'Packed'],
      'purpose': ['Holiday', 'Family trip', 'Solo travel', 'Business trip'],
      'personality': ['Social', 'Explorer', 'Planner', 'Balanced'],
      'popularity': 99,
    },
    {
      'destinationId': 'langkawi_skybridge',
      'place_id': 'langkawi_skybridge',
      'title': 'Langkawi Sky Bridge',
      'name': 'Langkawi Sky Bridge',
      'address': 'Langkawi, Kedah, Malaysia',
      'category': 'Adventure',
      'type': 'Nature',
      'rating': 4.6,
      'reviews': 22000,
      'description':
          'Mountain-top curved pedestrian bridge with scenic island and forest views.',
      'openingHours': 'Daily, subject to weather and attraction operations',
      'weeklyHours': {
        'Monday': '09:30–18:00',
        'Tuesday': '09:30–18:00',
        'Wednesday': '09:30–18:00',
        'Thursday': '09:30–18:00',
        'Friday': '09:30–18:00',
        'Saturday': '09:30–18:00',
        'Sunday': '09:30–18:00'
      },
      'admission': 'Cable-car/attraction tickets required for access.',
      'bestTime': 'Morning with clear weather',
      'visitTips': [
        'Check weather before travelling up',
        'Allow time for cable-car queues',
        'Wear comfortable shoes'
      ],
      'facilities': ['Cable car', 'Food outlets', 'Restrooms', 'Viewing areas'],
      'estimatedCost': 55.0,
      'recommendedDurationMinutes': 150,
      'indoor': false,
      'gps_coordinates': {'latitude': 6.3864, 'longitude': 99.6621},
      'interests': ['Adventure', 'Nature', 'Photography', 'Scenery'],
      'keywords': [
        'langkawi',
        'sky bridge',
        'cable car',
        'nature',
        'mountain',
        'viewpoint',
        'adventure'
      ],
      'budgetLevel': 'Moderate',
      'pace': ['Moderate', 'Packed'],
      'purpose': ['Holiday', 'Family trip', 'Solo travel'],
      'personality': ['Explorer', 'Social', 'Balanced'],
      'popularity': 94,
    },
    _catalogPlace(
      id: 'penang_clan_jetties',
      title: 'Clan Jetties of Penang',
      address: 'Weld Quay, George Town, Penang, Malaysia',
      category: 'Heritage',
      type: 'Waterfront',
      rating: 4.3,
      reviews: 9800,
      description:
          'Historic waterfront settlements with wooden walkways, clan houses and coastal views.',
      hours: '09:00–21:00',
      cost: 0,
      indoor: false,
      lat: 5.4133,
      lon: 100.3404,
      interests: ['Heritage', 'Culture', 'Photography', 'Local experience'],
      keywords: [
        'clan jetties',
        'chew jetty',
        'weld quay',
        'waterfront',
        'heritage',
        'george town'
      ],
      popularity: 90,
    ),
    _catalogPlace(
      id: 'penang_fort_cornwallis',
      title: 'Fort Cornwallis',
      address: 'Padang Kota Lama, George Town, Penang, Malaysia',
      category: 'Heritage',
      type: 'Historic Site',
      rating: 4.2,
      reviews: 6400,
      description:
          'Historic fort and colonial-era landmark near the Esplanade in George Town.',
      hours: '09:00–22:00',
      cost: 20,
      indoor: false,
      lat: 5.4206,
      lon: 100.3438,
      interests: ['History', 'Heritage', 'Architecture', 'Photography'],
      keywords: [
        'fort cornwallis',
        'fort',
        'colonial',
        'history',
        'esplanade',
        'padang kota'
      ],
      popularity: 84,
    ),
    _catalogPlace(
      id: 'penang_cheong_fatt_tze',
      title: 'Cheong Fatt Tze – The Blue Mansion',
      address: 'Leith Street, George Town, Penang, Malaysia',
      category: 'Heritage',
      type: 'Historic House',
      rating: 4.4,
      reviews: 6200,
      description:
          'Distinctive indigo mansion known for architecture, guided heritage visits and photography.',
      hours: '11:00–18:00',
      cost: 25,
      indoor: true,
      lat: 5.4213,
      lon: 100.3346,
      interests: ['Heritage', 'Architecture', 'Culture', 'Photography'],
      keywords: [
        'blue mansion',
        'cheong fatt tze',
        'mansion',
        'architecture',
        'heritage',
        'leith street'
      ],
      popularity: 88,
    ),
    _catalogPlace(
      id: 'penang_khoo_kongsi',
      title: 'Leong San Tong Khoo Kongsi',
      address: 'Cannon Square, George Town, Penang, Malaysia',
      category: 'Culture',
      type: 'Clan House',
      rating: 4.5,
      reviews: 5200,
      description:
          'Ornate Chinese clan house with detailed carvings, courtyards and cultural history.',
      hours: '09:00–17:00',
      cost: 15,
      indoor: true,
      lat: 5.4146,
      lon: 100.3361,
      interests: ['Culture', 'Heritage', 'Architecture', 'History'],
      keywords: [
        'khoo kongsi',
        'clan house',
        'cannon square',
        'chinese heritage',
        'architecture'
      ],
      popularity: 86,
    ),
    _catalogPlace(
      id: 'penang_botanic_gardens',
      title: 'Penang Botanic Gardens',
      address: 'Jalan Kebun Bunga, George Town, Penang, Malaysia',
      category: 'Nature',
      type: 'Garden',
      rating: 4.5,
      reviews: 12000,
      description:
          'Green urban garden with shaded walking paths, tropical plants and nearby hiking routes.',
      hours: '06:30–19:00',
      cost: 0,
      indoor: false,
      lat: 5.4374,
      lon: 100.2907,
      interests: ['Nature', 'Walking', 'Photography', 'Wellness'],
      keywords: [
        'botanic gardens',
        'botanical garden',
        'kebun bunga',
        'park',
        'walking',
        'nature'
      ],
      popularity: 91,
    ),
    _catalogPlace(
      id: 'penang_hin_bus_depot',
      title: 'Hin Bus Depot',
      address: 'Brick Kiln Road, George Town, Penang, Malaysia',
      category: 'Culture',
      type: 'Creative Space',
      rating: 4.5,
      reviews: 4700,
      description:
          'Creative community space with art, pop-ups, cafes and weekend market activity.',
      hours: '12:00–20:00',
      cost: 0,
      indoor: true,
      lat: 5.4088,
      lon: 100.3284,
      interests: ['Art', 'Culture', 'Food', 'Photography', 'Shopping'],
      keywords: [
        'hin bus depot',
        'art',
        'creative space',
        'market',
        'cafe',
        'weekend market'
      ],
      popularity: 83,
    ),
    _catalogPlace(
      id: 'penang_gurney_drive',
      title: 'Gurney Drive Hawker & Seafront',
      address: 'Gurney Drive, George Town, Penang, Malaysia',
      category: 'Food',
      type: 'Hawker Area',
      rating: 4.3,
      reviews: 19000,
      description:
          'Popular seafront area for Penang hawker food, snacks and evening dining.',
      hours: '17:00–23:30',
      cost: 35,
      indoor: false,
      lat: 5.4379,
      lon: 100.3109,
      interests: ['Food', 'Local experience', 'Social', 'Nightlife'],
      keywords: [
        'gurney drive',
        'hawker',
        'food',
        'street food',
        'lok lok',
        'rojak',
        'pasembur',
        'char koay teow'
      ],
      budgetLevel: 'Budget',
      popularity: 94,
    ),
    _catalogPlace(
      id: 'penang_new_lane_hawker',
      title: 'New Lane Hawker Centre',
      address: 'Lorong Baru, George Town, Penang, Malaysia',
      category: 'Food',
      type: 'Hawker Centre',
      rating: 4.4,
      reviews: 7600,
      description:
          'Evening hawker street with a wide mix of Penang dishes and casual local dining.',
      hours: '16:00–23:30',
      cost: 30,
      indoor: false,
      lat: 5.4130,
      lon: 100.3270,
      interests: ['Food', 'Local experience', 'Social'],
      keywords: [
        'new lane',
        'lorong baru',
        'hawker',
        'food',
        'char koay teow',
        'hokkien mee',
        'curry mee',
        'satay'
      ],
      budgetLevel: 'Budget',
      popularity: 89,
    ),
    _catalogPlace(
      id: 'penang_air_itam_curry_mee',
      title: 'Air Itam Curry Mee Area',
      address: 'Air Itam Market, Air Itam, Penang, Malaysia',
      category: 'Food',
      type: 'Local Food',
      rating: 4.5,
      reviews: 5100,
      description:
          'Air Itam food area known for Penang-style curry mee and other local breakfast dishes.',
      hours: '07:00–13:30',
      cost: 12,
      indoor: false,
      lat: 5.4004,
      lon: 100.2785,
      interests: ['Food', 'Local experience', 'Culture'],
      keywords: [
        'curry mee',
        'white curry mee',
        'curry noodles',
        'air itam curry mee',
        'penang curry mee',
        'breakfast',
        'noodles'
      ],
      budgetLevel: 'Budget',
      popularity: 91,
    ),
    _catalogPlace(
      id: 'penang_georgetown_curry_mee',
      title: 'George Town White Curry Mee Spots',
      address: 'George Town, Penang, Malaysia',
      category: 'Food',
      type: 'Local Food',
      rating: 4.4,
      reviews: 3800,
      description:
          'A group of central George Town eateries where travellers commonly look for Penang white curry mee.',
      hours: '08:00–20:00',
      cost: 15,
      indoor: true,
      lat: 5.4167,
      lon: 100.3320,
      interests: ['Food', 'Local experience'],
      keywords: [
        'curry mee',
        'white curry mee',
        'curry noodle',
        'penang curry noodles',
        'george town food',
        'spicy noodles'
      ],
      budgetLevel: 'Budget',
      popularity: 87,
    ),
    _catalogPlace(
      id: 'penang_air_itam_laksa',
      title: 'Air Itam Asam Laksa Area',
      address: 'Pasar Air Itam, Penang, Malaysia',
      category: 'Food',
      type: 'Local Food',
      rating: 4.4,
      reviews: 8700,
      description:
          'Busy local food area associated with Penang asam laksa and Air Itam market culture.',
      hours: '10:30–19:00',
      cost: 12,
      indoor: false,
      lat: 5.4010,
      lon: 100.2782,
      interests: ['Food', 'Culture', 'Local experience'],
      keywords: [
        'asam laksa',
        'laksa',
        'air itam laksa',
        'penang laksa',
        'noodles',
        'food'
      ],
      budgetLevel: 'Budget',
      popularity: 93,
    ),
    _catalogPlace(
      id: 'penang_chendul',
      title: 'Penang Road Chendul Area',
      address: 'Lebuh Keng Kwee, George Town, Penang, Malaysia',
      category: 'Food',
      type: 'Dessert',
      rating: 4.5,
      reviews: 15000,
      description:
          'Popular George Town lane for chendul, ais kacang and quick local dessert stops.',
      hours: '10:30–19:00',
      cost: 10,
      indoor: false,
      lat: 5.4167,
      lon: 100.3296,
      interests: ['Food', 'Local experience', 'Family'],
      keywords: [
        'chendul',
        'cendol',
        'dessert',
        'penang road',
        'ais kacang',
        'sweet'
      ],
      budgetLevel: 'Budget',
      popularity: 95,
    ),
    _catalogPlace(
      id: 'penang_armenian_street',
      title: 'Armenian Street & Street Art',
      address: 'Lebuh Armenian, George Town, Penang, Malaysia',
      category: 'Culture',
      type: 'Street Art',
      rating: 4.6,
      reviews: 21000,
      description:
          'Walkable heritage street known for murals, cafes, crafts and nearby clan-house attractions.',
      hours: 'Open all day',
      cost: 0,
      indoor: false,
      lat: 5.4147,
      lon: 100.3365,
      interests: ['Photography', 'Art', 'Heritage', 'Culture', 'Food'],
      keywords: [
        'armenian street',
        'street art',
        'murals',
        'art',
        'george town',
        'heritage'
      ],
      popularity: 96,
    ),
    _catalogPlace(
      id: 'kl_batu_caves',
      title: 'Batu Caves',
      address: 'Gombak, Selangor, Greater Kuala Lumpur, Malaysia',
      category: 'Culture',
      type: 'Temple',
      rating: 4.6,
      reviews: 70000,
      description:
          'Limestone cave complex and Hindu temple reached by a colourful staircase north of central Kuala Lumpur.',
      hours: '06:00–21:00',
      cost: 0,
      indoor: false,
      lat: 3.2379,
      lon: 101.6840,
      interests: ['Culture', 'Religion', 'Photography', 'Adventure', 'History'],
      keywords: [
        'batu caves',
        'cave',
        'temple',
        'hindu',
        'stairs',
        'kuala lumpur attraction'
      ],
      popularity: 98,
    ),
    _catalogPlace(
      id: 'kl_tower',
      title: 'Kuala Lumpur Tower',
      address: 'Jalan Puncak, Kuala Lumpur, Malaysia',
      category: 'City',
      type: 'Observation Tower',
      rating: 4.5,
      reviews: 28000,
      description:
          'Telecommunications tower with city observation experiences and skyline views.',
      hours: '09:00–22:00',
      cost: 60,
      indoor: true,
      lat: 3.1528,
      lon: 101.7038,
      interests: ['Photography', 'City', 'Architecture', 'Family'],
      keywords: [
        'kl tower',
        'menara kuala lumpur',
        'tower',
        'viewpoint',
        'skyline',
        'city view'
      ],
      budgetLevel: 'Premium',
      popularity: 94,
    ),
    _catalogPlace(
      id: 'kl_aquaria',
      title: 'Aquaria KLCC',
      address: 'Kuala Lumpur Convention Centre, Kuala Lumpur, Malaysia',
      category: 'Family',
      type: 'Aquarium',
      rating: 4.4,
      reviews: 23000,
      description:
          'Large indoor aquarium in the KLCC precinct with marine exhibits and a walk-through tunnel.',
      hours: '10:00–20:00',
      cost: 75,
      indoor: true,
      lat: 3.1533,
      lon: 101.7135,
      interests: ['Family', 'Wildlife', 'Education', 'Indoor'],
      keywords: [
        'aquaria klcc',
        'aquarium',
        'fish',
        'marine',
        'family',
        'indoor',
        'klcc'
      ],
      budgetLevel: 'Premium',
      popularity: 92,
    ),
    _catalogPlace(
      id: 'kl_central_market',
      title: 'Central Market Kuala Lumpur',
      address: 'Jalan Hang Kasturi, Kuala Lumpur, Malaysia',
      category: 'Shopping',
      type: 'Market',
      rating: 4.3,
      reviews: 30000,
      description:
          'Heritage market building with Malaysian crafts, souvenirs, food and cultural products.',
      hours: '10:00–22:00',
      cost: 0,
      indoor: true,
      lat: 3.1457,
      lon: 101.6953,
      interests: ['Shopping', 'Culture', 'Food', 'Heritage'],
      keywords: [
        'central market',
        'pasar seni',
        'souvenir',
        'craft',
        'shopping',
        'culture'
      ],
      budgetLevel: 'Budget',
      popularity: 93,
    ),
    _catalogPlace(
      id: 'kl_petaling_street',
      title: 'Petaling Street Chinatown',
      address: 'Petaling Street, Kuala Lumpur, Malaysia',
      category: 'Food',
      type: 'Market Street',
      rating: 4.2,
      reviews: 35000,
      description:
          'Busy Chinatown district with street food, markets, heritage shophouses and nearby temples.',
      hours: '08:00–23:00',
      cost: 25,
      indoor: false,
      lat: 3.1448,
      lon: 101.6976,
      interests: ['Food', 'Shopping', 'Culture', 'Heritage', 'Photography'],
      keywords: [
        'petaling street',
        'chinatown',
        'market',
        'street food',
        'shopping',
        'kuala lumpur food'
      ],
      budgetLevel: 'Budget',
      popularity: 95,
    ),
    _catalogPlace(
      id: 'kl_jalan_alor',
      title: 'Jalan Alor Food Street',
      address: 'Bukit Bintang, Kuala Lumpur, Malaysia',
      category: 'Food',
      type: 'Food Street',
      rating: 4.4,
      reviews: 24000,
      description:
          'Evening food street in Bukit Bintang with Malaysian and Asian dishes, seafood and casual dining.',
      hours: '17:00–02:00',
      cost: 40,
      indoor: false,
      lat: 3.1459,
      lon: 101.7080,
      interests: ['Food', 'Nightlife', 'Social', 'Local experience'],
      keywords: [
        'jalan alor',
        'food street',
        'bukit bintang',
        'street food',
        'dinner',
        'seafood'
      ],
      budgetLevel: 'Budget',
      popularity: 97,
    ),
    _catalogPlace(
      id: 'kl_islamic_arts_museum',
      title: 'Islamic Arts Museum Malaysia',
      address: 'Jalan Lembah Perdana, Kuala Lumpur, Malaysia',
      category: 'Culture',
      type: 'Museum',
      rating: 4.7,
      reviews: 9000,
      description:
          'Museum with Islamic decorative arts, architecture galleries, manuscripts and regional collections.',
      hours: '09:30–18:00',
      cost: 20,
      indoor: true,
      lat: 3.1415,
      lon: 101.6893,
      interests: ['Culture', 'History', 'Art', 'Architecture', 'Education'],
      keywords: [
        'islamic arts museum',
        'museum',
        'art',
        'history',
        'architecture',
        'culture'
      ],
      popularity: 90,
    ),
    _catalogPlace(
      id: 'kl_national_mosque',
      title: 'National Mosque of Malaysia',
      address: 'Jalan Perdana, Kuala Lumpur, Malaysia',
      category: 'Culture',
      type: 'Religious Site',
      rating: 4.6,
      reviews: 8300,
      description:
          'National mosque known for modern Malaysian Islamic architecture and landscaped grounds.',
      hours: '09:00–17:00',
      cost: 0,
      indoor: true,
      lat: 3.1419,
      lon: 101.6918,
      interests: ['Culture', 'Architecture', 'Religion', 'Photography'],
      keywords: [
        'national mosque',
        'masjid negara',
        'mosque',
        'architecture',
        'culture'
      ],
      budgetLevel: 'Budget',
      popularity: 88,
    ),
    _catalogPlace(
      id: 'kl_perdana_gardens',
      title: 'Perdana Botanical Gardens',
      address: 'Jalan Kebun Bunga, Kuala Lumpur, Malaysia',
      category: 'Nature',
      type: 'Park',
      rating: 4.5,
      reviews: 11000,
      description:
          'Large landscaped urban park with walking paths, gardens and green spaces near central museums.',
      hours: '07:00–20:00',
      cost: 0,
      indoor: false,
      lat: 3.1432,
      lon: 101.6852,
      interests: ['Nature', 'Walking', 'Family', 'Photography', 'Wellness'],
      keywords: [
        'perdana botanical gardens',
        'lake gardens',
        'park',
        'garden',
        'walking',
        'nature'
      ],
      budgetLevel: 'Budget',
      popularity: 89,
    ),
    _catalogPlace(
      id: 'kl_thean_hou',
      title: 'Thean Hou Temple',
      address: 'Robson Heights, Kuala Lumpur, Malaysia',
      category: 'Culture',
      type: 'Temple',
      rating: 4.6,
      reviews: 15000,
      description:
          'Hilltop Chinese temple with ornate architecture, city views and colourful ceremonial spaces.',
      hours: '08:00–22:00',
      cost: 0,
      indoor: false,
      lat: 3.1217,
      lon: 101.6872,
      interests: ['Culture', 'Architecture', 'Photography', 'Religion'],
      keywords: [
        'thean hou temple',
        'chinese temple',
        'temple',
        'architecture',
        'photography'
      ],
      budgetLevel: 'Budget',
      popularity: 91,
    ),
    _catalogPlace(
      id: 'kl_bukit_bintang',
      title: 'Bukit Bintang District',
      address: 'Bukit Bintang, Kuala Lumpur, Malaysia',
      category: 'Shopping',
      type: 'City District',
      rating: 4.5,
      reviews: 40000,
      description:
          'Central entertainment and shopping district with malls, dining, nightlife and easy transit connections.',
      hours: '10:00–00:00',
      cost: 0,
      indoor: false,
      lat: 3.1466,
      lon: 101.7115,
      interests: ['Shopping', 'Food', 'Nightlife', 'Social', 'City'],
      keywords: [
        'bukit bintang',
        'shopping',
        'nightlife',
        'mall',
        'city',
        'food',
        'pavilion'
      ],
      popularity: 97,
    ),
    _catalogPlace(
      id: 'kl_pavilion',
      title: 'Pavilion Kuala Lumpur',
      address: 'Bukit Bintang, Kuala Lumpur, Malaysia',
      category: 'Shopping',
      type: 'Shopping Mall',
      rating: 4.6,
      reviews: 50000,
      description:
          'Major Bukit Bintang shopping centre with fashion, dining, entertainment and indoor comfort.',
      hours: '10:00–22:00',
      cost: 0,
      indoor: true,
      lat: 3.1491,
      lon: 101.7135,
      interests: ['Shopping', 'Food', 'Luxury', 'Family'],
      keywords: [
        'pavilion kl',
        'pavilion kuala lumpur',
        'shopping mall',
        'bukit bintang',
        'fashion',
        'food'
      ],
      budgetLevel: 'Premium',
      popularity: 96,
    ),
    _catalogPlace(
      id: 'kl_saloma_link',
      title: 'Saloma Link',
      address: 'Kampung Baru, Kuala Lumpur, Malaysia',
      category: 'City',
      type: 'Pedestrian Bridge',
      rating: 4.5,
      reviews: 17000,
      description:
          'Illuminated pedestrian bridge connecting Kampung Baru with the KLCC area, popular for evening photos.',
      hours: '05:00–01:00',
      cost: 0,
      indoor: false,
      lat: 3.1592,
      lon: 101.7068,
      interests: ['Photography', 'City', 'Architecture', 'Walking'],
      keywords: [
        'saloma link',
        'bridge',
        'kampung baru',
        'klcc',
        'night photography',
        'city'
      ],
      budgetLevel: 'Budget',
      popularity: 90,
    ),
    _catalogPlace(
      id: 'kl_muzium_negara',
      title: 'National Museum of Malaysia',
      address: 'Jalan Damansara, Kuala Lumpur, Malaysia',
      category: 'History',
      type: 'Museum',
      rating: 4.4,
      reviews: 10000,
      description:
          'National museum presenting Malaysian history, culture, archaeology and traditional heritage.',
      hours: '09:00–17:00',
      cost: 5,
      indoor: true,
      lat: 3.1379,
      lon: 101.6872,
      interests: ['History', 'Culture', 'Education', 'Family'],
      keywords: [
        'national museum',
        'muzium negara',
        'museum',
        'history',
        'malaysia culture'
      ],
      budgetLevel: 'Budget',
      popularity: 88,
    ),
    _catalogPlace(
      id: 'kl_masjid_jamek_river',
      title: 'River of Life & Masjid Jamek Area',
      address: 'Jalan Tun Perak, Kuala Lumpur, Malaysia',
      category: 'Heritage',
      type: 'City Walk',
      rating: 4.3,
      reviews: 11000,
      description:
          'Historic central river-confluence area combining city heritage, mosque architecture and evening lighting.',
      hours: 'Open all day',
      cost: 0,
      indoor: false,
      lat: 3.1487,
      lon: 101.6958,
      interests: [
        'Heritage',
        'Photography',
        'Architecture',
        'Walking',
        'History'
      ],
      keywords: [
        'river of life',
        'masjid jamek',
        'heritage',
        'river',
        'city walk',
        'photography'
      ],
      budgetLevel: 'Budget',
      popularity: 89,
    ),
    _catalogPlace(
      id: 'kl_lot10_hutong',
      title: 'Lot 10 Hutong Food Court',
      address: 'Bukit Bintang, Kuala Lumpur, Malaysia',
      category: 'Food',
      type: 'Food Court',
      rating: 4.3,
      reviews: 12000,
      description:
          'Indoor food hall bringing together well-known Malaysian hawker-style dishes in central Bukit Bintang.',
      hours: '10:00–22:00',
      cost: 35,
      indoor: true,
      lat: 3.1460,
      lon: 101.7111,
      interests: ['Food', 'Local experience', 'Family', 'Shopping'],
      keywords: [
        'lot 10 hutong',
        'food court',
        'hawker',
        'bukit bintang',
        'malaysian food',
        'noodles'
      ],
      budgetLevel: 'Moderate',
      popularity: 90,
    ),
  ];

  Map<String, dynamic> get _engineInfo => {
        'contentBasedFiltering': true,
        'collaborativeFiltering': true,
        'weightedScoring': {
          'content': .60,
          'collaborative': .30,
          'popularity': .10
        },
        'contentTaxonomy': true,
        'collaborativeColdStart': 'neutral_confidence_aware',
        'deduplication': true,
        'diversityReranking': true,
        'ranking': true,
      };

  Future<dynamic> _searchDestinations(Map<String, String> query) async {
    final rawQuery = (query['q'] ?? '').trim();
    final q = _normaliseSearch(rawQuery);
    var rawLocation = (query['location'] ?? '').trim();
    final inferredLocation = _inferLocationFromQuery(q);
    if (inferredLocation.isNotEmpty &&
        (rawLocation.isEmpty ||
            _normaliseSearch(rawLocation).contains('malaysia'))) {
      rawLocation = inferredLocation;
    }
    final location = _normaliseSearch(rawLocation);
    final filter = _normaliseSearch((query['filter'] ?? '').trim());

    const noise = <String>{
      'attraction',
      'attractions',
      'place',
      'places',
      'thing',
      'things',
      'to',
      'do',
      'in',
      'near',
      'around',
      'best',
      'top',
      'show',
      'me',
      'find',
      'recommend',
      'suggestion',
      'suggestions',
      'trip',
      'travel',
    };
    final genericTerms = <String>{
      '',
      'attractions',
      'attraction',
      'places',
      'place',
      'things to do',
      'explore'
    };
    final queryTerms =
        _expandedSearchTerms(q).where((e) => !noise.contains(e)).toSet();
    final locationTerms = _tokenise(location);
    final dishIntent = _foodDishIntent(q);

    final scored = <Map<String, dynamic>>[];
    for (final raw in _destinations) {
      final item = Map<String, dynamic>.from(raw);
      final title =
          _normaliseSearch((item['title'] ?? item['name'] ?? '').toString());
      final address = _normaliseSearch((item['address'] ?? '').toString());
      final category = _normaliseSearch((item['category'] ?? '').toString());
      final type = _normaliseSearch((item['type'] ?? '').toString());
      final description =
          _normaliseSearch((item['description'] ?? '').toString());
      final interests = (item['interests'] as List? ?? [])
          .map((e) => _normaliseSearch(e.toString()))
          .toList();
      final keywords = (item['keywords'] as List? ?? [])
          .map((e) => _normaliseSearch(e.toString()))
          .toList();
      final searchable =
          '$title $address $category $type $description ${interests.join(' ')} ${keywords.join(' ')}';

      var score = 0.0;
      if (genericTerms.contains(q)) score += 22;
      if (q.isNotEmpty && title == q) score += 180;
      if (q.isNotEmpty && title.contains(q)) score += 120;
      if (q.isNotEmpty && keywords.any((k) => k == q)) score += 105;
      if (q.isNotEmpty && keywords.any((k) => k.contains(q) || q.contains(k)))
        score += 70;

      if (dishIntent.isNotEmpty) {
        if (searchable.contains(dishIntent)) score += 125;
        if (category.contains('food') || type.contains('food')) score += 22;
      }

      for (final term in queryTerms) {
        if (term.length < 2) continue;
        if (title.contains(term)) score += 36;
        if (category.contains(term) || type.contains(term)) score += 30;
        if (keywords.any((k) => k.contains(term))) score += 29;
        if (interests.any((x) => x.contains(term))) score += 22;
        if (description.contains(term)) score += 12;
        if (address.contains(term)) score += 8;
      }

      if (filter.isNotEmpty && filter != 'all') {
        if ('$category $type ${interests.join(' ')}'.contains(filter)) {
          score += 36;
        } else if (!(filter == 'food' && dishIntent.isNotEmpty)) {
          continue;
        }
      }

      if (locationTerms.isNotEmpty && !location.contains('malaysia')) {
        final locationMatch =
            locationTerms.any((term) => address.contains(term));
        if (locationMatch) {
          score += 70;
        } else {
          score -= 100;
        }
      }

      if (score > 0 || genericTerms.contains(q)) {
        item['searchScore'] = score.round();
        item['searchReason'] = dishIntent.isNotEmpty &&
                searchable.contains(dishIntent)
            ? 'Matches “${rawQuery.trim()}”'
            : 'Relevant to ${rawQuery.trim().isEmpty ? 'your search' : rawQuery.trim()}';
        scored.add(item);
      }
    }

    final sort = (query['sort'] ?? 'relevance').toLowerCase();
    scored.sort((a, b) {
      if (sort == 'rating') {
        final byRating = _num(b['rating']).compareTo(_num(a['rating']));
        if (byRating != 0) return byRating;
      } else if (sort == 'name') {
        final byName = (a['title'] ?? a['name'] ?? '')
            .toString()
            .compareTo((b['title'] ?? b['name'] ?? '').toString());
        if (byName != 0) return byName;
      }
      final bySearch = _num(b['searchScore']).compareTo(_num(a['searchScore']));
      if (bySearch != 0) return bySearch;
      return _num(b['rating']).compareTo(_num(a['rating']));
    });

    var result = scored
        .where((e) =>
            _num(e['searchScore']) >= (genericTerms.contains(q) ? 0 : 14))
        .take(30)
        .toList();

    // If the device is online, broaden low-volume searches with OpenStreetMap
    // Nominatim. No secret key is embedded in the APK. Local TravelMate
    // results remain first because they carry richer recommendation metadata.
    if (rawQuery.isNotEmpty && result.length < 12) {
      try {
        final online = await _onlinePlaceSearch(rawQuery, rawLocation);
        final existingIds = result
            .map((e) => (e['destinationId'] ?? e['place_id'] ?? e['title'])
                .toString()
                .toLowerCase())
            .toSet();
        for (final item in online) {
          final id =
              (item['destinationId'] ?? item['place_id'] ?? item['title'])
                  .toString()
                  .toLowerCase();
          final title = (item['title'] ?? '').toString().toLowerCase();
          if (existingIds.contains(id) ||
              result.any(
                  (e) => (e['title'] ?? '').toString().toLowerCase() == title))
            continue;
          result.add(item);
          existingIds.add(id);
          if (result.length >= 24) break;
        }
      } catch (_) {
        // Local ranked results remain available when the network source cannot be reached.
      }
    }

    await _writeList('last_search_results',
        result.map((e) => Map<String, dynamic>.from(e)).toList());
    return {
      'ok': true,
      'results': result,
      'source': result.any((e) => e['source'] == 'openstreetmap')
          ? 'combined'
          : 'local',
      'query': rawQuery,
      'locationUsed': rawLocation,
      'resultCount': result.length,
    };
  }

  String _inferLocationFromQuery(String q) {
    const aliases = <String, String>{
      'kuala lumpur': 'Kuala Lumpur, Malaysia',
      'kl': 'Kuala Lumpur, Malaysia',
      'k l': 'Kuala Lumpur, Malaysia',
      'kl ': 'Kuala Lumpur, Malaysia',
      ' kl': 'Kuala Lumpur, Malaysia',
      'klcc': 'Kuala Lumpur, Malaysia',
      'penang': 'Penang, Malaysia',
      'george town': 'Penang, Malaysia',
      'georgetown': 'Penang, Malaysia',
      'langkawi': 'Langkawi, Kedah, Malaysia',
      'melaka': 'Melaka, Malaysia',
      'malacca': 'Melaka, Malaysia',
      'johor bahru': 'Johor Bahru, Malaysia',
      'ipoh': 'Ipoh, Perak, Malaysia',
    };
    for (final entry in aliases.entries) {
      if (q == entry.key || q.contains(entry.key)) return entry.value;
    }
    return '';
  }

  String _foodDishIntent(String q) {
    const dishes = <String, List<String>>{
      'curry mee': [
        'curry mee',
        'white curry mee',
        'curry noodle',
        'curry noodles'
      ],
      'asam laksa': ['asam laksa', 'penang laksa', 'laksa'],
      'char koay teow': ['char koay teow', 'char kway teow', 'fried kway teow'],
      'nasi kandar': ['nasi kandar'],
      'chendul': ['chendul', 'cendol'],
      'hokkien mee': ['hokkien mee', 'prawn mee'],
      'roti canai': ['roti canai'],
      'satay': ['satay'],
    };
    for (final entry in dishes.entries) {
      if (entry.value.any((x) => q.contains(x))) return entry.key;
    }
    return '';
  }

  Future<List<Map<String, dynamic>>> _onlinePlaceSearch(
      String rawQuery, String rawLocation) async {
    final queryText =
        [rawQuery, rawLocation].where((e) => e.trim().isNotEmpty).join(', ');
    final uri = Uri.https('nominatim.openstreetmap.org', '/search', {
      'q': queryText,
      'format': 'jsonv2',
      'addressdetails': '1',
      'extratags': '1',
      'namedetails': '1',
      'countrycodes': 'my',
      'limit': '15',
    });
    final response = await http.get(
      uri,
      headers: const {
        'User-Agent': 'TravelMate-FYP/1.0 (educational travel planner)',
        'Accept-Language': 'en',
      },
    ).timeout(const Duration(seconds: 5));
    if (response.statusCode < 200 || response.statusCode >= 300) return [];
    final decoded = jsonDecode(response.body);
    if (decoded is! List) return [];

    final items = <Map<String, dynamic>>[];
    for (final raw in decoded.whereType<Map>()) {
      final r = Map<String, dynamic>.from(raw);
      final extra = r['extratags'] is Map
          ? Map<String, dynamic>.from(r['extratags'] as Map)
          : <String, dynamic>{};
      final named = r['namedetails'] is Map
          ? Map<String, dynamic>.from(r['namedetails'] as Map)
          : <String, dynamic>{};
      final title = (named['name:en'] ?? named['name'] ?? r['name'] ?? '')
          .toString()
          .trim();
      final display = (r['display_name'] ?? '').toString();
      final fallbackTitle = display.split(',').first.trim();
      final name = title.isNotEmpty ? title : fallbackTitle;
      if (name.isEmpty) continue;
      final type = (r['type'] ?? r['category'] ?? 'Place')
          .toString()
          .replaceAll('_', ' ');
      final opening = (extra['opening_hours'] ?? '').toString();
      items.add({
        'destinationId':
            'osm_${r['osm_type'] ?? ''}_${r['osm_id'] ?? r['place_id']}',
        'place_id':
            'osm_${r['osm_type'] ?? ''}_${r['osm_id'] ?? r['place_id']}',
        'title': name,
        'name': name,
        'address': display,
        'category': _titleCase(
            (r['category'] ?? 'Place').toString().replaceAll('_', ' ')),
        'type': _titleCase(type),
        'rating': null,
        'reviews': 0,
        'description':
            'Place information discovered from OpenStreetMap. Open the details page for available address, contact and operating information.',
        'openingHours': opening.isEmpty
            ? 'Operating hours are not listed in the current map record.'
            : opening,
        'weeklyHours': _weeklyFromOpeningHours(opening),
        'website': extra['website'] ?? extra['contact:website'] ?? '',
        'phone': extra['phone'] ?? extra['contact:phone'] ?? '',
        'estimatedCost': 0.0,
        'recommendedDurationMinutes': 90,
        'indoor': ['restaurant', 'cafe', 'museum', 'mall', 'shop']
            .any((x) => type.toLowerCase().contains(x)),
        'gps_coordinates': {
          'latitude': double.tryParse((r['lat'] ?? '').toString()),
          'longitude': double.tryParse((r['lon'] ?? '').toString()),
        },
        'interests': [_titleCase(type)],
        'keywords': [name, type, rawQuery],
        'budgetLevel': 'Moderate',
        'pace': ['Relaxed', 'Moderate', 'Packed'],
        'purpose': ['Holiday', 'Solo travel', 'Family trip'],
        'personality': ['Explorer', 'Planner', 'Balanced'],
        'popularity': ((_num(r['importance']) * 100).clamp(20, 95)).round(),
        'searchScore': 45,
        'searchReason': 'Additional online place match',
        'source': 'openstreetmap',
      });
    }
    return items;
  }

  Map<String, String> _weeklyFromOpeningHours(String hours) {
    if (hours.trim().isEmpty) {
      return {
        'Monday': 'Not listed',
        'Tuesday': 'Not listed',
        'Wednesday': 'Not listed',
        'Thursday': 'Not listed',
        'Friday': 'Not listed',
        'Saturday': 'Not listed',
        'Sunday': 'Not listed',
      };
    }
    return {
      'Monday': hours,
      'Tuesday': hours,
      'Wednesday': hours,
      'Thursday': hours,
      'Friday': hours,
      'Saturday': hours,
      'Sunday': hours,
    };
  }

  String _normaliseSearch(String value) => value
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9 ]'), ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();

  Set<String> _tokenise(String value) => _normaliseSearch(value)
      .split(' ')
      .where((e) => e.trim().length >= 2)
      .toSet();

  Set<String> _expandedSearchTerms(String value) {
    final terms = _tokenise(value);
    const synonyms = <String, List<String>>{
      'food': [
        'hawker',
        'restaurant',
        'eat',
        'cafe',
        'local',
        'noodle',
        'market'
      ],
      'eat': ['food', 'hawker', 'restaurant', 'cafe'],
      'restaurant': ['food', 'eat', 'dining', 'cafe'],
      'noodle': ['food', 'mee', 'laksa', 'curry'],
      'curry': ['curry mee', 'white curry mee', 'noodles', 'food'],
      'mee': ['noodles', 'curry mee', 'hokkien mee', 'food'],
      'laksa': ['asam laksa', 'food', 'noodles'],
      'history': ['heritage', 'museum', 'culture', 'historic', 'fort'],
      'heritage': ['history', 'museum', 'culture', 'architecture', 'old town'],
      'culture': ['heritage', 'museum', 'temple', 'art', 'history'],
      'museum': ['history', 'culture', 'indoor', 'gallery'],
      'nature': ['park', 'garden', 'forest', 'beach', 'hiking', 'hill'],
      'adventure': ['hiking', 'theme', 'park', 'outdoor', 'water', 'trail'],
      'shopping': ['mall', 'market', 'retail', 'souvenir'],
      'family': ['family', 'museum', 'attraction', 'park', 'aquarium'],
      'photo': ['photography', 'viewpoint', 'heritage', 'scenery', 'landmark'],
      'photography': ['photo', 'viewpoint', 'heritage', 'scenery', 'landmark'],
      'indoor': ['museum', 'shopping', 'mall', 'aquarium', 'gallery'],
      'beach': ['sea', 'sunset', 'coast', 'water'],
      'night': ['nightlife', 'evening', 'food street', 'market'],
      'attraction': ['landmark', 'museum', 'park', 'temple', 'heritage'],
      'attractions': ['landmark', 'museum', 'park', 'temple', 'heritage'],
      'kl': ['kuala lumpur'],
      'georgetown': ['george town', 'penang'],
    };
    final expanded = <String>{...terms};
    for (final term in terms) {
      expanded.addAll(synonyms[term] ?? const []);
    }
    final normal = _normaliseSearch(value);
    if (normal.contains('curry mee') || normal.contains('white curry')) {
      expanded
          .addAll(['curry mee', 'white curry mee', 'curry noodles', 'food']);
    }
    if (normal.contains('char koay teow') ||
        normal.contains('char kway teow')) {
      expanded.addAll(
          ['char koay teow', 'char kway teow', 'fried noodles', 'food']);
    }
    if (normal.contains('asam laksa'))
      expanded.addAll(['asam laksa', 'laksa', 'food']);
    if (normal.contains('nasi kandar'))
      expanded.addAll(['nasi kandar', 'food', 'rice']);
    return expanded;
  }

  Future<dynamic> _destinationDetails(String id) async {
    var item = _findDestination(id);
    String source = 'local';
    if (item == null) {
      final cached = await _readList('last_search_results');
      for (final candidate in cached) {
        final candidateId = (candidate['destinationId'] ??
                candidate['place_id'] ??
                candidate['title'] ??
                '')
            .toString();
        if (candidateId == id) {
          item = Map<String, dynamic>.from(candidate);
          source = (candidate['source'] ?? 'search').toString();
          break;
        }
      }
    }
    if (item == null)
      throw Exception(
          'Destination details are no longer available. Search for the place again.');
    return {'ok': true, 'destination': item, 'source': source};
  }

  Future<dynamic> _nearbyPlaces(String id, Map<String, String> query) async {
    final base = _findDestination(id);
    final baseGps = base?['gps_coordinates'];
    final radius = _num(query['radiusKm'] ?? 12);
    final results = <Map<String, dynamic>>[];
    if (baseGps is! Map) {
      return {
        'ok': true,
        'base': base ?? {},
        'items': results,
        'source': 'local',
      };
    }
    final baseLat = _num(baseGps['latitude']);
    final baseLon = _num(baseGps['longitude']);
    for (final raw in _destinations) {
      final item = Map<String, dynamic>.from(raw);
      final itemId =
          (item['destinationId'] ?? item['place_id'] ?? item['title'] ?? '')
              .toString();
      if (itemId.toLowerCase() == id.toLowerCase()) continue;
      final gps = item['gps_coordinates'];
      if (gps is! Map) continue;
      final distance = _distanceKm(
        baseLat,
        baseLon,
        _num(gps['latitude']),
        _num(gps['longitude']),
      );
      if (distance <= radius) {
        item['distanceKm'] = _money(distance);
        item['nearbyReason'] =
            '${item['title'] ?? 'This place'} is about ${distance.toStringAsFixed(1)} km from ${base?['title'] ?? 'the selected place'}.';
        results.add(item);
      }
    }
    results
        .sort((a, b) => _num(a['distanceKm']).compareTo(_num(b['distanceKm'])));
    return {
      'ok': true,
      'base': base ?? {},
      'items': results.take(12).toList(),
      'source': 'local',
    };
  }

  Future<dynamic> _destinationReviews(String id) async {
    Map<String, dynamic>? item = _findDestination(id);
    if (item == null) {
      final cached = await _readList('last_search_results');
      for (final candidate in cached) {
        final candidateId = (candidate['destinationId'] ??
                candidate['place_id'] ??
                candidate['title'] ??
                '')
            .toString();
        if (candidateId == id) {
          item = Map<String, dynamic>.from(candidate);
          break;
        }
      }
    }
    item ??= Map<String, dynamic>.from(_destinations.first);
    final title = item['title'];
    final rawBase = _num(item['rating']);
    final base = rawBase > 0 ? rawBase : 4.4;
    final category =
        (item['category'] ?? 'attraction').toString().toLowerCase();
    final reviews = [
      {
        'username': 'Aina R.',
        'rating': base,
        'snippet':
            '$title fitted nicely into our day plan. The location was easy to combine with nearby stops and the overall visit was worthwhile.',
        'date': '2 weeks ago',
      },
      {
        'username': 'Daniel T.',
        'rating': max(4.0, base - .2),
        'snippet':
            'A good choice for travellers interested in $category. I would suggest checking the busiest hours before going.',
        'date': '1 month ago',
      },
      {
        'username': 'Mei Ling',
        'rating': min(5.0, base + .1),
        'snippet':
            'The information and atmosphere made this one of the more memorable places on our itinerary. We spent longer here than expected.',
        'date': '1 month ago',
      },
      {
        'username': 'Hafiz K.',
        'rating': max(3.8, base - .3),
        'snippet':
            'Worth visiting, especially if you plan nearby attractions on the same day. Transport and timing matter during peak periods.',
        'date': '2 months ago',
      },
      {
        'username': 'Sofia N.',
        'rating': base,
        'snippet':
            'Good overall experience. The place matched the description and worked well for our travel pace.',
        'date': '2 months ago',
      },
      {
        'username': 'Jason L.',
        'rating': min(5.0, base + .2),
        'snippet':
            'I enjoyed the visit and would recommend keeping enough time for photos and exploring the surrounding area.',
        'date': '3 months ago',
      },
      {
        'username': 'Nurul A.',
        'rating': max(4.0, base - .1),
        'snippet':
            'Useful stop for a first trip. We checked the opening schedule first and avoided the busiest period.',
        'date': '3 months ago',
      },
      {
        'username': 'Wei Jian',
        'rating': base,
        'snippet':
            'A solid addition to the itinerary. I liked that there were other places nearby, so the day did not feel rushed.',
        'date': '4 months ago',
      },
    ];
    return {
      'ok': true,
      'source': 'local',
      'result': {
        'rating': item['rating'] ?? base,
        'reviews':
            (_num(item['reviews']) > 0 ? item['reviews'] : reviews.length),
        'review_summary':
            'Travellers commonly mention trip value, atmosphere, timing, accessibility and how easily the place fits into a day itinerary.',
        'user_reviews': reviews,
      },
    };
  }

  Map<String, dynamic>? _findDestination(String id) {
    final needle = id.trim().toLowerCase();
    for (final item in _destinations) {
      final ids = [
        item['destinationId'],
        item['place_id'],
        item['title'],
        item['name']
      ].map((e) => (e ?? '').toString().toLowerCase());
      if (ids.contains(needle)) return Map<String, dynamic>.from(item);
    }
    return null;
  }

  Future<dynamic> _saveFavourite(Map<String, dynamic> payload) async {
    final items = await _readList('favourites');
    final id =
        (payload['destinationId'] ?? payload['place_id'] ?? payload['title'])
            .toString();
    final record = {
      ...payload,
      'id': id,
      'destinationId': id,
      'savedAt': _now()
    };
    final index = items.indexWhere((e) => e['id'].toString() == id);
    if (index >= 0) {
      items[index] = record;
    } else {
      items.insert(0, record);
    }
    await _writeList('favourites', items);
    return {'ok': true, 'favourite': record};
  }

  Future<dynamic> _generateRecommendations(Map<String, dynamic> payload) async {
    final preferences = await _readMap('preferences') ?? {};
    final learnedProfile = await _readMap('learned_preference_profile');
    final effectivePreferences =
        PreferenceLearning.effectiveProfile(preferences, learnedProfile);
    final requestedDestination =
        (payload['destinationArea'] ?? 'Malaysia').toString().trim();
    final destinationScope =
        MalaysianLocality.normalizeScope(requestedDestination);
    if (destinationScope['resolved'] != true) {
      return {
        'ok': false,
        'error': 'Requested Malaysian destination could not be resolved.',
      };
    }
    final interests = (preferences['interests'] as List? ?? [])
        .map((value) => value.toString())
        .where((value) => value.trim().isNotEmpty)
        .toList();
    final travelType = (preferences['travelType'] ?? '').toString();
    final budget = (preferences['budgetRange'] ?? 'Moderate').toString();
    final pace = (preferences['travelPace'] ?? '').toString();
    final purpose = (preferences['travelPurpose'] ?? '').toString();
    final personality = (preferences['travelPersonality'] ?? '').toString();
    final eligibleCandidates = <Map<String, dynamic>>[];
    for (final raw in _destinations) {
      final candidate = MalaysianLocality.validateCandidate(
          Map<String, dynamic>.from(raw), destinationScope);
      if (candidate['geographicEligibility']?['eligible'] != true) continue;
      eligibleCandidates.add(Map<String, dynamic>.from(candidate));
    }

    final feedback =
        (payload['sharedFeedback'] as List? ?? await _readList('feedback'))
            .whereType<Map>()
            .map((value) => Map<String, dynamic>.from(value))
            .toList();
    final scored = RecommendationScoring.rankCandidates(
      candidates: eligibleCandidates,
      preferences: effectivePreferences,
      feedback: feedback,
      currentUserId: _uid,
      limit: 12,
    );
    final top = scored
        .map((item) => {...item, 'recommendationSource': 'fallback'})
        .map((item) =>
            MalaysianLocality.validateCandidate(item, destinationScope))
        .where((item) => item['geographicEligibility']?['eligible'] == true)
        .toList();
    final generatedAt = _now();
    final generationId =
        'local_rec_${DateTime.now().microsecondsSinceEpoch}_${_uid.hashCode.abs()}';
    final snapshot = <String, dynamic>{
      'recommendationGenerationId': generationId,
      'userId': _uid,
      'travellerId': _uid,
      'requestedDestination': requestedDestination,
      'destinationArea': requestedDestination,
      'canonicalDestinationScope': destinationScope,
      'preferenceProfileVersion': PreferenceLearning.effectiveVersion(
        (preferences['preferenceProfileVersion'] ??
                preferences['updatedAt'] ??
                'local_profile_legacy')
            .toString(),
        learnedProfile,
      ),
      'generatedAt': generatedAt,
      'source': 'fallback',
      'engine': _engineInfo,
      'recommendationResults': top,
    };
    final snapshots = await _readList('recommendation_snapshots');
    snapshots.insert(0, snapshot);
    await _writeList('recommendation_snapshots', snapshots);
    return {
      'ok': true,
      'recommendationGenerationId': generationId,
      'snapshot': snapshot,
      'recommendations': top,
      'source': 'fallback',
      'engine': _engineInfo,
      'profileUsed': {
        'interests': interests,
        'travelType': travelType,
        'budget': budget,
        'pace': pace,
        'purpose': purpose,
        'personality': personality,
      },
    };
  }

  Future<dynamic> _submitPreferenceFeedback(
    Map<String, dynamic> payload,
  ) async {
    final destinationId = (payload['destinationId'] ?? '').toString().trim();
    final feedbackType = (payload['feedbackType'] ?? '').toString().trim();
    final generationId =
        (payload['recommendationGenerationId'] ?? '').toString().trim();
    final sourceContext =
        (payload['sourceContext'] ?? 'recommendation').toString().trim();
    Map<String, dynamic>? snapshotItem;
    if (generationId.isNotEmpty) {
      final snapshots = await _readList('recommendation_snapshots');
      Map<String, dynamic>? snapshot;
      for (final candidate in snapshots) {
        if ((candidate['recommendationGenerationId'] ?? '').toString() ==
            generationId) {
          snapshot = candidate;
          break;
        }
      }
      if (snapshot == null) {
        return {
          'ok': false,
          'statusCode': 409,
          'error': 'Recommendation snapshot was not found.',
        };
      }
      for (final raw
          in snapshot['recommendationResults'] as List? ?? const []) {
        if (raw is! Map) continue;
        final item = Map<String, dynamic>.from(raw);
        final itemId = (item['destinationId'] ??
                item['place_id'] ??
                item['id'] ??
                item['title'] ??
                item['name'] ??
                '')
            .toString();
        if (itemId == destinationId) {
          snapshotItem = item;
          break;
        }
      }
      if (snapshotItem == null) {
        return {
          'ok': false,
          'statusCode': 409,
          'error':
              'Destination does not belong to this recommendation snapshot.',
        };
      }
    }
    try {
      final concepts = snapshotItem?['destinationConcepts'] ??
          payload['destinationConcepts'] ??
          RecommendationTaxonomy.candidateConcepts(payload);
      final now = _now();
      final eventId = 'local_feedback_${DateTime.now().microsecondsSinceEpoch}';
      final update = PreferenceLearning.applyFeedback(
        await _readMap('learned_preference_profile'),
        userId: _uid,
        destinationId: destinationId,
        feedbackType: feedbackType,
        destinationConcepts: concepts,
        recommendationGenerationId: generationId,
        sourceContext: sourceContext,
        now: now,
        eventId: eventId,
      );
      if (update.changed) {
        await _writeMap('learned_preference_profile', update.profile);
        final events = await _readList('recommendation_feedback_events');
        events.insert(0, Map<String, dynamic>.from(update.event!));
        await _writeList('recommendation_feedback_events', events);
      }
      return {
        'ok': true,
        'changed': update.changed,
        'learning': PreferenceLearning.publicState(update.profile),
        'message': update.changed
            ? 'Thanks — this will help improve future recommendations.'
            : 'Your feedback is already recorded.',
      };
    } on ArgumentError catch (error) {
      return {'ok': false, 'error': error.message.toString()};
    }
  }

  Future<dynamic> _resetPreferenceFeedback() async {
    final now = _now();
    final eventId = 'local_reset_${DateTime.now().microsecondsSinceEpoch}';
    final update = PreferenceLearning.reset(
      await _readMap('learned_preference_profile'),
      userId: _uid,
      now: now,
      eventId: eventId,
    );
    await _writeMap('learned_preference_profile', update.profile);
    final events = await _readList('recommendation_feedback_events');
    events.insert(0, Map<String, dynamic>.from(update.event!));
    await _writeList('recommendation_feedback_events', events);
    return {
      'ok': true,
      'changed': update.changed,
      'learning': PreferenceLearning.publicState(update.profile),
      'message': 'Learned recommendation preferences were reset.',
    };
  }

  // ------------------------------------------------------------------
  // Itinerary and budget
  // ------------------------------------------------------------------

  String? _personalisedInputError(Map<String, dynamic> payload) {
    if ((payload['title'] ?? '').toString().trim().isEmpty ||
        (payload['destinationArea'] ?? '').toString().trim().isEmpty) {
      return 'Enter a trip title and destination.';
    }
    final start = DateTime.tryParse((payload['startDate'] ?? '').toString());
    final end = DateTime.tryParse((payload['endDate'] ?? '').toString());
    if (start == null || end == null || end.isBefore(start)) {
      return 'Use a valid trip date range.';
    }
    if (_num(payload['travellerCount']).round() < 1) {
      return 'Traveller count must be at least 1.';
    }
    if (_num(payload['budgetLimit']) < 0) {
      return 'Budget cannot be negative.';
    }
    if ((payload['recommendationGenerationId'] ?? '')
        .toString()
        .trim()
        .isEmpty) {
      return 'A recommendation generation ID is required for a personalised trip.';
    }
    final requestId = (payload['generationRequestId'] ?? '').toString().trim();
    if (requestId.length < 8 || requestId.length > 128) {
      return 'A valid generation request ID is required.';
    }
    return null;
  }

  String _personalisedTripId(String generationRequestId) {
    final safeUser = _uid.replaceAll(RegExp(r'[^a-zA-Z0-9_-]'), '_');
    final safe = generationRequestId.replaceAll(RegExp(r'[^a-zA-Z0-9_-]'), '_');
    return 'personalised_${safeUser}_$safe';
  }

  Future<Map<String, dynamic>> _snapshotForTrip(
      Map<String, dynamic> trip, Map<String, dynamic> payload) async {
    final requestedGenerationId =
        (payload['recommendationGenerationId'] ?? '').toString().trim();
    final tripGenerationId =
        (trip['recommendationGenerationId'] ?? '').toString().trim();
    if (requestedGenerationId.isNotEmpty &&
        tripGenerationId.isNotEmpty &&
        requestedGenerationId != tripGenerationId) {
      throw Exception(
          'Recommendation snapshot does not match the snapshot linked to this trip.');
    }
    final generationId =
        tripGenerationId.isNotEmpty ? tripGenerationId : requestedGenerationId;
    if (generationId.isEmpty) return <String, dynamic>{};

    final snapshots = await _readList('recommendation_snapshots');
    Map<String, dynamic>? snapshot;
    for (final candidate in snapshots) {
      if (candidate['recommendationGenerationId'].toString() == generationId) {
        snapshot = candidate;
        break;
      }
    }
    if (snapshot == null || snapshot['travellerId'].toString() != _uid) {
      throw Exception('Recommendation snapshot not found for this traveller.');
    }
    if (_requestedArea(snapshot['requestedDestination'].toString()) !=
        _requestedArea((trip['destinationArea'] ?? '').toString())) {
      throw Exception(
          'Recommendation snapshot destination does not match this trip.');
    }
    return snapshot;
  }

  Future<dynamic> _generatePersonalisedTrip(
      Map<String, dynamic> payload) async {
    final inputError = _personalisedInputError(payload);
    if (inputError != null) {
      return {
        'ok': false,
        'error': inputError,
        'stage': 'input_validation',
        'retryable': false,
      };
    }

    final requestId = payload['generationRequestId'].toString().trim();
    final id = _personalisedTripId(requestId);
    final existing = await _tripById(id);
    if (existing != null &&
        _requestedArea(existing['destinationArea'].toString()) !=
            _requestedArea(payload['destinationArea'].toString())) {
      return {
        'ok': false,
        'error':
            'Generation request is already linked to a different destination.',
        'tripId': id,
        'status': existing['status'],
        'retryable': false,
      };
    }

    final candidate = existing ??
        <String, dynamic>{
          ...payload,
          'id': id,
          'travellerId': _uid,
          'activities': <Map<String, dynamic>>[],
        };
    try {
      await _snapshotForTrip(candidate, payload);
    } catch (error) {
      return {
        'ok': false,
        'error': error.toString().replaceFirst('Exception: ', ''),
        'tripId': existing == null ? null : id,
        'stage': 'snapshot_validation',
        'retryable': false,
      };
    }

    if (existing?['status'] == 'planned') {
      return {
        'ok': true,
        'id': id,
        'tripId': id,
        'status': 'planned',
        'itinerary': existing,
        'reused': true,
      };
    }
    if (existing?['status'] == 'generating') {
      return {
        'ok': true,
        'id': id,
        'tripId': id,
        'status': 'generating',
        'itinerary': existing,
        'inProgress': true,
        'reused': true,
      };
    }

    if (existing == null) {
      final now = _now();
      await _replaceTrip({
        ...payload,
        'id': id,
        'travellerId': _uid,
        'activities': <Map<String, dynamic>>[],
        'planningFlow': 'personalised',
        'generationRequestId': requestId,
        'status': 'generating',
        'generationAttempts': 0,
        'retryable': false,
        'createdAt': now,
        'updatedAt': now,
      });
    }

    final result = await _generateAndPlanTrip(id, payload);
    if (result is Map) result['reused'] = existing != null;
    return result;
  }

  Future<dynamic> _createTrip(Map<String, dynamic> payload) async {
    final trips = await _readList('itineraries');
    final id = 'trip_${DateTime.now().millisecondsSinceEpoch}';
    final activities = (payload['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    for (var i = 0; i < activities.length; i++) {
      activities[i]['activityId'] ??= '${id}_a${i + 1}';
      activities[i]['sequenceNo'] ??= i + 1;
      activities[i]['dayNo'] ??= 1;
    }
    final trip = <String, dynamic>{
      ...payload,
      'id': id,
      'travellerId': _uid,
      'activities': activities,
      'status': payload['status'] ?? 'draft',
      'createdAt': _now(),
      'updatedAt': _now(),
    };
    trips.insert(0, trip);
    await _writeList('itineraries', trips);
    return {'ok': true, 'id': id, 'itinerary': trip};
  }

  Future<Map<String, dynamic>?> _tripById(String id) async {
    final trips = await _readList('itineraries');
    for (final trip in trips) {
      if (trip['id'].toString() == id) return trip;
    }
    return null;
  }

  Future<void> _replaceTrip(Map<String, dynamic> updated) async {
    final trips = await _readList('itineraries');
    final index =
        trips.indexWhere((e) => e['id'].toString() == updated['id'].toString());
    if (index >= 0) {
      trips[index] = updated;
    } else {
      trips.insert(0, updated);
    }
    await _writeList('itineraries', trips);
  }

  Future<dynamic> _updateTrip(String id, Map<String, dynamic> payload) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    trip.addAll(payload);
    trip['id'] = id;
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {'ok': true, 'itinerary': trip};
  }

  Future<dynamic> _addActivity(String id, Map<String, dynamic> payload) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    final activities = (trip['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final activity = <String, dynamic>{
      ...payload,
      'activityId': payload['activityId'] ??
          '${id}_a${DateTime.now().microsecondsSinceEpoch}',
      'sequenceNo': activities.length + 1,
      'dayNo': payload['dayNo'] ?? 1,
    };
    activities.add(activity);
    trip['activities'] = activities;
    final recalculated = planConstraintAwareItinerary(trip,
        preserveOrder: true, respectDayAssignments: true);
    trip
      ..clear()
      ..addAll(recalculated);
    trip['budgetEstimate'] = _calculateBudget(trip);
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {
      'ok': true,
      'activity': activity,
      'itinerary': trip,
      'activities': trip['activities'],
      'budget': trip['budgetEstimate'],
    };
  }

  Future<dynamic> _removeActivity(String id, String activityId) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    final activities = (trip['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    activities.removeWhere((e) => e['activityId'].toString() == activityId);
    for (var i = 0; i < activities.length; i++)
      activities[i]['sequenceNo'] = i + 1;
    trip['activities'] = activities;
    final recalculated = planConstraintAwareItinerary(trip,
        preserveOrder: true, respectDayAssignments: true);
    trip
      ..clear()
      ..addAll(recalculated);
    trip['budgetEstimate'] = _calculateBudget(trip);
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {
      'ok': true,
      'itinerary': trip,
      'activities': trip['activities'],
      'budget': trip['budgetEstimate']
    };
  }

  Future<dynamic> _updateActivity(
      String id, String activityId, Map<String, dynamic> payload) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    final activities = (trip['activities'] as List? ?? [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
    final index =
        activities.indexWhere((item) => '${item['activityId']}' == activityId);
    if (index < 0) throw Exception('Activity not found.');
    activities[index] = {...activities[index], ...payload};
    trip['activities'] = activities;
    final recalculated = planConstraintAwareItinerary(trip,
        preserveOrder: true, respectDayAssignments: true);
    trip
      ..clear()
      ..addAll(recalculated);
    trip['budgetEstimate'] = _calculateBudget(trip);
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {
      'ok': true,
      'itinerary': trip,
      'activities': trip['activities'],
      'budget': trip['budgetEstimate'],
    };
  }

  Future<dynamic> _rearrangeActivities(
      String id, Map<String, dynamic> payload) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    final current = (trip['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final ids = (payload['orderedActivityIds'] as List? ?? [])
        .map((e) => e.toString())
        .toList();
    final ordered = <Map<String, dynamic>>[];
    for (final idValue in ids) {
      final found = current.where((e) => e['activityId'].toString() == idValue);
      if (found.isNotEmpty) ordered.add(found.first);
    }
    for (final item in current) {
      if (!ordered.any((e) => e['activityId'] == item['activityId']))
        ordered.add(item);
    }
    for (var i = 0; i < ordered.length; i++) {
      ordered[i]['sequenceNo'] = i + 1;
    }
    trip['activities'] = ordered;
    final recalculated = planConstraintAwareItinerary(trip,
        preserveOrder: true, respectDayAssignments: true);
    trip
      ..clear()
      ..addAll(recalculated);
    trip['budgetEstimate'] = _calculateBudget(trip);
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {
      'ok': true,
      'itinerary': trip,
      'activities': trip['activities'],
      'budget': trip['budgetEstimate']
    };
  }

  int _tripDays(Map<String, dynamic> trip) {
    try {
      final start = DateTime.parse((trip['startDate'] ?? '').toString());
      final end = DateTime.parse((trip['endDate'] ?? '').toString());
      return (end.difference(start).inDays + 1).clamp(1, 14).toInt();
    } catch (_) {
      return 3;
    }
  }

  Future<dynamic> _generateItinerary(
      String id, Map<String, dynamic> payload) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');

    final snapshot = await _snapshotForTrip(trip, payload);
    final recommendationSnapshot = snapshot.isEmpty ? null : snapshot;
    final generationId = (trip['recommendationGenerationId'] ??
            payload['recommendationGenerationId'] ??
            '')
        .toString()
        .trim();

    var activities = (trip['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    for (final activity in activities) {
      final activityGenerationId =
          (activity['recommendationGenerationId'] ?? '').toString();
      if (activityGenerationId.isNotEmpty &&
          activityGenerationId != generationId) {
        throw Exception(
            'Itinerary contains recommendations from a different snapshot.');
      }
    }
    if (activities.isEmpty) {
      final recs = recommendationSnapshot != null
          ? (recommendationSnapshot['recommendationResults'] as List? ?? [])
              .whereType<Map>()
              .map((item) => Map<String, dynamic>.from(item))
              .where((item) => _matchesRequestedArea(
                  item, (trip['destinationArea'] ?? '').toString()))
              .toList()
          : _destinations
              .map((item) => Map<String, dynamic>.from(item))
              .where((item) => _matchesRequestedArea(
                  item, (trip['destinationArea'] ?? '').toString()))
              .toList();
      if (recs.isEmpty && recommendationSnapshot != null) {
        throw Exception(
            'Linked recommendation snapshot has no destination-relevant results.');
      }
      if (recs.isEmpty) {
        throw Exception(
            'No destination candidates are available for this trip.');
      }
      activities = recs
          .take(20)
          .map((item) => {
                'activityId':
                    '${id}_a${DateTime.now().microsecondsSinceEpoch}_${item['destinationId']}',
                'activityName': item['title'] ?? item['name'],
                'destinationId': item['destinationId'] ?? item['place_id'],
                'address': item['address'] ?? '',
                'estimatedCost': item['estimatedCost'] ?? 0,
                'gps_coordinates':
                    item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
                'indoor': item['indoor'] ?? false,
                'category': item['category'] ?? item['type'],
                'type': item['type'] ?? item['category'],
                'description': item['description'] ?? '',
                'openingHours': item['openingHours'] ?? '',
                if (item['recommendedDurationMinutes'] != null)
                  'recommendedDurationMinutes':
                      item['recommendedDurationMinutes'],
                if (item['providerDurationMinutes'] != null)
                  'providerDurationMinutes': item['providerDurationMinutes'],
                'durationSource': item['durationSource'] ?? '',
                if (generationId.isNotEmpty)
                  'recommendationGenerationId': generationId,
              })
          .toList();
    }

    final days = _tripDays(trip);
    final weatherNotes = <String>[];
    bool likelyRain = false;
    Map<String, dynamic> forecastData = {};
    try {
      final location = await _searchLocation(
          (payload['destinationName'] ?? trip['destinationArea'] ?? '')
              .toString());
      final results = location['results'] as List? ?? [];
      if (results.isNotEmpty) {
        final first = Map<String, dynamic>.from(results.first as Map);
        final forecast = await _weather({
          'latitude': '${first['latitude']}',
          'longitude': '${first['longitude']}',
        });
        forecastData = Map<String, dynamic>.from(
            forecast['weather'] is Map ? forecast['weather'] as Map : const {});
        final daily = forecastData['daily'] as Map?;
        final rain = (daily?['precipitation_probability_max'] as List? ?? []);
        likelyRain = rain.any((v) => _num(v) >= 60);
        if (likelyRain)
          weatherNotes.add(
              'Rain is possible on part of the trip; indoor activities are prioritised where practical.');
      }
    } catch (_) {
      weatherNotes.add(
          'Weather information will refresh when an internet connection is available.');
    }

    trip['activities'] = activities;
    trip['tripDays'] = days;
    trip['status'] = 'generating';
    trip['generationContext'] = {
      'destinationPlanning': true,
      'activityArrangement': true,
      'tripDayGeneration': true,
      'weatherConsideration': true,
      'weatherNotes': weatherNotes,
      'destinationSource': recommendationSnapshot?['source'] ?? 'fallback',
      'recommendationGenerationId':
          recommendationSnapshot?['recommendationGenerationId'],
    };
    trip['updatedAt'] = _now();
    final scheduled =
        planConstraintAwareItinerary(trip, forecast: forecastData);
    await _replaceTrip(scheduled);
    return {'ok': true, 'itinerary': scheduled};
  }

  Future<dynamic> _generateAndPlanTrip(
      String id, Map<String, dynamic> payload) async {
    var trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');

    try {
      await _snapshotForTrip(trip, payload);
    } catch (error) {
      return {
        'ok': false,
        'error': error.toString().replaceFirst('Exception: ', ''),
        'id': id,
        'tripId': id,
        'status': trip['status'] ?? 'draft',
        'stage': 'snapshot_validation',
        'retryable': false,
      };
    }

    final startedAt = _now();
    trip = {
      ...trip,
      'status': 'generating',
      'generationStartedAt': startedAt,
      'generationAttempts': _num(trip['generationAttempts']).round() + 1,
      'lastGenerationError': null,
      'generationFailedAt': null,
      'retryable': false,
      'updatedAt': startedAt,
    };
    await _replaceTrip(trip);

    var stage = 'itinerary_generation';
    Map<String, dynamic>? partial;
    try {
      final generated = await _generateItinerary(id, payload);
      partial = Map<String, dynamic>.from(generated['itinerary'] as Map);
      stage = 'budget_calculation';
      final calculatedBudget = _calculateBudget(partial);

      stage = 'save_generated_trip';
      final plannedAt = _now();
      final planned = <String, dynamic>{
        ...partial,
        'budgetEstimate': calculatedBudget,
        'status': 'planned',
        'plannedAt': plannedAt,
        'lastGenerationError': null,
        'generationFailedAt': null,
        'retryable': false,
        'updatedAt': plannedAt,
      };
      await _replaceTrip(planned);
      return {
        'ok': true,
        'id': id,
        'tripId': id,
        'status': 'planned',
        'itinerary': planned,
      };
    } catch (error) {
      final message = error.toString().replaceFirst('Exception: ', '');
      final failedAt = _now();
      final failed = <String, dynamic>{
        ...trip,
        if (partial != null) ...partial,
        'status': 'generation_failed',
        'generationFailureStage': stage,
        'lastGenerationError': message,
        'generationFailedAt': failedAt,
        'retryable': true,
        'updatedAt': failedAt,
      };
      await _replaceTrip(failed);
      return {
        'ok': false,
        'error': message,
        'id': id,
        'tripId': id,
        'status': 'generation_failed',
        'stage': stage,
        'retryable': true,
        'itinerary': failed,
      };
    }
  }

  Future<dynamic> _saveTrip(String id) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    trip['status'] = 'planned';
    trip['plannedAt'] = _now();
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {'ok': true, 'itinerary': trip};
  }

  Map<String, dynamic> _calculateBudget(Map<String, dynamic> trip) {
    final activities =
        (trip['activities'] as List? ?? []).whereType<Map>().toList();
    final activityCost =
        activities.fold<double>(0, (sum, e) => sum + _num(e['estimatedCost']));
    final flight = _num(trip['flightCost']);
    final days = _tripDays(trip);
    final nights = max(0, days - 1);
    final rooms = max(1, _num(trip['roomQuantity']).round());
    final hasHotelTotal =
        trip['hotelCost'] != null && '${trip['hotelCost']}'.trim().isNotEmpty;
    final nightlyRate = _num(trip['hotelNightlyRate'] ?? trip['nightlyRate']);
    final hotel =
        hasHotelTotal ? _num(trip['hotelCost']) : nightlyRate * nights * rooms;
    final carRental = _num(trip['carRentalCost']);
    final travellers = max(1, _num(trip['travellerCount']).round());
    final transport = trip['transportCost'] != null
        ? _num(trip['transportCost'])
        : days * 35.0;
    final food = trip['foodCost'] != null
        ? _num(trip['foodCost'])
        : days * travellers * 60.0;
    final total = flight + hotel + carRental + transport + food + activityCost;
    final limit = _num(trip['budgetLimit']);
    final remaining = limit - total;
    final over = max(0.0, -remaining);
    final status = limit > 0 && total > limit ? 'over_budget' : 'within_budget';
    return {
      'limit': _money(limit),
      'flight': _money(flight),
      'hotel': _money(hotel),
      'hotelNights': nights,
      'hotelRooms': rooms,
      'carRental': _money(carRental),
      'transport': _money(transport),
      'food': _money(food),
      'activities': _money(activityCost),
      'total': _money(total),
      'remaining': _money(remaining),
      'overBy': _money(over),
      'status': status,
      'costProvenance': {
        'flight': flight > 0 ? 'confirmed' : 'not_selected',
        'hotel': hasHotelTotal
            ? 'confirmed_total'
            : (nightlyRate > 0
                ? 'estimated_from_nightly_rate'
                : 'not_selected'),
        'carRental': carRental > 0 ? 'confirmed' : 'not_selected',
        'transport': trip['transportCost'] != null
            ? 'provided'
            : 'estimated_daily_allowance',
        'food':
            trip['foodCost'] != null ? 'provided' : 'estimated_daily_allowance',
        'activities': 'mixed_estimates',
      },
      'comparison': status == 'over_budget'
          ? 'The current plan exceeds the budget by RM ${_money(over)}. Review the suggested lower-cost alternatives.'
          : 'The current plan is within budget with RM ${_money(max(0, remaining))} remaining.',
    };
  }

  Future<dynamic> _lowerCostAlternatives(String id) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    final budget = _calculateBudget(trip);
    final over = _num(budget['overBy']);
    final items = <Map<String, dynamic>>[
      {
        'alternativeType': 'Accommodation',
        'title': 'Choose a lower-cost room option',
        'estimatedSavings':
            max(40, min(180, _num(trip['hotelCost']) * .25)).round(),
        'data':
            'Compare lower-priced hotel offers or reduce the room category while keeping the same destination.',
      },
      {
        'alternativeType': 'Transport',
        'title': 'Group nearby activities',
        'estimatedSavings': 35,
        'data':
            'Arrange nearby attractions on the same day and use public transport for short city journeys.',
      },
      {
        'alternativeType': 'Activities',
        'title': 'Replace one higher-cost activity',
        'estimatedSavings': 45,
        'data':
            'Swap one paid attraction for a heritage walk, public beach, park or other lower-cost destination.',
      },
      {
        'alternativeType': 'Food',
        'title': 'Use a local-food daily budget',
        'estimatedSavings': 30,
        'data':
            'Plan one or two hawker meals per day while keeping one higher-value dining experience.',
      },
    ];
    return {'ok': true, 'overBy': over, 'alternatives': items};
  }

  Future<dynamic> _applyLowerCostAlternative(
      String id, Map<String, dynamic> payload) async {
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    final alternative = Map<String, dynamic>.from(payload['alternative'] is Map
        ? payload['alternative'] as Map
        : payload);
    final kind = (alternative['alternativeType'] ?? alternative['type'] ?? '')
        .toString()
        .toLowerCase();
    final rawData = alternative['data'];
    final data = rawData is Map
        ? Map<String, dynamic>.from(rawData)
        : <String, dynamic>{};
    final savings =
        _num(alternative['estimatedSavings'] ?? alternative['saving']);

    if (kind == 'flight' && data.isNotEmpty) {
      trip['selectedFlight'] = data;
      trip['flightCost'] = _num(data['price']);
    } else if (kind == 'hotel' || kind == 'accommodation') {
      if (data.isNotEmpty) {
        trip['selectedHotel'] = data;
        trip['hotelCost'] = _num(data['price']);
      } else {
        trip['hotelCost'] = max(0, _num(trip['hotelCost']) - savings);
      }
    } else if (kind.contains('car') && data.isNotEmpty) {
      trip['selectedCarRental'] = data;
      trip['carRentalCost'] = _num(data['totalPrice'] ?? data['price']);
    } else if (kind == 'transport' || kind == 'schedule') {
      trip['transportCost'] =
          max(0, _num(_calculateBudget(trip)['transport']) - savings);
    } else if (kind == 'food') {
      trip['foodCost'] = max(0, _num(_calculateBudget(trip)['food']) - savings);
    } else if (kind == 'activity' || kind == 'activities') {
      final activities = (trip['activities'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
      if (activities.isNotEmpty) {
        activities.sort((a, b) =>
            _num(b['estimatedCost']).compareTo(_num(a['estimatedCost'])));
        activities.first['estimatedCost'] =
            max(0, _num(activities.first['estimatedCost']) - savings);
        activities.first['budgetNote'] = 'Lower-cost alternative applied';
        trip['activities'] = activities;
      }
    } else {
      throw Exception('Unsupported lower-cost alternative.');
    }

    trip['lastAppliedLowerCostAlternative'] = alternative;
    trip['budgetEstimate'] = _calculateBudget(trip);
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {
      'ok': true,
      'itinerary': trip,
      'budget': trip['budgetEstimate'],
      'applied': alternative,
    };
  }

  // ------------------------------------------------------------------
  // Weather (real public Open-Meteo calls where internet is available)
  // ------------------------------------------------------------------

  Future<dynamic> _searchLocation(String place) async {
    try {
      final uri = Uri.https('geocoding-api.open-meteo.com', '/v1/search', {
        'name': place,
        'count': '5',
        'language': 'en',
        'format': 'json',
      });
      final response = await http.get(uri).timeout(const Duration(seconds: 15));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return {'ok': true, 'results': data['results'] ?? []};
      }
    } catch (_) {}

    final lower = place.toLowerCase();
    final point = lower.contains('kuala')
        ? {'name': 'Kuala Lumpur', 'latitude': 3.1390, 'longitude': 101.6869}
        : lower.contains('langkawi')
            ? {'name': 'Langkawi', 'latitude': 6.3500, 'longitude': 99.8000}
            : {
                'name': 'George Town',
                'latitude': 5.4141,
                'longitude': 100.3288
              };
    return {
      'ok': true,
      'results': [point]
    };
  }

  Future<dynamic> _weather(Map<String, String> query) async {
    final lat = query['latitude'] ?? '5.4141';
    final lon = query['longitude'] ?? '100.3288';
    try {
      final uri = Uri.https('api.open-meteo.com', '/v1/forecast', {
        'latitude': lat,
        'longitude': lon,
        'current':
            'temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code',
        'daily':
            'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
        'timezone': 'auto',
        'forecast_days': '7',
      });
      final response = await http.get(uri).timeout(const Duration(seconds: 20));
      if (response.statusCode == 200) {
        return {
          'ok': true,
          'weather': jsonDecode(response.body),
          'source': 'open_meteo'
        };
      }
    } catch (_) {}

    final now = DateTime.now();
    final dates = List.generate(7, (i) => _date(now.add(Duration(days: i))));
    return {
      'ok': true,
      'source': 'local',
      'weather': {
        'current': {
          'temperature_2m': 30,
          'relative_humidity_2m': 72,
          'wind_speed_10m': 8,
          'weather_code': 2,
        },
        'daily': {
          'time': dates,
          'temperature_2m_max': [31, 31, 30, 30, 31, 32, 31],
          'temperature_2m_min': [25, 25, 24, 25, 25, 25, 24],
          'precipitation_probability_max': [35, 45, 65, 55, 40, 30, 50],
        },
      },
    };
  }

  // ------------------------------------------------------------------
  // Flights and hotels
  // ------------------------------------------------------------------

  Future<dynamic> _flightSearch(Map<String, String> query) async {
    final from = (query['departure_id'] ?? 'KUL').toUpperCase();
    final to = (query['arrival_id'] ?? 'PEN').toUpperCase();
    final nonstop = query['nonstop'] == 'true';
    final travellers = max(1, _num(query['traveller_count'] ?? 1).round());
    final rows = [
      [
        'Malaysia Airlines',
        'MH1138',
        129.0,
        60,
        '08:10',
        '09:10',
        0,
        'Economy',
        'Boeing 737-800',
        'Terminal 1',
        'Terminal 1',
        '7 kg cabin',
        '20 kg checked',
        'Standard seat selection',
        'Snack / beverage subject to service'
      ],
      [
        'AirAsia',
        'AK6112',
        89.0,
        65,
        '10:25',
        '11:30',
        0,
        'Economy',
        'Airbus A320',
        'Terminal 2',
        'Main Terminal',
        '7 kg cabin',
        'Checked baggage optional',
        'Standard fare',
        'Meals available for purchase'
      ],
      [
        'Batik Air',
        'OD2108',
        108.0,
        60,
        '13:40',
        '14:40',
        0,
        'Economy',
        'Boeing 737',
        'Terminal 1',
        'Main Terminal',
        '7 kg cabin',
        '20 kg checked',
        'Standard seat',
        'Light refreshment subject to service'
      ],
      [
        'Firefly',
        'FY1432',
        149.0,
        70,
        '16:05',
        '17:15',
        0,
        'Economy',
        'ATR 72',
        'Subang / selected terminal',
        'Main Terminal',
        '7 kg cabin',
        '10 kg checked',
        'Standard seat',
        'Light refreshment subject to service'
      ],
      [
        'Malaysia Airlines',
        'MH2602',
        168.0,
        155,
        '18:20',
        '20:55',
        1,
        'Economy',
        'Boeing 737-800',
        'Terminal 1',
        'Main Terminal',
        '7 kg cabin',
        '20 kg checked',
        'Flexible connection option',
        'Snack / beverage subject to service'
      ],
    ];
    var items = rows
        .where((r) => !nonstop || r[6] == 0)
        .map((r) => {
              'id': 'flight_${r[1]}_${query['outbound_date'] ?? ''}',
              'airline': r[0],
              'flightNumber': r[1],
              'departureAirport': from,
              'arrivalAirport': to,
              'departureTime': r[4],
              'arrivalTime': r[5],
              'durationMinutes': r[3],
              'stops': r[6],
              'stopText': r[6] == 0 ? 'Nonstop' : '${r[6]} stop',
              'unitPrice': r[2],
              'travellerCount': travellers,
              'price': _money(_num(r[2]) * travellers),
              'currency': 'MYR',
              'bookingToken': 'ref_${r[1]}',
              'outboundDate': query['outbound_date'],
              'returnDate': query['return_date'],
              'cabinClass': r[7],
              'aircraft': r[8],
              'departureTerminal': r[9],
              'arrivalTerminal': r[10],
              'cabinBaggage': r[11],
              'checkedBaggage': r[12],
              'fareConditions': r[13],
              'meal': r[14],
              'changePolicy': 'Changes subject to fare rules and availability',
              'refundPolicy': 'Refundability depends on the selected fare',
            })
        .toList();
    if (query['sort'] == 'price_low') {
      items.sort((a, b) => _num(a['price']).compareTo(_num(b['price'])));
    } else if (query['sort'] == 'duration') {
      items.sort((a, b) =>
          _num(a['durationMinutes']).compareTo(_num(b['durationMinutes'])));
    }
    return {'ok': true, 'items': items, 'source': 'local'};
  }

  Future<dynamic> _selectFlight(Map<String, dynamic> payload) async {
    final id = (payload['itineraryId'] ?? '').toString();
    final flight = Map<String, dynamic>.from(payload['flight'] ?? {});
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    trip['selectedFlight'] = flight;
    trip['flightCost'] = _num(flight['price']);
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {'ok': true, 'itinerary': trip, 'budget': _calculateBudget(trip)};
  }

  Future<dynamic> _hotelSearch(Map<String, dynamic> payload) async {
    final destination =
        (payload['destination'] ?? 'George Town, Penang').toString();
    final refundableOnly = payload['refundable'] == true;
    final roomQuantity = max(1, _num(payload['roomQuantity'] ?? 1).round());
    final rows = [
      [
        'Heritage Courtyard Hotel',
        238.0,
        4.7,
        4,
        'Deluxe Heritage Room',
        'Breakfast included',
        true,
        '15:00',
        '12:00',
        '1 King bed',
        '32 m²',
        ['Wi-Fi', 'Breakfast', 'Air conditioning', 'Front desk', 'Restaurant'],
        'Free cancellation before the stated deadline; later cancellation may be charged.'
      ],
      [
        'Blue Grey City Hotel',
        188.0,
        4.5,
        4,
        'Superior King',
        'Room only',
        true,
        '15:00',
        '12:00',
        '1 King bed',
        '28 m²',
        ['Wi-Fi', 'Gym', 'Air conditioning', 'Front desk', 'Parking'],
        'Refundable according to the selected offer conditions.'
      ],
      [
        'Clan Jetty Boutique Stay',
        142.0,
        4.4,
        3,
        'Standard Queen',
        'Room only',
        false,
        '14:00',
        '12:00',
        '1 Queen bed',
        '22 m²',
        ['Wi-Fi', 'Air conditioning', 'Front desk'],
        'Non-refundable rate.'
      ],
      [
        'Garden Lane Residence',
        118.0,
        4.2,
        3,
        'Studio Room',
        'Breakfast available',
        true,
        '14:00',
        '11:00',
        '1 Queen bed',
        '30 m²',
        ['Wi-Fi', 'Kitchenette', 'Air conditioning', 'Parking'],
        'Cancellation allowed before the offer deadline.'
      ],
      [
        'Budget Lane Inn',
        98.0,
        4.0,
        2,
        'Economy Double',
        'Room only',
        false,
        '14:00',
        '11:00',
        '1 Double bed',
        '18 m²',
        ['Wi-Fi', 'Air conditioning'],
        'Non-refundable promotional rate.'
      ],
    ];
    var items = rows
        .where((r) => !refundableOnly || r[6] == true)
        .map((r) => {
              'offerId':
                  'local_offer_${r[0].toString().toLowerCase().replaceAll(' ', '_')}',
              'hotelId': 'hotel_${r[0].toString().hashCode.abs()}',
              'name': r[0],
              'address': destination,
              'price': r[1],
              'nightlyRoomRate': r[1],
              'roomQuantity': roomQuantity,
              'currency': 'MYR',
              'rating': r[2],
              'stars': r[3],
              'roomName': r[4],
              'boardName': r[5],
              'refundable': r[6],
              'checkInTime': r[7],
              'checkOutTime': r[8],
              'bedType': r[9],
              'roomSize': r[10],
              'amenities': r[11],
              'cancellationPolicy': r[12],
              'checkin': payload['checkin'],
              'checkout': payload['checkout'],
              'taxesAndFeesIncluded': true,
              'description':
                  '${r[0]} offers a practical stay in $destination with ${r[4].toString().toLowerCase()} accommodation and convenient access to nearby travel areas.',
              'houseRules': [
                'Valid identification may be required at check-in',
                'Check-in and check-out times apply',
                'Special requests are subject to availability'
              ],
            })
        .toList();
    if (roomQuantity > 1) {
      items = items
          .map((item) => {
                ...item,
                'price': _money(_num(item['price']) * roomQuantity),
              })
          .toList();
    }
    if (payload['sort'] == 'price_low') {
      items.sort((a, b) => _num(a['price']).compareTo(_num(b['price'])));
    } else if (payload['sort'] == 'rating') {
      items.sort((a, b) => _num(b['rating']).compareTo(_num(a['rating'])));
    }
    return {'ok': true, 'items': items, 'source': 'local'};
  }

  Future<dynamic> _prebook(Map<String, dynamic> payload) async {
    final offer = (payload['offerId'] ?? '').toString();
    if (offer.isEmpty) throw Exception('Offer ID is required.');
    return {
      'ok': true,
      'source': 'local',
      'result': {
        'prebookId': 'prebook_${DateTime.now().millisecondsSinceEpoch}',
        'offerId': offer,
        'status': 'prebooked',
      },
    };
  }

  Future<dynamic> _bookHotel(Map<String, dynamic> payload) async {
    final selected = Map<String, dynamic>.from(payload['selectedHotel'] ?? {});
    final id = 'booking_${DateTime.now().millisecondsSinceEpoch}';
    final booking = <String, dynamic>{
      'id': id,
      'bookingId': id,
      'bookingReference':
          'TM-${DateTime.now().millisecondsSinceEpoch.toString().substring(5)}',
      'bookingStatus': 'confirmed',
      'hotelName': selected['name'] ?? 'Hotel',
      'roomType': selected['roomName'] ?? '',
      'price': _num(payload['hotelCost'] ?? selected['price']),
      'roomQuantity': selected['roomQuantity'] ?? payload['roomQuantity'] ?? 1,
      'currency': selected['currency'] ?? 'MYR',
      'holder': payload['holder'] ?? {},
      'createdAt': _now(),
    };
    final bookings = await _readList('bookings');
    bookings.insert(0, booking);
    await _writeList('bookings', bookings);

    final itineraryId = (payload['itineraryId'] ?? '').toString();
    Map<String, dynamic>? budget;
    if (itineraryId.isNotEmpty) {
      final trip = await _tripById(itineraryId);
      if (trip != null) {
        trip['selectedHotel'] = selected;
        trip['hotelCost'] = booking['price'];
        await _replaceTrip(trip);
        budget = _calculateBudget(trip);
      }
    }
    return {
      'ok': true,
      'booking': booking,
      'budget': budget,
      'source': 'local'
    };
  }

  // ------------------------------------------------------------------
  // Payment, feedback, assistant
  // ------------------------------------------------------------------

  Future<dynamic> _recordPayment(Map<String, dynamic> payload) async {
    final amount = _num(payload['amount']);
    if (amount <= 0) throw Exception('Enter a positive amount.');
    final id = 'pay_${DateTime.now().millisecondsSinceEpoch}';
    final record = {
      'id': id,
      'bookingId': payload['bookingId'] ?? '',
      'amount': _money(amount),
      'currency': 'MYR',
      'paymentStatus': 'successful',
      'transactionReference':
          'TM-PAY-${DateTime.now().millisecondsSinceEpoch.toString().substring(6)}',
      'cardBrand': payload['cardBrand'] ?? 'Card',
      'cardLast4': payload['cardLast4'] ?? '',
      'cardholderName': payload['cardholderName'] ?? '',
      'billingEmail': payload['billingEmail'] ?? '',
      'createdAt': _now(),
    };
    final items = await _readList('payments');
    items.insert(0, record);
    await _writeList('payments', items);
    return {'ok': true, 'payment': record, 'source': 'local'};
  }

  Future<dynamic> _updatePaymentStatus(String id, String status) async {
    final items = await _readList('payments');
    final index = items.indexWhere((item) => item['id'].toString() == id);
    if (index < 0) throw Exception('Payment record not found.');
    items[index] = {
      ...Map<String, dynamic>.from(items[index] as Map),
      'paymentStatus': status,
      'updatedAt': _now(),
    };
    await _writeList('payments', items);
    return {'ok': true, 'payment': items[index], 'status': status};
  }

  Future<dynamic> _carRentalSearch(Map<String, dynamic> payload) async {
    final pickup =
        (payload['pickupLocation'] ?? 'George Town, Penang').toString();
    final pickupDate =
        DateTime.tryParse((payload['pickupDate'] ?? '').toString()) ??
            DateTime.now().add(const Duration(days: 14));
    final dropoffDate =
        DateTime.tryParse((payload['dropoffDate'] ?? '').toString()) ??
            pickupDate.add(const Duration(days: 2));
    final days = max(1, dropoffDate.difference(pickupDate).inDays + 1);
    final vehicleType =
        (payload['vehicleType'] ?? 'All').toString().toLowerCase();
    final rows = [
      ['Perodua Myvi Compact', 'Compact', 5, 2, 95.0],
      ['Toyota Vios Sedan', 'Sedan', 5, 3, 145.0],
      ['Toyota Innova MPV', 'MPV', 7, 4, 238.0],
    ];
    final items = rows
        .where((row) =>
            vehicleType == 'all' ||
            row[1].toString().toLowerCase() == vehicleType)
        .map((row) => {
              'rentalId': 'local_car_${row[1].toString().toLowerCase()}',
              'provider': 'TravelMate Mobility Partner',
              'vehicleName': row[0],
              'vehicleType': row[1],
              'seats': row[2],
              'bags': row[3],
              'dailyRate': row[4],
              'currency': 'MYR',
              'pickupLocation': pickup,
              'dropoffLocation': payload['dropoffLocation'] ?? pickup,
              'pickupDate': _date(pickupDate),
              'dropoffDate': _date(dropoffDate),
              'rentalDays': days,
              'totalPrice': _money(_num(row[4]) * days),
              'transmission': 'Automatic',
              'fuelPolicy': 'Full-to-full',
              'included': [
                'Basic insurance',
                'Unlimited mileage',
                'Roadside support',
              ],
              'sandbox': true,
            })
        .toList();
    return {'ok': true, 'items': items, 'source': 'local'};
  }

  Future<dynamic> _selectCarRental(Map<String, dynamic> payload) async {
    final id = (payload['itineraryId'] ?? '').toString();
    final rental = Map<String, dynamic>.from(payload['rental'] ?? {});
    final trip = await _tripById(id);
    if (trip == null) throw Exception('Itinerary not found.');
    trip['selectedCarRental'] = rental;
    trip['carRentalCost'] = _num(rental['totalPrice'] ?? rental['price']);
    trip['budgetEstimate'] = _calculateBudget(trip);
    trip['updatedAt'] = _now();
    await _replaceTrip(trip);
    return {
      'ok': true,
      'itinerary': trip,
      'budget': trip['budgetEstimate'],
      'selectedCarRental': rental,
    };
  }

  Future<dynamic> _createFeedback(Map<String, dynamic> payload) async {
    final id = 'feedback_${DateTime.now().millisecondsSinceEpoch}';
    final item = <String, dynamic>{
      ...payload,
      'id': id,
      'feedbackStatus': 'visible',
      'submittedAt': _now(),
    };
    final items = await _readList('feedback');
    items.insert(0, item);
    await _writeList('feedback', items);
    return {'ok': true, 'feedback': item};
  }

  Future<dynamic> _chatSessions() async {
    final sessions = await _readList('chat_sessions');
    sessions.sort((a, b) => (b['updatedAt'] ?? '')
        .toString()
        .compareTo((a['updatedAt'] ?? '').toString()));
    return {'ok': true, 'items': sessions};
  }

  Future<dynamic> _chatSessionById(String id) async {
    final sessions = await _readList('chat_sessions');
    Map<String, dynamic>? session;
    for (final item in sessions) {
      if (item['id'].toString() == id) {
        session = item;
        break;
      }
    }
    if (session == null) throw Exception('Chat session not found.');
    return {'ok': true, 'session': session};
  }

  Future<dynamic> _createChatSession(Map<String, dynamic> payload) async {
    final sessions = await _readList('chat_sessions');
    final id = 'session_${DateTime.now().millisecondsSinceEpoch}';
    final session = <String, dynamic>{
      'id': id,
      'title': (payload['title'] ?? 'New travel chat').toString(),
      'messages': <Map<String, dynamic>>[],
      'createdAt': _now(),
      'updatedAt': _now(),
    };
    sessions.insert(0, session);
    await _writeList('chat_sessions', sessions);
    return {'ok': true, 'session': session};
  }

  Future<dynamic> _chat(Map<String, dynamic> payload) async {
    final message = (payload['message'] ?? '').toString().trim();
    if (message.isEmpty) throw Exception('Enter a travel question.');

    var sessionId = (payload['sessionId'] ?? '').toString();
    var sessions = await _readList('chat_sessions');
    Map<String, dynamic>? session;
    if (sessionId.isNotEmpty) {
      for (final s in sessions) {
        if (s['id'].toString() == sessionId) {
          session = s;
          break;
        }
      }
    }
    if (session == null) {
      final created = await _createChatSession({'title': _chatTitle(message)});
      session = Map<String, dynamic>.from(created['session'] as Map);
      sessionId = session['id'].toString();
      sessions = await _readList('chat_sessions');
    }

    final prefs = await _readMap('preferences') ?? {};
    final trips = await _readList('itineraries');
    final latest = trips.isEmpty ? <String, dynamic>{} : trips.first;
    final existingPlanning = session['planningState'] is Map
        ? Map<String, dynamic>.from(session['planningState'] as Map)
        : <String, dynamic>{};

    Map<String, dynamic>? plan;
    List<Map<String, dynamic>> placeSuggestions = [];
    String reply;

    final planningIntent =
        _hasPlanningIntent(message) || existingPlanning.isNotEmpty;
    if (planningIntent) {
      final planning =
          _advancePlanningConversation(message, prefs, existingPlanning);
      final state = Map<String, dynamic>.from(planning['state'] as Map);
      session['planningState'] = state;
      if (planning['ready'] == true) {
        plan = _buildPlanFromPlanningState(state, prefs);
        reply = _tripPlanReply(plan, prefs);
        session['planningState'] = <String, dynamic>{};
      } else {
        reply = (planning['reply'] ?? '').toString();
      }
    } else if (_looksLikePlaceSearch(message)) {
      final inferred = _inferLocationFromQuery(_normaliseSearch(message));
      final data = await _searchDestinations({
        'q': message,
        'location': inferred.isEmpty ? 'Malaysia' : inferred,
      });
      placeSuggestions = (data['results'] as List? ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .take(6)
          .toList();
      if (placeSuggestions.isEmpty) {
        reply =
            'I could not find a strong match yet. Try adding the city and what you want, for example “curry mee in Penang” or “culture attractions in Kuala Lumpur”.';
      } else {
        final city = inferred.isEmpty ? 'that area' : inferred.split(',').first;
        final names = placeSuggestions
            .map((e) => '• ${e['title'] ?? e['name']}')
            .join('\n');
        reply =
            'Here are several matches around $city:\n$names\n\nOpen a place card below for details, or add it to one of your Trips.';
      }
    } else {
      reply = _assistantReply(message, prefs, latest);
    }

    final item = <String, dynamic>{
      'id': 'chat_${DateTime.now().microsecondsSinceEpoch}',
      'message': message,
      'reply': reply,
      'source': 'travelmate',
      'createdAt': _now(),
      if (plan != null) 'tripPlan': plan,
      if (placeSuggestions.isNotEmpty) 'placeSuggestions': placeSuggestions,
    };

    final messageList = (session['messages'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    messageList.add(item);
    session['messages'] = messageList;
    session['updatedAt'] = _now();
    if ((session['title'] ?? '').toString() == 'New travel chat') {
      session['title'] = _chatTitle(message);
    }

    final sessionIndex =
        sessions.indexWhere((e) => e['id'].toString() == sessionId);
    if (sessionIndex >= 0) {
      sessions[sessionIndex] = session;
    } else {
      sessions.insert(0, session);
    }
    await _writeList('chat_sessions', sessions);

    final history = await _readList('chat_history');
    history.add({...item, 'sessionId': sessionId});
    await _writeList('chat_history', history);

    return {
      'ok': true,
      'item': item,
      'reply': reply,
      'source': 'travelmate',
      'session': session,
      'sessionId': sessionId,
    };
  }

  bool _hasPlanningIntent(String message) {
    final q = _normaliseSearch(message);
    return q.contains('plan') ||
        q.contains('itinerary') ||
        q.contains('trip') ||
        q.contains('travel schedule') ||
        q.contains('travel route');
  }

  bool _looksLikePlaceSearch(String message) {
    final q = _normaliseSearch(message);
    const words = [
      'attraction',
      'attractions',
      'place',
      'places',
      'food',
      'restaurant',
      'cafe',
      'curry mee',
      'laksa',
      'museum',
      'temple',
      'park',
      'shopping',
      'things to do',
      'where to go',
      'where can i',
    ];
    return words.any((x) => q.contains(x));
  }

  Map<String, dynamic> _advancePlanningConversation(
    String message,
    Map<String, dynamic> prefs,
    Map<String, dynamic> existing,
  ) {
    final q = _normaliseSearch(message);
    final state = <String, dynamic>{...existing};

    final inferred = _inferLocationFromQuery(q);
    if (inferred.isNotEmpty) state['destination'] = inferred.split(',').first;

    final dayMatch = RegExp(r'(\d+)\s*[- ]?day').firstMatch(q) ??
        RegExp(r'for\s+(\d+)\s+days').firstMatch(q);
    if (dayMatch != null) {
      state['days'] =
          (int.tryParse(dayMatch.group(1) ?? '') ?? 3).clamp(1, 10).toInt();
    }

    final budgetMatch =
        RegExp(r'(?:rm|myr)\s*([0-9]+(?:\.[0-9]+)?)').firstMatch(q) ??
            RegExp(r'budget\s*(?:is|of|around|about)?\s*([0-9]+(?:\.[0-9]+)?)')
                .firstMatch(q);
    if (budgetMatch != null) {
      state['budget'] = double.tryParse(budgetMatch.group(1) ?? '');
    }

    const interestWords = <String, String>{
      'food': 'Food',
      'curry mee': 'Food',
      'laksa': 'Food',
      'culture': 'Culture',
      'heritage': 'Heritage',
      'history': 'History',
      'nature': 'Nature',
      'hiking': 'Adventure',
      'adventure': 'Adventure',
      'shopping': 'Shopping',
      'photo': 'Photography',
      'photography': 'Photography',
      'museum': 'History',
      'nightlife': 'Nightlife',
      'beach': 'Nature',
      'family': 'Family',
      'architecture': 'Architecture',
    };
    final requestedInterests = <String>{};
    for (final entry in interestWords.entries) {
      if (q.contains(entry.key)) requestedInterests.add(entry.value);
    }
    if (requestedInterests.isNotEmpty)
      state['interests'] = requestedInterests.toList();

    if (q.contains('relaxed') || q.contains('slow pace'))
      state['pace'] = 'Relaxed';
    if (q.contains('packed') || q.contains('many places') || q.contains('busy'))
      state['pace'] = 'Packed';
    if (q.contains('moderate') || q.contains('balanced pace'))
      state['pace'] = 'Moderate';

    if (q.contains('family') || q.contains('kids') || q.contains('children'))
      state['companions'] = 'Family';
    if (q.contains('couple') || q.contains('partner'))
      state['companions'] = 'Couple';
    if (q.contains('solo') || q.contains('alone')) state['companions'] = 'Solo';
    if (q.contains('friends')) state['companions'] = 'Friends';

    final missing = <String>[];
    if ((state['destination'] ?? '').toString().trim().isEmpty)
      missing.add('destination');
    if (state['days'] == null) missing.add('days');
    if ((state['interests'] as List? ?? []).isEmpty) missing.add('interests');
    if (state['budget'] == null) missing.add('budget');

    if (missing.isEmpty) {
      state['pace'] ??= prefs['travelPace'] ?? 'Moderate';
      state['companions'] ??= 'Traveller';
      return {'ready': true, 'state': state, 'reply': ''};
    }

    final knownDestination = (state['destination'] ?? '').toString();
    final intro = knownDestination.isEmpty
        ? 'I can build this with you instead of giving a fixed itinerary.'
        : 'I’ll plan for $knownDestination. I need a little more detail so the route matches you.';
    final questions = <String>[];
    if (missing.contains('destination'))
      questions.add('Which city or destination are you travelling to?');
    if (missing.contains('days'))
      questions.add('How many days will the trip be?');
    if (missing.contains('interests')) {
      final saved = (prefs['interests'] as List? ?? []).join(', ');
      questions.add(saved.isEmpty
          ? 'What do you want most: food, culture, nature, shopping, history, nightlife or something else?'
          : 'What should I focus on for this trip? Your saved interests are $saved, but you can choose something different.');
    }
    if (missing.contains('budget'))
      questions.add('What is your approximate budget in RM?');

    return {
      'ready': false,
      'state': state,
      'reply':
          '$intro\n\n${questions.map((q) => '• $q').join('\n')}\n\nYou can answer everything in one message, for example: “3 days, food and culture, RM1200, relaxed pace”.',
    };
  }

  String _chatTitle(String message) {
    final clean = message.trim().replaceAll(RegExp(r'\s+'), ' ');
    if (clean.length <= 34) return clean;
    return '${clean.substring(0, 34)}…';
  }

  Map<String, dynamic> _buildPlanFromPlanningState(
    Map<String, dynamic> state,
    Map<String, dynamic> prefs,
  ) {
    final days = (int.tryParse('${state['days']}') ?? 3).clamp(1, 10).toInt();
    final destination = (state['destination'] ?? 'Penang').toString();
    final requested = (state['interests'] as List? ?? [])
        .map((e) => _normaliseSearch(e.toString()))
        .where((e) => e.isNotEmpty)
        .toSet();
    final saved = (prefs['interests'] as List? ?? [])
        .map((e) => _normaliseSearch(e.toString()))
        .toSet();
    final targetInterests = requested.isEmpty ? saved : requested;
    final destinationToken = _normaliseSearch(destination).split(' ').first;

    final candidates = _destinations
        .where((d) {
          final addr = _normaliseSearch((d['address'] ?? '').toString());
          if (destination.toLowerCase().contains('kuala lumpur')) {
            return addr.contains('kuala lumpur') ||
                addr.contains('gombak') ||
                addr.contains('selangor');
          }
          if (destination.toLowerCase().contains('penang'))
            return addr.contains('penang');
          if (destination.toLowerCase().contains('langkawi'))
            return addr.contains('langkawi');
          return addr.contains(destinationToken);
        })
        .map((e) => Map<String, dynamic>.from(e))
        .toList();

    int rank(Map<String, dynamic> x) {
      final ints = (x['interests'] as List? ?? [])
          .map((e) => _normaliseSearch(e.toString()))
          .toSet();
      final keywords = (x['keywords'] as List? ?? [])
          .map((e) => _normaliseSearch(e.toString()))
          .join(' ');
      var score = ints.intersection(targetInterests).length * 120;
      for (final interest in targetInterests) {
        if (keywords.contains(interest)) score += 35;
      }
      score += _num(x['popularity']).round();
      return score;
    }

    candidates.sort((a, b) => rank(b).compareTo(rank(a)));

    final requiredCount = min(days * 3, candidates.length);
    final selected = <Map<String, dynamic>>[];
    final categoryCounts = <String, int>{};
    for (final item in candidates) {
      final cat =
          _normaliseSearch((item['category'] ?? item['type'] ?? '').toString());
      final count = categoryCounts[cat] ?? 0;
      if (count >= max(2, days)) continue;
      selected.add(item);
      categoryCounts[cat] = count + 1;
      if (selected.length >= requiredCount) break;
    }
    for (final item in candidates) {
      if (selected.length >= requiredCount) break;
      if (!selected.any((e) => e['destinationId'] == item['destinationId']))
        selected.add(item);
    }

    final activities = <Map<String, dynamic>>[];
    const slots = ['09:00', '13:30', '17:30'];
    for (var i = 0; i < selected.length; i++) {
      final d = selected[i];
      activities.add({
        'activityName': d['title'],
        'destinationId': d['destinationId'],
        'address': d['address'] ?? '',
        'dayNo': (i ~/ 3) + 1,
        'timeSlot': slots[i % 3],
        'estimatedCost': d['estimatedCost'] ?? 0,
        'category': d['category'] ?? d['type'] ?? '',
        'indoor': d['indoor'] ?? false,
        'openingHours': d['openingHours'] ?? '',
      });
    }

    final budget = _num(state['budget']) > 0
        ? _num(state['budget'])
        : (prefs['budgetRange']?.toString().toLowerCase() == 'budget'
            ? 700.0
            : prefs['budgetRange']?.toString().toLowerCase() == 'premium'
                ? 2200.0
                : 1300.0);
    final start = DateTime.now().add(const Duration(days: 14));
    final end = start.add(Duration(days: days - 1));
    return {
      'title': '$days-Day $destination Trip',
      'destinationArea': destination,
      'startDate': _date(start),
      'endDate': _date(end),
      'travellerCount': 1,
      'budgetLimit': _money(budget),
      'activities': activities,
      'requestedInterests': targetInterests.map(_titleCase).toList(),
      'pace': state['pace'] ?? prefs['travelPace'] ?? 'Moderate',
      'companions': state['companions'] ?? 'Traveller',
      'status': 'generated',
    };
  }

  String _tripPlanReply(Map<String, dynamic> plan, Map<String, dynamic> prefs) {
    final activities = (plan['activities'] as List? ?? []);
    final grouped = <int, List<String>>{};
    for (final raw in activities) {
      final a = Map<String, dynamic>.from(raw as Map);
      final day = int.tryParse('${a['dayNo']}') ?? 1;
      grouped
          .putIfAbsent(day, () => [])
          .add('${a['timeSlot']} ${a['activityName']}');
    }
    final focus = (plan['requestedInterests'] as List? ?? []).join(', ');
    final lines = <String>[
      'Here is a personalised ${plan['title']}.',
      if (focus.isNotEmpty) 'Focus: $focus.',
      'Pace: ${plan['pace'] ?? 'Moderate'} • Budget: RM ${plan['budgetLimit']}.',
      '',
    ];
    for (final entry in grouped.entries) {
      lines.add('Day ${entry.key}: ${entry.value.join(' • ')}');
    }
    if (grouped.isEmpty) {
      lines.add(
          'I found the destination, but I need more place data before I can build a useful day-by-day route. Try searching Explore for the destination and save a few places first.');
    } else {
      lines.add('');
      lines.add(
          'You can save this plan to Trips, then search for more places, add them, remove them, or drag them into a different sequence.');
    }
    return lines.join('\n');
  }

  Future<dynamic> _saveChatPlan(Map<String, dynamic> payload) async {
    final raw = payload['plan'];
    if (raw is! Map) throw Exception('No trip plan is available to save.');
    final plan = Map<String, dynamic>.from(raw);
    return _createTrip(plan);
  }

  String _assistantReply(
      String message, Map<String, dynamic> prefs, Map<String, dynamic> trip) {
    final q = message.toLowerCase();
    final interests = (prefs['interests'] as List? ?? []).join(', ');
    final budget = prefs['budgetRange'] ?? 'Moderate';
    final destination = trip['destinationArea'] ?? 'your selected destination';
    final tripBudget = _calculateBudget(trip);

    if (q.contains('rain') || q.contains('weather')) {
      return 'For rainy periods, prioritise indoor attractions such as museums, heritage houses, shopping areas and food stops. If you already have a trip in Trips, regenerate the itinerary after checking the forecast so weather-sensitive activities can be moved.';
    }
    if (q.contains('budget') || q.contains('cheap') || q.contains('save')) {
      return 'Your travel profile uses a $budget budget preference. For $destination, compare lower-priced rooms and flights first, group nearby activities on the same day, use public transport where practical and replace one higher-cost attraction if the itinerary exceeds the limit. Current estimated total: RM ${tripBudget['total'] ?? 0}.';
    }
    if (q.contains('flight')) {
      return 'Open Flights, search your route and date, then open a flight to see fare, baggage, terminal, aircraft, duration and conditions. Compare at least two options before attaching one to an itinerary so its cost is included in the trip budget.';
    }
    if (q.contains('hotel')) {
      return 'Open Hotels, search by destination and dates, then open a hotel offer to review room type, amenities, check-in time, cancellation conditions, board option and price. You can then continue to the booking flow and attach the cost to your itinerary.';
    }
    if (q.contains('food') || q.contains('eat')) {
      return 'For a food-focused plan, combine a morning heritage area, a lunch hawker stop and an evening food district. Your saved interests currently include ${interests.isEmpty ? 'general travel interests' : interests}, so TravelMate will rank matching food-related places higher.';
    }
    return 'I can help you create and save a trip plan, compare destinations, explain your recommendation matches, arrange itinerary days, review weather, compare flights and hotels, and control your travel budget. Ask me something specific, or say “Plan a 3-day Penang trip”.';
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  double _num(dynamic value) => double.tryParse((value ?? 0).toString()) ?? 0;
  double _money(dynamic value) => double.parse(_num(value).toStringAsFixed(2));
  double _distanceKm(double lat1, double lon1, double lat2, double lon2) {
    const radius = 6371.0;
    final dLat = (lat2 - lat1) * pi / 180;
    final dLon = (lon2 - lon1) * pi / 180;
    final a = sin(dLat / 2) * sin(dLat / 2) +
        cos(lat1 * pi / 180) *
            cos(lat2 * pi / 180) *
            sin(dLon / 2) *
            sin(dLon / 2);
    return radius * 2 * atan2(sqrt(a), sqrt(max(0, 1 - a)));
  }

  String _now() => DateTime.now().toIso8601String();
  String _date(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  String _titleCase(String value) =>
      value.isEmpty ? value : '${value[0].toUpperCase()}${value.substring(1)}';
}
