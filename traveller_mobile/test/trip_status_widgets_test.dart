import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

class _MockTripsApi extends ApiService {
  final List<Map<String, dynamic>> trips;
  int getCalls = 0;

  _MockTripsApi({required this.trips});

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    getCalls++;
    if (path == '/api/fr5/itineraries') {
      return {'ok': true, 'items': trips};
    }
    if (path.startsWith('/api/fr5/itineraries/')) {
      final id = path.split('/').last;
      final found = trips.firstWhere(
        (t) => t['id'].toString() == id,
        orElse: () => trips.first,
      );
      return {'ok': true, 'itinerary': found};
    }
    throw StateError('Unexpected GET $path');
  }
}

Widget _wrap(Widget child) => MaterialApp(
      theme: buildInkWashTheme(),
      home: child,
    );

void main() {
  final refDate = DateTime(2026, 10, 22);

  final ongoingTrip = {
    'id': 'trip_ongoing',
    'title': 'Active Penang Trip',
    'destinationArea': 'George Town, Penang',
    'startDate': '2026-10-20',
    'endDate': '2026-10-25',
    'tripDays': 6,
    'status': 'planned',
    'activities': [
      {'activityName': 'Chew Jetty', 'dayNo': 1},
    ],
    'budgetEstimate': {'total': 850},
  };

  final plannedTrip = {
    'id': 'trip_planned',
    'title': 'Upcoming Penang Getaway',
    'destinationArea': 'Batu Ferringhi, Penang',
    'startDate': '2026-10-26',
    'endDate': '2026-10-28',
    'tripDays': 3,
    'status': 'planned',
    'activities': [
      {'activityName': 'Escape Theme Park', 'dayNo': 1},
    ],
    'budgetEstimate': {'total': 1200},
  };

  final expiredTrip = {
    'id': 'trip_expired',
    'title': 'Past Penang Holiday',
    'destinationArea': 'Penang Hill',
    'startDate': '2026-10-10',
    'endDate': '2026-10-14',
    'tripDays': 5,
    'status': 'planned',
    'activities': [
      {'activityName': 'Kek Lok Si', 'dayNo': 1},
    ],
    'budgetEstimate': {'total': 900},
  };

  final draftPlannedTrip = {
    'id': 'trip_draft_planned',
    'title': 'Draft Future Plan',
    'destinationArea': 'Penang',
    'startDate': '2026-11-01',
    'endDate': '2026-11-04',
    'tripDays': 4,
    'status': 'draft',
    'activities': <Map<String, dynamic>>[],
    'budgetEstimate': {'total': 500},
  };

  final historicalTrip = {
    'id': 'MBdcQ3NF1onYkCXivEaJ',
    'title': 'My Personalised Penang Trip',
    'destinationArea': 'Penang',
    'startDate': '2026-10-31',
    'endDate': '2026-11-03',
    'tripDays': 3,
    'status': 'planned',
    'activities': <Map<String, dynamic>>[],
    'scheduledActivityCount': 0,
    'budgetEstimate': {'total': 1200.0},
    'dailySchedule': [
      {
        'dayNo': 1,
        'dayDate': '2026-09-17', // Stale legacy date
        'activities': [
          {'activityName': 'Chew Jetty', 'timeSlot': '09:00', 'category': 'Heritage'},
          {'activityName': 'George Town Heritage Core', 'timeSlot': '11:00', 'category': 'Heritage'},
          {'activityName': 'Kek Lok Si Temple', 'timeSlot': '14:00', 'category': 'Sightseeing'},
          {'activityName': 'Wonderfood Museum', 'timeSlot': '16:30', 'category': 'Museum'},
        ],
      },
      {
        'dayNo': 2,
        'dayDate': '2026-09-18', // Stale legacy date
        'activities': [
          {'activityName': 'Wonderfood Museum', 'timeSlot': '09:30', 'category': 'Museum'},
          {'activityName': 'George Town Food Trail', 'timeSlot': '12:00', 'category': 'Food'},
          {'activityName': 'Esplanade & Fort Cornwallis Area', 'timeSlot': '15:00', 'category': 'Sightseeing'},
        ],
      },
      {
        'dayNo': 3,
        'dayDate': '2026-09-19', // Stale legacy date
        'activities': [
          {'activityName': 'Pinang Peranakan Mansion', 'timeSlot': '10:00', 'category': 'Heritage'},
          {'activityName': 'Penang Botanic Gardens', 'timeSlot': '13:00', 'category': 'Nature'},
          {'activityName': 'Penang Hill', 'timeSlot': '16:00', 'category': 'Scenic'},
        ],
      },
    ],
  };

  group('Trip Status Badges and Cards', () {
    testWidgets('renders Planned badge with calm blue info tone', (tester) async {
      final api = _MockTripsApi(trips: [plannedTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      final badge = find.byKey(const ValueKey('trip-status-trip_planned'));
      expect(badge, findsOneWidget);

      final chip = tester.widget<StatusChip>(badge);
      expect(chip.text, 'Planned');
      expect(chip.tone, AppStatusTone.info);
    });

    testWidgets('renders Ongoing badge with green success tone', (tester) async {
      final api = _MockTripsApi(trips: [ongoingTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      final badge = find.byKey(const ValueKey('trip-status-trip_ongoing'));
      expect(badge, findsOneWidget);

      final chip = tester.widget<StatusChip>(badge);
      expect(chip.text, 'Ongoing');
      expect(chip.tone, AppStatusTone.success);
    });

    testWidgets('renders Expired badge with neutral tone', (tester) async {
      final api = _MockTripsApi(trips: [expiredTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      final badge = find.byKey(const ValueKey('trip-status-trip_expired'));
      expect(badge, findsOneWidget);

      final chip = tester.widget<StatusChip>(badge);
      expect(chip.text, 'Expired');
      expect(chip.tone, AppStatusTone.neutral);
    });

    testWidgets('Draft trip renders both temporal badge and Draft badge without contradiction', (tester) async {
      final api = _MockTripsApi(trips: [draftPlannedTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('trip-status-trip_draft_planned')), findsOneWidget);
      expect(find.text('Draft'), findsOneWidget);
    });
  });

  group('Trips Filtering & Sorting', () {
    testWidgets('All filter displays Ongoing, Planned, and Expired in preferred order', (tester) async {
      tester.view.physicalSize = const Size(800, 2000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final api = _MockTripsApi(trips: [expiredTrip, plannedTrip, ongoingTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      // All trips present
      expect(find.text('Active Penang Trip'), findsOneWidget);
      expect(find.text('Upcoming Penang Getaway'), findsOneWidget);
      expect(find.text('Past Penang Holiday'), findsOneWidget);

      // Verify order on screen: Ongoing is first, then Planned, then Expired
      final ongoingPos = tester.getTopLeft(find.text('Active Penang Trip')).dy;
      final plannedPos = tester.getTopLeft(find.text('Upcoming Penang Getaway')).dy;
      final expiredPos = tester.getTopLeft(find.text('Past Penang Holiday')).dy;

      expect(ongoingPos, lessThan(plannedPos));
      expect(plannedPos, lessThan(expiredPos));
    });

    testWidgets('Planned filter isolates upcoming trips only', (tester) async {
      final api = _MockTripsApi(trips: [ongoingTrip, plannedTrip, expiredTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('filter-planned')));
      await tester.pumpAndSettle();

      expect(find.text('Upcoming Penang Getaway'), findsOneWidget);
      expect(find.text('Active Penang Trip'), findsNothing);
      expect(find.text('Past Penang Holiday'), findsNothing);
    });

    testWidgets('Ongoing filter isolates active trips only', (tester) async {
      final api = _MockTripsApi(trips: [ongoingTrip, plannedTrip, expiredTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('filter-ongoing')));
      await tester.pumpAndSettle();

      expect(find.text('Active Penang Trip'), findsOneWidget);
      expect(find.text('Upcoming Penang Getaway'), findsNothing);
      expect(find.text('Past Penang Holiday'), findsNothing);
    });

    testWidgets('Expired filter isolates past trips only', (tester) async {
      final api = _MockTripsApi(trips: [ongoingTrip, plannedTrip, expiredTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('filter-expired')));
      await tester.pumpAndSettle();

      expect(find.text('Past Penang Holiday'), findsOneWidget);
      expect(find.text('Active Penang Trip'), findsNothing);
      expect(find.text('Upcoming Penang Getaway'), findsNothing);
    });

    testWidgets('Filter changes do not trigger extra API network re-reads', (tester) async {
      final api = _MockTripsApi(trips: [ongoingTrip, plannedTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      expect(api.getCalls, 1);

      await tester.tap(find.byKey(const ValueKey('filter-planned')));
      await tester.pumpAndSettle();
      expect(api.getCalls, 1);

      await tester.tap(find.byKey(const ValueKey('filter-ongoing')));
      await tester.pumpAndSettle();
      expect(api.getCalls, 1);

      await tester.tap(find.byKey(const ValueKey('filter-all')));
      await tester.pumpAndSettle();
      expect(api.getCalls, 1);
    });

    testWidgets('Displays category-specific empty state when filter has zero matching trips', (tester) async {
      // Only planned trip exists
      final api = _MockTripsApi(trips: [plannedTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      // Tap Ongoing
      await tester.tap(find.byKey(const ValueKey('filter-ongoing')));
      await tester.pumpAndSettle();

      expect(find.text('No ongoing trips'), findsOneWidget);
      expect(find.textContaining('Trips taking place today will appear here automatically'), findsOneWidget);

      // Tap Expired
      await tester.tap(find.byKey(const ValueKey('filter-expired')));
      await tester.pumpAndSettle();

      expect(find.text('No expired trips'), findsOneWidget);
      expect(find.textContaining('Completed trips whose travel dates have passed'), findsOneWidget);
    });
  });

  group('Trip Details Temporal Status Consistency', () {
    testWidgets('Trip Details shows Ongoing status matching TripsTab card', (tester) async {
      final api = _MockTripsApi(trips: [ongoingTrip]);
      await tester.pumpWidget(
        _wrap(TripDetailsScreen(tripId: 'trip_ongoing', api: api, referenceDate: refDate)),
      );
      await tester.pumpAndSettle();

      final badge = find.byKey(const ValueKey('trip-temporal-status-chip'));
      expect(badge, findsOneWidget);

      final chip = tester.widget<StatusChip>(badge);
      expect(chip.text, 'Ongoing');
      expect(chip.tone, AppStatusTone.success);
    });

    testWidgets('Trip Details shows Expired status matching TripsTab card', (tester) async {
      final api = _MockTripsApi(trips: [expiredTrip]);
      await tester.pumpWidget(
        _wrap(TripDetailsScreen(tripId: 'trip_expired', api: api, referenceDate: refDate)),
      );
      await tester.pumpAndSettle();

      final badge = find.byKey(const ValueKey('trip-temporal-status-chip'));
      expect(badge, findsOneWidget);

      final chip = tester.widget<StatusChip>(badge);
      expect(chip.text, 'Expired');
      expect(chip.tone, AppStatusTone.neutral);
    });
  });

  group('Historical Trip Compatibility & Activity Counter Integrity', () {
    testWidgets('Historical Penang Trip MBdcQ3NF1onYkCXivEaJ is Planned and preserves 10 activities count', (tester) async {
      final api = _MockTripsApi(trips: [historicalTrip]);
      await tester.pumpWidget(_wrap(TripsTab(api: api, referenceDate: refDate)));
      await tester.pumpAndSettle();

      expect(find.text('My Personalised Penang Trip'), findsOneWidget);

      // 1. Authoritative temporal status is Planned (dates 31 Oct - 3 Nov are upcoming on 22 Oct)
      final badge = find.byKey(const ValueKey('trip-status-MBdcQ3NF1onYkCXivEaJ'));
      expect(badge, findsOneWidget);
      expect(tester.widget<StatusChip>(badge).text, 'Planned');

      // 2. Preserves 10 activities counter from dailySchedule
      expect(find.text('10 activities · RM 1200.0 estimated'), findsOneWidget);
    });
  });
}
