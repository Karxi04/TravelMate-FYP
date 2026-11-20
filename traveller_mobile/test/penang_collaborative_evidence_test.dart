import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';

void main() {
  final fixture = jsonDecode(File('../backend_api/tests/fixtures/penang_collaborative_benchmark.json').readAsStringSync()) as Map;
  final golden = jsonDecode(File('../backend_api/tests/fixtures/penang_collaborative_expected.json').readAsStringSync()) as Map;
  final peers = (fixture['peerPreferences'] as Map).map((key, value) =>
      MapEntry('$key', Map<String, dynamic>.from(value as Map)));
  final synthetic = (fixture['ratingContributions'] as List)
      .map((row) => Map<String, dynamic>.from(row as Map)).toList();
  // Counterfactual qualifying inputs exist only in this test, never in app storage.
  final qualifying = synthetic.map((row) => <String, dynamic>{
    for (final key in ['id', 'travellerId', 'destinationId', 'rating',
      'feedbackStatus', 'moderationStatus', 'updatedAt']) key: row[key],
  }).toList();
  for (final expected in golden['cases'] as List) {
    final candidate = Map<String, dynamic>.from((fixture['candidates'] as List)
        .firstWhere((row) => row['destinationId'] == expected['destinationId']) as Map);
    final profile = Map<String, dynamic>.from(fixture['currentProfiles'][expected['profile']] as Map);
    test('${expected['profile']} ${candidate['destinationId']} matches existing Python CF formula', () {
      final result = RecommendationScoring.scoreCandidate(candidate: candidate,
          preferences: profile, feedback: qualifying, peerPreferences: peers,
          currentUserId: 'cf_benchmark_viewer');
      expect(result['collaborativeRatingCount'], expected['eligiblePeers']);
      expect(result['rawCollaborativeScore'], closeTo(expected['rawPeerScore'] as num, .011));
      expect(result['collaborativeConfidence'], closeTo(expected['confidence'] as num, .011));
      expect(result['collaborativeScore'], closeTo(expected['collaborativeScore'] as num, .011));
      expect(result['finalScore'], closeTo(.6 * (result['contentScore'] as num) +
          .3 * (result['collaborativeScore'] as num) + .1 * (result['popularityScore'] as num), .02));
      final blocked = RecommendationScoring.scoreCandidate(candidate: candidate,
          preferences: profile, feedback: synthetic, peerPreferences: peers);
      expect(blocked['collaborativeRatingCount'], 0);
      expect(blocked['collaborativeConfidence'], 0);
      expect(blocked['collaborativeScore'], 50);
    });
  }

  test('alias duplicates and latest hidden contribution cannot inflate evidence', () {
    final profile = Map<String, dynamic>.from(fixture['currentProfiles']['culture_photography'] as Map);
    Map score(List<Map<String, dynamic>> rows) => RecommendationScoring.scoreCandidate(
        candidate: {'destinationId': 'penang_hill'}, preferences: profile,
        feedback: rows, peerPreferences: {'peer': profile});
    final old = <String, dynamic>{'id': 'old', 'travellerId': 'peer',
      'destinationId': 'penang_hill', 'rating': 5, 'updatedAt': '2026-01-01'};
    final latest = <String, dynamic>{...old, 'id': 'new', 'destinationId': 'local_penang_hill',
      'rating': 1, 'updatedAt': '2026-02-01'};
    expect(score([old, latest])['rawCollaborativeScore'], 20);
    expect(score([old, latest])['collaborativeRatingCount'], 1);
    expect(score([old, {...latest, 'feedbackStatus': 'hidden',
      'moderationStatus': 'approved'}])['collaborativeRatingCount'], 0);
    expect(score([{...old, 'fypPreview': true}])['collaborativeRatingCount'], 0);
  });

  Future<void> explain(WidgetTester tester, Map<String, dynamic> patch, {double textScale = 1}) async {
    await tester.pumpWidget(MaterialApp(theme: buildInkWashTheme(),
      builder: (context, child) => MediaQuery(data: MediaQuery.of(context)
          .copyWith(textScaler: TextScaler.linear(textScale)), child: child!), home: Scaffold(
      body: SingleChildScrollView(child: SizedBox(width: 320, child: RecommendationCard(
        recommendation: {'destinationId': 'local_penang_hill', 'title': 'Penang Hill',
          'finalScore': 62, 'scoreBreakdown': {'content': 70, 'collaborative': 50,
          'popularity': 50}, ...patch}, onView: () {}))))));
    await tester.ensureVisible(find.text('Recommendation score: 62/100'));
    await tester.tap(find.text('Recommendation score: 62/100'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  }

  testWidgets('cold start explains missing reviewer profiles without claiming a real average', (tester) async {
    await explain(tester, {'collaborativeConfidence': 0, 'collaborativeRatingCount': 0,
      'collaborativeFallbackReason': 'missing_peer_preferences'});
    expect(find.text('50/100 (Neutral baseline)'), findsOneWidget);
    expect(find.textContaining('not an average review rating'), findsOneWidget);
    expect(find.textContaining('Reviewers had no matching saved preference profiles'), findsOneWidget);
  });

  testWidgets('an evidence-backed fifty is not labelled cold start', (tester) async {
    await explain(tester, {'collaborativeConfidence': .667, 'collaborativeRatingCount': 2,
      'rawCollaborativeScore': 50, 'collaborativeSource': 'neutral (legacy wording)'});
    expect(find.text('50/100 (Peer evidence)'), findsOneWidget);
    expect(find.textContaining('2 qualifying peer rating(s)'), findsOneWidget);
    expect(find.textContaining('Raw peer score: 50.0/100'), findsOneWidget);
    expect(find.text('50/100 (Neutral baseline)'), findsNothing);
  });

  testWidgets('legacy saved scores with absent metadata disclose unavailable evidence', (tester) async {
    await explain(tester, {});
    expect(find.text('50/100 (Evidence unavailable)'), findsOneWidget);
    expect(find.textContaining('saved score has not been recalculated'), findsOneWidget);
    expect(find.textContaining('No peer ratings from similar travellers qualified'), findsNothing);
  });

  testWidgets('sparse evidence reports raw score and confidence', (tester) async {
    await explain(tester, {'collaborativeConfidence': .333, 'collaborativeRatingCount': 1,
      'rawCollaborativeScore': 100, 'scoreBreakdown': {'content': 70,
      'collaborative': 66.67, 'popularity': 50}});
    expect(find.text('67/100 (Peer evidence)'), findsOneWidget);
    expect(find.textContaining('Evidence confidence: 33%'), findsOneWidget);
    expect(find.textContaining('confidence is not prediction accuracy'), findsOneWidget);
  });

  testWidgets('evidence explanation fits a320dp display with large text', (tester) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await explain(tester, {}, textScale: 1.8);
    await tester.ensureVisible(find.textContaining('saved score has not been recalculated'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
