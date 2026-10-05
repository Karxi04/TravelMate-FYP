import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/constraint_itinerary_planner.dart';

Map<String, dynamic> activity(int index, {Map<String, dynamic>? changes}) => {
      'activityId': 'a$index',
      'activityName': 'Activity $index',
      'category': 'museum',
      'estimatedCost': 10,
      'gps_coordinates': {
        'latitude': 5.40 + index * .005,
        'longitude': 100.30 + index * .005,
      },
      ...?changes,
    };

Map<String, dynamic> trip(int days, int count, {String pace = 'moderate'}) => {
      'startDate': '2026-10-10',
      'endDate': DateTime(2026, 10, 10)
          .add(Duration(days: days - 1))
          .toIso8601String()
          .substring(0, 10),
      'travelPace': pace,
      'activities': [for (var i = 0; i < count; i++) activity(i)],
    };

void main() {
  test('pace windows create dynamic capacity and explicit overflow', () {
    final relaxed = planConstraintAwareItinerary(trip(1, 12, pace: 'relaxed'));
    final active = planConstraintAwareItinerary(trip(1, 12, pace: 'active'));

    expect(relaxed['dailyPlanningWindow'],
        {'startTime': '10:00', 'endTime': '20:00'});
    expect(active['dailyPlanningWindow'],
        {'startTime': '08:00', 'endTime': '21:30'});
    expect(relaxed['scheduledActivityCount'],
        lessThan(active['scheduledActivityCount'] as int));
    expect(relaxed['unscheduledActivityCount'], greaterThan(0));
  });

  test('weather maps by date and never invents out-of-range weather', () {
    final planned = planConstraintAwareItinerary(
      trip(2, 4),
      forecast: {
        'daily': {
          'time': ['2026-10-10'],
          'precipitation_probability_max': [80],
          'weather_code': [61],
        }
      },
    );
    final days = planned['dailySchedule'] as List;
    expect(days.first['weather']['heavyRainLikely'], isTrue);
    expect(days[1]['weather']['source'], 'unavailable');
    expect(days[1]['weather']['message'],
        'Weather forecast unavailable for this date.');
  });

  test('closed and non-fitting places remain as unscheduled suggestions', () {
    final source = trip(1, 0);
    source['activities'] = [
      activity(1, changes: {'openingHours': 'Closed'}),
      activity(2, changes: {
        'openingHours': '09:00-10:00',
        'recommendedDurationMinutes': 180,
      }),
    ];
    final planned = planConstraintAwareItinerary(source);

    expect(planned['activities'], isEmpty);
    expect(planned['unscheduledActivityCount'], 2);
    expect(
        (planned['unscheduledSuggestions'] as List).first['unscheduledReason'],
        contains('closed'));
  });

  test('recalculation preserves requested order and recomputes metadata', () {
    final generated = planConstraintAwareItinerary(trip(2, 5));
    final items = List<Map<String, dynamic>>.from(
        (generated['activities'] as List)
            .map((item) => Map<String, dynamic>.from(item)));
    final firstId = items.first['activityId'];
    items.removeAt(0);
    generated['activities'] = items.reversed.toList();
    generated['unscheduledSuggestions'] = [];

    final recalculated = planConstraintAwareItinerary(generated,
        preserveOrder: true, respectDayAssignments: true);
    final recalculatedItems = recalculated['activities'] as List;
    expect(recalculatedItems.any((item) => item['activityId'] == firstId),
        isFalse);
    expect(recalculatedItems.every((item) => item['timeRangeLabel'] != null),
        isTrue);
  });

  test('change day recalculates the activity on the requested day', () {
    final generated = planConstraintAwareItinerary(trip(2, 3));
    final items = List<Map<String, dynamic>>.from(
        (generated['activities'] as List)
            .map((item) => Map<String, dynamic>.from(item)));
    items.first['dayNo'] = 2;
    generated['activities'] = items;
    generated['unscheduledSuggestions'] = [];

    final recalculated = planConstraintAwareItinerary(generated,
        preserveOrder: true, respectDayAssignments: true);
    final moved = (recalculated['activities'] as List)
        .firstWhere((item) => item['activityId'] == items.first['activityId']);
    expect(moved['dayNo'], 2);
    expect(moved['scheduledStartTime'], isNotEmpty);
  });
}
