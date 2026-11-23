import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'flexible_planning_test.dart' show PlanningApi, app, reveal;

void main() {
  for (final mode in ['smart', 'manual', 'assisted']) {
    for (final scope in ['day', 'remaining']) {
      testWidgets('$mode Improve $scope previews, cancels, applies and reopens', (tester) async {
        final api = PlanningApi();
        api.trip['planningMode'] = mode;
        api.trip['planningBlocks'] = [
          {
            'blockId': 'rest',
            'dayNo': 1,
            'type': 'rest',
            'label': 'Personal rest',
            'startTime': '14:00',
            'endTime': '15:00'
          }
        ];
        api.trip['dailySchedule'][0]['planningBlocks'] = api.trip['planningBlocks'];
        final before = jsonEncode(api.trip);
        await tester.pumpWidget(app(TripDetailsScreen(tripId: 'personal-plan', api: api)));
        await tester.pumpAndSettle();
        Future<void> preview() async {
          await reveal(tester, 'Schedule assistance');
          await tester.tap(find.text('Schedule assistance'));
          await tester.pumpAndSettle();
          expect(find.text('Improve this day'), findsOneWidget);
          expect(find.text('Improve remaining days'), findsOneWidget);
          expect(find.byType(PopupMenuItem<String>), findsNWidgets(2));
          expect(find.textContaining('Regenerate'), findsNothing);
          await tester.tap(find.text(scope == 'day' ? 'Improve this day' : 'Improve remaining days'));
          await tester.pumpAndSettle();
          final request = api.posts.last['body'] as Map;
          expect(request['action'], 'improve');
          expect(request['scope'], scope);
          expect(request['dayNo'], 1);
          expect(request['expectedItineraryRevision'], 1);
        }

        await preview();
        expect(api.applies, 0);
        expect(jsonEncode(api.trip), before);
        await tester.tap(find.text('Keep current plan'));
        await tester.pumpAndSettle();
        expect(api.applies, 0);
        expect(jsonEncode(api.trip), before);
        await preview();
        await tester.tap(find.byKey(const ValueKey('apply-flight-adjustment-btn')));
        await tester.pumpAndSettle();
        expect(api.applies, 1);
        expect(jsonEncode(api.trip), before);
        await tester.pumpWidget(const SizedBox());
        await tester.pumpWidget(app(TripDetailsScreen(tripId: 'personal-plan', api: api)));
        await tester.pumpAndSettle();
        await reveal(tester, 'Personal rest');
        expect(find.text('Personal rest'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }
}
