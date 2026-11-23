import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/constraint_itinerary_planner.dart';

void main() {
  final cases =
      jsonDecode(File('../backend_api/tests/fixtures/pr93_relaxed_scheduling.json').readAsStringSync()) as List;
  for (final fixture in cases.cast<Map>()) {
    test('shared relaxed schedule: ${fixture['name']}', () {
      final trip = Map<String, dynamic>.from(fixture['trip']);
      final before = jsonEncode(trip);
      final expected = fixture['expected'] as Map;
      final result = planConstraintAwareItinerary(trip);
      final rows = (result['activities'] as List).cast<Map>();
      expect(rows.map((row) => row['activityId']), expected['ids']);
      for (final field in {'starts': 'scheduledStartTime', 'ends': 'scheduledEndTime'}.entries) {
        if (expected.containsKey(field.key)) expect(rows.map((row) => row[field.value]), expected[field.key]);
      }
      final window = result['dailySchedule'][0]['planningWindow'];
      if (expected.containsKey('window')) expect([window['startTime'], window['endTime']], expected['window']);
      for (final row in rows) {
        if ((expected['provisional'] as List? ?? []).contains(row['activityId']))
          expect(row['scheduleFeasibility'], 'provisional');
        expect((row['scheduledEndTime'] as String).compareTo(window['endTime']), lessThanOrEqualTo(0));
      }
      expect(rows.length, lessThanOrEqualTo(2));
      expect([...rows, ...result['unscheduledSuggestions']].map((row) => row['activityId']).toSet(),
          (trip['activities'] as List).map((row) => row['activityId']).toSet());
      expect(jsonEncode(trip), before);
    });
  }
}
