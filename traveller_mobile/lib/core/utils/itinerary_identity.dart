import '../../services/review_contract.dart';
import 'dart:math';
import 'malaysian_locality.dart';

String _name(Map row) =>
    '${row['title'] ?? row['name'] ?? row['activityName'] ?? ''}'
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
        .trim();

const attractionIdentityPolicy = 'trip-wide-v1';
const _idFields = [
  'destinationId',
  'place_id',
  'data_id',
  'data_cid',
  'canonicalAttractionId',
  'id'
];

Set<String> _ids(Map row) {
  final ids = [for (final key in _idFields) row[key]];
  for (final alias
      in (row['identityConsolidation'] as List? ?? []).whereType<Map>()) {
    ids.add(alias['destinationId']);
    if (alias['sourceIds'] is Map)
      ids.addAll((alias['sourceIds'] as Map).values);
  }
  return ids
      .where((value) => value != null && '$value'.trim().isNotEmpty)
      .map((value) => ReviewContract.destinationId('$value'.trim()))
      .toSet();
}

Map<String, dynamic> _geo(Map<String, dynamic> row) =>
    Map<String, dynamic>.from(MalaysianLocality.validateCandidate(
        row, {'resolved': true})['normalizedGeography'] as Map);

Object? _ticket(Map row) {
  final evidence = row['pricingEvidence'];
  return row['costProvenance'] == 'verified_ticket' &&
          evidence is Map &&
          evidence['applicability'] == 'applicable' &&
          '${row['priceSourceUrl'] ?? ''}'.trim().isNotEmpty &&
          '${row['priceVerifiedAt'] ?? ''}'.trim().isNotEmpty
      ? evidence['ticketProductId'] ?? row['ticketProductId']
      : null;
}

const _hillNames = {
  'penang hill',
  'bukit bendera',
  'penang hill bukit bendera',
  'bukit bendera penang hill'
};
const _stationNames = {
  'penang hill lower station',
  'penang hill railway lower station',
  'penang hill funicular lower station',
  'stesen bawah bukit bendera'
};

// The documented Lower Station and summit pins can refer to one main visit.
bool _hillArea(Map<String, dynamic> row) {
  final geo = _geo(row);
  final lat = geo['latitude'], lon = geo['longitude'];
  return geo['state'] == 'Penang' &&
      geo['conflict'] != true &&
      (lat is num && lon is num
          ? lat >= 5.40 && lat <= 5.44 && lon >= 100.25 && lon <= 100.285
          : geo['city'] == 'Air Itam');
}

bool _hillMain(Map<String, dynamic> row) =>
    !['access', 'entrance', 'boarding_station'].contains(row['locationRole']) &&
    _hillNames.contains(_name(row)) &&
    _hillArea(row);

bool _separateTickets(Map a, Map b) =>
    (a['independentSubAttraction'] == true ||
        b['independentSubAttraction'] == true) &&
    _ticket(a) != null &&
    _ticket(b) != null &&
    _ticket(a) != _ticket(b);

bool sameAttraction(Map<String, dynamic> a, Map<String, dynamic> b) {
  if (_separateTickets(a, b)) return false;
  if (_ids(a).intersection(_ids(b)).isNotEmpty) return true;
  if (a['independentSubAttraction'] == true ||
      b['independentSubAttraction'] == true ||
      {
        'park',
        'temple',
        'museum',
        'mosque',
        'beach',
        'viewpoint',
        'viewing area',
        'station'
      }.contains(_name(a))) return false;
  if (_hillNames.contains(_name(a)) &&
      _hillNames.contains(_name(b)) &&
      _hillMain(a) &&
      _hillMain(b)) return true;
  if (_name(a).isEmpty || _name(a) != _name(b)) return false;
  final ga = _geo(a), gb = _geo(b);
  if (ga['conflict'] == true ||
      gb['conflict'] == true ||
      ga['state'] == null ||
      ga['state'] != gb['state']) return false;
  final lat1 = double.tryParse('${ga['latitude']}'),
      lat2 = double.tryParse('${gb['latitude']}');
  final lon1 = double.tryParse('${ga['longitude']}'),
      lon2 = double.tryParse('${gb['longitude']}');
  if (lat1 != null && lat2 != null && lon1 != null && lon2 != null) {
    final dy = (lat1 - lat2) * pi / 180, dx = (lon1 - lon2) * pi / 180;
    final h = pow(sin(dy / 2), 2) +
        cos(lat1 * pi / 180) * cos(lat2 * pi / 180) * pow(sin(dx / 2), 2);
    return 12742 * asin(min(1, sqrt(h))) <= .5;
  }
  return ga['city'] != null && ga['city'] == gb['city'];
}

bool _access(Map<String, dynamic> a, Map<String, dynamic> main) {
  if (['access', 'entrance', 'boarding_station'].contains(main['locationRole']))
    return false;
  if (a['independentSubAttraction'] == true ||
      a['intentionalRepeat'] == true ||
      a['priceVerified'] == true ||
      a['admissionPriceVerified'] == true ||
      a['costProvenance'] == 'verified_ticket') return false;
  if (['access', 'entrance', 'boarding_station'].contains(a['locationRole'])) {
    if (_ids(main).contains('${a['parentDestinationId']}')) return true;
    if (a['attractionFamilyId'] != null &&
        a['attractionFamilyId'] == main['attractionFamilyId'] &&
        main['locationRole'] == 'main') return true;
  }
  // PHC's direction page establishes the lower station as access, not a second main visit.
  return _stationNames.contains(_name(a)) && _hillMain(main) && _hillArea(a);
}

/// Only call for newly selected automatic candidates, never when reopening/recalculating a trip.
List<Map<String, dynamic>> consolidateGeneratedCandidates(
    List<Map<String, dynamic>> rows,
    {bool automatic = false}) {
  final kept = <Map<String, dynamic>>[];
  for (final source in rows) {
    final row = Map<String, dynamic>.from(source);
    if (automatic) row.remove('intentionalRepeat');
    final matches = kept
        .where((other) =>
            row['intentionalRepeat'] != true &&
            other['intentionalRepeat'] != true &&
            sameAttraction(other, row))
        .toList();
    if (matches.isEmpty) {
      kept.add(row);
      continue;
    }
    final retained = matches.first;
    for (final duplicate in [row, ...matches.skip(1)]) {
      if (_separateTickets(retained, duplicate)) continue;
      retained['identityConsolidation'] = [
        ...?retained['identityConsolidation'] as List?,
        {
          'destinationId': duplicate['destinationId'],
          'sourceIds': {
            for (final key in _idFields)
              if (duplicate[key] != null) key: duplicate[key]
          },
          'reason': 'same_attraction'
        },
        ...?duplicate['identityConsolidation'] as List?,
      ];
      if (!identical(duplicate, row)) kept.remove(duplicate);
    }
  }
  final output = <Map<String, dynamic>>[];
  for (final row in kept) {
    final mains = kept.where((r) =>
        !identical(r, row) &&
        r['intentionalRepeat'] != true &&
        _access(row, r));
    if (mains.isEmpty) {
      output.add(row);
      continue;
    }
    final main = mains.first;
    main['supportingAccess'] = [
      ...?main['supportingAccess'] as List?,
      {
        'destinationId': row['destinationId'] ?? row['place_id'],
        'title': row['title'] ?? row['activityName'],
        'role': 'access',
        'transportDetailsVerified': false,
        'note':
            'Access point; confirm transport, journey time and any separate ticket cost before visiting.'
      }
    ];
  }
  return output;
}
