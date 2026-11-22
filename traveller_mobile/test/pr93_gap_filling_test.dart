import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/constraint_itinerary_planner.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/flight_adjustment_preview_sheet.dart';
import 'flexible_planning_test.dart' show PlanningApi, app;

class GapApi extends PlanningApi {
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    final response = await super.post(path, body);
    if (path.endsWith('/preview')) {
      response['preview']['gapFilling'] = {'addedCount': 0, 'message': 'No suitable additional attractions were found for your available time.'};
      response['preview']['additionalEvidenceStatus'] = 'unavailable';
    }
    return response;
  }
}

void main() {
  test('packed days balance across actual windows and retain the rest day', () {
    final trip = {
      'startDate': '2026-11-25', 'endDate': '2026-11-29',
      'planningMode': 'smart', 'travelPace': 'active', 'geographyPlanningPolicy': localDaysPolicy,
      'planningPreferences': {'interests': ['Culture']},
      'travelDayPreferences': {'days': [{'dayNo': 3, 'restDay': true}]},
      'activities': [for (var i = 0; i < 30; i++) {
        'activityId': '$i', 'destinationId': '$i', 'activityName': 'Museum $i', 'category': 'museum',
        'openingHours': '08:00-21:30', 'providerDurationMinutes': 60, 'estimatedCost': 10,
        'gps_coordinates': {'latitude': 5.4, 'longitude': 100.3}
      }]
    };
    final result = planConstraintAwareItinerary(trip);
    expect((result['dailySchedule'] as List).map((day) => day['activities'].length), [5, 5, 0, 5, 5]);
    expect((result['activities'] as List).map((row) => row['destinationId']).toSet().length, 20);
  });

  testWidgets('no-addition explanation and explicit suggestion refresh cancel preserve the trip', (tester) async {
    final api = GapApi();
    await tester.pumpWidget(app(Builder(builder: (context) => TextButton(onPressed: () =>
      FlightAdjustmentPreviewSheet.show(context: context, api: api, tripId: 'personal-plan', trip: api.trip,
        previewRequest: {'planningChanges': <String, dynamic>{}, 'action': 'improve', 'scope': 'day', 'dayNo': 1}),
      child: const Text('Open preview')))));
    await tester.tap(find.text('Open preview'));
    await tester.pumpAndSettle();
    expect(find.text('No suitable additional attractions were found for your available time.'), findsOneWidget);
    await tester.ensureVisible(find.text('Refresh suggestions for additional places'));
    await tester.tap(find.text('Refresh suggestions for additional places'));
    await tester.pumpAndSettle();
    expect(find.text('Refresh suggestions?'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(api.posts.where((row) => (row['path'] as String).startsWith('/api/fr4')), isEmpty);
    expect(api.applies, 0);
  });
}
