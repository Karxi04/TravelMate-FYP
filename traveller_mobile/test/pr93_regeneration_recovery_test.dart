import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/flight_adjustment_preview_sheet.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/planning_settings_sheet.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/personal_block_editor.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/planning_time_validation.dart';
import 'flexible_planning_test.dart' show PlanningApi, app, reveal;

class RecoveryApi extends PlanningApi {
  int previews = 0, generations = 0;
  String code = 'RECOMMENDATION_REFRESH_REQUIRED';
  String action = 'refresh_suggestions';
  bool ready = false;
  final commands = <Map<String, dynamic>>[];
  RecoveryApi() {
    trip['recommendationGenerationId'] = 'fyp-evaluation-old';
  }
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr4/recommendations/generate') {
      generations++;
      ready = true;
      return {'ok': true, 'recommendationGenerationId': 'fyp-evaluation-new'};
    }
    if (path.endsWith('/flight-adjustment/preview')) {
      previews++;
      commands.add(Map<String, dynamic>.from(body ?? {}));
      if (!ready)
        throw ApiException('Sanitized server reason', 409,
            {'code': code, 'nextAction': action});
    }
    return super.post(path, body);
  }
}

Future<void> openPreview(WidgetTester tester, RecoveryApi api,
    {String scope = 'day'}) async {
  await tester.pumpWidget(app(Builder(
      builder: (context) => TextButton(
          onPressed: () => FlightAdjustmentPreviewSheet.show(
                  context: context,
                  api: api,
                  tripId: api.trip['id'],
                  trip: api.trip,
                  previewRequest: {
                    'planningChanges': <String, dynamic>{},
                    'action': 'regenerate',
                    'scope': scope,
                    'dayNo': 2,
                    'expectedItineraryRevision': 1
                  }),
          child: const Text('Regenerate')))));
  await tester.tap(find.text('Regenerate'));
  await tester.pumpAndSettle();
}

Map<String, dynamic> timedTrip() => {
      'startDate': '2026-11-25',
      'endDate': '2026-11-27',
      'selectedFlight': {
        'outboundSegments': [
          {'arrivalDate': '2026-11-25', 'arrivalTime': '14:50'}
        ],
        'returnSegments': [
          {'departureDate': '2026-11-27', 'departureTime': '10:55'}
        ]
      },
      'activities': <Map<String, dynamic>>[]
    };

void main() {
  for (final scope in ['day', 'full']) {
    testWidgets(
        'explicit $scope refresh recovers a new generation without saving or looping',
        (tester) async {
      final api = RecoveryApi();
      await openPreview(tester, api, scope: scope);
      expect(api.previews, 1);
      expect(api.generations, 0);
      expect(api.applies, 0);
      expect(find.textContaining('saved suggestions need to be refreshed'),
          findsOneWidget);
      expect(find.text('Refresh preview'), findsNothing);
      await tester.tap(find.text('Refresh suggestions'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(api.generations, 0);
      expect(api.previews, 1);
      await tester.tap(find.text('Refresh suggestions'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Refresh suggestions now'));
      await tester.pumpAndSettle();
      expect(api.generations, 1);
      expect(api.previews, 2);
      final request = api.commands.last;
      expect(request['scope'], scope);
      expect(request['dayNo'], 2);
      expect(request['recommendationGenerationId'], 'fyp-evaluation-new');
      expect(request['expectedLinkedGenerationId'], 'fyp-evaluation-old');
      expect(request['refreshSuggestions'], true);
      expect(request['expectedItineraryRevision'], 1);
      expect(api.trip['recommendationGenerationId'], 'fyp-evaluation-old');
      expect(api.applies, 0);
      await tester.tap(find.text('Keep current plan'));
      await tester.pumpAndSettle();
      expect(api.applies, 0);
      expect(tester.takeException(), isNull);
    });
  }

  for (final failure in [
    (
      'FLIGHT_TIMING_INCOMPLETE',
      'review_flight',
      'Some flight times are missing. Review your selected flight.',
      'Review selected flight'
    ),
    (
      'PLANNING_TIME_CONFLICT',
      'edit_preferences',
      'Sanitized server reason',
      'Edit travel preferences'
    ),
    (
      'PROTECTED_ACTIVITY_CONFLICT',
      'review_fixed_activity',
      'A fixed activity prevents this schedule change.',
      'Review fixed activity'
    ),
    (
      'NO_REGENERATION_CANDIDATES',
      'keep_current',
      'No suitable replacement activities were found.',
      'Keep current itinerary'
    ),
  ]) {
    testWidgets('${failure.$1} has its own action and no automatic retry',
        (tester) async {
      final api = RecoveryApi()
        ..code = failure.$1
        ..action = failure.$2;
      await openPreview(tester, api);
      expect(find.text(failure.$3), findsOneWidget);
      expect(find.text(failure.$4), findsOneWidget);
      expect(find.textContaining('Your itinerary has changed'), findsNothing);
      expect(find.text('Refresh preview'), findsNothing);
      expect(api.previews, 1);
      expect(api.generations, 0);
      await tester.tap(find.text(failure.$4));
      await tester.pumpAndSettle();
      expect(api.previews, 1);
      expect(api.applies, 0);
    });
  }

  testWidgets(
      'stale Trip recovery reloads its current revision before another preview',
      (tester) async {
    final api = RecoveryApi()
      ..code = 'STALE_ITINERARY'
      ..action = 'reload_trip';
    await openPreview(tester, api);
    api.ready = true;
    api.trip['itineraryRevision'] = 4;
    await tester.tap(find.text('Reload Trip'));
    await tester.pumpAndSettle();
    expect(api.commands.last['expectedItineraryRevision'], 4);
    expect(api.previews, 2);
    expect(api.generations, 0);
    expect(api.applies, 0);
  });

  for (final mode in ['smart', 'manual', 'assisted', 'legacy']) {
    testWidgets(
        '$mode Travel Preferences preserves mode and sends no incidental planningMode',
        (tester) async {
      final api = PlanningApi();
      if (mode == 'legacy') {
        api.trip.remove('planningMode');
      } else {
        api.trip['planningMode'] = mode;
      }
      await tester.pumpWidget(app(Builder(
          builder: (context) => TextButton(
              onPressed: () =>
                  PlanningSettingsSheet.show(context, api, api.trip),
              child: const Text('Settings')))));
      await tester.tap(find.text('Settings'));
      await tester.pumpAndSettle();
      expect(find.text('Travel Preferences'), findsOneWidget);
      expect(find.text('Planning style'), findsNothing);
      await reveal(tester, 'Preview planning changes');
      await tester.tap(find.text('Preview planning changes'));
      await tester.pumpAndSettle();
      expect(
          (api.posts.last['body']['planningChanges'] as Map)
              .containsKey('planningMode'),
          false);
      expect(api.trip['planningMode'], mode == 'legacy' ? null : mode);
      expect(api.applies, 0);
    });
  }

  for (final times in [
    ('15:00', '14:00'),
    ('10:00', '10:00'),
    ('23:00', '01:00'),
    ('09:00', null),
    (null, '18:00')
  ]) {
    test('invalid same-day window $times is rejected immediately', () {
      final error = planningTimeError({
        'startDate': '2026-11-25',
        'endDate': '2026-11-27'
      }, {
        'days': [
          {'dayNo': 2, 'startTime': times.$1, 'endTime': times.$2}
        ]
      }, []);
      expect(error, contains('end time must be later'));
    });
  }
  test(
      'flight cutoffs, personal/travel context, overlap, fixed visits and valid non-flight intervals',
      () {
    final trip = timedTrip();
    final bounds = planningTravelBounds(trip, {});
    expect(bounds.arrival, DateTime(2026, 11, 25, 17, 50));
    expect(bounds.departure, DateTime(2026, 11, 27, 7, 25));
    final lunch = <String, dynamic>{
      'label': 'Lunch break',
      'type': 'meal',
      'dayNo': 1,
      'boundary': 'personal',
      'startTime': '12:00',
      'endTime': '13:00'
    };
    expect(planningTimeError(trip, {}, [lunch]), null);
    expect(
        planningTimeError(trip, {}, [
          {...lunch, 'boundary': 'destination'}
        ]),
        contains('travel times'));
    expect(
        planningTimeError(trip, {}, [
          lunch,
          {...lunch, 'startTime': '12:30', 'endTime': '13:30'}
        ]),
        contains('overlaps'));
    expect(
        planningTimeError(trip, {
          'days': [
            {'dayNo': 1, 'startTime': '09:00', 'endTime': '18:00'}
          ]
        }, []),
        contains('travel times'));
    expect(
        planningTimeError(trip, {
          'days': [
            {'dayNo': 3, 'startTime': '06:00', 'endTime': '08:00'}
          ]
        }, []),
        contains('travel times'));
    expect(
        planningTimeError({
          'startDate': '2026-11-25',
          'endDate': '2026-11-27'
        }, {
          'days': [
            {'dayNo': 2, 'startTime': '09:00', 'endTime': '18:00'}
          ]
        }, []),
        null);
    trip['activities'] = [
      {
        'dayNo': 1,
        'fixed': true,
        'scheduledStartTime': '12:00',
        'scheduledEndTime': '13:00'
      }
    ];
    expect(planningTimeError(trip, {}, [lunch]), contains('fixed activity'));
    expect(
        planningTimeError(trip, {
          'days': [
            {'dayNo': 1, 'startTime': '18:00', 'endTime': '19:00'}
          ]
        }, []),
        contains('fixed activity'));
    trip['planningAvailability'] = {
      'days': {
        '2026-11-25': {'baseStartMinutes': 540, 'baseEndMinutes': 1080}
      }
    };
    expect(
        planningTimeError(trip, {
          'arrival': {'choice': 'custom', 'startTime': '19:00'}
        }, []),
        contains('leaves no sightseeing time'));
  });

  test(
      'overnight buffers remain attached to the actual travel date and do not grant a next-day preference',
      () {
    final trip = timedTrip();
    (trip['selectedFlight'] as Map)['outboundSegments'] = [
      {'arrivalDate': '2026-11-25', 'arrivalTime': '23:00'}
    ];
    expect(
        planningTimeError(trip, {
          'arrival': {'choice': 'custom', 'startTime': '10:00'}
        }, []),
        contains('travel limit'));
    expect(
        planningTimeError({
          'startDate': '2026-11-25',
          'endDate': '2026-11-25'
        }, {
          'arrival': {'choice': 'custom', 'startTime': '15:00'},
          'departure': {'choice': 'custom', 'endTime': '14:00'}
        }, []),
        contains('end after it starts'));
  });

  for (final width in [320.0, 360.0, 390.0]) {
    testWidgets(
        'invalid daily hours disable Preview with inline feedback at $width large text',
        (tester) async {
      tester.view.physicalSize = Size(width, 850);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = PlanningApi();
      api.trip['travelDayPreferences'] = {
        'days': [
          {'dayNo': 2, 'startTime': '15:00', 'endTime': '14:00'}
        ]
      };
      await tester.pumpWidget(app(
          Builder(
              builder: (context) => TextButton(
                  onPressed: () =>
                      PlanningSettingsSheet.show(context, api, api.trip),
                  child: const Text('Settings'))),
          scale: 1.6));
      await tester.tap(find.text('Settings'));
      await tester.pumpAndSettle();
      await reveal(tester, 'Preview planning changes');
      expect(
          find.textContaining('Day 2: end time must be later'), findsOneWidget);
      expect(
          tester
              .widget<FilledButton>(
                  find.widgetWithText(FilledButton, 'Preview planning changes'))
              .onPressed,
          isNull);
      expect(api.posts, isEmpty);
      expect(tester.takeException(), isNull);
    });
    testWidgets('personal editor detects overlap before Save at $width',
        (tester) async {
      tester.view.physicalSize = Size(width, 850);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(app(
          PersonalBlockEditor(dayCount: 3, trip: timedTrip(), initial: {
            'label': 'Lunch',
            'type': 'meal',
            'dayNo': 1,
            'startTime': '12:00',
            'endTime': '13:00',
            'boundary': 'personal'
          }, otherBlocks: const [
            {
              'label': 'Rest',
              'dayNo': 1,
              'type': 'rest',
              'startTime': '12:30',
              'endTime': '14:00'
            }
          ]),
          scale: 1.6));
      await tester.pumpAndSettle();
      expect(find.textContaining('overlaps another personal activity'),
          findsOneWidget);
      expect(tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
          isNull);
      expect(tester.takeException(), isNull);
    });
  }
}
