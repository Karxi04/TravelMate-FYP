import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/alternative_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/models/budget_model.dart';
import 'final_travel_workflows_test.dart' show app;

class EvidenceApi extends ApiService {
  final requests = <Map<String, dynamic>>[];
  Map<String, dynamic>? search;
  String reason = 'no_offers';
  bool reused = false;
  Completer<Map<String, dynamic>>? pending;
  final List<Map<String, dynamic>> timing = [];
  Map<String, dynamic> get state => {
        'ok': true,
        'stateVersion': 'revision-one',
        'budget': {'total': 1400, 'limit': 700, 'flight': 934, 'hotel': 300},
        'flightComparison': {
          'status': 'eligible',
          'originalCabin': 1,
          'reasons': []
        },
        'hotelComparison': {'status': 'eligible', 'reasons': []},
        'alternatives': [],
        'flightTimingPreviews': timing,
      };
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async => state;
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    requests.add({'path': path, 'body': body});
    if (path.endsWith('/discover')) {
      search = pending != null
          ? await pending!.future
          : {
              'searchId': 'owned-search',
              'status': 'completed',
              'providerReached': true,
              'requestsAttempted': 1,
              'candidateCount': reason == 'no_offers' ? 0 : 4,
              'validQuoteCount': reason == 'no_offers' ? 0 : 3,
              'cheaperCandidateCount': 0,
              'reasonCode': reason,
              'reused': reused,
            };
      return {'ok': true, 'search': search};
    }
    return {
      ...state,
      if (search != null &&
          (body?['searchIds'] as Map?)?['hotel'] == 'owned-search')
        'searches': {
          'hotel': {...search!, 'searchStatus': search!['status']}
        }
    };
  }
}

Widget screen(EvidenceApi api, {double scale = 1}) => app(
    AlternativeScreen(
        api: api,
        tripId: 'owned',
        budget: BudgetModel(
            accommodation: 300,
            food: 166,
            transportation: 0,
            activities: 0,
            flight: 934),
        userBudget: 700),
    scale: scale);

Future<void> searchHotel(WidgetTester tester) async {
  await tester.scrollUntilVisible(find.text('Find cheaper hotels'), 200);
  await tester.pump();
  await tester.tap(find.text('Find cheaper hotels'));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Search now'));
  await tester.pump();
}

void main() {
  testWidgets('initial saved comparison does not claim a provider search ran',
      (tester) async {
    final api = EvidenceApi();
    await tester.pumpWidget(screen(api));
    await tester.pumpAndSettle();
    expect(
        find.textContaining('Provider search has not started'), findsWidgets);
    expect(api.requests.where((row) => row['path'].endsWith('/discover')),
        isEmpty);
    expect(find.textContaining('No verified cheaper'), findsNothing);
  });

  for (final reason in [
    'no_offers',
    'no_cheaper_comparable_offers',
    'expired_quote',
    'quotes_rejected',
    'evidence_unavailable'
  ]) {
    testWidgets(
        'completed search distinguishes $reason and keeps exact search reference',
        (tester) async {
      final api = EvidenceApi()
        ..reason = reason
        ..reused = true;
      await tester.pumpWidget(screen(api));
      await tester.pumpAndSettle();
      await searchHotel(tester);
      await tester.pumpAndSettle();
      final expected = switch (reason) {
        'no_offers' => 'Provider search completed with no offers returned.',
        'no_cheaper_comparable_offers' =>
          'Provider search completed with no cheaper comparable offers.',
        'expired_quote' =>
          'Returned quotes expired before comparison. Search again for current evidence.',
        'evidence_unavailable' =>
          'This saved search has no candidate-count evidence. A fresh provider search is needed to establish availability.',
        _ =>
          'Provider offers were returned, but none qualified. Review rejection details.',
      };
      await tester.ensureVisible(find.text(expected));
      await tester.pump();
      expect(find.text(expected), findsOneWidget);
      expect(
          find.text('Reused saved search evidence; no new provider request.'),
          findsOneWidget);
      expect(api.requests.last['body']['searchIds']['hotel'], 'owned-search');
      expect(
          api.requests.where((row) => row['path'].endsWith('/discover')).length,
          1);
      expect(
          api.requests.where((row) => row['path'].endsWith('/apply')), isEmpty);
    });
  }

  for (final width in [320.0, 360.0, 390.0]) {
    testWidgets(
        'grouped timing choices remain distinct at ${width}dp and enlarged text',
        (tester) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = EvidenceApi();
      for (final price in [420, 500])
        api.timing.add({
          'currentCost': 934,
          'proposedCost': price,
          'reason': 'Required visit cannot fit after arrival.',
          'affectedDays': [1],
          'proposedFlight': {
            'airline': 'Airline $price',
            'outboundSegments': [
              {
                'flightNumber': 'MH$price',
                'departureTime': '10:50',
                'arrivalTime': '11:50'
              }
            ]
          },
          'itineraryChanges': [
            {'activityName': 'Required visit', 'kind': 'unscheduled'}
          ],
        });
      await tester.pumpWidget(screen(api, scale: 1.6));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
          find.text('Unavailable options · details'), 150);
      await tester.pump();
      await tester.tap(find.text('Unavailable options · details'));
      await tester.pumpAndSettle();
      expect(find.text('Required visit cannot fit after arrival.'),
          findsOneWidget);
      expect(find.text('Review timing'), findsNWidgets(2));
      await tester.ensureVisible(find.text('Review timing').last);
      await tester.pump();
      await tester.tap(find.text('Review timing').last);
      await tester.pumpAndSettle();
      expect(find.text('Required visit — unscheduled'), findsOneWidget);
      expect(find.text('Confirm change'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
      'pending provider search disables repeat submission and refresh replay',
      (tester) async {
    final api = EvidenceApi()..pending = Completer<Map<String, dynamic>>();
    await tester.pumpWidget(screen(api));
    await tester.pumpAndSettle();
    await searchHotel(tester);
    await tester.pump();
    expect(
        api.requests.where((row) => row['path'].endsWith('/discover')).length,
        1);
    expect(
        tester
            .widget<OutlinedButton>(
                find.widgetWithText(OutlinedButton, 'Searching…'))
            .onPressed,
        isNull);
    api.pending!.complete({
      'searchId': 'owned-search',
      'status': 'unavailable',
      'providerReached': true,
      'requestsAttempted': 1,
      'failureCode': 'provider_timeout'
    });
    await tester.pumpAndSettle();
    expect(
        find.textContaining('The provider search timed out.'), findsOneWidget);
    expect(
        api.requests.where((row) => row['path'].endsWith('/discover')).length,
        1);
  });
}
