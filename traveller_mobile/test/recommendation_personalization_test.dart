import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';

const candidates = <Map<String, dynamic>>[
  {
    'destinationId': 'food_market',
    'title': 'Penang Street Food Market',
    'category': 'Hawker centre and local cuisine',
    'interests': ['Street Food', 'Cafe'],
    'budgetLevel': 'Budget',
    'pace': ['Relaxed', 'Moderate'],
    'purpose': ['Holiday', 'Solo travel'],
    'personality': ['Social', 'Relaxed'],
    'rating': 4.4,
    'popularity': 80,
  },
  {
    'destinationId': 'heritage_museum',
    'title': 'Penang Heritage Museum',
    'category': 'Historic museum and architecture',
    'interests': ['Culture', 'Heritage', 'History'],
    'budgetLevel': 'Moderate',
    'pace': ['Relaxed', 'Moderate'],
    'purpose': ['Educational trip', 'Holiday'],
    'personality': ['Planner', 'Explorer'],
    'rating': 4.4,
    'popularity': 80,
  },
  {
    'destinationId': 'nature_trail',
    'title': 'Penang Forest Adventure Trail',
    'category': 'Hiking and outdoor activity',
    'interests': ['Nature', 'Adventure', 'Hiking'],
    'budgetLevel': 'Moderate',
    'pace': ['Packed', 'Active'],
    'purpose': ['Holiday', 'Solo travel'],
    'personality': ['Explorer'],
    'rating': 4.4,
    'popularity': 80,
  },
  {
    'destinationId': 'shopping_mall',
    'title': 'Penang Leisure Mall',
    'category': 'Shopping retail and entertainment',
    'interests': ['Shopping', 'Leisure'],
    'budgetLevel': 'Moderate',
    'pace': ['Relaxed'],
    'purpose': ['Holiday', 'Family trip'],
    'personality': ['Social', 'Relaxed'],
    'rating': 4.4,
    'popularity': 80,
  },
];

Map<String, dynamic> profile(
  List<String> interests,
  String travelType, {
  String pace = 'Moderate',
  String purpose = 'Holiday',
  String personality = 'Balanced',
}) =>
    {
      'interests': interests,
      'travelType': travelType,
      'travelPace': pace,
      'budgetRange': 'Moderate',
      'travelPurpose': purpose,
      'travelPersonality': personality,
    };

void main() {
  test('multi-word interests map to shared concepts', () {
    expect(
      RecommendationTaxonomy.conceptsFor(
          ['Local Cuisine', 'Cafe', 'Street Food Market']),
      containsAll({'food', 'shopping'}),
    );
    expect(
      RecommendationTaxonomy.conceptsFor(['Local Culture', 'Historic Site']),
      {'culture'},
    );
  });

  test('controlled profiles produce meaningfully different first choices', () {
    final cases = {
      'food_market': profile(
        ['Food', 'Local Cuisine', 'Cafe'],
        'Food',
        pace: 'Relaxed',
        personality: 'Social',
      ),
      'heritage_museum': profile(
        ['Culture', 'Heritage', 'History'],
        'Culture',
        purpose: 'Educational trip',
        personality: 'Planner',
      ),
      'nature_trail': profile(
        ['Nature', 'Outdoor', 'Adventure'],
        'Nature',
        pace: 'Active',
        personality: 'Explorer',
      ),
      'shopping_mall': profile(
        ['Shopping', 'Leisure', 'Entertainment'],
        'Shopping',
        pace: 'Relaxed',
        personality: 'Relaxed',
      ),
    };

    for (final entry in cases.entries) {
      final ranked = RecommendationScoring.rankCandidates(
        candidates: candidates,
        preferences: entry.value,
      );
      expect(ranked.first['destinationId'], entry.key);
      expect(ranked.first['matchedInterests'], isNotEmpty);
    }
  });

  test('cold start is neutral and 60/30/10 weighting remains exact', () {
    final scored = RecommendationScoring.scoreCandidate(
      candidate: candidates.first,
      preferences: profile(['Food'], 'Food'),
    );

    expect(scored['collaborativeScore'], 50);
    expect(scored['collaborativeConfidence'], 0);
    expect(scored['collaborativeSource'], contains('neutral cold-start'));
    final breakdown = Map<String, dynamic>.from(scored['scoreBreakdown']);
    expect(breakdown['contentWeight'], .60);
    expect(breakdown['collaborativeWeight'], .30);
    expect(breakdown['popularityWeight'], .10);
    expect(
      scored['score'],
      closeTo(
        RecommendationScoring.weightedScore(
          (scored['contentScore'] as num).toDouble(),
          (scored['collaborativeScore'] as num).toDouble(),
          (scored['popularityScore'] as num).toDouble(),
        ),
        .02,
      ),
    );
  });

  test('reasons only claim evidence-backed factors', () {
    final scored = RecommendationScoring.scoreCandidate(
      candidate: const {
        'destinationId': 'food_only',
        'title': 'Penang Hawker Centre',
        'category': 'Street food',
        'rating': 4.2,
        'popularity': 70,
      },
      preferences: profile(
        ['Local Cuisine'],
        'Food',
        pace: 'Relaxed',
        personality: 'Social',
      ),
    );

    expect(scored['recommendationReason'], contains('Food and local cuisine'));
    expect(
        scored['recommendationReason'], isNot(contains('budget preference')));
    expect(scored['recommendationReason'], isNot(contains('travel pace')));
  });

  test('duplicate destination names are returned only once', () {
    final ranked = RecommendationScoring.rankCandidates(
      candidates: [
        ...candidates,
        {...candidates.first, 'destinationId': 'duplicate_provider_id'},
      ],
      preferences: profile(['Food'], 'Food'),
    );

    expect(
      ranked.where((item) => item['title'] == 'Penang Street Food Market'),
      hasLength(1),
    );
  });
}
