import 'dart:convert';

import 'package:http/http.dart' as http;

/// Resolves a relevant, unique image for a destination/place without requiring
/// the TravelMate Flask backend.
///
/// Resolution order:
/// 1. Use an image URL already supplied by the place provider.
/// 2. Search English Wikipedia for the exact place/dish and use its lead image.
/// 3. Search Wikimedia Commons for an image related to the exact place.
/// 4. Return null and let the UI render a category-specific fallback.
///
/// A per-place cache plus a session-wide assigned-URL set prevents different
/// place cards from reusing the same resolved image whenever alternatives are
/// available.
class PlaceImageService {
  static final Map<String, String?> _resolvedByPlace = <String, String?>{};
  static final Map<String, Future<String?>> _pendingByPlace =
      <String, Future<String?>>{};
  static final Map<String, String> _ownerByImageUrl = <String, String>{};
  static final Map<String, Set<String>> _failedUrlsByPlace =
      <String, Set<String>>{};
  static final Map<String, int> _sameUrlRetryCount = <String, int>{};

  static const Map<String, String> _wikipediaTitleHints = <String, String>{
    'george town unesco heritage area': 'George Town, Penang',
    'george town heritage core': 'George Town, Penang',
    'george town food trail': 'Penang cuisine',
    'penang road chendul area': 'Cendol',
    'air itam curry mee area': 'Curry mee',
    'george town white curry mee spots': 'Curry mee',
    'air itam asam laksa area': 'Asam laksa',
    'new lane hawker centre': 'New Lane, George Town',
    'gurney drive hawker & seafront': 'Gurney Drive',
    'petronas twin towers / klcc': 'Petronas Towers',
    'petronas twin towers': 'Petronas Towers',
    'petronas twin towers & klcc': 'Petronas Towers',
    'klcc': 'Petronas Towers',
    'river of life / masjid jamek': 'Jamek Mosque',
    'kuala lumpur tower': 'Kuala Lumpur Tower',
    'kl tower': 'Kuala Lumpur Tower',
    'penang botanic gardens': 'Penang Botanic Gardens',
    'penang hill': 'Penang Hill',
    'kek lok si temple': 'Kek Lok Si',
    'kek lok si': 'Kek Lok Si',
    'pinang peranakan mansion': 'Pinang Peranakan Mansion',
    'wonderfood museum': 'Wonderfood Museum Penang',
    'batu ferringhi beach': 'Batu Ferringhi',
    'batu ferringhi': 'Batu Ferringhi',
    'esplanade & fort cornwallis area': 'Fort Cornwallis',
    'fort cornwallis': 'Fort Cornwallis',
    'chew jetty': 'Clan Jetties',
    'gurney plaza': 'Gurney Plaza',
    'escape penang': 'Escape (theme park)',
    'batu caves temple': 'Batu Caves',
    'batu caves': 'Batu Caves',
    'merdeka square & sultan abdul samad building':
        'Merdeka Square, Kuala Lumpur',
    'merdeka square': 'Merdeka Square, Kuala Lumpur',
    'sultan abdul samad building': 'Sultan Abdul Samad Building',
    'bukit bintang & jalan alor food street': 'Bukit Bintang',
    'bukit bintang': 'Bukit Bintang',
    'jalan alor': 'Jalan Alor',
    'thean hou temple': 'Thean Hou Temple',
    'perdana botanical garden & national museum': 'Perdana Botanical Gardens',
    'perdana botanical gardens': 'Perdana Botanical Gardens',
    'national museum': 'National Museum (Malaysia)',
    "a famosa & st. paul's hill": 'A Famosa',
    'a famosa': 'A Famosa',
    "st. paul's church": "St. Paul's Church, Malacca",
    'jonker street heritage walk': 'Jonker Walk',
    'jonker street': 'Jonker Walk',
    'the stadthuys & red square': 'Stadthuys',
    'stadthuys': 'Stadthuys',
    'melaka river cruise': 'Malacca River',
    'melaka river': 'Malacca River',
    'baba & nyonya heritage museum': 'Baba Nyonya Heritage Museum',
    'langkawi skycab & sky bridge': 'Langkawi Cable Car',
    'langkawi skycab': 'Langkawi Cable Car',
    'langkawi sky bridge': 'Langkawi Sky Bridge',
    'kilim karst geoforest park': 'Kilim Karst Geoforest Park',
    'pantai cenang beach': 'Pantai Cenang',
    'pantai cenang': 'Pantai Cenang',
    'underwater world langkawi': 'Underwater World Langkawi',
    'kinabalu national park': 'Kinabalu Park',
    'kinabalu park': 'Kinabalu Park',
    'sepilok orangutan rehabilitation centre':
        'Sepilok Orangutan Rehabilitation Centre',
    'tunku abdul rahman marine park': 'Tunku Abdul Rahman National Park',
    'tunku abdul rahman park': 'Tunku Abdul Rahman National Park',
    'kota kinabalu city mosque & waterfront': 'Kota Kinabalu City Mosque',
    'kota kinabalu city mosque': 'Kota Kinabalu City Mosque',
    'sarawak cultural village': 'Sarawak Cultural Village',
    'bako national park': 'Bako National Park',
    'kuching waterfront & borneo cultures museum': 'Borneo Cultures Museum',
    'kuching waterfront': 'Kuching Waterfront',
    'borneo cultures museum': 'Borneo Cultures Museum',
    'semenggoh wildlife centre': 'Semenggoh Nature Reserve',
  };

  static String _placeKey(Map<String, dynamic> place) {
    final title =
        (place['title'] ?? place['name'] ?? place['activityName'] ?? 'place')
            .toString()
            .trim();
    final canonicalTitle = _wikipediaTitleHints[title.toLowerCase()];
    if (canonicalTitle != null) {
      return 'known:${canonicalTitle.toLowerCase()}';
    }
    final id = (place['destinationId'] ??
            place['placeId'] ??
            place['place_id'] ??
            place['data_id'] ??
            place['data_cid'] ??
            place['id'] ??
            '')
        .toString()
        .trim();
    if (id.isNotEmpty) return id.toLowerCase();
    final address =
        (place['address'] ?? place['location'] ?? '').toString().trim();
    return '${title.toLowerCase()}|${address.toLowerCase()}';
  }

  static List<String> _explicitImageUrls(Map<String, dynamic> place) {
    final urls = <String>[];

    void add(dynamic raw) {
      if (raw is List) {
        for (final item in raw) {
          add(item);
        }
        return;
      }
      if (raw is Map) {
        add(raw['thumbnail']);
        add(raw['image']);
        add(raw['link']);
        add(raw['url']);
        add(raw['source']);
        return;
      }
      final value = (raw ?? '').toString().trim();
      if ((value.startsWith('https://') || value.startsWith('http://')) &&
          !urls.contains(value)) {
        urls.add(value);
      }
    }

    add(place['thumbnail']);
    add(place['image']);
    add(place['imageUrl']);
    add(place['mainPhoto']);
    add(place['main_photo']);
    add(place['photo']);
    add(place['heroImage']);
    add(place['galleryImages']);
    add(place['photos']);
    add(place['images']);
    return urls;
  }

  static bool _claimImage(String key, String url) {
    final normalized = url.trim();
    if (normalized.isEmpty) return false;
    final owner = _ownerByImageUrl[normalized];
    if (owner != null && owner != key) return false;
    _ownerByImageUrl[normalized] = key;
    return true;
  }

  static Future<String?> resolve(Map<String, dynamic> place) {
    final key = _placeKey(place);
    if (_resolvedByPlace.containsKey(key)) {
      return Future<String?>.value(_resolvedByPlace[key]);
    }
    final existing = _pendingByPlace[key];
    if (existing != null) return existing;

    final pending = _resolveInternal(key, place).then((value) {
      if (value != null) _resolvedByPlace[key] = value;
      _pendingByPlace.remove(key);
      return value;
    }).catchError((_) {
      _pendingByPlace.remove(key);
      return null;
    });

    _pendingByPlace[key] = pending;
    return pending;
  }

  /// Clears a failed resolution and retries it. With several provider images,
  /// a failed URL is skipped immediately. A sole image gets one same-URL retry
  /// for transient network failures before fallback resolution is attempted.
  static Future<String?> retry(
    Map<String, dynamic> place, {
    String? failedUrl,
  }) {
    final key = _placeKey(place);
    final rejected = failedUrl?.trim();
    if (rejected != null && rejected.isNotEmpty) {
      final explicitUrls = _explicitImageUrls(place);
      final retryKey = '$key|$rejected';
      final shouldRetrySameUrl =
          explicitUrls.length <= 1 && (_sameUrlRetryCount[retryKey] ?? 0) == 0;
      if (shouldRetrySameUrl) {
        _sameUrlRetryCount[retryKey] = 1;
      } else {
        _failedUrlsByPlace.putIfAbsent(key, () => <String>{}).add(rejected);
        if (_ownerByImageUrl[rejected] == key) {
          _ownerByImageUrl.remove(rejected);
        }
      }
    }
    _resolvedByPlace.remove(key);
    _pendingByPlace.remove(key);
    return resolve(place);
  }

  static List<String> explicitImageUrlsForTesting(
    Map<String, dynamic> place,
  ) =>
      List<String>.unmodifiable(_explicitImageUrls(place));

  static bool searchIdentityMatchesForTesting(
    String query,
    String candidateTitle,
  ) =>
      _matchesSearchIdentity(query, candidateTitle);

  static List<String> wikipediaSummaryImagesForTesting(
    String articleTitle,
    Object? decoded,
  ) =>
      List<String>.unmodifiable(
        _wikipediaSummaryImageUrls(articleTitle, decoded),
      );

  static Future<String?> _resolveInternal(
    String key,
    Map<String, dynamic> place,
  ) async {
    final failedUrls = _failedUrlsByPlace[key] ?? const <String>{};
    for (final url in _explicitImageUrls(place)) {
      if (failedUrls.contains(url)) continue;
      if (_claimImage(key, url)) return url;
    }

    final title =
        (place['title'] ?? place['name'] ?? place['activityName'] ?? '')
            .toString()
            .trim();
    final address =
        (place['address'] ?? place['location'] ?? '').toString().trim();
    final category =
        (place['category'] ?? place['type'] ?? '').toString().trim();

    if (title.isEmpty) return null;

    final lowerTitle = title.toLowerCase();
    final hintedTitle = _wikipediaTitleHints[lowerTitle];

    final queries = <String>[];
    void addQuery(String value) {
      final q = value.trim();
      if (q.isNotEmpty && !queries.contains(q)) queries.add(q);
    }

    if (hintedTitle != null) addQuery(hintedTitle);
    addQuery(title);

    final locationContext = _shortLocation(address);
    if (locationContext.isNotEmpty) addQuery('$title $locationContext');
    if (category.isNotEmpty && locationContext.isNotEmpty) {
      addQuery('$title $category $locationContext');
    }

    if (hintedTitle != null) {
      for (final candidate in await _wikipediaSummaryImages(hintedTitle)) {
        if (failedUrls.contains(candidate)) continue;
        if (_claimImage(key, candidate)) return candidate;
      }
    }

    for (final query in queries) {
      final candidates = await _searchWikipedia(query);
      for (final candidate in candidates) {
        if (failedUrls.contains(candidate)) continue;
        if (_claimImage(key, candidate)) return candidate;
      }
    }

    for (final query in queries.reversed) {
      final candidates = await _searchCommons(query);
      for (final candidate in candidates) {
        if (failedUrls.contains(candidate)) continue;
        if (_claimImage(key, candidate)) return candidate;
      }
    }

    return null;
  }

  static Future<List<String>> _wikipediaSummaryImages(
      String articleTitle) async {
    try {
      final uri = Uri(
        scheme: 'https',
        host: 'en.wikipedia.org',
        pathSegments: <String>[
          'api',
          'rest_v1',
          'page',
          'summary',
          articleTitle,
        ],
      );
      final response = await http.get(
        uri,
        headers: const {
          'User-Agent': 'TravelMate-FYP/1.0 (student travel planning app)',
          'Accept': 'application/json',
        },
      ).timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return const [];
      final decoded = jsonDecode(response.body);
      return _wikipediaSummaryImageUrls(articleTitle, decoded);
    } catch (_) {
      return const [];
    }
  }

  static List<String> _wikipediaSummaryImageUrls(
    String articleTitle,
    Object? decoded,
  ) {
    if (decoded is! Map) return const [];
    final returnedTitle = (decoded['title'] ?? '').toString();
    if (!_matchesSearchIdentity(articleTitle, returnedTitle)) return const [];
    final urls = <String>[];
    for (final field in const ['originalimage', 'thumbnail']) {
      final image = decoded[field];
      if (image is! Map) continue;
      final source = (image['source'] ?? '').toString().trim();
      if (source.startsWith('http') && !urls.contains(source)) {
        urls.add(source);
      }
    }
    return urls;
  }

  static String _shortLocation(String address) {
    if (address.trim().isEmpty) return '';
    final parts = address
        .split(',')
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();
    if (parts.isEmpty) return '';
    if (parts.length == 1) return parts.first;
    return parts.take(2).join(', ');
  }

  static Future<List<String>> _searchWikipedia(String query) async {
    try {
      final uri = Uri.https('en.wikipedia.org', '/w/api.php', <String, String>{
        'action': 'query',
        'generator': 'search',
        'gsrsearch': query,
        'gsrnamespace': '0',
        'gsrlimit': '8',
        'prop': 'pageimages|pageterms',
        'piprop': 'thumbnail',
        'pithumbsize': '1200',
        'pilimit': '8',
        'format': 'json',
        'formatversion': '2',
        'redirects': '1',
      });
      final response = await http.get(
        uri,
        headers: const {
          'User-Agent': 'TravelMate-FYP/1.0 (student travel planning app)',
          'Accept': 'application/json',
        },
      ).timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return const [];
      final decoded = jsonDecode(response.body);
      if (decoded is! Map) return const [];
      final queryData = decoded['query'];
      if (queryData is! Map) return const [];
      final pages = queryData['pages'];
      if (pages is! List) return const [];

      final urls = <String>[];
      for (final raw in pages) {
        if (raw is! Map) continue;
        final pageTitle = (raw['title'] ?? '').toString().toLowerCase();
        if (_looksLikeNonPhoto(pageTitle)) continue;
        if (!_matchesSearchIdentity(query, pageTitle)) continue;
        final thumb = raw['thumbnail'];
        if (thumb is Map) {
          final source = (thumb['source'] ?? '').toString().trim();
          if (source.startsWith('http') && !urls.contains(source)) {
            urls.add(source);
          }
        }
      }
      return urls;
    } catch (_) {
      return const [];
    }
  }

  static Future<List<String>> _searchCommons(String query) async {
    try {
      final uri = Uri.https(
        'commons.wikimedia.org',
        '/w/api.php',
        <String, String>{
          'action': 'query',
          'generator': 'search',
          'gsrsearch': query,
          'gsrnamespace': '6',
          'gsrlimit': '12',
          'prop': 'imageinfo',
          'iiprop': 'url|mime',
          'iiurlwidth': '1200',
          'format': 'json',
          'formatversion': '2',
        },
      );
      final response = await http.get(
        uri,
        headers: const {
          'User-Agent': 'TravelMate-FYP/1.0 (student travel planning app)',
          'Accept': 'application/json',
        },
      ).timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return const [];
      final decoded = jsonDecode(response.body);
      if (decoded is! Map) return const [];
      final queryData = decoded['query'];
      if (queryData is! Map) return const [];
      final pages = queryData['pages'];
      if (pages is! List) return const [];

      final urls = <String>[];
      for (final raw in pages) {
        if (raw is! Map) continue;
        final pageTitle = (raw['title'] ?? '').toString().toLowerCase();
        if (_looksLikeNonPhoto(pageTitle)) continue;
        if (!_matchesSearchIdentity(query, pageTitle)) continue;
        final infos = raw['imageinfo'];
        if (infos is! List || infos.isEmpty || infos.first is! Map) continue;
        final info = infos.first as Map;
        final mime = (info['mime'] ?? '').toString().toLowerCase();
        if (!mime.startsWith('image/')) continue;
        final url = (info['thumburl'] ?? info['url'] ?? '').toString().trim();
        if (url.startsWith('http') && !urls.contains(url)) urls.add(url);
      }
      return urls;
    } catch (_) {
      return const [];
    }
  }

  static bool _looksLikeNonPhoto(String title) {
    final bad = <String>[
      'logo',
      'icon',
      'flag',
      'map of',
      'location map',
      'coat of arms',
      'diagram',
      'route map',
      'wordmark',
    ];
    return bad.any(title.contains);
  }

  static bool _matchesSearchIdentity(String query, String candidateTitle) {
    const ignored = <String>{
      'area',
      'attraction',
      'centre',
      'center',
      'malaysia',
      'place',
      'restaurant',
      'tourist',
      'file',
      'jpg',
      'jpeg',
      'png',
    };
    Set<String> tokens(String value) => RegExp(r'[a-z0-9]+')
        .allMatches(value.toLowerCase())
        .map((match) => match.group(0)!)
        .where((token) => token.length > 2 && !ignored.contains(token))
        .toSet();

    final actual = tokens(candidateTitle.replaceFirst('file:', ''));
    if (actual.isEmpty) return false;

    // Check full query
    final expectedFull = tokens(query);
    if (expectedFull.isNotEmpty) {
      if (expectedFull.every(actual.contains)) return true;
      if (actual.length >= 2 && actual.every(expectedFull.contains)) return true;
      if (expectedFull.intersection(actual).length >= 2) return true;
    }

    // Support composite queries separated by '&', 'and', '/', or '+'
    final parts =
        query.split(RegExp(r'\s*(?:&|and|\/|\+)\s*', caseSensitive: false));
    if (parts.length > 1) {
      for (final part in parts) {
        final expectedPart = tokens(part);
        if (expectedPart.isEmpty) continue;
        if (expectedPart.every(actual.contains)) return true;
        if (actual.length >= 2 && actual.every(expectedPart.contains)) {
          return true;
        }
        if (expectedPart.intersection(actual).length >= 2) return true;
      }
    }

    return false;
  }
}
