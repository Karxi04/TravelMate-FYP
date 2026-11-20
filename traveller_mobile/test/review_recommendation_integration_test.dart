import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/demonstration_recommendations_screen.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'core_personalization_notifications_test.dart' show RecsApi;

Map<String, dynamic> object(dynamic value) => Map<String, dynamic>.from(value as Map);
List<Map<String, dynamic>> objects(dynamic value) => (value as List).map(object).toList();

class _EvidenceApi extends RecsApi {
  final simulationReads = <Map<String, String>>[];
  bool mixed = false;
  final row = <String, dynamic>{
    'destinationId': 'local_kek_lok_si', 'title': 'Kek Lok Si Temple',
    'synthetic': true, 'recommendationEvidenceMode': 'demonstration',
    'score': 62, 'scoreBreakdown': {'content': 70, 'collaborative': 50, 'popularity': 60.82},
    'collaborativeRatingCount': 3, 'collaborativeConfidence': 1, 'rawCollaborativeScore': 50,
    'popularityEvidence': {'source': 'demonstration_approved_reviews', 'rating': 3.8, 'reviewCount': 10},
  };
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr4/recommendations/demonstration') {
      simulationReads.add({...?query});
      return {'synthetic': true, 'recommendationEvidenceMode': 'demonstration',
        'areas': ['Penang', 'Johor'], 'profiles': [
          {'key': 'current', 'label': 'My preferences (simulation only)'},
          {'key': 'nature', 'label': 'Nature and adventure'}],
        'recommendations': [{...row, if (mixed) 'synthetic': false}]};
    }
    final data = await super.get(path, query);
    if (path == '/api/fr4/recommendations') return {...data, 'demonstrationAvailable': true};
    return data;
  }
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) =>
      throw StateError('This acceptance flow must not write: $path');
  @override
  Future<dynamic> put(String path, [Map<String, dynamic>? body]) =>
      throw StateError('This acceptance flow must not write: $path');
}

void main() {
  final fixture = object(jsonDecode(File('../backend_api/tests/fixtures/penang_review_integration_parity.json').readAsStringSync()));
  final input = object(fixture['input']);
  for (final key in ['culture', 'nature', 'family']) {
    test('12 attractions, genuine-contract and demonstration scores match Python for $key', () {
      final preferences = object(input['currentProfiles'][key]);
      for (final simulation in [false, true]) {
        final feedback = objects(input[simulation ? 'examples' : 'genuineEligibilityFixtures']);
        final peers = object(input[simulation ? 'exampleProfiles' : 'genuineFixtureProfiles'])
            .map((k, v) => MapEntry(k, object(v)));
        final summaries = RecommendationScoring.reviewSummaries(feedback, demonstration: simulation);
        final expected = objects(fixture['expected']).where((r) => r['profile'] == key &&
            r['mode'] == (simulation ? 'demonstration' : 'genuine_eligibility_fixture'));
        expect(expected.length, 12);
        for (final row in expected) {
          final candidate = objects(input['candidates']).firstWhere((c) => c['destinationId'] == row['destinationId']);
          final actual = RecommendationScoring.scoreCandidate(candidate: candidate, preferences: preferences,
            feedback: feedback, peerPreferences: peers, reviewSummaries: summaries,
            evidenceMode: simulation ? 'demonstration' : 'genuine');
          for (final pair in [('contentScore', 'content'), ('rawCollaborativeScore', 'rawPeer'),
            ('collaborativeConfidence', 'confidence'), ('collaborativeScore', 'collaborative'),
            ('popularityScore', 'popularity'), ('finalScore', 'hybrid')]) {
            expect(actual[pair.$1], closeTo(row[pair.$2] as num, .02), reason: '${row['title']} ${pair.$1}');
          }
          expect(actual['collaborativeRatingCount'], row['eligiblePeers']);
          expect(actual['popularitySource'], row['popularitySource']);
          expect(actual['popularityEvidence'], row['popularityEvidence']);
        }
      }
    });
  }

  test('all104 examples stay synthetic and excluded from genuine summaries and peer evidence', () {
    final examples = objects(input['examples']);
    final before = jsonEncode(examples);
    expect(examples.length, 104);
    expect(RecommendationScoring.reviewSummaries(examples), isEmpty);
    expect(RecommendationScoring.approvedContributions(examples, demonstration: true).length, 96);
    final preferences = object(input['currentProfiles']['culture']);
    final peers = object(input['exampleProfiles']).map((k,v) => MapEntry(k,object(v)));
    for (final candidate in objects(input['candidates'])) {
      final row = RecommendationScoring.scoreCandidate(candidate: candidate, preferences: preferences,
        feedback: examples, peerPreferences: peers);
      expect(row['collaborativeRatingCount'], 0);
      expect(row['collaborativeScore'], 50);
      expect(row['popularityScore'], 50);
    }
    expect(jsonEncode(examples), before);
  });

  test('verified provider takes precedence; canonical local fallback is genuine and exact', () {
    final feedback = [for (var i=0; i<10; i++) <String,dynamic>{
      'travellerId': 'isolated_$i', 'destinationId': 'kek_lok_si',
      'rating': [5,5,4,4,4,4,3,3,3,3][i], 'feedbackStatus': 'visible', 'moderationStatus': 'approved'}];
    final summaries = RecommendationScoring.reviewSummaries(feedback);
    Map score(Map<String,dynamic> candidate) => RecommendationScoring.scoreCandidate(
      candidate: candidate, preferences: {}, reviewSummaries: summaries);
    final provider = score({'destinationId':'other-provider-id','reviewDestinationId':'local_kek_lok_si',
      'ratingSource':'provider','rating':4.5,'reviews':9000});
    expect(provider['popularityScore'], 90);
    expect(provider['popularitySource'], 'provider_rating_review_count');
    final local = score({'destinationId':'other-provider-id','reviewDestinationId':'local_kek_lok_si',
      'ratingSource':'unverified_local_catalog','rating':5,'reviews':90000});
    expect(local['popularityScore'], 60.82);
    expect(local['popularityEvidence']['rating'], 3.8);
    expect(local['popularityEvidence']['reviewCount'], 10);
  });

  test('normal discovery and standalone generation cannot accept demonstration evidence', () async {
    expect(() => validateDiscoveryResponse({'recommendationEvidenceMode':'demonstration'}), throwsStateError);
    expect(() => validateDiscoveryResponse({'recommendations':[{'synthetic':true}]}), throwsStateError);
    final memory = <String,String>{};
    final api = StandaloneApiService(uidOverride:'isolated',memoryStore:memory);
    await expectLater(api.post('/api/fr4/recommendations/generate', {'evidenceMode':'demonstration'}), throwsStateError);
    expect(memory, isEmpty);
  });

  testWidgets('For You opens a read-only simulation and returns to the original generation', (tester) async {
    tester.view.physicalSize = const Size(800,1600); tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final api = _EvidenceApi();
    await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(), home:RecommendationScreen(api:api,initialDestination:'Penang')));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Demonstration review data')); await tester.pumpAndSettle();
    expect(find.text('Demonstration reviews'), findsOneWidget);
    expect(find.text('Kek Lok Si Temple'), findsOneWidget);
    await tester.ensureVisible(find.text('View simulation')); await tester.tap(find.text('View simulation'));
    await tester.pumpAndSettle();
    expect(find.textContaining('existing destination identity'), findsOneWidget);
    await tester.tap(find.text('Close')); await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Back')); await tester.pumpAndSettle();
    expect(find.byType(RecommendationScreen), findsOneWidget);
    expect(api.generations, 0); expect(api.feedback, isEmpty);
    expect(api.simulationReads, [{'profileKey':'current','destinationArea':'Penang'}]);
    expect(tester.takeException(), isNull);
  });

  testWidgets('simulation profile and area selection uses GET only; reopening reloads ephemeral results', (tester) async {
    final api = _EvidenceApi();
    Future<void> open() async {
      await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:DemonstrationRecommendationsScreen(api:api)));
      await tester.pumpAndSettle();
    }
    await open();
    await tester.tap(find.text('My preferences (simulation only)')); await tester.pumpAndSettle();
    await tester.tap(find.text('Nature and adventure').last); await tester.pumpAndSettle();
    await tester.tap(find.text('Penang')); await tester.pumpAndSettle();
    await tester.tap(find.text('Johor').last); await tester.pumpAndSettle();
    expect(api.simulationReads.last, {'profileKey':'nature','destinationArea':'Johor'});
    await tester.pumpWidget(const SizedBox()); await tester.pumpAndSettle();
    await open();
    expect(api.simulationReads.last, {'profileKey':'current','destinationArea':'Penang'});
    expect(api.generations,0); expect(api.feedback,isEmpty);
    expect(tester.takeException(),isNull);
  });

  testWidgets('mixed public/simulated response fails closed without showing cards', (tester) async {
    final api = _EvidenceApi()..mixed = true;
    await tester.pumpWidget(MaterialApp(home:DemonstrationRecommendationsScreen(api:api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('No saved recommendations were changed'),findsOneWidget);
    expect(find.text('Kek Lok Si Temple'),findsNothing);
    expect(api.generations,0);
  });

  for (final entry in [
    ('provider_rating_review_count','Verified provider rating: 4.5/5'),
    ('genuine_approved_local_reviews','Approved genuine TravelMate reviews: 4.5/5'),
    ('demonstration_approved_reviews','Demonstration review data: 4.5/5'),
  ]) {
    testWidgets('score explanation identifies ${entry.$1} without creating trip/feedback actions', (tester) async {
      final simulation = entry.$1 == 'demonstration_approved_reviews';
      final api = _EvidenceApi();
      var actions=0;
      await tester.pumpWidget(MaterialApp(theme:buildInkWashTheme(),home:Scaffold(body:SingleChildScrollView(
        child:RecommendationCard(recommendation:{...api.row, 'synthetic':simulation,
          'recommendationEvidenceMode':simulation ? 'demonstration':'genuine',
          'popularityEvidence':{'source':entry.$1,'rating':4.5,'reviewCount':10}},
          onView:(){}, onAddToTrip:()=>actions++, onPreferenceFeedback:(_)=>actions++)))));
      await tester.pumpAndSettle();
      if (simulation) {
        expect(find.text('Add to Trip'),findsNothing);
        expect(find.byType(PopupMenuButton<String>),findsNothing);
        expect(find.text('Demonstration review data'),findsOneWidget);
      }
      await tester.ensureVisible(find.text('Recommendation score: 62/100'));
      await tester.tap(find.text('Recommendation score: 62/100')); await tester.pumpAndSettle();
      expect(find.textContaining(entry.$2),findsOneWidget);
      expect(find.textContaining('Eligible reviewers: 3'),findsOneWidget);
      expect(actions,0); expect(tester.takeException(),isNull);
    });
  }
}
