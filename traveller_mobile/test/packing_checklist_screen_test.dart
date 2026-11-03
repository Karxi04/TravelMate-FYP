import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/packing_models.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/packing_checklist_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/packing_trip_selector_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockPackingApi extends ApiService {
  final bool standalone;
  Map<String, dynamic> checklistData;
  final List<Map<String, dynamic>> trips;
  int? forceStatusCode;
  String? forceErrorMessage;

  final List<Map<String, dynamic>> postCalls = [];
  final List<Map<String, dynamic>> patchCalls = [];
  int getCalls = 0;

  _MockPackingApi({
    this.standalone = false,
    Map<String, dynamic>? initialData,
    List<Map<String, dynamic>>? tripsData,
  })  : checklistData = initialData ?? _sampleReadyData(),
        trips = tripsData ?? [
          {
            'id': 'trip_penang_1',
            'title': 'Penang Cultural Holiday',
            'destination': 'Penang',
            'destinationCity': 'George Town',
            'startDate': '2026-11-20',
            'endDate': '2026-11-23',
            'durationDays': 4,
          }
        ];

  @override
  bool get isStandalone => standalone;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    getCalls++;
    if (forceStatusCode != null) {
      throw ApiException(forceErrorMessage ?? 'Error', forceStatusCode!, {});
    }
    if (path == '/api/fr5/itineraries') {
      return {'ok': true, 'items': trips};
    }
    if (path.contains('/packing-checklist')) {
      return Map<String, dynamic>.from(checklistData);
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postCalls.add({'path': path, 'body': body});
    if (forceStatusCode != null) {
      throw ApiException(forceErrorMessage ?? 'Error', forceStatusCode!, {});
    }
    if (path.contains('/packing-checklist')) {
      final action = body?['action'];
      if (action == 'generate') {
        checklistData = _sampleReadyData();
        return Map<String, dynamic>.from(checklistData);
      }
      if (action == 'refresh') {
        final expectedRev = body?['expectedRevision'] as int? ?? 1;
        final currentRev = (checklistData['checklist']?['revision'] as int?) ?? 1;
        if (expectedRev != currentRev) {
          throw const ApiException('Revision conflict', 409, {'currentRevision': 2});
        }
        checklistData['needsRefresh'] = false;
        checklistData['checklist']['revision'] = currentRev + 1;
        return Map<String, dynamic>.from(checklistData);
      }
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) async {
    patchCalls.add({'path': path, 'body': body});
    if (forceStatusCode != null) {
      throw ApiException(forceErrorMessage ?? 'Error', forceStatusCode!, {});
    }
    if (path.contains('/packing-checklist')) {
      final expectedRev = body?['expectedRevision'] as int? ?? 1;
      final currentRev = (checklistData['checklist']?['revision'] as int?) ?? 1;
      if (expectedRev != currentRev) {
        throw const ApiException('Revision conflict', 409, {'currentRevision': 2});
      }

      final action = body?['action'];
      final items = List<Map<String, dynamic>>.from(
        (checklistData['checklist']['items'] as List).map((i) => Map<String, dynamic>.from(i)),
      );

      if (action == 'update') {
        final itemId = body?['itemId'];
        final index = items.indexWhere((i) => i['itemId'] == itemId);
        if (index >= 0) {
          if (body!.containsKey('isPacked')) items[index]['isPacked'] = body['isPacked'];
          if (body.containsKey('quantity')) items[index]['quantity'] = body['quantity'];
          if (body.containsKey('name')) items[index]['name'] = body['name'];
          if (body.containsKey('category')) items[index]['category'] = body['category'];
        }
      } else if (action == 'add') {
        items.add({
          'itemId': body?['itemId'] ?? 'custom_new',
          'name': body?['name'] ?? 'New Item',
          'category': body?['category'] ?? 'miscellaneous',
          'quantity': body?['quantity'] ?? 1,
          'isPacked': false,
          'isCustom': true,
          'source': 'user',
          'reason': 'Added by user.',
          'suppressed': false,
          'applicable': true,
        });
      } else if (action == 'remove') {
        final itemId = body?['itemId'];
        final index = items.indexWhere((i) => i['itemId'] == itemId);
        if (index >= 0) {
          if (items[index]['isCustom'] == true) {
            items.removeAt(index);
          } else {
            items[index]['suppressed'] = true;
          }
        }
      } else if (action == 'restore') {
        final itemId = body?['itemId'];
        final index = items.indexWhere((i) => i['itemId'] == itemId);
        if (index >= 0) {
          items[index]['suppressed'] = false;
        }
      }

      checklistData['checklist']['items'] = items;
      checklistData['checklist']['revision'] = currentRev + 1;

      // Update progress
      final active = items.where((i) => i['suppressed'] != true && i['applicable'] != false).toList();
      final packed = active.where((i) => i['isPacked'] == true).length;
      checklistData['progress'] = {
        'totalItems': active.length,
        'packedItems': packed,
        'unpackedItems': active.length - packed,
        'completionPercentage': active.isEmpty ? 0.0 : ((packed / active.length) * 100).toDouble(),
      };

      return Map<String, dynamic>.from(checklistData);
    }
    return {'ok': true};
  }
}

Map<String, dynamic> _sampleNotGeneratedData() => {
      'ok': true,
      'state': 'not_generated',
      'message': 'No packing checklist exists yet for this trip.',
      'categories': [
        {'id': 'documents', 'name': 'Travel Documents'},
        {'id': 'clothing', 'name': 'Clothing'},
        {'id': 'personal_care', 'name': 'Personal Care & Toiletries'},
        {'id': 'electronics', 'name': 'Electronics'},
        {'id': 'activity', 'name': 'Activity Essentials'},
        {'id': 'weather', 'name': 'Weather Essentials'},
        {'id': 'miscellaneous', 'name': 'Miscellaneous'},
      ],
      'progress': {'totalItems': 0, 'packedItems': 0, 'unpackedItems': 0, 'completionPercentage': 0.0},
    };

Map<String, dynamic> _sampleReadyData({
  bool needsRefresh = false,
  bool weatherUnavailable = false,
}) =>
    {
      'ok': true,
      'state': 'ready',
      'needsRefresh': needsRefresh,
      'checklist': {
        'tripId': 'trip_penang_1',
        'schemaVersion': 1,
        'ruleVersion': 1,
        'revision': 1,
        'tripContext': {
          'destination': 'Penang',
          'startDate': '2026-11-20',
          'endDate': '2026-11-23',
          'durationDays': 4,
          'international': false,
        },
        'weatherContext': weatherUnavailable
            ? {
                'status': 'unavailable',
                'source': null,
                'dates': [],
                'message': 'Current trip weather is unavailable; weather items are general precautions.',
              }
            : {
                'status': 'forecast_applied',
                'source': 'openweathermap',
                'dates': ['2026-11-20', '2026-11-21', '2026-11-22', '2026-11-23'],
                'message': 'Warm tropical weather expected (28°C–32°C). Light rain possible.',
              },
        'items': [
          {
            'itemId': 'travel_documents',
            'name': 'Identification & Bookings',
            'category': 'documents',
            'quantity': 1,
            'isPacked': false,
            'isCustom': false,
            'source': 'general',
            'reason': 'General travel documents.',
            'suppressed': false,
            'applicable': true,
          },
          {
            'itemId': 'clothing_changes',
            'name': 'Clothing changes',
            'category': 'clothing',
            'quantity': 4,
            'isPacked': false,
            'isCustom': false,
            'source': 'trip',
            'reason': 'One change per day for 4-day trip.',
            'suppressed': false,
            'applicable': true,
          },
          {
            'itemId': 'power_bank',
            'name': 'Power bank',
            'category': 'electronics',
            'quantity': 1,
            'isPacked': false,
            'isCustom': false,
            'source': 'general',
            'reason': 'For charging mobile devices on the move.',
            'suppressed': false,
            'applicable': true,
          },
        ],
      },
      'categories': [
        {'id': 'documents', 'name': 'Travel Documents'},
        {'id': 'clothing', 'name': 'Clothing'},
        {'id': 'personal_care', 'name': 'Personal Care & Toiletries'},
        {'id': 'electronics', 'name': 'Electronics'},
        {'id': 'activity', 'name': 'Activity Essentials'},
        {'id': 'weather', 'name': 'Weather Essentials'},
        {'id': 'miscellaneous', 'name': 'Miscellaneous'},
      ],
      'progress': {
        'totalItems': 3,
        'packedItems': 0,
        'unpackedItems': 3,
        'completionPercentage': 0.0,
      },
      'weatherContext': weatherUnavailable
          ? {
              'status': 'unavailable',
              'source': null,
              'dates': [],
              'message': 'Current trip weather is unavailable; weather items are general precautions.',
            }
          : {
              'status': 'forecast_applied',
              'source': 'openweathermap',
              'dates': ['2026-11-20', '2026-11-21', '2026-11-22', '2026-11-23'],
              'message': 'Warm tropical weather expected (28°C–32°C). Light rain possible.',
            },
    };

void main() {
  Widget wrap(Widget child) => MaterialApp(
        home: Scaffold(body: child),
      );

  group('Packing Models & DTO Unit Tests', () {
    test('PackingItem parsing and json serialization', () {
      final json = {
        'itemId': 'sunscreen',
        'name': 'Sunscreen SPF 50+',
        'category': 'personal_care',
        'quantity': 2,
        'isPacked': true,
        'isCustom': false,
        'source': 'activity',
        'reason': 'Outdoor island activities.',
        'suppressed': false,
        'applicable': true,
      };

      final item = PackingItem.fromJson(json);
      expect(item.itemId, 'sunscreen');
      expect(item.name, 'Sunscreen SPF 50+');
      expect(item.category, 'personal_care');
      expect(item.quantity, 2);
      expect(item.isPacked, isTrue);
      expect(item.isCustom, isFalse);
      expect(item.suppressed, isFalse);

      final out = item.toJson();
      expect(out['itemId'], 'sunscreen');
      expect(out['quantity'], 2);
      expect(out['isPacked'], isTrue);
    });

    test('PackingProgress parsing and completion percentage calculation', () {
      final p1 = PackingProgress.fromJson({
        'totalItems': 10,
        'packedItems': 5,
        'unpackedItems': 5,
        'completionPercentage': 50.0,
      });
      expect(p1.totalItems, 10);
      expect(p1.packedItems, 5);
      expect(p1.completionPercentage, 50.0);

      final p0 = PackingProgress.fromJson({'totalItems': 0, 'packedItems': 0});
      expect(p0.completionPercentage, 0.0);
    });

    test('PackingChecklist filters active and suppressed items correctly', () {
      final checklist = PackingChecklist.fromJson({
        'tripId': 'trip_1',
        'revision': 1,
        'items': [
          {'itemId': 'i1', 'name': 'Item 1', 'category': 'clothing', 'suppressed': false, 'applicable': true},
          {'itemId': 'i2', 'name': 'Item 2', 'category': 'clothing', 'suppressed': true, 'applicable': true},
          {'itemId': 'i3', 'name': 'Item 3', 'category': 'clothing', 'suppressed': false, 'applicable': false},
        ],
      });

      expect(checklist.activeItems.length, 1);
      expect(checklist.activeItems.first.itemId, 'i1');
      expect(checklist.suppressedItems.length, 1);
      expect(checklist.suppressedItems.first.itemId, 'i2');
    });

    test('PackingChecklistResponse parses synthetic backend DTO example', () {
      final sample = _sampleReadyData();
      final res = PackingChecklistResponse.fromJson(sample);
      expect(res.isReady, isTrue);
      expect(res.categories.length, 7);
      expect(res.checklist?.items.length, 3);
      expect(res.progress.totalItems, 3);
      expect(res.weatherContext.status, 'forecast_applied');
    });
  });

  group('Packing Checklist Screen UI & Workflow Tests', () {
    testWidgets('Displays not generated state and triggers generation action', (tester) async {
      final api = _MockPackingApi(initialData: _sampleNotGeneratedData());

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Packing Checklist for Penang Cultural Holiday'), findsOneWidget);
      expect(find.text('Generate Checklist'), findsOneWidget);

      await tester.tap(find.text('Generate Checklist'));
      await tester.pumpAndSettle();

      expect(api.postCalls.length, 1);
      expect(api.postCalls.first['body']?['action'], 'generate');
      expect(find.text('Identification & Bookings'), findsOneWidget);
      expect(find.text('Clothing changes'), findsOneWidget);
      expect(find.text('Power bank'), findsOneWidget);
    });

    testWidgets('Renders progress bar, categories, and items', (tester) async {
      final api = _MockPackingApi();

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      // Header and progress
      expect(find.text('Penang Cultural Holiday'), findsOneWidget);
      expect(find.textContaining('0 of 3 Items Packed'), findsOneWidget);

      // Categories
      expect(find.text('Travel Documents'), findsOneWidget);
      expect(find.text('Clothing'), findsOneWidget);
      expect(find.text('Electronics'), findsOneWidget);
    });

    testWidgets('Toggling item checkbox updates packed status and progress', (tester) async {
      final api = _MockPackingApi();

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      final checkbox = find.byType(Checkbox).first;
      await tester.tap(checkbox);
      await tester.pumpAndSettle();

      expect(api.patchCalls.length, 1);
      expect(api.patchCalls.first['body']?['action'], 'update');
      expect(api.patchCalls.first['body']?['isPacked'], isTrue);
      expect(find.textContaining('1 of 3 Items Packed'), findsOneWidget);
    });

    testWidgets('Adding custom item with validation and category selection', (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);

      final api = _MockPackingApi();

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      // Tap Add Item button (FloatingActionButton)
      await tester.tap(find.byType(FloatingActionButton));
      await tester.pumpAndSettle();

      expect(find.text('Add Custom Item'), findsOneWidget);

      // Tap submit with empty name to check validation
      await tester.tap(find.text('Add to Checklist'));
      await tester.pump();
      expect(find.text('Enter an item name'), findsOneWidget);

      // Enter HTML markup to check sanitization validation
      await tester.enterText(find.byType(TextFormField), '<b>Malaysian Ringgit</b>');
      await tester.tap(find.text('Add to Checklist'));
      await tester.pump();
      expect(find.text('HTML markup is not allowed'), findsOneWidget);

      // Enter clean valid item name
      await tester.enterText(find.byType(TextFormField), 'Snorkel Gear');
      await tester.tap(find.text('Add to Checklist'));
      await tester.pumpAndSettle();

      expect(api.patchCalls.any((call) => call['body']?['action'] == 'add'), isTrue);
      final addCall = api.patchCalls.firstWhere((call) => call['body']?['action'] == 'add');
      expect(addCall['body']?['name'], 'Snorkel Gear');
      expect(find.text('Snorkel Gear'), findsOneWidget);
      expect(find.text('Custom'), findsOneWidget);
    });

    testWidgets('Suppressing and restoring generated suggestions', (tester) async {
      final api = _MockPackingApi();

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Identification & Bookings'), findsOneWidget);

      // Open item menu for first item
      final menuButtons = find.byIcon(Icons.more_vert_rounded);
      expect(menuButtons, findsWidgets);
      await tester.tap(menuButtons.first);
      await tester.pumpAndSettle();

      // Tap Hide suggestion
      expect(find.text('Hide suggestion'), findsOneWidget);
      await tester.tap(find.text('Hide suggestion'));
      await tester.pumpAndSettle();

      // Verify remove patch was sent
      expect(api.patchCalls.any((c) => c['body']?['action'] == 'remove'), isTrue);

      // Item should now be in suppressed section
      expect(find.textContaining('Hidden suggestions (1)'), findsOneWidget);

      // Expand accordion
      await tester.tap(find.textContaining('Hidden suggestions (1)'));
      await tester.pumpAndSettle();

      // Tap Restore
      expect(find.text('Restore'), findsOneWidget);
      await tester.tap(find.text('Restore'));
      await tester.pumpAndSettle();

      // Verify restore patch call
      expect(api.patchCalls.any((c) => c['body']?['action'] == 'restore'), isTrue);
      expect(find.text('Identification & Bookings'), findsOneWidget);
    });

    testWidgets('Itinerary changed refresh banner triggers refreshSuggestions', (tester) async {
      final api = _MockPackingApi(initialData: _sampleReadyData(needsRefresh: true));

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Itinerary Changed'), findsOneWidget);
      expect(find.text('Refresh Suggestions'), findsOneWidget);

      await tester.tap(find.text('Refresh Suggestions'));
      await tester.pumpAndSettle();

      expect(api.postCalls.any((c) => c['body']?['action'] == 'refresh'), isTrue);
      expect(find.text('Itinerary Changed'), findsNothing);
    });

    testWidgets('Optimistic concurrency 409 reloads state without crash', (tester) async {
      final api = _MockPackingApi();

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      // Force conflict on next mutation
      api.forceStatusCode = 409;
      api.forceErrorMessage = 'Revision conflict';

      final checkbox = find.byType(Checkbox).first;
      await tester.tap(checkbox);
      await tester.pump();

      // Shows conflict snackbar/notification
      expect(find.textContaining('Checklist changed on server'), findsOneWidget);

      // Clears conflict error and reloads
      api.forceStatusCode = null;
      await tester.pumpAndSettle();
      expect(find.text('Identification & Bookings'), findsOneWidget);
    });

    testWidgets('Service unavailable 503 error shows friendly retry state', (tester) async {
      final api = _MockPackingApi();
      api.forceStatusCode = 503;
      api.forceErrorMessage = 'Service temporarily unavailable';

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Checklist unavailable'), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);

      api.forceStatusCode = null;
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.text('Identification & Bookings'), findsOneWidget);
    });

    testWidgets('Trip unavailable 404 error shows friendly not found state', (tester) async {
      final api = _MockPackingApi();
      api.forceStatusCode = 404;
      api.forceErrorMessage = 'Trip not found';

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_missing_999',
        api: api,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Trip Unavailable'), findsOneWidget);
      expect(find.text('Go back'), findsOneWidget);
    });

    testWidgets('Weather context unavailable advisory notice is displayed', (tester) async {
      final api = _MockPackingApi(initialData: _sampleReadyData(weatherUnavailable: true));

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      expect(find.textContaining('Current trip weather is unavailable'), findsOneWidget);
    });

    testWidgets('Standalone mode disables mutations and displays notice', (tester) async {
      final api = _MockPackingApi(standalone: true);

      await tester.pumpWidget(wrap(PackingChecklistScreen(
        tripId: 'trip_penang_1',
        tripTitle: 'Penang Cultural Holiday',
        api: api,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Connection Required'), findsOneWidget);
      expect(find.byType(FloatingActionButton), findsNothing);
    });
  });

  group('Packing Trip Selector Screen Tests', () {
    testWidgets('Lists user trips and navigates to PackingChecklistScreen on tap', (tester) async {
      final api = _MockPackingApi(tripsData: [
        {
          'id': 'trip_penang_100',
          'title': 'Penang Heritage Getaway',
          'destination': 'Penang',
          'destinationCity': 'George Town',
          'startDate': '2026-11-20',
          'endDate': '2026-11-23',
          'durationDays': 4,
        }
      ]);

      await tester.pumpWidget(wrap(PackingTripSelectorScreen(api: api)));
      await tester.pumpAndSettle();

      expect(find.text('Select Trip for Packing'), findsOneWidget);
      expect(find.text('Penang Heritage Getaway'), findsOneWidget);

      await tester.tap(find.text('Penang Heritage Getaway'));
      await tester.pumpAndSettle();

      // Navigated to checklist
      expect(find.byType(PackingChecklistScreen), findsOneWidget);
    });

    testWidgets('Empty trips state guides user to plan a trip first', (tester) async {
      final api = _MockPackingApi(tripsData: []);

      await tester.pumpWidget(wrap(PackingTripSelectorScreen(api: api)));
      await tester.pumpAndSettle();

      expect(find.text('No Saved Trips Found'), findsOneWidget);
      expect(find.text('Plan a Trip'), findsOneWidget);
    });
  });
}
