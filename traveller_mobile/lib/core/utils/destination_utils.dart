import 'dart:math';

class DestinationUtils {
  static Iterable<dynamic> _aliases(Map row) => row['identityAliases'] is List ? row['identityAliases'] : const [];
  static Map _map(dynamic value) => value is Map ? value : const {};
  static bool samePlace(Map<String, dynamic> a, Map<String, dynamic> b) {
    Set<String> ids(Map row) => {
      for (final key in ['destinationId', 'place_id', 'data_id', 'data_cid', 'id', 'reviewDestinationId'])
        if ('${row[key] ?? ''}'.isNotEmpty) '${row[key]}',
      ..._aliases(row).whereType<String>(),
    };
    if (ids(a).intersection(ids(b)).isNotEmpty) return true;
    String text(dynamic value) => '$value'.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim();
    if (text(resolveName(a)) != text(resolveName(b))) return false;
    final ga = a['normalizedGeography'] is Map ? _map(a['normalizedGeography']) : a;
    final gb = b['normalizedGeography'] is Map ? _map(b['normalizedGeography']) : b;
    final state = text(ga['state'] ?? '');
    if (state.isEmpty || state != text(gb['state'] ?? '') || ga['conflict'] == true || gb['conflict'] == true) return false;
    final ca = a['gps_coordinates'] is Map ? _map(a['gps_coordinates']) : ga;
    final cb = b['gps_coordinates'] is Map ? _map(b['gps_coordinates']) : gb;
    final lat1 = double.tryParse('${ca['latitude']}');
    final lon1 = double.tryParse('${ca['longitude']}');
    final lat2 = double.tryParse('${cb['latitude']}');
    final lon2 = double.tryParse('${cb['longitude']}');
    if (lat1 != null && lon1 != null && lat2 != null && lon2 != null) {
      if (![lat1, lon1, lat2, lon2].every((value) => value.isFinite) || lat1.abs() > 90 || lat2.abs() > 90 || lon1.abs() > 180 || lon2.abs() > 180) return false;
      final dy = (lat2 - lat1) * pi / 180;
      final dx = (lon2 - lon1) * pi / 180;
      final h = pow(sin(dy / 2), 2) + cos(lat1 * pi / 180) * cos(lat2 * pi / 180) * pow(sin(dx / 2), 2);
      return h.isFinite && 12742 * asin(sqrt(h.clamp(0, 1))) <= .5;
    }
    final city = text(ga['city'] ?? '');
    return city.isNotEmpty && city == text(gb['city'] ?? '');
  }

  static List<Map<String, dynamic>> uniquePlaces(Iterable<Map<String, dynamic>> items) {
    final output = <Map<String, dynamic>>[];
    for (final row in items) {
      final index = output.indexWhere((existing) => samePlace(existing, row));
      if (index < 0) {
        output.add(row);
      } else {
        final existing = output[index];
        output[index] = {...existing,
          for (final entry in row.entries)
            if (existing[entry.key] == null || existing[entry.key] == '') entry.key: entry.value,
          'identityAliases': {..._aliases(existing).whereType<String>(), ..._aliases(row).whereType<String>(), resolveId(existing), resolveId(row)}.take(8).toList(),
        };
      }
    }
    return output;
  }
  /// Canonical destination ID resolver used consistently across
  /// search, details, feedback submission/retrieval, and itinerary planning.
  static String resolveId(Map<String, dynamic>? item) {
    if (item == null) return '';
    final id = item['destinationId'] ??
        item['place_id'] ??
        item['data_id'] ??
        item['data_cid'] ??
        item['id'] ??
        item['title'] ??
        item['name'] ??
        '';
    return id.toString().trim();
  }

  static String resolveName(Map<String, dynamic>? item) {
    if (item == null) return 'Place';
    final name = item['title'] ?? item['name'] ?? item['destinationName'] ?? 'Place';
    return name.toString().trim();
  }
}
