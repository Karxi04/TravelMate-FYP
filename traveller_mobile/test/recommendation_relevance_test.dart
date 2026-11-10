import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'core_personalization_notifications_test.dart' show RecsApi;

class RelevanceApi extends RecsApi {
  String basis='hybrid_v1';
  final settingsWrites=<Map>[];
  RelevanceApi() {
    minimum=80;
    pool.clear();
    for (final entry in [('weak','High ranking venue',90,30),('strong','Strong personal fit',60,90)]) {
      pool.add({'destinationId':entry.$1,'title':entry.$2,'finalScore':entry.$3,'hybridRankingScore':entry.$3,
        'personalSuitabilityScore':entry.$4,'discoveryEligible':entry.$1=='strong','scoringVersion':'relevance_v2','evidenceConfidence':.778,
        'collaborativeConfidence':0,'type':entry.$1=='weak' ? 'Adventure' : 'Culture','matchedInterests':entry.$1=='weak' ? [] : ['Culture'],
        'scoreBreakdown':{'content':70,'collaborative':50,'popularity':50}});
    }
  }
  @override
  Future<dynamic> get(String path,[Map<String,String>? query]) async {
    if(path=='/api/fr4/settings') return {'minimumMatchScore':minimum,'scoreBasis':basis};
    return super.get(path,query);
  }
  @override
  Future<dynamic> put(String path,[Map<String,dynamic>? body]) async {
    settingsWrites.add({...body!});basis=body['scoreBasis'];
    return super.put(path,body);
  }
}

void main() {
  final cases=jsonDecode(File('../backend_api/tests/fixtures/recommendation_relevance_cases.json').readAsStringSync()) as Map;
  for(final entry in cases['cases']) {
    test('Python/Dart edge-case parity ${entry['label']}',() {
      final row=RecommendationScoring.scoreCandidate(candidate:Map<String,dynamic>.from(entry['candidate']),preferences:Map<String,dynamic>.from(entry['preferences']));
      for(final key in ['contentScore','collaborativeScore','popularityScore','finalScore','personalSuitabilityScore','evidenceConfidence']) {
        final expected=entry['expected'][key];
        expect(row[key],expected==null ? isNull : closeTo((expected as num).toDouble(),.011),reason:key);
      }
      expect(row['destinationConcepts'],entry['expected']['destinationConcepts']);
      expect(row['interestEvidenceSource'],entry['expected']['interestEvidenceSource']);
    });
  }
  test('personal threshold cannot fall back to hybrid score or change the selected minimum',() {
    final snapshot={'recommendationResults':[
      {'destinationId':'strong','finalScore':60,'personalSuitabilityScore':90},
      {'destinationId':'weak','finalScore':90,'personalSuitabilityScore':30},
      {'destinationId':'unknown','finalScore':90}]};
    final page=recommendationPage(snapshot,{'scoreBasis':'personal_v2','minimumMatchScore':80,'limit':1});
    expect((page['recommendationResults'] as List).single['destinationId'],'strong');
    expect(page['pagination']['minimumMatchScore'],80);
    expect(()=>recommendationPage(snapshot,{'scoreBasis':'invented'}),throwsArgumentError);
  });
  test('standalone old settings remain legacy until explicit same-value choice; accounts isolated',() async {
    final memory=<String,String>{'travelmate_a_recommendation_settings':jsonEncode({'minimumMatchScore':80})};
    final a=StandaloneApiService(uidOverride:'a',memoryStore:memory);
    final other=StandaloneApiService(uidOverride:'other',memoryStore:memory);
    final before=Map.of(memory);
    expect((await a.get('/api/fr4/settings'))['scoreBasis'],'hybrid_v1');
    expect(memory,before);
    await a.put('/api/fr4/settings',{'minimumMatchScore':80,'scoreBasis':'personal_v2'});
    expect((await a.get('/api/fr4/settings'))['minimumMatchScore'],80);
    expect((await a.get('/api/fr4/settings'))['scoreBasis'],'personal_v2');
    expect((await other.get('/api/fr4/settings'))['minimumMatchScore'],70);
  });
  test('standalone candidate reuse retains earlier discovery and rejects foreign generation',() async {
    final memory=<String,String>{'travelmate_a_preferences':jsonEncode({'interests':['Culture'],'travelType':'Culture'})};
    final a=StandaloneApiService(uidOverride:'a',memoryStore:memory);
    Map place(String id)=>{'destinationId':id,'title':'Heritage museum $id','type':'museum','address':'Penang, Malaysia','source':'openstreetmap'};
    memory['travelmate_a_last_search_results']=jsonEncode([place('first')]);
    final first=await a.post('/api/fr4/recommendations/generate',{'destinationArea':'Penang','scoreBasis':'personal_v2','minimumMatchScore':70});
    memory['travelmate_a_last_search_results']=jsonEncode([place('second')]);
    final second=await a.post('/api/fr4/recommendations/generate',{'destinationArea':'Penang','scoreBasis':'personal_v2','minimumMatchScore':70,'previousGenerationId':first['recommendationGenerationId']});
    final ids=(second['recommendations'] as List).map((r)=>r['destinationId']);
    expect(ids,containsAll(['first','second']));
    final other=StandaloneApiService(uidOverride:'other',memoryStore:memory);
    await expectLater(other.post('/api/fr4/recommendations/generate',{'destinationArea':'Penang','previousGenerationId':first['recommendationGenerationId']}),throwsStateError);
  });
  test('peer confidence counts distinct valid users and unverified popularity cannot decide ties',() {
    final profile=<String,dynamic>{'interests':['Culture'],'travelType':'Culture'};
    final rows=<Map<String,dynamic>>[
      for(var i=0;i<5;i++) {'destinationId':'x','travellerId':'p','rating':5,'updatedAt':'2026-01-01'},
      {'destinationId':'x','travellerId':'p','rating':1,'updatedAt':'2026-02-01'},
      {'destinationId':'x','travellerId':'bad','rating':99},
    ];
    final row=RecommendationScoring.scoreCandidate(candidate:{'destinationId':'x','title':'Heritage museum'},preferences:profile,feedback:rows,peerPreferences:{'p':profile,'bad':profile},currentUserId:'self');
    expect(row['collaborativeRatingCount'],1);expect(row['rawCollaborativeScore'],20);
    final ranked=RecommendationScoring.rankCandidates(candidates:[
      {'destinationId':'a','title':'Museum a','ratingSource':'unverified_local_catalog','rating':1,'reviews':1},
      {'destinationId':'z','title':'Museum z','ratingSource':'unverified_local_catalog','rating':5,'reviews':90000},
    ],preferences:profile);
    expect(ranked.map((r)=>r['destinationId']).toList(),['a','z']);
  });
  testWidgets('discovery ignores saved 80 and excludes a high-ranked unrelated venue', (tester) async {
    tester.view.physicalSize=const Size(900,2000);tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
    final api=RelevanceApi();
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:RecommendationScreen(api:api,initialDestination:'Penang')));
    await tester.pumpAndSettle();
    expect(find.text('Strong personal fit'),findsOneWidget);
    expect(find.text('High ranking venue'),findsNothing);
    expect(find.byType(Slider),findsNothing);
    expect(find.byType(DropdownButton<String>),findsNothing);
    expect(api.settingsWrites,isEmpty);expect(api.minimum,80);
    expect(tester.takeException(),isNull);
  });
  testWidgets('score tap explains personal suitability, hybrid ranking and missing peer evidence',(tester) async {
    final place=RelevanceApi().pool.last;
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:Scaffold(body:SingleChildScrollView(child:RecommendationCard(recommendation:place,onView:(){})))));
    await tester.pumpAndSettle();
    final match=find.text('Personal match: 90/100');
    await tester.ensureVisible(match);await tester.tap(match);await tester.pumpAndSettle();
    expect(find.textContaining('Evidence coverage describes available metadata'),findsOneWidget);
    expect(find.textContaining('No peer ratings from similar travellers'),findsOneWidget);
    expect(tester.takeException(),isNull);
  });
}
