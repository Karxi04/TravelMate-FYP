import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'core_personalization_notifications_test.dart' show RecsApi;

// Widget fixtures only; these values are never submitted as customer evidence.
Map<String,dynamic> evaluationRecommendation() => {
  'destinationId':'kek_lok_si','title':'Kek Lok Si Temple','address':'Air Itam, Penang, Malaysia',
  'category':'Culture','destinationConcepts':['culture'],'discoveryEligible':true,
  'synthetic':true,'recommendationEvidenceMode':'fyp_evaluation','recommendationSource':'fyp_evaluation',
  'matchedInterests':['Culture','Photography','Food','Nature','History','Architecture','Family','Relaxation','Scenery'],
  'score':62.08,'finalScore':62.08,'collaborativeScore':60,'collaborativeRatingCount':3,
  'collaborativeConfidence':.6,'rawCollaborativeScore':66.67,
  'popularitySource':'demonstration_approved_reviews',
  'popularityEvidence':{'source':'demonstration_approved_reviews','rating':3.8,'reviewCount':10},
  'scoreBreakdown':{'content':63.33,'collaborative':60,'popularity':60.82},
  'matchReasons':['Matches your Culture interests'],
};

Map<String,dynamic> evaluationEnvelope(Map data) => {...data,
  'source':'fyp_evaluation','synthetic':true,'recommendationEvidenceMode':'fyp_evaluation',
  'recommendationGenerationId':'fyp-evaluation-widget',
  'evidenceProvenance':{'source':'sample_community_evaluation','synthetic':true},
  'requiresExplicitRegeneration':data['stale']==true,
  'recommendations':data['stale']==true ? []:[evaluationRecommendation()],
};

class EvaluationRecsApi extends RecsApi {
  bool stale=false;
  bool initialEmpty=false;
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    final data=await super.get(path,query);
    if(path=='/api/fr4/recommendations' && initialEmpty) return {
      ...evaluationEnvelope(data as Map),'recommendationGenerationId':'',
      'recommendations':[],'requiresExplicitRegeneration':true};
    return path=='/api/fr4/recommendations' ? evaluationEnvelope({...data as Map,'stale':stale}):data;
  }
  @override
  Future<dynamic> post(String path,[Map<String,dynamic>? body]) async {
    final data=await super.post(path,body);
    return path=='/api/fr4/recommendations/generate' ? evaluationEnvelope(data as Map):data;
  }
}

void main() {
  testWidgets('first evaluation visit does not generate before an explicit tap',(tester) async {
    final api=EvaluationRecsApi()..initialEmpty=true;
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:RecommendationScreen(api:api,initialDestination:'Penang')));
    await tester.pumpAndSettle();
    expect(api.generations,0);expect(find.text(recommendationStartMessage),findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('update-recommendation-evidence')));
    await tester.tap(find.byKey(const ValueKey('update-recommendation-evidence')));await tester.pumpAndSettle();
    expect(api.generations,1);expect(find.text('Kek Lok Si Temple'),findsOneWidget);
    expect(tester.takeException(),isNull);
  });
  testWidgets('evaluation questionnaire changes wait for explicit regeneration',(tester) async {
    final api=EvaluationRecsApi()..stale=true;
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:RecommendationScreen(api:api,initialDestination:'Penang')));
    await tester.pumpAndSettle();
    expect(api.generations,0);
    expect(find.text(recommendationPreferenceUpdateMessage),findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('update-recommendation-evidence')));
    await tester.tap(find.byKey(const ValueKey('update-recommendation-evidence')));await tester.pumpAndSettle();
    expect(api.generations,1);expect(find.text(recommendationPreferenceUpdateMessage),findsNothing);
    expect(find.text('Kek Lok Si Temple'),findsOneWidget);expect(tester.takeException(),isNull);
  });
  test('only complete matching server evaluation envelopes enter normal discovery',() {
    final data=evaluationEnvelope({'pagination':{'discoveryMode':recommendationDiscoveryMode}});
    validateDiscoveryResponse(data);
    for(final key in ['synthetic','evidenceProvenance','recommendationEvidenceMode']) {
      final invalid={...data}..remove(key);
      expect(()=>validateDiscoveryResponse(invalid),throwsStateError);
    }
    expect(()=>validateDiscoveryResponse({...data,'recommendations':[{'title':'Mixed genuine row'}]}),throwsStateError);
    expect(()=>validateDiscoveryResponse({'pagination':{'discoveryMode':recommendationDiscoveryMode},
      'recommendations':[evaluationRecommendation()]}),throwsStateError);
  });

  for(final width in [320.0,360.0,390.0]) {
    for(final scale in [1.0,1.8]) {
      testWidgets('normal evaluation card actions and nine labels at $width scale $scale',(tester) async {
        tester.view.physicalSize=Size(width,1000);tester.view.devicePixelRatio=1;
        addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
        var views=0,adds=0;String? feedback;
        await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),
          builder:(context,child)=>MediaQuery(data:MediaQuery.of(context).copyWith(textScaler:TextScaler.linear(scale)),child:child!),
          home:Scaffold(body:SingleChildScrollView(child:SizedBox(width:width*.76,
            child:RecommendationCard(carousel:true,discovery:true,recommendation:evaluationRecommendation(),
              onView:()=>views++,onAddToTrip:()=>adds++,onPreferenceFeedback:(value)=>feedback=value))))));
        await tester.pumpAndSettle();
        expect(find.text('3.8 · 10 sample reviews'),findsOneWidget);
        expect(find.text('Hybrid score: 62.1/100'),findsOneWidget);
        expect(find.text('Scenery'),findsOneWidget);
        expect(find.text('Demonstration review data'),findsNothing);
        expect(find.text('View simulation'),findsNothing);
        expect(find.descendant(of:find.byType(RecommendationCard),matching:find.byWidgetPredicate((w)=>
          w is SingleChildScrollView && w.scrollDirection==Axis.horizontal)),findsNothing);
        await tester.ensureVisible(find.text('View'));await tester.tap(find.text('View'));
        await tester.ensureVisible(find.text('Add to trip'));await tester.tap(find.text('Add to trip'));
        await tester.ensureVisible(find.byType(PopupMenuButton<String>));await tester.tap(find.byType(PopupMenuButton<String>));
        await tester.pumpAndSettle();await tester.tap(find.text('More like this'));await tester.pumpAndSettle();
        expect(views,1);expect(adds,1);expect(feedback,'more_like_this');
        await tester.ensureVisible(find.text('Why this suggestion'));await tester.tap(find.text('Why this suggestion'));
        await tester.pumpAndSettle();
        expect(find.textContaining('not genuine customer peer evidence'),findsOneWidget);
        expect(find.textContaining('Qualifying evaluation contributors: 3'),findsOneWidget);
        expect(tester.takeException(),isNull);
      });
    }
  }

  testWidgets('For You uses normal results, real feedback action and accessible configuration disclosure',(tester) async {
    final api=EvaluationRecsApi();
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:RecommendationScreen(api:api,initialDestination:'Penang')));
    await tester.pumpAndSettle();
    expect(find.text('Kek Lok Si Temple'),findsOneWidget);
    expect(find.byIcon(Icons.science_outlined),findsNothing);
    expect(find.text('View simulation'),findsNothing);
    await tester.ensureVisible(find.text('Recommendation data sources'));
    await tester.tap(find.text('Recommendation data sources'));await tester.pumpAndSettle();
    expect(find.text('FYP evaluation configuration'),findsOneWidget);
    expect(find.textContaining('not verified real tourists'),findsOneWidget);
    await tester.tapAt(const Offset(10,10));await tester.pumpAndSettle();
    await tester.ensureVisible(find.byType(PopupMenuButton<String>));await tester.pumpAndSettle();
    await tester.tap(find.byType(PopupMenuButton<String>));
    await tester.pumpAndSettle();await tester.tap(find.text('Not for me'));await tester.pumpAndSettle();
    expect(api.feedback.single['recommendationGenerationId'],'fyp-evaluation-widget');
    expect(api.generations,1);expect(tester.takeException(),isNull);
  });

  testWidgets('provider counts remain provider evidence in evaluation cards',(tester) async {
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(
      recommendation:{...evaluationRecommendation(),'popularityEvidence':{
        'source':'provider_rating_review_count','rating':4.4,'reviewCount':15505}},onView:(){})))));
    await tester.pumpAndSettle();
    expect(find.text('4.4 · 15505 provider reviews'),findsOneWidget);
    expect(find.textContaining('sample reviews'),findsNothing);expect(tester.takeException(),isNull);
  });

  testWidgets('local summary hides provider badge even in an older provider-first generation',(tester) async {
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(
      recommendation:{...evaluationRecommendation(),
        'demonstrationReviewSummary':{'source':'demonstration_approved_reviews','synthetic':true,'rating':3.8,'reviews':15},
        'popularityEvidence':{'source':'provider_rating_review_count','rating':4.4,'reviewCount':15505}},onView:(){})))));
    await tester.pumpAndSettle();
    expect(find.text('3.8 · 15 sample reviews'),findsOneWidget);
    expect(find.textContaining('provider reviews'),findsNothing);
    expect(tester.takeException(),isNull);
    await tester.ensureVisible(find.text('Recommendation score: 62/100'));
    await tester.tap(find.text('Recommendation score: 62/100'));await tester.pumpAndSettle();
    expect(find.textContaining('This earlier evaluation used provider popularity although local reviews are available'),findsOneWidget);
    expect(tester.takeException(),isNull);
  });

  for(final invalid in [<String,dynamic>{'reviews':0},{'synthetic':false},{'rating':6}]) {
    testWidgets('invalid local summary uses honest provider fallback $invalid',(tester) async {
      await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(
        recommendation:{...evaluationRecommendation(),
          'demonstrationReviewSummary':{'source':'demonstration_approved_reviews','synthetic':true,'rating':3.8,'reviews':15,...invalid},
          'popularityEvidence':{'source':'provider_rating_review_count','rating':4.4,'reviewCount':15505}},onView:(){})))));
      await tester.pumpAndSettle();
      expect(find.text('4.4 · 15505 provider reviews'),findsOneWidget);
      expect(find.textContaining('sample reviews'),findsNothing);expect(tester.takeException(),isNull);
    });
  }
}
