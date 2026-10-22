import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

Map<String, dynamic> _activity({
  required String id,
  required String name,
  required int day,
  required String start,
  required String end,
  required String category,
  required num cost,
  int travelMinutes = 0,
  double? distance,
  String travelSource = 'not_applicable',
}) =>
    {
      'activityId': id,
      'destinationId': 'destination_$id',
      'activityName': name,
      'dayNo': day,
      'dayDate': '2026-10-${24 + day}',
      'scheduledStartTime': start,
      'scheduledEndTime': end,
      'timeSlot': start,
      'timeRangeLabel': '$start - $end',
      'category': category,
      'recommendedDurationMinutes': 105,
      'durationSource': 'provider_catalog',
      'durationEstimated': false,
      'estimatedCost': cost,
      'travelDurationMinutes': travelMinutes,
      'travelDistanceKm': distance,
      'travelTimeSource': travelSource,
      'openingHoursStatus': 'open',
      'scheduleNotes': [
        'Scheduled earlier because this attraction closes at 5 PM.'
      ],
      'address': 'George Town, Penang',
    };

Map<String, dynamic> _richTrip({String status = 'planned'}) {
  final first = _activity(
    id: 'a1',
    name: 'Kek Lok Si Temple',
    day: 1,
    start: '09:30',
    end: '11:15',
    category: 'Culture',
    cost: 30,
  );
  final second = _activity(
    id: 'a2',
    name: 'Penang Hill',
    day: 1,
    start: '13:30',
    end: '15:30',
    category: 'Nature',
    cost: 56,
    travelMinutes: 18,
    distance: 7.2,
    travelSource: 'estimated_haversine',
  );
  final third = _activity(
    id: 'a3',
    name: 'George Town Night Market',
    day: 2,
    start: '18:00',
    end: '19:45',
    category: 'Food',
    cost: 40,
  );
  return {
    'id': 'trip_target',
    'title': 'Penang Getaway',
    'destinationArea': 'Penang, Malaysia',
    'startDate': '2026-10-25',
    'endDate': '2026-10-28',
    'tripDays': 3,
    'travellerCount': 2,
    'budgetLimit': 1000,
    'status': status,
    'recommendationGenerationId': 'rec_secret_internal_123',
    'activities': [first, second, third],
    'dailySchedule': [
      {
        'dayNo': 1,
        'dayDate': '2026-10-25',
        'activities': [first, second],
        'planningBlocks': [
          {
            'type': 'meal_rest',
            'label': 'Lunch and rest',
            'startTime': '12:30',
            'endTime': '13:30',
            'durationMinutes': 60,
            'estimated': true,
          }
        ],
        'weather': {
          'source': 'forecast',
          'description': 'Cloudy',
          'temperatureMax': 29,
          'heavyRainLikely': false,
        },
        'estimatedCost': 86,
      },
      {
        'dayNo': 2,
        'dayDate': '2026-10-26',
        'activities': [third],
        'planningBlocks': const <Map<String, dynamic>>[],
        'weather': {
          'source': 'unavailable',
          'message': 'Weather forecast unavailable for this date.',
        },
        'estimatedCost': 40,
      },
      {
        'dayNo': 3,
        'dayDate': '2026-10-27',
        'activities': const <Map<String, dynamic>>[],
        'planningBlocks': const <Map<String, dynamic>>[],
        'weather': {'source': 'unavailable'},
        'estimatedCost': 0,
      },
    ],
    'unscheduledSuggestions': [
      {
        'activityId': 'u1',
        'destinationId': 'penang_botanic_gardens',
        'activityName': 'Penang Botanic Gardens',
        'unscheduledReason':
            'Could not fit within available time, travel, and opening-hour constraints.',
      }
    ],
    'budgetEstimate': {
      'total': 720,
      'limit': 1000,
      'activities': 86,
      'food': 160,
      'transport': 90,
      'hotel': 290,
      'flight': 94,
      'costProvenance': {
        'activities': 'mixed_estimates',
        'food': 'estimated_daily_allowance',
        'transport': 'provided',
        'hotel': 'confirmed_total',
        'flight': 'confirmed',
      },
    },
  };
}

class _TripApi extends ApiService {
  final Map<String, dynamic> trip;
  int listReads = 0;
  int generationCalls = 0;
  int rearrangeCalls = 0;
  int deleteCalls = 0;
  int moveCalls = 0;
  int searchCalls = 0;
  final List<Map<String, dynamic>> activityPosts = [];
  List<Map<String, dynamic>> searchResults = [];
  Map<String, dynamic>? lastGenerationBody;
  Map<String, dynamic>? lastMoveBody;
  List<String> lastOrder = [];

  _TripApi({String status = 'planned'}) : trip = _richTrip(status: status) {
    if (status == 'generation_failed') {
      trip
        ..['retryable'] = true
        ..['generationFailureStage'] = 'budget_calculation'
        ..['lastGenerationError'] = 'Internal stack trace: budget exploded';
    }
  }

  void _syncDays() {
    final activities = (trip['activities'] as List).whereType<Map>().toList();
    for (final rawDay in (trip['dailySchedule'] as List).whereType<Map>()) {
      final day = rawDay as Map<String, dynamic>;
      final dayNo = day['dayNo'];
      day['activities'] = activities
          .where((item) => item['dayNo'] == dayNo)
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
    }
  }

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries') {
      listReads += 1;
      return {
        'ok': true,
        'items': [
          {'id': 'trip_decoy', 'title': 'Wrong trip'},
          trip,
        ],
      };
    }
    if (path == '/api/fr3/destinations/search') {
      searchCalls += 1;
      return {'ok': true, 'results': searchResults};
    }
    if (path.startsWith('/api/fr3/destinations/')) {
      return {
        'ok': true,
        'destination': {
          'destinationId': path.split('/').last,
          'title': 'Destination details',
        },
      };
    }
    if (path.endsWith('/budget')) {
      return {'ok': true, 'budget': trip['budgetEstimate']};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr5/itineraries/trip_target/activities') {
      activityPosts.add(Map<String, dynamic>.from(body ?? const {}));
      return {'ok': true, 'itinerary': trip};
    }
    if (path == '/api/fr5/itineraries/trip_target/generate') {
      generationCalls += 1;
      lastGenerationBody = Map<String, dynamic>.from(body ?? const {});
      trip
        ..['status'] = 'planned'
        ..['retryable'] = false
        ..remove('lastGenerationError')
        ..remove('generationFailureStage');
      return {'ok': true, 'status': 'planned', 'itinerary': trip};
    }
    if (path.endsWith('/activities/rearrange')) {
      rearrangeCalls += 1;
      lastOrder = (body?['orderedActivityIds'] as List? ?? const [])
          .map((value) => value.toString())
          .toList();
      final current = (trip['activities'] as List)
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
      trip['activities'] = lastOrder
          .map((id) => current.firstWhere((item) => item['activityId'] == id))
          .toList();
      _syncDays();
      return {'ok': true, 'itinerary': trip};
    }
    throw StateError('Unexpected POST $path');
  }

  @override
  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    if (path.contains('/activities/')) {
      moveCalls += 1;
      lastMoveBody = Map<String, dynamic>.from(body ?? const {});
      final id = path.split('/').last;
      final item = (trip['activities'] as List)
          .whereType<Map>()
          .firstWhere((activity) => activity['activityId'] == id);
      item['dayNo'] = body?['dayNo'];
      _syncDays();
      return {'ok': true, 'itinerary': trip};
    }
    throw StateError('Unexpected PUT $path');
  }

  @override
  Future<dynamic> delete(String path) async {
    if (path.contains('/activities/')) {
      deleteCalls += 1;
      final id = path.split('/').last;
      (trip['activities'] as List)
          .removeWhere((activity) => activity['activityId'] == id);
      _syncDays();
      return {'ok': true, 'itinerary': trip};
    }
    throw StateError('Unexpected DELETE $path');
  }
}

Future<void> _pumpTrip(
  WidgetTester tester,
  _TripApi api, {
  bool settle = true,
}) async {
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      home: TripDetailsScreen(tripId: 'trip_target', api: api),
    ),
  );
  if (settle) {
    await tester.pumpAndSettle();
  } else {
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _show(WidgetTester tester, Finder target) async {
  final scrollable = find.byKey(const ValueKey('trip-details-scroll'));
  for (var i = 0; i < 18 && target.evaluate().isEmpty; i++) {
    await tester.drag(scrollable, const Offset(0, -350));
    await tester.pump();
  }
  if (target.evaluate().isEmpty) {
    for (var i = 0; i < 18 && target.evaluate().isEmpty; i++) {
      await tester.drag(scrollable, const Offset(0, 350));
      await tester.pump();
    }
  }
  expect(target, findsWidgets);
  await tester.ensureVisible(target.first);
  await tester.pump();
}

Future<void> _scrollTripToTop(WidgetTester tester) async {
  final scrollable = find.byKey(const ValueKey('trip-details-scroll'));
  for (var i = 0; i < 12; i++) {
    await tester.drag(scrollable, const Offset(0, 500));
    await tester.pump();
  }
}

void main() {
  testWidgets('loads the exact trip and presents a traveller-friendly header',
      (tester) async {
    final api = _TripApi();
    await _pumpTrip(tester, api);

    expect(api.listReads, 1);
    expect(find.text('Penang Getaway'), findsOneWidget);
    expect(find.text('Penang, Malaysia'), findsWidgets);
    expect(find.text('25–28 Oct 2026'), findsOneWidget);
    expect(find.text('2 travellers'), findsOneWidget);
    expect(find.text('Planned'), findsOneWidget);
    expect(find.text('Wrong trip'), findsNothing);
    expect(find.text('rec_secret_internal_123'), findsNothing);
    expect(find.text('estimated_haversine'), findsNothing);
    expect(find.text('provider_catalog'), findsNothing);
    expect(find.text('openingHoursStatus'), findsNothing);
  });

  testWidgets('day switching shows weather, timeline, travel and rest blocks',
      (tester) async {
    await _pumpTrip(tester, _TripApi());

    expect(find.text('Cloudy · 29°C'), findsOneWidget);
    expect(find.text('RM 86 estimated'), findsOneWidget);
    await _show(tester, find.text('Kek Lok Si Temple'));
    expect(find.text('Kek Lok Si Temple'), findsOneWidget);
    await _show(tester, find.text('Penang Hill'));
    expect(find.text('Penang Hill'), findsOneWidget);
    await _show(tester, find.text('Lunch and rest'));
    expect(find.text('Lunch and rest'), findsOneWidget);
    await _show(tester, find.text('~18 min estimated · 7.2 km'));
    expect(find.text('~18 min estimated · 7.2 km'), findsOneWidget);
    await _scrollTripToTop(tester);
    await tester.tap(find.byKey(const ValueKey('trip-day-2')));
    await tester.pump();
    expect(find.text('Forecast unavailable'), findsOneWidget);
    await _show(tester, find.text('George Town Night Market'));
    expect(find.text('George Town Night Market'), findsOneWidget);
    expect(find.text('Kek Lok Si Temple'), findsNothing);
  });

  testWidgets('day cards merge saved images from current activity snapshots',
      (tester) async {
    final api = _TripApi();
    final current = (api.trip['activities'] as List).first as Map;
    current['imageUrl'] = 'https://images.example/kek-lok-si.jpg';
    final stored = ((api.trip['dailySchedule'] as List).first
        as Map)['activities'] as List;
    stored[0] = Map<String, dynamic>.from(stored.first as Map)
      ..['activityId'] = 'legacy-a1'
      ..remove('imageUrl');

    await _pumpTrip(tester, api);

    final image = tester
        .widgetList<TravelPlaceImage>(find.byType(TravelPlaceImage))
        .firstWhere(
            (widget) => widget.place['destinationId'] == 'destination_a1');
    expect(image.place['imageUrl'], 'https://images.example/kek-lok-si.jpg');
  });

  testWidgets('add-place flow preserves provider image fields in Trip request',
      (tester) async {
    final api = _TripApi();
    api.searchResults = [
      {
        'destinationId': 'provider_penang_hill',
        'title': 'Penang Hill',
        'address': 'Air Itam, Penang',
        'thumbnail': 'https://images.example/penang-hill-thumb.jpg',
        'photos': [
          {'image': 'https://images.example/penang-hill-full.jpg'}
        ],
      }
    ];
    await _pumpTrip(tester, api);
    await _show(tester, find.text('Edit itinerary'));
    await tester.tap(find.text('Edit itinerary'));
    await tester.pump();
    await _show(tester, find.text('Search and add places'));
    await tester.tap(find.text('Search and add places'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Penang Hill'));
    await tester.pump();
    await tester.tap(find.text('Add 1'));
    await tester.pumpAndSettle();

    expect(api.activityPosts, hasLength(1));
    expect(api.activityPosts.single['thumbnail'],
        'https://images.example/penang-hill-thumb.jpg');
    expect(api.activityPosts.single['photos'], [
      {'image': 'https://images.example/penang-hill-full.jpg'}
    ]);
  });

  testWidgets('budget and unscheduled suggestions use product language',
      (tester) async {
    await _pumpTrip(tester, _TripApi());

    await _show(tester, find.byKey(const ValueKey('trip-budget-progress')));
    expect(find.text('RM 720 of RM 1000 estimated'), findsOneWidget);
    expect(find.text('confirmed · RM 290'), findsOneWidget);
    expect(find.text('estimated · RM 160'), findsOneWidget);

    await _show(tester, find.text('Couldn’t fit into your schedule'));
    expect(find.text('Penang Botanic Gardens'), findsOneWidget);
    expect(
      find.text('It couldn’t fit within the available opening hours.'),
      findsOneWidget,
    );
    expect(find.textContaining('available time, travel'), findsNothing);
  });

  testWidgets('generating lifecycle state is intentional', (tester) async {
    await _pumpTrip(tester, _TripApi(status: 'generating'), settle: false);
    expect(find.text('Building itinerary'), findsOneWidget);
    expect(find.text('Building your itinerary…'), findsOneWidget);
    expect(find.textContaining('distance, opening hours and budget'),
        findsOneWidget);
  });

  testWidgets('draft lifecycle state is clear', (tester) async {
    await _pumpTrip(tester, _TripApi(status: 'draft'));
    expect(find.text('Draft'), findsOneWidget);
  });

  testWidgets('generation failure hides raw errors and retries its snapshot',
      (tester) async {
    final api = _TripApi(status: 'generation_failed');
    await _pumpTrip(tester, api);

    expect(find.text('Needs attention'), findsOneWidget);
    expect(find.text('Trip generation did not finish'), findsOneWidget);
    expect(find.textContaining('Your trip draft is safe'), findsOneWidget);
    expect(find.textContaining('Internal stack trace'), findsNothing);
    expect(find.textContaining('budget_calculation'), findsNothing);

    await tester.tap(find.text('Retry generation'));
    await tester.pumpAndSettle();
    expect(api.generationCalls, 1);
    expect(api.lastGenerationBody?['recommendationGenerationId'],
        'rec_secret_internal_123');
    expect(find.text('Planned'), findsOneWidget);
  });

  testWidgets('edit mode preserves reorder, move, remove and add operations',
      (tester) async {
    final api = _TripApi();
    await _pumpTrip(tester, api);
    await _show(tester, find.text('Edit itinerary'));
    await tester.tap(find.text('Edit itinerary'));
    await tester.pump();

    final reorderable = tester.widget<ReorderableListView>(
      find.byKey(const ValueKey('edit-itinerary-list')),
    );
    reorderable.onReorder(0, 2);
    await tester.pumpAndSettle();
    expect(api.rearrangeCalls, 1);
    expect(api.lastOrder.take(2), ['a2', 'a1']);
    expect(api.listReads, greaterThan(1));

    await _show(tester, find.byTooltip('Activity actions').first);
    await tester.tap(find.byTooltip('Activity actions').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Move to Day 2').first);
    await tester.pumpAndSettle();
    expect(api.moveCalls, 1);
    expect(api.lastMoveBody?['dayNo'], 2);
    await _scrollTripToTop(tester);
    await tester.tap(find.byKey(const ValueKey('trip-day-2')));
    await tester.pump();
    expect(find.text('Day 2 itinerary'), findsOneWidget);
    await _show(tester, find.text('Edit itinerary'));
    await tester.tap(find.text('Edit itinerary'));
    await tester.pump();

    await _show(tester, find.byTooltip('Activity actions').first);
    await tester.tap(find.byTooltip('Activity actions').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Remove activity').first);
    await tester.pumpAndSettle();
    expect(find.text('Remove this activity?'), findsOneWidget);
    await tester.tap(find.text('Remove'));
    await tester.pumpAndSettle();
    expect(api.deleteCalls, 1);

    await _show(tester, find.text('Search and add places'));
    await tester.tap(find.text('Search and add places'));
    await tester.pumpAndSettle();
    expect(find.byType(TripPlacePickerScreen), findsOneWidget);
    expect(api.searchCalls, 1);
  });
}
