import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/database_chat_cards.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';
import 'chat_action_audit_test.dart'
    show ActionApi, copy, frame, tap, reveal, fullPackage;

Map<String, dynamic> card() => {
      'id': 'p1',
      'title': 'Actual public package',
      'destination': 'Penang',
      'durationDays': 2,
      'operatorName': 'Approved operator',
      'inclusions': ['Private transport'],
      'serviceInclusions': {
        'accommodation': false,
        'transport': true,
        'guideActivities': null
      },
      'chatQuote': {
        'originalSubtotal': 500,
        'promotionDiscount': 75,
        'finalPayable': 425,
        'currency': 'MYR',
        'priceBasis': 'per_person',
        'taxIncluded': true,
        'promotion': {
          'id': 'c1',
          'campaignTitle': 'Approved saving',
          'startDate': '2020-01-01',
          'endDate': '2099-01-01',
          'termsConditions': 'Actual approved terms'
        }
      },
      'quoteContext': {
        'isReference': false,
        'partyKnown': true,
        'dateKnown': true,
        'participants': {'adults': 2, 'children': 1},
        'departureDate': '2030-12-12'
      }
    };

class DatabaseApi extends ActionApi {
  bool stale = false, unavailable = false;
  Completer<dynamic>? detailsGate;
  @override
  bool get isStandalone => false;
  DatabaseApi() {
    sessions = [
      {
        'id': 'db-session',
        'title': 'Packages',
        'planningState': {'commerceRevision': 4},
        'messages': [
          {
            'message': 'Find packages',
            'reply': 'Verified results',
            'packages': [card()]
          }
        ]
      }
    ];
  }
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr11/packages/p1') {
      gets.add(path);
      if (detailsGate != null) return detailsGate!.future;
      if (unavailable) throw const ApiException('No longer available', 404, {});
      return {'ok': true, 'package': fullPackage('p1')};
    }
    return super.get(path, query);
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (stale && path == '/api/fr11/chat') {
      posts.add({'path': path, 'body': copy(body!)});
      sessions.first['planningState'] = {'commerceRevision': 5};
      throw const ApiException('Stale', 409, {'code': 'stale_chat_context'});
    }
    return super.post(path, body);
  }
}

void main() {
  testWidgets('tap retrieves complete current package and carries party/date',
      (tester) async {
    final api = DatabaseApi();
    await frame(tester, ChatTab(api: api), width: 360);
    await tap(tester, find.byKey(const ValueKey('chat-package-p1')));
    final details = tester.widget<TourismPackageDetailsScreen>(
        find.byType(TourismPackageDetailsScreen));
    expect(details.item['fullDescription'], 'Full public description p1');
    expect(details.initialAdults, 2);
    expect(details.initialChildren, 1);
    expect(details.initialDepartureDate, '2030-12-12');
    expect(api.gets, contains('/api/fr11/packages/p1'));
    expect(api.gets, isNot(contains('/api/public/tourism-packages')));
    expect(api.posts, isEmpty);
    expect(tester.takeException(), isNull);
  });
  testWidgets('archived card cannot open stale details', (tester) async {
    final api = DatabaseApi()..unavailable = true;
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-package-p1')));
    expect(find.byType(TourismPackageDetailsScreen), findsNothing);
    expect(find.textContaining('No longer available'), findsWidgets);
    expect(api.posts, isEmpty);
  });
  testWidgets(
      'quote shows genuine totals and unknown inclusions at narrow width',
      (tester) async {
    final value = card();
    value['quoteContext']['isReference'] = true;
    value['quoteContext']['partyKnown'] = false;
    await frame(
        tester,
        Scaffold(
            body: SingleChildScrollView(
                child: DatabasePackageCard(package: value))),
        width: 320);
    for (final text in [
      'MYR 425.00',
      'MYR 500.00',
      'Reference party total',
      'Accommodation: Not included',
      'Transportation: Included',
      'Guide / activities: Unknown — review brochure'
    ]) {
      expect(find.text(text), findsOneWidget);
    }
    expect(find.textContaining('Approved saving'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('stale chat refreshes and sends revision', (tester) async {
    final api = DatabaseApi()..stale = true;
    await frame(tester, ChatTab(api: api));
    await tester.enterText(find.byType(TextField), 'Below RM600');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(api.posts.single['body']['commerceRevision'], 4);
    expect(find.textContaining('Review the refreshed chat'), findsWidgets);
    expect(
        api.gets.where((p) => p == '/api/fr11/sessions/db-session').length, 2);
  });
  testWidgets('owned statuses remain distinct and Saved Trips action works',
      (tester) async {
    final api = DatabaseApi();
    (api.sessions.first['messages'] as List).first.addAll({
      'packages': [],
      'ownedTrips': [
        {'title': 'My trip', 'startDate': '2030-12-12', 'endDate': '2030-12-13'}
      ],
      'ownedOrders': [
        {
          'title': 'My purchase',
          'orderId': 'owned-order',
          'amount': 425,
          'currency': 'MYR',
          'paymentStatus': 'paid',
          'statusOverview': {
            'travellerTrip': {'label': 'Created'},
            'operatorReadiness': {'label': 'Awaiting Arrangements'},
            'supplierArrangements': {'label': 'Pending'}
          }
        }
      ]
    });
    await frame(tester, ChatTab(api: api));
    await reveal(tester, find.text('Supplier arrangements: Pending'));
    expect(find.textContaining('Payment: paid'), findsOneWidget);
    expect(
        find.text('Operator readiness: Awaiting Arrangements'), findsOneWidget);
    await tap(tester, find.text('Open Saved Trips'));
    expect(find.byType(TripsTab), findsOneWidget);
    expect(api.posts, isEmpty);
  });
  test('standalone never fabricates quotes or a package itinerary', () async {
    final api = StandaloneApiService(uidOverride: 'a', memoryStore: {});
    final first = await api.post('/api/fr11/chat',
        {'message': 'Find discounted Penang packages', 'guidedPlanning': true});
    expect(first['reply'], contains('cannot be verified in standalone'));
    expect(first['item']['packages'], isNull);
    expect(first['item']['tripPlan'], isNull);
    final second = await api.post('/api/fr11/chat', {
      'sessionId': first['sessionId'],
      'message': 'Below RM600',
      'guidedPlanning': true
    });
    expect(second['reply'], contains('authenticated TravelMate backend'));
    final own = await api.post('/api/fr11/chat', {
      'sessionId': first['sessionId'],
      'message': 'Plan my own itinerary, not a tourism package',
      'guidedPlanning': true
    });
    expect(own['reply'], isNot(contains('cannot be verified in standalone')));
  });
  testWidgets(
      'booking summary reuses selected party and date in server quote only',
      (tester) async {
    final api = DatabaseApi();
    await frame(tester, ChatTab(api: api));
    await tap(tester, find.byKey(const ValueKey('chat-package-p1')));
    await tap(tester, find.byKey(const ValueKey('package-book-now-cta')));
    final body = api.posts.single['body'];
    expect(
        api.posts.single['path'], '/api/fr15/package-checkout-attempts/quote');
    expect(body['participants'], {'adults': 2, 'children': 1});
    expect(body['departureDate'], '2030-12-12');
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'UID-keyed account remount ignores previous pending package result',
      (tester) async {
    final old = DatabaseApi()..detailsGate = Completer<dynamic>();
    await frame(tester, ChatTab(key: const ValueKey('account-a'), api: old));
    await tap(tester, find.byKey(const ValueKey('chat-package-p1')));
    final other = ActionApi();
    await frame(tester, ChatTab(key: const ValueKey('account-b'), api: other));
    old.detailsGate!.complete({'ok': true, 'package': fullPackage('p1')});
    await tester.pumpAndSettle();
    expect(find.byType(TourismPackageDetailsScreen), findsNothing);
    expect(find.text('Actual public package'), findsNothing);
    expect(find.text('Verified results'), findsNothing);
    expect(other.posts, isEmpty);
  });
  test(
      'standalone saved trips use actual account scope and do not leak another account',
      () async {
    final memory = <String, String>{
      'travelmate_a_itineraries': jsonEncode([
        {'id': 'mine', 'title': 'Actual saved trip'}
      ])
    };
    final a = StandaloneApiService(uidOverride: 'a', memoryStore: memory);
    final b = StandaloneApiService(uidOverride: 'b', memoryStore: memory);
    final result = await a.post('/api/fr11/chat',
        {'message': 'Show my saved trips', 'guidedPlanning': true});
    expect(result['item']['ownedTrips'].single['id'], 'mine');
    expect(result['item']['tripPlan'], isNull);
    final other = await b.post('/api/fr11/chat',
        {'message': 'Show my saved trips', 'guidedPlanning': true});
    expect(other['item']['ownedTrips'], isEmpty);
    expect(other.toString(), isNot(contains('Actual saved trip')));
  });
}
