import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/widgets/local_place_rating.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'fyp_evaluation_journey_test.dart' show EvaluationRecsApi, evaluationRecommendation;

Map<String,dynamic> summary([Map<String,dynamic> changes=const {}]) => {
  'recommendationEvidenceMode':'fyp_evaluation','ratingBasis':'private_illustrative',
  'privateExamplesAllowed':true,'reviewEnvironment':'private_demo',
  'rating':4.9,'reviews':999,'sampleSummary':{'rating':3.5,'reviews':16},...changes,
};

class ReviewEvidenceApi extends EvaluationRecsApi {
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    final data=await super.get(path,query);
    return path=='/api/fr4/recommendations' ? {...data as Map,
      'stale':true,'staleReason':'review_evidence_changed','requiresExplicitRegeneration':true,'recommendations':[]} : data;
  }
}

void main() {
  testWidgets('FYP badge uses approved local summary, not genuine/provider totals',(tester) async {
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:LocalReviewRatingBadge(summary:summary()))));
    expect(find.text('3.5 · 16 Reviews'),findsOneWidget);
    expect(find.byIcon(Icons.star_rounded),findsOneWidget);
    expect(find.textContaining('999'),findsNothing);expect(find.textContaining('sample'),findsNothing);
  });
  testWidgets('missing or unauthorized local summary never borrows a rating',(tester) async {
    for(final value in [summary({'sampleSummary':{'rating':null,'reviews':0}}),summary({'privateExamplesAllowed':false})]) {
      await tester.pumpWidget(MaterialApp(home:Scaffold(body:LocalReviewRatingBadge(summary:value))));
      expect(find.text('Not rated yet'),findsOneWidget);
    }
  });
  testWidgets('genuine badge presentation and aggregate stay unchanged',(tester) async {
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:LocalReviewRatingBadge(summary:{'rating':4.2,'reviews':8}))));
    expect(find.text('4.2 (8 reviews)'),findsOneWidget);
  });
  testWidgets('ordinary evaluation reasons are natural; details retain provenance',(tester) async {
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(
      discovery:true,recommendation:{...evaluationRecommendation(),
        'matchReasons':['Highly rated in sample community data']},onView:(){})))));
    expect(find.text('Popular among reviewers'),findsOneWidget);
    expect(find.text('Highly rated in sample community data'),findsNothing);
    expect(find.text('Demonstration review data'),findsNothing);
    await tester.ensureVisible(find.text('Why this suggestion'));await tester.tap(find.text('Why this suggestion'));
    await tester.pumpAndSettle();
    expect(find.textContaining('not genuine customer peer evidence'),findsOneWidget);
    expect(find.textContaining('unweighted destination aggregate'),findsOneWidget);
  });
  testWidgets('changed moderation asks for regeneration without blaming preferences',(tester) async {
    final api=ReviewEvidenceApi();
    await tester.pumpWidget(MaterialApp(home:RecommendationScreen(api:api,initialDestination:'Penang')));
    await tester.pumpAndSettle();
    expect(find.text(recommendationReviewUpdateMessage),findsOneWidget);
    expect(find.text(recommendationPreferenceUpdateMessage),findsNothing);
    expect(api.generations,0);
  });
}
