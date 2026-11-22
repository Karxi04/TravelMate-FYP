import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/activity_payload_helper.dart';
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
  for(final place in [
    ('local_my_perak_zoo_taiping','Zoo Taiping','Taiping, Perak, Malaysia'),
    ('local_my_kuala_lumpur_aquaria_klcc','Aquaria KLCC','Kuala Lumpur, Malaysia'),
    ('local_melaka_cruise','Melaka River Cruise','Melaka City, Melaka, Malaysia'),
  ]) {
    test('nationwide Trip payload preserves identity and excludes evaluation evidence: ${place.$2}',() {
      final payload=buildActivityPayload({...evaluationRecommendation(),
        'destinationId':place.$1,'title':place.$2,'address':place.$3,
        'evidenceProvenance':{'synthetic':true,'source':'sample_community_evaluation'},
        'demonstrationReviewSummary':{'rating':3.5,'reviews':8}});
      expect(payload['destinationId'],place.$1);expect(payload['activityName'],place.$2);
      for(final key in ['synthetic','recommendationEvidenceMode','evidenceProvenance','collaborativeScore',
        'collaborativeRatingCount','demonstrationReviewSummary','popularityEvidence','scoreBreakdown']) {
        expect(payload.containsKey(key),isFalse);
      }
    });
    testWidgets('nationwide local evaluation card preserves badge, source and actions: ${place.$2}',(tester) async {
      var views=0,adds=0;
      await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:Scaffold(body:SingleChildScrollView(
        child:RecommendationCard(discovery:true,recommendation:{...evaluationRecommendation(),
          'destinationId':place.$1,'title':place.$2,'address':place.$3,
          'popularityEvidence':{'source':'demonstration_approved_reviews','rating':3.5,'reviewCount':8},
          'demonstrationReviewSummary':{'source':'demonstration_approved_reviews','synthetic':true,'rating':3.5,'reviews':8}},
          onView:()=>views++,onAddToTrip:()=>adds++)))));
      await tester.pumpAndSettle();
      expect(find.text(place.$2),findsOneWidget);expect(find.text('3.5 · 8 Reviews'),findsOneWidget);
      expect(find.textContaining('provider reviews'),findsNothing);
      await tester.ensureVisible(find.text('View'));await tester.pump();await tester.tap(find.text('View'));
      await tester.ensureVisible(find.text('Add to trip'));await tester.pump();await tester.tap(find.text('Add to trip'));
      expect(views,1);expect(adds,1);
      await tester.ensureVisible(find.text('Why this suggestion'));await tester.pump();await tester.tap(find.text('Why this suggestion'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('How recommendations work')); await tester.pump();
      await tester.tap(find.text('How recommendations work')); await tester.pumpAndSettle();
      expect(find.textContaining('Qualifying evaluation contributors: 3'),findsOneWidget);
      expect(find.textContaining('unweighted destination aggregate'),findsOneWidget);
      expect(tester.takeException(),isNull);
    });
  }
  testWidgets('first evaluation visit does not generate before an explicit tap',(tester) async {
    final api=EvaluationRecsApi()..initialEmpty=true;
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:RecommendationScreen(api:api,initialDestination:'Penang')));
    await tester.pumpAndSettle();
    expect(api.generations,0);expect(find.text(recommendationStartMessage),findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('update-recommendation-evidence')));await tester.pump();
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
    await tester.ensureVisible(find.byKey(const ValueKey('update-recommendation-evidence')));await tester.pump();
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
        expect(find.text('3.8 · 10 Reviews'),findsOneWidget);
        expect(find.text('Hybrid score: 62.1/100'),findsOneWidget);
        expect(find.text('Scenery'),findsOneWidget);
        expect(find.text('Demonstration review data'),findsNothing);
        expect(find.text('View simulation'),findsNothing);
        expect(find.descendant(of:find.byType(RecommendationCard),matching:find.byWidgetPredicate((w)=>
          w is SingleChildScrollView && w.scrollDirection==Axis.horizontal)),findsNothing);
        await tester.ensureVisible(find.text('View'));await tester.pump();await tester.tap(find.text('View'));
        await tester.ensureVisible(find.text('Add to trip'));await tester.pump();await tester.tap(find.text('Add to trip'));
        await tester.ensureVisible(find.byType(PopupMenuButton<String>));await tester.pump();await tester.tap(find.byType(PopupMenuButton<String>));
        await tester.pumpAndSettle();await tester.tap(find.text('More like this'));await tester.pumpAndSettle();
        expect(views,1);expect(adds,1);expect(feedback,'more_like_this');
        await tester.ensureVisible(find.text('Why this suggestion'));await tester.pump();await tester.tap(find.text('Why this suggestion'));
        await tester.pumpAndSettle();
        expect(find.textContaining('not genuine customer peer evidence'),findsOneWidget);
        await tester.ensureVisible(find.text('How recommendations work')); await tester.pump();
        await tester.tap(find.text('How recommendations work')); await tester.pumpAndSettle();
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
    expect(find.text('Recommendation data sources'),findsNothing);
    expect(find.text('GeoNames · CC BY 4.0'),findsNothing);
    await tester.ensureVisible(find.text('Why this suggestion'));await tester.pump();
    await tester.tap(find.text('Why this suggestion'));await tester.pumpAndSettle();
    expect(find.textContaining('not genuine customer peer evidence'),findsOneWidget);
    await tester.tapAt(const Offset(10,10));await tester.pumpAndSettle();
    await tester.ensureVisible(find.byType(PopupMenuButton<String>));await tester.pump();await tester.pumpAndSettle();
    await tester.tap(find.byType(PopupMenuButton<String>));
    await tester.pumpAndSettle();await tester.tap(find.text('Not for me'));await tester.pumpAndSettle();
    expect(api.feedback.single['recommendationGenerationId'],'fyp-evaluation-widget');
    expect(api.generations,1);expect(tester.takeException(),isNull);
  });

  testWidgets('provider-only evidence never becomes an evaluation rating badge',(tester) async {
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(
      recommendation:{...evaluationRecommendation(),'popularityEvidence':{
        'source':'provider_rating_review_count','rating':4.4,'reviewCount':15505}},onView:(){})))));
    await tester.pumpAndSettle();
    expect(find.text('Not rated yet'),findsOneWidget);
    expect(find.textContaining('provider reviews'),findsNothing);
    expect(find.textContaining('sample reviews'),findsNothing);expect(tester.takeException(),isNull);
  });

  testWidgets('local summary hides provider badge even in an older provider-first generation',(tester) async {
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(
      recommendation:{...evaluationRecommendation(),
        'demonstrationReviewSummary':{'source':'demonstration_approved_reviews','synthetic':true,'rating':3.8,'reviews':15},
        'popularityEvidence':{'source':'provider_rating_review_count','rating':4.4,'reviewCount':15505}},onView:(){})))));
    await tester.pumpAndSettle();
    expect(find.text('3.8 · 15 Reviews'),findsOneWidget);
    expect(find.textContaining('provider reviews'),findsNothing);
    expect(tester.takeException(),isNull);
    await tester.ensureVisible(find.text('Recommendation score: 62/100'));await tester.pump();
    await tester.tap(find.text('Recommendation score: 62/100'));await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('How recommendations work')); await tester.pump();
    await tester.tap(find.text('How recommendations work')); await tester.pumpAndSettle();
    expect(find.textContaining('This saved evaluation predates the local-only policy'),findsOneWidget);
    expect(tester.takeException(),isNull);
  });

  for(final invalid in [<String,dynamic>{'reviews':0},{'synthetic':false},{'rating':6}]) {
    testWidgets('invalid local summary never falls back to provider badge $invalid',(tester) async {
      await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(
        recommendation:{...evaluationRecommendation(),
          'demonstrationReviewSummary':{'source':'demonstration_approved_reviews','synthetic':true,'rating':3.8,'reviews':15,...invalid},
          'popularityEvidence':{'source':'provider_rating_review_count','rating':4.4,'reviewCount':15505}},onView:(){})))));
      await tester.pumpAndSettle();
      expect(find.text('Not rated yet'),findsOneWidget);
      expect(find.textContaining('provider reviews'),findsNothing);
      expect(find.textContaining('sample reviews'),findsNothing);expect(tester.takeException(),isNull);
    });
  }
}
