import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/alternative_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/planning_settings_sheet.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'flexible_planning_test.dart' show PlanningApi, app, reveal;
import 'alternative_search_regressions_test.dart'
    show EvidenceApi, screen, searchHotel;

class UpdatedTripApi extends EvidenceApi {
  String revision = 'revision-one';
  @override
  Map<String, dynamic> get state => {...super.state, 'stateVersion': revision};
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    final result = await super.post(path, body);
    if (path.endsWith('/discover')) revision = 'revision-two';
    return result;
  }
}

Future<void> settings(
    WidgetTester tester, PlanningApi api, double scale) async {
  await tester.pumpWidget(app(
      Builder(
          builder: (context) => TextButton(
              onPressed: () =>
                  PlanningSettingsSheet.show(context, api, api.trip),
              child: const Text('Settings'))),
      scale: scale));
  await tester.tap(find.text('Settings'));
  await tester.pumpAndSettle();
  await reveal(tester, 'Travel schedule');
  await tester.tap(find.text('Travel schedule'));
  await tester.pumpAndSettle();
}

Map<String, dynamic> recommendation(
        {bool evaluation = false, bool peers = true}) =>
    {
      'destinationId': 'isolated-nature',
      'title': 'A long attraction name in Penang, Malaysia',
      'finalScore': 77.5,
      'hybridRankingScore': 77.5,
      'personalSuitabilityScore': 91.0,
      'scoringVersion': 'recovery_v3',
      'matchedInterests': ['Nature', 'Photography'],
      'scoreBreakdown': {
        'content': 80.0,
        'collaborative': 75.0,
        'popularity': 70.0
      },
      'collaborativeConfidence': peers ? 1.0 : 0.0,
      'collaborativeRatingCount': peers ? 3 : 0,
      'rawCollaborativeScore': peers ? 75.0 : 50.0,
      'popularitySource': evaluation
          ? 'demonstration_approved_reviews'
          : 'genuine_approved_local_reviews',
      'popularityEvidence': {
        'source': evaluation
            ? 'demonstration_approved_reviews'
            : 'genuine_approved_local_reviews',
        'rating': 3.5,
        'reviewCount': 8
      },
      if (evaluation) ...{
        'synthetic': true,
        'recommendationEvidenceMode': 'fyp_evaluation'
      },
    };

void main() {
  testWidgets(
      'saved supplier receipt survives changed Trip state without another provider search',
      (tester) async {
    final api = UpdatedTripApi()..reason = 'no_cheaper_comparable_offers';
    await tester.pumpWidget(screen(api));
    await tester.pumpAndSettle();
    await searchHotel(tester);
    await tester.pumpAndSettle();
    expect(api.requests.last['body']['searchIds']['hotel'], 'owned-search');
    expect(
        api.requests.where((row) => row['path'].endsWith('/discover')).length,
        1);
    expect(
        api.requests.where((row) => row['path'].endsWith('/apply')), isEmpty);
    expect(find.byType(AlternativeScreen), findsOneWidget);
  });

  for (final width in [320.0, 360.0, 390.0]) {
    for (final scale in [1.0, 1.6]) {
      testWidgets(
          'transport estimates remain readable at $width scale $scale through pickers and keyboard',
          (tester) async {
        tester.view.physicalSize = Size(width, 850);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final api = PlanningApi();
        api.trip['travelDayPreferences'] = {
          'transport': {
            'arrivalDate': '2027-12-12',
            'arrivalTime': '10:00',
            'departureDate': '2027-12-16',
            'departureTime': '20:00',
            'bufferMinutes': 30
          }
        };
        await settings(tester, api, scale);
        for (final field in [
          'arrival-date',
          'arrival-time',
          'departure-date',
          'departure-time'
        ]) {
          final button = find.byKey(ValueKey('transport-$field'));
          await tester.ensureVisible(button);
          await tester.pump();
          final rect = tester.getRect(button);
          expect(rect.left, greaterThanOrEqualTo(0));
          expect(rect.right, lessThanOrEqualTo(width));
        }
        final arrival = find.byKey(const ValueKey('transport-arrival-date'));
        await tester.ensureVisible(arrival);
        await tester.pump();
        await tester.tap(arrival);
        await tester.pumpAndSettle();
        await tester.tap(find.descendant(
            of: find.byType(DatePickerDialog), matching: find.text('Cancel')));
        await tester.pumpAndSettle();
        expect(find.text('2027-12-12'), findsOneWidget);
        final clear = find.byKey(const ValueKey('clear-arrival-estimate'));
        await tester.ensureVisible(clear);
        await tester.pump();
        await tester.tap(clear);
        await tester.pumpAndSettle();
        expect(find.text('2027-12-16'), findsOneWidget);
        expect(find.text('20:00'), findsOneWidget);
        final extra = find.byKey(const ValueKey('extra-travel-time'));
        await tester.ensureVisible(extra);
        await tester.pump();
        await tester.enterText(extra, '45');
        tester.view.viewInsets = const FakeViewPadding(bottom: 300);
        addTearDown(tester.view.resetViewInsets);
        await tester.pumpAndSettle();
        await reveal(tester, 'Preview planning changes');
        expect(tester.getRect(find.text('Preview planning changes')).bottom,
            lessThanOrEqualTo(550));
        expect(tester.takeException(), isNull);
        expect(api.posts, isEmpty);
      });
    }

    for (final evaluation in [false, true]) {
      testWidgets(
          'concise independent scores and accurate expandable provenance at $width evaluation $evaluation',
          (tester) async {
        tester.view.physicalSize = Size(width, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final rec = recommendation(evaluation: evaluation);
        await tester.pumpWidget(app(
            SingleChildScrollView(
                child: RecommendationCard(
                    recommendation: rec,
                    discovery: true,
                    onView: () {},
                    onAddToTrip: () {})),
            scale: 1.6));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('Why this suggestion'));
        await tester.pump();
        await tester.tap(find.text('Why this suggestion'));
        await tester.pumpAndSettle();
        expect(find.text('Why this suggestion?'), findsOneWidget);
        expect(find.text('Overall match: 77.5/100'), findsOneWidget);
        for (final text in [
          'Your interests (60%)',
          'Similar profiles (30%)',
          'Popularity (10%)',
          '80/100',
          '75/100',
          '70/100'
        ]) {
          expect(find.text(text), findsOneWidget);
        }
        expect(find.textContaining('FYP'), findsNothing);
        expect(find.textContaining('Evidence confidence:'), findsNothing);
        final scroll =
            find.byKey(const ValueKey('recommendation-explanation-scroll'));
        await tester.scrollUntilVisible(
            find.text('How recommendations work'), 180,
            scrollable: find
                .descendant(of: scroll, matching: find.byType(Scrollable))
                .first);
        await tester.pump();
        await tester.tap(find.text('How recommendations work'));
        await tester.pumpAndSettle();
        expect(
            find.textContaining('Evidence confidence: 100%'), findsOneWidget);
        expect(
            find.textContaining(evaluation
                ? 'not verified genuine Traveller submissions'
                : 'Approved genuine TravelMate reviews:'),
            findsOneWidget);
        expect(tester.takeException(), isNull);
        expect(rec['hybridRankingScore'], 77.5);
        expect(rec['personalSuitabilityScore'], 91);
      });
    }
  }

  testWidgets(
      'attached flight schedule cannot be edited through transport estimates',
      (tester) async {
    final api = PlanningApi();
    api.trip['selectedFlight'] = {
      'outboundSegments': [
        {
          'arrivalDate': '2027-12-12',
          'arrivalTime': '11:50',
          'arrivalAirportCode': 'PEN'
        }
      ],
      'returnSegments': [
        {
          'departureDate': '2027-12-16',
          'departureTime': '20:00',
          'departureAirportCode': 'PEN'
        }
      ]
    };
    await tester.pumpWidget(app(Builder(
        builder: (context) => TextButton(
            onPressed: () => PlanningSettingsSheet.show(context, api, api.trip),
            child: const Text('Settings')))));
    await tester.tap(find.text('Settings'));
    await tester.pumpAndSettle();
    await reveal(tester, 'Travel schedule');
    expect(find.textContaining('11:50'), findsOneWidget);
    expect(find.byKey(const ValueKey('transport-arrival-date')), findsNothing);
    expect(find.byKey(const ValueKey('extra-travel-time')), findsNothing);
    expect(api.posts, isEmpty);
    expect(tester.takeException(), isNull);
  });
}
