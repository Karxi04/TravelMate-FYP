class MalaysianLocality {
  static const Map<String, List<String>> _stateAliases = {
    'Johor': ['johor'],
    'Kedah': ['kedah'],
    'Kelantan': ['kelantan'],
    'Melaka': ['melaka', 'malacca'],
    'Negeri Sembilan': ['negeri sembilan'],
    'Pahang': ['pahang'],
    'Penang': ['penang', 'pulau pinang'],
    'Perak': ['perak'],
    'Perlis': ['perlis'],
    'Sabah': ['sabah'],
    'Sarawak': ['sarawak'],
    'Selangor': ['selangor'],
    'Terengganu': ['terengganu', 'trengganu'],
    'Kuala Lumpur': ['kuala lumpur', 'wilayah persekutuan kuala lumpur'],
    'Putrajaya': ['putrajaya', 'wilayah persekutuan putrajaya'],
    'Labuan': ['labuan', 'wilayah persekutuan labuan'],
  };

  static const Map<String, Map<String, Object>> _localities = {
    'George Town': {
      'state': 'Penang',
      'aliases': ['george town', 'georgetown']
    },
    'Air Itam': {
      'state': 'Penang',
      'aliases': ['air itam', 'ayer itam']
    },
    'Bayan Lepas': {
      'state': 'Penang',
      'aliases': ['bayan lepas']
    },
    'Batu Ferringhi': {
      'state': 'Penang',
      'aliases': ['batu ferringhi', 'batu ferenggi']
    },
    'Tanjung Bungah': {
      'state': 'Penang',
      'aliases': ['tanjung bungah']
    },
    'Tanjung Tokong': {
      'state': 'Penang',
      'aliases': ['tanjung tokong']
    },
    'Balik Pulau': {
      'state': 'Penang',
      'aliases': ['balik pulau']
    },
    'Butterworth': {
      'state': 'Penang',
      'aliases': ['butterworth']
    },
    'Bukit Mertajam': {
      'state': 'Penang',
      'aliases': ['bukit mertajam']
    },
    'Seberang Perai': {
      'state': 'Penang',
      'aliases': ['seberang perai', 'province wellesley']
    },
    'Kuala Lumpur': {
      'state': 'Kuala Lumpur',
      'aliases': ['kuala lumpur', 'kl']
    },
    'Petaling Jaya': {
      'state': 'Selangor',
      'aliases': ['petaling jaya', 'pj']
    },
    'Shah Alam': {
      'state': 'Selangor',
      'aliases': ['shah alam']
    },
    'Ipoh': {
      'state': 'Perak',
      'aliases': ['ipoh']
    },
    'Johor Bahru': {
      'state': 'Johor',
      'aliases': ['johor bahru', 'jb']
    },
    'Alor Setar': {
      'state': 'Kedah',
      'aliases': ['alor setar', 'alor star']
    },
    'Langkawi': {
      'state': 'Kedah',
      'aliases': ['langkawi', 'kuah']
    },
  };

  static const Map<String, List<double>> _stateCenters = {
    'Penang': [5.4141, 100.3288],
    'Kuala Lumpur': [3.1390, 101.6869],
    'Selangor': [3.0738, 101.5183],
    'Perak': [4.5921, 101.0901],
    'Johor': [1.4854, 103.7618],
    'Kedah': [6.1184, 100.3685],
  };

  static String _normalise(Object? value) => value
      .toString()
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .trim();

  static ({int index, String value})? _lastMatch(
      String value, Map<String, List<String>> entries) {
    final padded = ' ${_normalise(value)} ';
    ({int index, String value})? best;
    for (final entry in entries.entries) {
      for (final alias in entry.value) {
        final index = padded.lastIndexOf(' $alias ');
        if (index >= 0 && (best == null || index > best.index)) {
          best = (index: index, value: entry.key);
        }
      }
    }
    return best;
  }

  static String? _stateFromText(Object? value) {
    final states = _lastMatch(value.toString(), _stateAliases);
    final localityStates = <String, List<String>>{};
    for (final locality in _localities.values) {
      localityStates.putIfAbsent(locality['state']! as String, () => []);
      localityStates[locality['state']]!
          .addAll((locality['aliases']! as List).cast<String>());
    }
    final cities = _lastMatch(value.toString(), localityStates);
    if (states == null) return cities?.value;
    if (cities == null) return states.value;
    return cities.index > states.index ? cities.value : states.value;
  }

  static String? _cityFromText(Object? value) {
    final aliases = <String, List<String>>{
      for (final entry in _localities.entries)
        entry.key: (entry.value['aliases']! as List).cast<String>(),
    };
    return _lastMatch(value.toString(), aliases)?.value;
  }

  static Map<String, dynamic> normalizeScope(String value) {
    final normalized = _normalise(value);
    final city = _cityFromText(normalized);
    final state = city == null
        ? _stateFromText(normalized)
        : _localities[city]!['state']! as String;
    final malaysia = normalized == 'malaysia' || normalized == 'my';
    final center = _stateCenters[state];
    final scopeKey = city != null
        ? 'my:${_normalise(state).replaceAll(' ', '_')}:${_normalise(city).replaceAll(' ', '_')}'
        : state != null
            ? 'my:${_normalise(state).replaceAll(' ', '_')}'
            : malaysia
                ? 'my'
                : '';
    return {
      'country': state != null || malaysia ? 'Malaysia' : null,
      'state': state,
      'city': city,
      'canonicalName': city != null
          ? '$city, $state, Malaysia'
          : state != null
              ? '$state, Malaysia'
              : malaysia
                  ? 'Malaysia'
                  : value.trim(),
      'scopeKey': scopeKey,
      'latitude': center?.first,
      'longitude': center?.last,
      'resolved': scopeKey.isNotEmpty,
    };
  }

  static (double?, double?) _coordinates(Map<String, dynamic> item) {
    final raw = item['gps_coordinates'] ??
        item['gpsCoordinates'] ??
        (item['location'] is Map ? item['location'] : null);
    final gps = raw is Map ? raw : const {};
    final latitude = double.tryParse(
        '${gps['latitude'] ?? gps['lat'] ?? item['latitude'] ?? item['lat'] ?? ''}');
    final longitude = double.tryParse(
        '${gps['longitude'] ?? gps['lng'] ?? gps['lon'] ?? item['longitude'] ?? item['lng'] ?? ''}');
    return (latitude, longitude);
  }

  static String? _coordinateState(double? lat, double? lng) {
    if (lat == null || lng == null) return null;
    if (lat >= 2.95 && lat <= 3.27 && lng >= 101.55 && lng <= 101.80) {
      return 'Kuala Lumpur';
    }
    if (lat >= 2.88 && lat <= 3.00 && lng >= 101.64 && lng <= 101.76) {
      return 'Putrajaya';
    }
    if ((lat >= 5.12 && lat <= 5.59 && lng >= 100.15 && lng <= 100.35) ||
        (lat >= 5.10 && lat <= 5.57 && lng >= 100.35 && lng <= 100.57)) {
      return 'Penang';
    }
    if (lat >= 2.95 && lat <= 3.25 && lng >= 101.40 && lng <= 101.66) {
      return 'Selangor';
    }
    if (lat >= 4.40 && lat <= 4.75 && lng >= 100.90 && lng <= 101.30) {
      return 'Perak';
    }
    if (lat >= 1.30 && lat <= 1.70 && lng >= 103.50 && lng <= 104.05) {
      return 'Johor';
    }
    if (lat >= 5.95 && lat <= 6.25 && lng >= 100.20 && lng <= 100.50) {
      return 'Kedah';
    }
    if (lat >= 5.20 && lat <= 5.45 && lng >= 115.15 && lng <= 115.35) {
      return 'Labuan';
    }
    return null;
  }

  static Map<String, dynamic> validateCandidate(
      Map<String, dynamic> item, Map<String, dynamic> scope) {
    final (latitude, longitude) = _coordinates(item);
    final coordinateState = _coordinateState(latitude, longitude);
    final explicitState = _stateFromText(item['state'] ??
        item['administrative_area'] ??
        item['administrativeArea'] ??
        item['region'] ??
        '');
    final explicitCity =
        _cityFromText(item['city'] ?? item['locality'] ?? item['town'] ?? '');
    final address = [
      item['address'],
      item['formatted_address'],
      item['formattedAddress'],
      item['vicinity'],
      item['neighborhood'],
      item['area'],
      if (item['location'] is String) item['location'],
    ].where((value) => value != null).join(' ');
    final addressCity = _cityFromText(address);
    final addressState = _stateFromText(address);
    final city = explicitCity ?? addressCity;
    final cityState =
        city == null ? null : _localities[city]!['state'] as String;
    final textState = explicitState ?? cityState ?? addressState;
    final state = coordinateState ?? textState;
    final evidence = coordinateState != null
        ? 'coordinates'
        : explicitState != null
            ? 'state'
            : cityState != null
                ? 'city'
                : addressState != null
                    ? 'address'
                    : 'unresolved';
    final conflict = coordinateState != null &&
        textState != null &&
        coordinateState != textState;
    final eligible = scope['resolved'] == true &&
        state != null &&
        (scope['state'] == null || scope['state'] == state) &&
        (scope['city'] == null || scope['city'] == city);
    return {
      ...item,
      'normalizedGeography': {
        'country': state == null ? null : 'Malaysia',
        'state': state,
        'city': city,
        'latitude': latitude,
        'longitude': longitude,
        'evidence': evidence,
        'conflict': conflict,
        'resolved': state != null,
      },
      'geographicEligibility': {
        'eligible': eligible,
        'reason': state == null
            ? 'unresolved_candidate_geography'
            : scope['state'] != null && scope['state'] != state
                ? 'state_out_of_scope'
                : scope['city'] != null && scope['city'] != city
                    ? 'city_out_of_scope_or_unresolved'
                    : 'geographically_eligible',
        'evidence': evidence,
        'requestedScope': scope['scopeKey'],
      },
    };
  }
}
