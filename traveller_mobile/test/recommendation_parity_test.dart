import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';

void main() {
  final fixture = jsonDecode(
      File('../backend_api/tests/fixtures/penang_core_demo.json')
          .readAsStringSync()) as Map;
  final golden = jsonDecode(
      File('../backend_api/tests/fixtures/recommendation_parity.json')
          .readAsStringSync()) as Map;
  final candidates = (fixture['candidates'] as List)
      .map((v) => Map<String, dynamic>.from(v as Map))
      .toList();
  final peers = (golden['peers'] as Map).map((key, value) =>
      MapEntry('$key', Map<String, dynamic>.from(value as Map)));
  final feedback = (golden['feedback'] as List)
      .map((v) => Map<String, dynamic>.from(v as Map))
      .toList();
  for (final rawCase in golden['cases']) {
    final profile = Map<String, dynamic>.from(rawCase['preferences'] as Map);
    test(
        'profile ${rawCase['label']} matches real Python components for the same 16 genuine Penang places',
        () {
      final ranked = RecommendationScoring.rankCandidates(candidates:candidates,preferences:profile,feedback:feedback,peerPreferences:peers,currentUserId:'${profile['travellerId']}',limit:150);
      expect(ranked.map((row)=>row['destinationId']).toList(),rawCase['expectedRanking']);
      for (final candidate in candidates) {
        final result = RecommendationScoring.scoreCandidate(
            candidate: candidate,
            preferences: profile,
            feedback: feedback,
            peerPreferences: peers,
            currentUserId: '${profile['travellerId']}');
        final expected = (rawCase['expected'] as List).firstWhere(
            (row) => row['destinationId'] == candidate['destinationId']);
        for (final key in [
          'contentScore',
          'collaborativeScore',
          'popularityScore',
          'finalScore',
          'personalSuitabilityScore',
          'evidenceConfidence'
        ]) {
          expect(result[key], closeTo((expected[key] as num).toDouble(), .011),
              reason: '${candidate['title']} $key');
        }
        expect(result['popularitySource'], 'neutral_missing_rating');
      }
    });
  }
  test(
      'adding an unrelated questionnaire interest does not penalize a specialist',
      () {
    final candidate = <String, dynamic>{
      'destinationId': 'fixture',
      'title': 'A venue',
      'category': 'Cultural museums'
    };
    Map score(List interests) => RecommendationScoring.scoreCandidate(
        candidate: candidate, preferences: {'interests': interests});
    expect(score(['Culture'])['contentScore'],
        score(['Culture', 'Food'])['contentScore']);
    expect(
        score(['Culture'])['contentSignals']['interests']
            ['primaryCategoryMatch'],
        true);
    final invalid = RecommendationScoring.scoreCandidate(candidate: {
      ...candidate,
      'rating': double.nan
    }, preferences: {
      'interests': ['Culture']
    });
    expect(invalid['popularityScore'], 50);
    expect((invalid['finalScore'] as num).isFinite, true);
  });
}
