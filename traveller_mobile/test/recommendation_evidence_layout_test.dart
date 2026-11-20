import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/local_place_rating.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'core_personalization_notifications_test.dart' show RecsApi;

Map<String,dynamic> currentEvidence() => {
  'collaborativeRatingCount':0,'collaborativeConfidence':0.0,'rawCollaborativeScore':50.0,
  'popularitySource':'neutral_missing_rating',
  'popularityEvidence':{'source':'neutral_missing_rating','rating':null,'reviewCount':null},
};

class _GenerationApi extends RecsApi {
  final generationReads=<String>[];
  Map<String,dynamic> data(String generation) => {
    'ok':true,'recommendationGenerationId':generation,'source':'cache',
    'snapshot':{'requestedDestination':'Penang'},
    'pagination':{'discoveryMode':recommendationDiscoveryMode},
    'recommendations':[{'destinationId':'isolated-place','title':'Place $generation',
      'type':'Culture','discoveryEligible':true,'score':60,
      if(generation=='new-generation') ...currentEvidence()}],
  };
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    if(path=='/api/fr4/recommendations') {
      final id=query?['generationId'] ?? 'new-generation';generationReads.add(id);return data(id);
    }
    return super.get(path,query);
  }
  @override
  Future<dynamic> post(String path,[Map<String,dynamic>? body]) async {
    if(path=='/api/fr4/recommendations/generate') {generations++;return data('new-generation');}
    throw StateError('No other writes authorized in this test');
  }
}

void main() {
  test('fresh zero-peer evidence is distinct from old/incomplete snapshot metadata', () {
    expect(recommendationHasCurrentEvidence(currentEvidence()),isTrue);
    expect(recommendationsNeedEvidenceUpdate([currentEvidence()]),isFalse);
    final old={...currentEvidence()}..remove('popularityEvidence');
    final before=Map.of(old);
    expect(recommendationsNeedEvidenceUpdate([old]),isTrue);
    expect(old,before);
    for(final key in ['collaborativeRatingCount','collaborativeConfidence','rawCollaborativeScore','popularitySource']) {
      final partial={...currentEvidence()}..remove(key);
      expect(recommendationHasCurrentEvidence(partial),isFalse,reason:key);
    }
  });

  for(final width in [320.0,360.0,390.0]) {
    for(final scale in [1.0,1.8]) {
      for(final count in [1,3,5,9]) {
        for(final carousel in [false,true]) {
          testWidgets('wraps $count labels at $width scale $scale carousel $carousel', (tester) async {
            tester.view.physicalSize=Size(width,1000);tester.view.devicePixelRatio=1;
            addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
            addTearDown(LocalReviewRatings.invalidate);
            final id='isolated-$width-$scale-$count-$carousel';
            final interests=List.generate(count,(i)=>'Interest ${i+1}');
            const title='A long Malaysian destination name that must wrap completely without an ellipsis';
            const address='A long address with street, locality and state information in Penang, Malaysia';
            const category='A detailed cultural category that must remain completely readable';
            LocalReviewRatings.remember(id,{'rating':4.5,'reviews':123});
            var views=0,adds=0;
            String? feedback;
            await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),
              builder:(context,child)=>MediaQuery(data:MediaQuery.of(context).copyWith(textScaler:TextScaler.linear(scale)),child:child!),
              home:Scaffold(body:SingleChildScrollView(child:SizedBox(width:carousel ? math.min(width*.76,280):width,
                child:RecommendationCard(carousel:carousel,discovery:true,
                  recommendation:{'destinationId':id,'title':title,'address':address,'category':category,
                    'matchedInterests':interests,'score':60,'recommendationSource':'cache',
                    'matchReasons':['A complete explanation of the available preference and destination evidence.'],...currentEvidence()},
                  onView:()=>views++,onAddToTrip:()=>adds++,onPreferenceFeedback:(value)=>feedback=value))))));
            await tester.pumpAndSettle();
            final card=find.byType(RecommendationCard);
            expect(find.descendant(of:card,matching:find.byWidgetPredicate((w)=>
              w is SingleChildScrollView && w.scrollDirection==Axis.horizontal)),findsNothing);
            final bounds=tester.getRect(card);
            for(final text in [title,address,category,...interests,'4.5 (123 reviews)','Saved provider information']) {
              final found=find.text(text);expect(found,findsOneWidget,reason:text);
              final box=tester.getRect(found);
              expect(box.left,greaterThanOrEqualTo(bounds.left),reason:text);
              expect(box.right,lessThanOrEqualTo(bounds.right+.1),reason:text);
              expect(box.bottom,lessThanOrEqualTo(bounds.bottom+.1),reason:text);
              final widget=tester.widget<Text>(found);
              expect(widget.maxLines,isNull,reason:text);
              expect(widget.overflow,isNot(TextOverflow.ellipsis),reason:text);
            }
            expect(tester.takeException(),isNull);
            await tester.ensureVisible(find.text('View'));await tester.tap(find.text('View'));await tester.pump();
            await tester.ensureVisible(find.text('Add to trip'));await tester.tap(find.text('Add to trip'));await tester.pump();
            expect(views,1);expect(adds,1);expect(tester.takeException(),isNull);
            final menu=find.byKey(ValueKey('recommendation-feedback-$id'));
            await tester.ensureVisible(menu);await tester.tap(menu);await tester.pumpAndSettle();
            await tester.tap(find.text('More like this'));await tester.pumpAndSettle();
            expect(feedback,'more_like_this');expect(tester.takeException(),isNull);
          });
        }
      }
    }
  }

  testWidgets('demonstration source and all labels wrap; unavailable rating is honest and writes stay hidden',(tester) async {
    tester.view.physicalSize=const Size(320,1000);tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:Scaffold(body:SingleChildScrollView(
      child:SizedBox(width:240,child:RecommendationCard(carousel:true,discovery:true,
        recommendation:{'destinationId':'isolated-demo','title':'Demonstration attraction','score':50,
          'synthetic':true,'recommendationEvidenceMode':'demonstration','matchedInterests':List.generate(9,(i)=>'Demo interest $i')},
        onView:(){},onAddToTrip:()=>throw StateError('Must be hidden'),onPreferenceFeedback:(_)=>throw StateError('Must be hidden')))))));
    await tester.pumpAndSettle();
    expect(find.text('Not rated yet'),findsOneWidget);
    expect(find.text('Demonstration review data'),findsOneWidget);
    expect(find.text('Demo interest 8'),findsOneWidget);
    expect(find.text('Add to trip'),findsNothing);
    expect(find.byType(PopupMenuButton<String>),findsNothing);
    expect(tester.takeException(),isNull);
  });

  testWidgets('old saved evidence refresh is explicit and reloading keeps the new generation',(tester) async {
    final api=_GenerationApi();
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:RecommendationScreen(
      api:api,initialDestination:'Penang',initialGenerationId:'old-generation')));
    await tester.pumpAndSettle();
    expect(api.generations,0);
    expect(find.text(recommendationEvidenceUpdateMessage),findsOneWidget);
    await tester.ensureVisible(find.byKey(const ValueKey('update-recommendation-evidence')));
    await tester.tap(find.byKey(const ValueKey('update-recommendation-evidence')));await tester.pumpAndSettle();
    expect(api.generations,1);
    expect(find.text(recommendationEvidenceUpdateMessage),findsNothing);
    expect(find.text('Place new-generation'),findsOneWidget);
    await tester.ensureVisible(find.text('Change preferences'));await tester.tap(find.text('Change preferences'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Back'));await tester.pumpAndSettle();
    expect(api.generationReads.last,'new-generation');
    expect(find.text('Place old-generation'),findsNothing);
    expect(api.generations,1);expect(tester.takeException(),isNull);
  });
}
