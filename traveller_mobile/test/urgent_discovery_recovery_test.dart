import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'core_personalization_notifications_test.dart' show RecsApi;

class HtmlFailureApi extends RecsApi {
  final bool cached;
  bool failing = true;
  HtmlFailureApi(this.cached);
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    if(path=='/api/fr4/recommendations' && !cached && failing) {
      return {'ok':true,'recommendationGenerationId':'invalid-candidates',
        'recommendations':[{'title':'Unrelated cached venue','discoveryEligible':false}],
        'pagination':{'discoveryMode':recommendationDiscoveryMode}};
    }
    return super.get(path,query);
  }
  @override
  Future<dynamic> post(String path,[Map<String,dynamic>? body]) async {
    if(path=='/api/fr4/recommendations/generate' && failing) {
      return ApiService.decodeResponse(http.Response('<!doctype html><html>500 Internal Server Error private trace</html>',500));
    }
    return super.post(path,body);
  }
}

class OnDeviceApi extends ApiService {
  final StandaloneApiService local;
  OnDeviceApi(this.local);
  @override
  bool get isStandalone=>true;
  @override
  Future<dynamic> get(String path,[Map<String,String>? query])=>local.get(path,query);
  @override
  Future<dynamic> post(String path,[Map<String,dynamic>? body])=>local.post(path,body);
}

void main() {
  test('HTTP decoder sanitizes HTML and 5xx but preserves structured client-error contracts',() {
    for(final response in [http.Response('<html>private trace</html>',500),
      http.Response(jsonEncode({'error':'private backend exception','code':'retry_later','requestId':'abcdef1234567890'}),503),
      http.Response('<html>private trace</html>',400)]) {
      try {ApiService.decodeResponse(response);fail('Expected API error');}
      on ApiException catch(error) {
        expect(userFacingApiError(error),backendUnavailableMessage);
        expect(error.message, isNot(contains('private')));
        expect(error.data['error'] ?? '', isNot(contains('<html>')));
      }
    }
    try {ApiService.decodeResponse(http.Response(jsonEncode({'error':'Date conflict','code':'date_conflict','tripDates':{'startDate':'2026-11-10'}}),409));fail('Expected conflict');}
    on ApiException catch(error) {expect(error.code,'date_conflict');expect(error.tripDates?['startDate'],'2026-11-10');expect(error.message,'Date conflict');}
  });

  final fixture=jsonDecode(File('../backend_api/tests/fixtures/photography_food_discovery.json').readAsStringSync()) as Map;
  final base=jsonDecode(File('../backend_api/tests/fixtures/penang_core_demo.json').readAsStringSync()) as Map;
  test('Python/Dart frozen Photography Food scores and discovery retain independent human labels',() {
    final candidates=[...base['candidates'],...fixture['additionalCandidates']].map((value)=>Map<String,dynamic>.from(value as Map)).toList();
    final profile=Map<String,dynamic>.from(fixture['profile']);
    final rows=RecommendationScoring.rankCandidates(candidates:candidates,preferences:profile,limit:150);
    expect(rows.map((row)=>row['destinationId']).toList(),fixture['baselineOrdering']);
    final shown=<Map>[];
    for(final row in rows) {
      final before=fixture['baselineScores'][row['destinationId']];
      for(final key in ['finalScore','personalSuitabilityScore','contentScore','collaborativeScore','popularityScore']) {
        expect(row[key],before[key]==null ? isNull : closeTo((before[key] as num).toDouble(),.011),reason:'${row['destinationId']} $key');
      }
      final annotation=discoveryAnnotations(row,profile);
      if(annotation['discoveryEligible']==true) shown.add({...row,...annotation});
    }
    expect(shown,hasLength(10));
    expect(shown.take(5).every((row)=>fixture['judgements'][row['destinationId']]['grade']>0),isTrue);
    expect(shown.where((row)=>row['foodExperienceType']=='dining'),hasLength(2));
    expect(shown.singleWhere((row)=>row['destinationId']=='demo_penang_wonderfood')['foodExperienceType'],'food_museum');
    expect(shown.singleWhere((row)=>row['destinationId']=='demo_penang_spice')['foodExperienceType'],'culinary_culture');
    expect(shown.any((row)=>row['destinationId']=='demo_penang_armenian'),isFalse,reason:'Human relevance does not inject missing production tags.');
    for (final entry in {'Verified cooking school experience':'cooking','Verified cooking class':'cooking',
      'Food museum':'food_museum','Hawker centre':'dining','Ordinary botanical garden':null}.entries) {
      final candidate={'title':entry.key,'destinationConcepts':RecommendationTaxonomy.candidateConcepts({'title':entry.key}).toList()};
      expect(discoveryAnnotations(candidate,{'interests':['Food']})['foodExperienceType'],entry.value);
    }
  });

  for(final cached in [true,false]) {
    testWidgets('HTML failure gives one error and functional Retry; cached=$cached',(tester) async {
      final api=HtmlFailureApi(cached);
      await tester.pumpWidget(MaterialApp(home:RecommendationScreen(api:api,initialDestination:'Penang')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('Refresh for you'),-300,scrollable:find.byType(Scrollable).first);
      await tester.ensureVisible(find.text('Refresh for you'));await tester.pumpAndSettle();
      await tester.tap(find.text('Refresh for you'));await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text(backendUnavailableMessage),300,scrollable:find.byType(Scrollable).first);
      expect(find.text(backendUnavailableMessage),findsOneWidget);
      expect(find.byType(AppErrorState),cached ? findsNothing : findsOneWidget);
      expect(find.textContaining('<html>'),findsNothing);
      expect(find.textContaining('private trace'),findsNothing);
      expect(find.text('No relevant suggestions available yet'),findsNothing);
      api.failing=false;
      final retry=find.text(cached ? 'Retry' : 'Try again');
      await tester.ensureVisible(retry);await tester.pumpAndSettle();
      await tester.tap(retry);await tester.pumpAndSettle();
      expect(find.text(backendUnavailableMessage),findsNothing);
      await tester.scrollUntilVisible(find.text('Fixture place 0'),300,scrollable:find.byType(Scrollable).first);
      expect(find.text('Fixture place 0'),findsOneWidget);
    });
  }

  testWidgets('real standalone discovery ignores saved90 and displays supported suggestions without mode controls',(tester) async {
    tester.view.physicalSize=const Size(1000,2400);tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
    final memory=<String,String>{'travelmate_isolated_preferences':jsonEncode({...fixture['profile'],'travellerId':'isolated'}),
      'travelmate_isolated_recommendation_settings':jsonEncode({'minimumMatchScore':90,'scoreBasis':'hybrid_v1'})};
    final local=StandaloneApiService(uidOverride:'isolated',memoryStore:memory);
    final original=memory['travelmate_isolated_recommendation_settings'];
    await tester.pumpWidget(MaterialApp(home:RecommendationScreen(api:OnDeviceApi(local),initialDestination:'Penang')));
    await tester.pumpAndSettle();
    expect(find.byType(Slider),findsNothing);expect(find.byType(DropdownButton<String>),findsNothing);
    final response=await local.get('/api/fr4/recommendations',{'destinationArea':'Penang','discoveryMode':recommendationDiscoveryMode});
    expect(response['recommendations'],isNotEmpty);
    final themes=(response['recommendations'] as List).expand((row)=>row['discoveryMatchedConcepts'] as List).toSet();
    expect(themes,containsAll(['photography','food']));
    expect(memory['travelmate_isolated_recommendation_settings'],original);
    expect(find.text('No relevant suggestions available yet'),findsNothing);
    await tester.scrollUntilVisible(find.text('Why this suggestion').first,300,scrollable:find.byType(Scrollable).first);
    await tester.ensureVisible(find.text('Why this suggestion').first);await tester.tap(find.text('Why this suggestion').first);await tester.pumpAndSettle();
    expect(find.textContaining('not an enjoyment probability'),findsOneWidget);
  });

  testWidgets('food museum card explains that a food theme is not dining',(tester) async {
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(
      discovery:true,recommendation:{'title':'Wonderfood Museum','foodExperienceType':'food_museum','finalScore':64},onView:(){})))));
    await tester.pumpAndSettle();
    expect(find.text('Food-themed museum; dining is not implied.'),findsOneWidget);
    expect(find.textContaining('Personal match:'),findsNothing);
  });

  test('standalone null feedback stays unchanged and cannot silently lose negative history',() async {
    final memory=<String,String>{'travelmate_null_preferences':jsonEncode({...fixture['profile'],'travellerId':'null'}),
      'travelmate_null_learned_preference_profile':jsonEncode({'feedbackByDestination':null})};
    final local=StandaloneApiService(uidOverride:'null',memoryStore:memory);
    final original=Map.of(memory);
    await expectLater(local.post('/api/fr4/recommendations/generate',{'destinationArea':'Penang','discoveryMode':recommendationDiscoveryMode}),throwsStateError);
    expect(memory,original);
  });
}
