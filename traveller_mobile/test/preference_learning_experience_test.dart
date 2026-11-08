import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/preference_learning.dart';
import 'package:travelmate_traveller/core/utils/recommendation_taxonomy.dart';
import 'package:travelmate_traveller/modules/fr01_user_management/profile_tab.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';

Map<String, dynamic> _place({
  String id = 'food_place',
  String type = 'restaurant',
}) =>
    {
      'destinationId': id,
      'title': id == 'food_place' ? 'Local Food Hall' : 'Shopping Centre',
      'type': type,
      'category': type,
      'rating': 4.5,
      'reviews': 200,
      'popularity': 80,
      'finalScore': 82,
      'recommendationSource': 'cache',
    };

void main() {
  test('feedback learns separately, reverses cleanly, and preserves base data',
      () {
    final base = {
      'interests': ['Culture'],
      'travelType': 'Explorer',
      'preferenceProfileVersion': 'base_v1',
    };
    final positive = PreferenceLearning.applyFeedback(
      null,
      userId: 'u1',
      destinationId: 'food_place',
      feedbackType: 'more_like_this',
      destinationConcepts: ['food'],
      recommendationGenerationId: 'rec1',
      sourceContext: 'test',
      now: '2026-10-05T00:00:00Z',
      eventId: '1',
    );
    expect(positive.profile['affinities']['food'], .15);
    expect(base['interests'], ['Culture']);

    final noOp = PreferenceLearning.applyFeedback(
      positive.profile,
      userId: 'u1',
      destinationId: 'food_place',
      feedbackType: 'more_like_this',
      destinationConcepts: ['food'],
      recommendationGenerationId: 'rec1',
      sourceContext: 'test',
      now: '2026-10-05T00:01:00Z',
      eventId: '2',
    );
    expect(noOp.changed, isFalse);

    final reversed = PreferenceLearning.applyFeedback(
      positive.profile,
      userId: 'u1',
      destinationId: 'food_place',
      feedbackType: 'not_for_me',
      destinationConcepts: ['food'],
      recommendationGenerationId: 'rec1',
      sourceContext: 'test',
      now: '2026-10-05T00:02:00Z',
      eventId: '3',
    );
    expect(reversed.profile['affinities']['food'], -.12);
    expect(reversed.event?['previousFeedbackType'], 'more_like_this');
  });

  test(
      'bounded learning changes content only inside the existing score formula',
      () {
    Map<String, dynamic> learned(double value) => {
          'affinities': {'food': value},
          'learnedPreferenceVersion': 'learned_1',
        };
    final base = <String, dynamic>{'interests': <String>[]};
    final neutral = RecommendationScoring.scoreCandidate(
      candidate: _place(),
      preferences: base,
    );
    final positive = RecommendationScoring.scoreCandidate(
      candidate: _place(),
      preferences: PreferenceLearning.effectiveProfile(base, learned(1)),
    );
    final negative = RecommendationScoring.scoreCandidate(
      candidate: _place(),
      preferences: PreferenceLearning.effectiveProfile(base, learned(-1)),
    );
    expect(positive['contentScore'], greaterThan(neutral['contentScore']));
    expect(negative['contentScore'], lessThan(neutral['contentScore']));
    expect(positive['scoreBreakdown']['contentWeight'], .60);
    expect(positive['scoreBreakdown']['collaborativeWeight'], .30);
    expect(positive['scoreBreakdown']['popularityWeight'], .10);
    expect(
      positive['recommendationReason'],
      contains('Based on your recent interest in Food'),
    );
  });

  test(
      'effective versions change after learning and reset clears only learning',
      () {
    final update = PreferenceLearning.applyFeedback(
      null,
      userId: 'u1',
      destinationId: 'shopping_place',
      feedbackType: 'not_for_me',
      destinationConcepts: ['shopping'],
      recommendationGenerationId: 'rec1',
      sourceContext: 'test',
      now: 'now',
      eventId: '4',
    );
    expect(
      PreferenceLearning.effectiveVersion('base_v1', update.profile),
      isNot('base_v1'),
    );
    final reset = PreferenceLearning.reset(
      update.profile,
      userId: 'u1',
      now: 'later',
      eventId: '5',
    );
    expect(reset.profile['affinities'], isEmpty);
    expect(reset.profile['feedbackByDestination'], isEmpty);
  });

  testWidgets('For You submits simple feedback against the displayed snapshot',
      (tester) async {
    final api = _LearningApi();
    await tester.pumpWidget(
      MaterialApp(
        theme: buildInkWashTheme(),
        home: RecommendationScreen(api: api),
      ),
    );
    await tester.pumpAndSettle();

    final feedbackButton = find.byKey(
      const ValueKey('recommendation-feedback-food_place'),
    );
    await tester.ensureVisible(feedbackButton);
    await tester.pumpAndSettle();
    await tester.tap(feedbackButton);
    await tester.pumpAndSettle();
    await tester.tap(find.text('More like this'));
    await tester.pumpAndSettle();

    expect(api.lastFeedback?['recommendationGenerationId'], 'rec_visible_1');
    expect(api.lastFeedback?['feedbackType'], 'more_like_this');
    expect(find.text('More like this saved'), findsOneWidget);
    expect(
      find.text('Thanks — this will help improve future recommendations.'),
      findsOneWidget,
    );
  });

  testWidgets('Profile explains learning and confirms a learning-only reset',
      (tester) async {
    final api = _LearningApi();
    await tester.pumpWidget(
      MaterialApp(
        theme: buildInkWashTheme(),
        home: ProfileTab(api: api),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.text('TravelMate adapts recommendations using your feedback.'),
      findsOneWidget,
    );
    expect(find.text('More Food'), findsOneWidget);
    expect(find.textContaining('0.15'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('reset-learned-preferences')));
    await tester.pumpAndSettle();
    expect(find.text('Reset learned preferences?'), findsOneWidget);
    expect(find.textContaining('trips and reviews will stay unchanged'),
        findsOneWidget);
    await tester.tap(find.text('Reset learning'));
    await tester.pumpAndSettle();
    expect(api.resetCalls, 1);
  });

  testWidgets('card exposes Not for me and shows existing feedback state',
      (tester) async {
    String? selected;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildInkWashTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: RecommendationCard(
              recommendation: _place(id: 'shopping_place', type: 'shopping'),
              preferenceFeedback: 'not_for_me',
              onPreferenceFeedback: (value) => selected = value,
              onView: () {},
            ),
          ),
        ),
      ),
    );

    expect(find.text('Not for me saved'), findsOneWidget);
    await tester.tap(find.byKey(
      const ValueKey('recommendation-feedback-shopping_place'),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Not for me').last);
    expect(selected, 'not_for_me');
  });
}

class _LearningApi extends ApiService {
  Map<String, dynamic>? lastFeedback;
  int resetCalls = 0;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    switch (path) {
      case '/api/fr1/me':
        return {
          'ok': true,
          'profile': {'name': 'Alya', 'email': 'alya@example.com'},
        };
      case '/api/fr2/preferences':
        return {
          'ok': true,
          'preferences': {
            'travelPersonality': 'Explorer',
            'interests': ['Food'],
          },
        };
      case '/api/fr4/recommendations':
        return {
          'ok': true,
          'recommendationGenerationId': 'rec_visible_1',
          'recommendations': [_place()],
          'source': 'cache',
        };
      case '/api/fr4/preference-feedback':
        return {
          'ok': true,
          'learning': {
            'currentFeedback': <String, dynamic>{},
            'tendencies': [
              {'concept': 'food', 'label': 'Food', 'direction': 'up'},
            ],
            'hasLearnedPreferences': true,
          },
        };
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr4/recommendations/generate') {
      return {'ok':true,'recommendationGenerationId':'rec_updated','recommendations':[_place()],'source':'cache'};
    }
    if (path == '/api/fr4/preference-feedback') {
      lastFeedback = body;
      return {'ok': true};
    }
    throw StateError('Unexpected POST $path');
  }

  @override
  Future<dynamic> delete(String path) async {
    if (path == '/api/fr4/preference-feedback') {
      resetCalls += 1;
      return {
        'ok': true,
        'learning': {
          'currentFeedback': <String, dynamic>{},
          'tendencies': <dynamic>[],
          'hasLearnedPreferences': false,
        },
      };
    }
    throw StateError('Unexpected DELETE $path');
  }
}
