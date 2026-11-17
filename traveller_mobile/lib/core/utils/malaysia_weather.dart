import 'malaysian_locality.dart';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'malaysian_locations.dart';

/// Standalone weather uses the same pinned source files as Flask, not new geographic facts.
class MalaysiaWeather {
  static Future<MalaysiaWeather>? _instance;
  static Future<MalaysiaWeather> load() => _instance ??= _load();
  static Future<MalaysiaWeather> _load() async => MalaysiaWeather(
      jsonDecode(await rootBundle.loadString(
          'assets/geography/malaysia_states.geojson')) as Map,
      jsonDecode(await rootBundle.loadString(
          'assets/geography/malaysia_locations.json')) as Map);
  final Map boundary;
  final Map dataset;
  MalaysiaWeather(this.boundary, this.dataset);
  static String stateName(String value) =>
      const {
        'Pulau Pinang': 'Penang',
        'W.P. Kuala Lumpur': 'Kuala Lumpur',
        'W.P. Putrajaya': 'Putrajaya',
        'W.P. Labuan': 'Labuan'
      }[value] ??
      value;

  int _ring(double x, double y, List ring) {
    var inside = false;
    for (var i = 0; i < ring.length - 1; i++) {
      final a = ring[i] as List, b = ring[i + 1] as List;
      final ax = (a[0] as num).toDouble(), ay = (a[1] as num).toDouble();
      final bx = (b[0] as num).toDouble(), by = (b[1] as num).toDouble();
      final cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax);
      if (cross.abs() <= 1e-12 &&
          x >= (ax < bx ? ax : bx) &&
          x <= (ax > bx ? ax : bx) &&
          y >= (ay < by ? ay : by) &&
          y <= (ay > by ? ay : by)) return 2;
      if ((ay > y) != (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax)
        inside = !inside;
    }
    return inside ? 1 : 0;
  }

  late final List<
      ({
        String state,
        List rings,
        double west,
        double east,
        double south,
        double north
      })> _polygons = [
    for (final feature in boundary['features'] as List)
      for (final polygon in feature['geometry']['type'] == 'MultiPolygon'
          ? feature['geometry']['coordinates'] as List
          : [feature['geometry']['coordinates']])
        (
          state: stateName('${feature['properties']['state']}'),
          rings: polygon as List,
          west: (polygon[0] as List)
              .map((p) => (p[0] as num).toDouble())
              .reduce((a, b) => a < b ? a : b),
          east: (polygon[0] as List)
              .map((p) => (p[0] as num).toDouble())
              .reduce((a, b) => a > b ? a : b),
          south: (polygon[0] as List)
              .map((p) => (p[1] as num).toDouble())
              .reduce((a, b) => a < b ? a : b),
          north: (polygon[0] as List)
              .map((p) => (p[1] as num).toDouble())
              .reduce((a, b) => a > b ? a : b)
        )
  ];

  String? coordinateState(double lat, double lon) {
    if (!lat.isFinite || !lon.isFinite) return null;
    final found = <String>{};
    for (final polygon in _polygons) {
      if (lon < polygon.west ||
          lon > polygon.east ||
          lat < polygon.south ||
          lat > polygon.north) continue;
      final outer = _ring(lon, lat, polygon.rings.first as List);
      if (outer == 2) return null;
      if (outer == 1 &&
          !polygon.rings.skip(1).any((r) => _ring(lon, lat, r as List) != 0))
        found.add(polygon.state);
    }
    return found.length == 1 ? found.single : null;
  }

  Map<String, dynamic>? point(Map row) {
    final lat = double.tryParse('${row['latitude']}'),
        lon = double.tryParse('${row['longitude']}');
    if (lat == null ||
        lon == null ||
        coordinateState(lat, lon) != row['state'] ||
        !RegExp(r'^[0-9]{1,10}$').hasMatch('${row['id']}') ||
        row['name'] is! String ||
        (row['name'] as String).trim().isEmpty ||
        (row['name'] as String).length > 150) return null;
    final name =
        '${row['name']}${row['kind'] == 'district' ? ' District' : ''}';
    return {
      'id': 'geonames:${row['id']}',
      'name': name,
      'admin1': row['state'],
      'country': 'Malaysia',
      'label': '$name, ${row['state']}, Malaysia',
      'latitude': lat,
      'longitude': lon,
      'requiresCity': false,
      'aliases': row['aliases'],
      'population': row['population'],
      'pointDescription':
          'Representative locality point; conditions vary within the area.'
    };
  }

  late final List<Map<String, dynamic>> all = [
    for (final row in dataset['places'] as List)
      if (point(row as Map) case final p?) p
  ];
  late final Set<String> _fastIds = (dataset['places'] as List)
      .where((r) => r['fast'] == true)
      .map((r) => 'geonames:${r['id']}')
      .toSet();
  late final List<Map<String, dynamic>> catalogue = _uniqueLabels([
    for (final state in (dataset['counts']['byState'] as Map).keys)
      {
        'id': 'state:$state',
        'name': state,
        'admin1': state,
        'country': 'Malaysia',
        'label': '$state, Malaysia',
        'aliases': MalaysianLocality.aliasesForState(state.toString()),
        'requiresCity': true,
        'pointDescription':
            'Choose a city or locality; weather varies across the state.'
      },
    ...all.where((p) => _fastIds.contains(p['id'])),
  ]);

  List<Map<String, dynamic>> _uniqueLabels(List<Map<String, dynamic>> rows) {
    final counts = <String, int>{};
    for (final row in rows) {
      final label = '${row['label']}';
      counts[label] = (counts[label] ?? 0) + 1;
    }
    return rows.where((r) => counts['${r['label']}'] == 1).toList();
  }

  List<Map<String, dynamic>> search(String query) =>
      _uniqueLabels(matchingMalaysianLocations(
          all
              .map((p) => {
                    ...p,
                    'city': p['name'],
                    'state': p['admin1'],
                    'canonicalName': p['label']
                  })
              .toList(),
          query));
}
