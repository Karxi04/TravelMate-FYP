import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'package:travelmate_traveller/widgets/local_place_rating.dart';

Widget _wrap(Widget child, {double width = 360, double textScale = 1.0}) {
  return MaterialApp(
    theme: buildInkWashTheme(),
    home: MediaQuery(
      data: MediaQueryData(
        size: Size(width, 800),
        textScaler: TextScaler.linear(textScale),
      ),
      child: Scaffold(
        body: SingleChildScrollView(
          child: SizedBox(
            width: width,
            child: child,
          ),
        ),
      ),
    ),
  );
}

void main() {
  group('Batch 21E-C2: Truthful Recommendation Scores & Explainable Matching', () {
    testWidgets('1. Accurate ranking-score labeling and no % match wording',
        (tester) async {
      final rec = {
        'destinationId': 'rec_gt',
        'title': 'George Town Heritage Core',
        'address': 'George Town, Penang',
        'category': 'Heritage',
        'rating': 4.7,
        'finalScore': 72.94,
        'matchReasons': ['Matches your Culture and Food interests'],
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: rec,
        onView: () {},
      )));
      await tester.pump();

      // Must display truthful ranking score label
      expect(find.text('Recommendation score: 73/100'), findsOneWidget);
      // Misleading % match must be strictly absent
      expect(find.textContaining('% match'), findsNothing);
      expect(find.textContaining('73%'), findsNothing);
    });

    testWidgets('2. Scenario A: culture/food/nature/shopping preserves score order and display rounding',
        (tester) async {
      final items = [
        {
          'destinationId': 'rec_gt',
          'title': 'George Town Heritage Core',
          'finalScore': 72.94,
          'matchReasons': ['Matches your Culture and Food interests'],
        },
        {
          'destinationId': 'rec_kls',
          'title': 'Kek Lok Si Temple',
          'finalScore': 56.32,
          'matchReasons': ['Matches your Culture interests'],
        },
        {
          'destinationId': 'rec_ph',
          'title': 'Penang Hill',
          'finalScore': 50.66,
          'matchReasons': ['Matches your Nature interests'],
        },
      ];

      await tester.pumpWidget(MaterialApp(
        theme: buildInkWashTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: Column(
              children: items
                  .map((item) => RecommendationCard(
                        recommendation: item,
                        onView: () {},
                      ))
                  .toList(),
            ),
          ),
        ),
      ));
      await tester.pump();

      // Verify rounding only affects presentation, scores are accurate
      expect(find.text('Recommendation score: 73/100'), findsOneWidget);
      expect(find.text('Recommendation score: 56/100'), findsOneWidget);
      expect(find.text('Recommendation score: 51/100'), findsOneWidget);

      // Verify underlying map numeric values are strictly preserved
      expect(items[0]['finalScore'], 72.94);
      expect(items[1]['finalScore'], 56.32);
      expect(items[2]['finalScore'], 50.66);

      // Order in UI is strictly George Town, Kek Lok Si, Penang Hill
      final gtOffset = tester.getTopLeft(find.text('George Town Heritage Core')).dy;
      final klsOffset = tester.getTopLeft(find.text('Kek Lok Si Temple')).dy;
      final phOffset = tester.getTopLeft(find.text('Penang Hill')).dy;
      expect(gtOffset < klsOffset, isTrue);
      expect(klsOffset < phOffset, isTrue);
    });

    testWidgets('3. Scenario B: cold-start traveller has transparent neutral baseline without fake peer feedback',
        (tester) async {
      final coldStartRec = {
        'destinationId': 'rec_cold',
        'title': 'Penang Botanic Gardens',
        'finalScore': 58.4,
        'contentScore': 64.0,
        'collaborativeScore': 50.0,
        'popularityScore': 50.0,
        'collaborativeConfidence': 0.0,
        'collaborativeRatingCount': 0,
        'collaborativeSource': 'no similar traveller evidence; neutral score 50 applied',
        'scoreBreakdown': {
          'contentWeight': 0.60,
          'collaborativeWeight': 0.30,
          'popularityWeight': 0.10,
          'content': 64.0,
          'collaborative': 50.0,
          'popularity': 50.0,
        },
        'matchReasons': ['Matches your Nature interests'],
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: coldStartRec,
        onView: () {},
      )));
      await tester.pump();

      expect(find.text('Recommendation score: 58/100'), findsOneWidget);
      expect(find.text('Matches your Nature interests'), findsOneWidget);
      // Does NOT claim similar travellers rated this
      expect(find.textContaining('similar travellers liked'), findsNothing);
      expect(find.textContaining('Highly rated by similar'), findsNothing);

      // Tap score chip to open score breakdown explanation sheet
      await tester.tap(find.text('Recommendation score: 58/100'));
      await tester.pumpAndSettle();

      // Verifies breakdown explains cold-start neutral baseline
      expect(find.text('Recommendation Score (58/100)'), findsOneWidget);
      expect(find.text('50/100 (Neutral baseline)'), findsOneWidget);
      expect(find.textContaining('No peer ratings from similar travellers are recorded yet'), findsOneWidget);
      expect(find.textContaining('not an enjoyment probability'), findsOneWidget);

      // Close modal
      await tester.tap(find.text('Close'), warnIfMissed: false);
      await tester.pumpAndSettle();
    });

    testWidgets('4. Scenario C: missing scoreBreakdown and matchReasons uses graceful neutral fallback',
        (tester) async {
      final sparseRec = {
        'destinationId': 'rec_sparse',
        'title': 'Clan Jetties of Penang',
        'finalScore': 61.2,
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: sparseRec,
        onView: () {},
      )));
      await tester.pump();

      expect(find.text('Recommendation score: 61/100'), findsOneWidget);
      // Shows truthful neutral fallback reason
      expect(find.text('Recommended based on available destination information.'), findsOneWidget);

      // Tap score details when scoreBreakdown is absent
      await tester.tap(find.text('Recommendation score: 61/100'));
      await tester.pumpAndSettle();

      expect(find.text('Detailed score breakdown is not available for this recommendation.'), findsOneWidget);
    });

    testWidgets('5. Scenario D: historical recommendation with % match in recommendationReason strips stale wording',
        (tester) async {
      final historicalRec = {
        'destinationId': 'rec_hist',
        'title': 'Kek Lok Si Temple',
        'score': 86.0,
        'recommendationReason': '86% match • Fits your culture profile • Popular and well reviewed',
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: historicalRec,
        onView: () {},
      )));
      await tester.pump();

      expect(find.text('Recommendation score: 86/100'), findsOneWidget);
      expect(find.text('Fits your culture profile'), findsOneWidget);
      expect(find.text('Popular and well reviewed'), findsOneWidget);
      expect(find.textContaining('% match'), findsNothing);
    });

    testWidgets('6. Scenario E: low ranking score is displayed truthfully without artificial inflation',
        (tester) async {
      final lowScoreRec = {
        'destinationId': 'rec_low',
        'title': 'Remote Activity',
        'finalScore': 32.1,
        'matchReasons': ['Limited profile evidence'],
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: lowScoreRec,
        onView: () {},
      )));
      await tester.pump();

      expect(find.text('Recommendation score: 32/100'), findsOneWidget);
      expect(find.textContaining('% match'), findsNothing);
    });

    testWidgets('7. Missing or null score does not show score chip or % match',
        (tester) async {
      final noScoreRec = {
        'destinationId': 'rec_none',
        'title': 'Unscored Scenic Viewpoint',
        'category': 'Viewpoint',
        'matchReasons': ['Popular with visitors in Penang'],
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: noScoreRec,
        onView: () {},
      )));
      await tester.pump();

      expect(find.text('Unscored Scenic Viewpoint'), findsOneWidget);
      expect(find.textContaining('Recommendation score:'), findsNothing);
      expect(find.textContaining('% match'), findsNothing);
      expect(find.text('Popular with visitors in Penang'), findsOneWidget);
    });

    testWidgets('8. Matched-interest chips display only when supported by evidence',
        (tester) async {
      LocalReviewRatings.remember('rec_interests', {'rating':4.0,'reviews':2});
      addTearDown(LocalReviewRatings.invalidate);
      final recWithInterests = {
        'destinationId': 'rec_interests',
        'title': 'Penang Street Food Tour',
        'category': 'Food Tour',
        'rating': 4.9,
        'finalScore': 88.0,
        'matchedInterests': ['Food and dining', 'Culture and heritage'],
        'matchReasons': ['Matches your Food and Culture interests'],
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: recWithInterests,
        onView: () {},
      )));
      await tester.pump();

      expect(find.text('Food and dining'), findsOneWidget);
      expect(find.text('Culture and heritage'), findsOneWidget);
      expect(find.text('Food Tour'), findsOneWidget);
      expect(find.text('4.9 rating'), findsNothing);
      expect(find.text('4.0 · 2 reviews'), findsOneWidget);
    });

    testWidgets('9. View button triggers navigation callback',
        (tester) async {
      var viewed = false;
      final rec = {
        'destinationId': 'rec_nav',
        'title': 'Batu Ferringhi Beach',
        'finalScore': 75.0,
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: rec,
        onView: () => viewed = true,
      )));
      await tester.pump();

      await tester.tap(find.byKey(const ValueKey('recommendation-view-rec_nav')));
      expect(viewed, isTrue);
    });

    testWidgets('10. Add to trip button triggers callback without mutating data',
        (tester) async {
      var added = false;
      final originalMap = <String, dynamic>{
        'destinationId': 'rec_add',
        'title': 'Tropical Spice Garden',
        'finalScore': 68.5,
        'estimatedCost': 35.0,
      };

      await tester.pumpWidget(_wrap(RecommendationCard(
        recommendation: originalMap,
        onView: () {},
        onAddToTrip: () => added = true,
      )));
      await tester.pump();

      await tester.tap(find.byKey(const ValueKey('recommendation-add-rec_add')));
      expect(added, isTrue);
      // Original map is untouched
      expect(originalMap['finalScore'], 68.5);
      expect(originalMap['estimatedCost'], 35.0);
    });

    testWidgets('11. Large text layout scales gracefully without RenderFlex overflow',
        (tester) async {
      final rec = {
        'destinationId': 'rec_large',
        'title': 'Very Long Destination Name In Beautiful Island Of Penang Malaysia',
        'address': 'Jalan Batu Ferringhi, 11100 George Town, Pulau Pinang',
        'category': 'Historical Attraction',
        'rating': 4.8,
        'finalScore': 84.7,
        'matchedInterests': ['Culture and heritage'],
        'matchReasons': [
          'Matches your Culture and heritage interests',
          'Fits your relaxed travel pace',
        ],
      };

      await tester.pumpWidget(_wrap(
        RecommendationCard(
          recommendation: rec,
          onView: () {},
        ),
        width: 320,
        textScale: 1.8,
      ));
      await tester.pump();

      // No RenderFlex overflow exception
      expect(tester.takeException(), isNull);
      expect(find.text('Recommendation score: 85/100'), findsOneWidget);
    });
  });
}
