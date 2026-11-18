import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/constraint_itinerary_planner.dart';

Map<String, dynamic> _visit(String id, String name, double? lat,
    {double lng = 102.57, String category = 'Culture'}) => {
  'activityId': id,
  'destinationId': id,
  'activityName': name,
  'category': category,
  'gps_coordinates': lat == null ? {} : {'latitude': lat, 'longitude': lng},
  'recommendedDurationMinutes': 75,
  'openingHours': '08:00 - 21:00',
};

Map<String, dynamic> _trip(List<Map<String, dynamic>> visits) => {
  'geographyPlanningPolicy': localDaysPolicy,
  'destinationArea': 'Johor',
  'startDate': '2030-12-12',
  'endDate': '2030-12-14',
  'travelMode': 'own_vehicle',
  'travelPace': 'Packed',
  'activities': visits,
};

Iterable<Object?> _ids(dynamic rows) =>
    (rows as List).cast<Map>().map((item) => item['activityId']);

void main() {
  test('standalone holds the Johor Bahru visit for an explicit travel day', () {
    final trip = _trip([
      _visit('gallery', 'Muar Gallery', 2.055),
      _visit('market', 'Muar Market', 2.057),
      _visit('temple', 'Temple', 1.49, lng: 103.783011),
    ]);
    final local = planConstraintAwareItinerary(trip);
    expect(_ids(local['activities']), ['gallery', 'market']);
    final optional = (local['unscheduledSuggestions'] as List).single as Map;
    expect(optional['unscheduledReason'], contains('too far'));
    final moved = planConstraintAwareItinerary({
      ...local,
      'confirmedIntercityTransfer': {'dayNo': 2, 'mode': 'drive', 'toDestinationId': 'temple'},
    });
    final days = (moved['dailySchedule'] as List).cast<Map>();
    expect(_ids(days[0]['activities']), ['gallery', 'market']);
    expect(days[1]['activities'], isEmpty);
    final transfer = (days[1]['planningBlocks'] as List).single as Map;
    expect(transfer['type'], 'intercity_transfer');
    expect(transfer['durationMinutes'], greaterThan(300));
    expect(_ids(days[2]['activities']), ['temple']);
    expect(moved['intercityTransferStatus'], 'planned');
  });

  test('walking keeps the limit and unknown coordinates do not prove proximity', () {
    final open = [
      _visit('first', 'River Gallery', 2.055),
      _visit('second', 'Market', 2.1),
      _visit('unknown', 'Legacy stop', null),
    ];
    final drive = planConstraintAwareItinerary(_trip(open));
    expect(_ids(drive['activities']), ['first', 'second']);
    final walk = planConstraintAwareItinerary({..._trip(open), 'transportMode': 'walk'});
    expect(_ids(walk['activities']).length, 1);
    final reasons = (walk['unscheduledSuggestions'] as List).cast<Map>();
    expect(reasons.any((row) => row['unscheduledReason'].toString().contains('reliable journey')), isTrue);
  });

  test('packed nature plan has shopping and one ordinary hike on the same day', () {
    final rows = [
      _visit('hike', 'Hill Hike', 2.055, category: 'Nature'),
      _visit('repeat', 'Mountain Hike', 2.056, category: 'Nature'),
      _visit('garden', 'Botanic Garden', 2.057, category: 'Nature'),
      _visit('mall', 'Local Mall', 2.058, category: 'Shopping'),
    ];
    final plan = planConstraintAwareItinerary({
      ..._trip(rows),
      'endDate': '2030-12-12',
      'interests': ['Nature', 'Shopping'],
    });
    expect(_ids(plan['activities']), containsAll(['hike', 'garden', 'mall']));
    expect(_ids(plan['unscheduledSuggestions']), ['repeat']);
  });
}
