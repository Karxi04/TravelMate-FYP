import 'recommendation_taxonomy.dart';

class PreferenceLearningUpdate {
  final Map<String, dynamic> profile;
  final Map<String, dynamic>? event;
  final bool changed;

  const PreferenceLearningUpdate({
    required this.profile,
    required this.event,
    required this.changed,
  });
}

class PreferenceLearning {
  static const double affinityMin = -1;
  static const double affinityMax = 1;
  static const double moreLikeThisStep = .15;
  static const double notForMeStep = -.12;
  static const double learnedInterestStrength = .30;
  static const validFeedbackTypes = {'more_like_this', 'not_for_me'};

  static List<String> canonicalConcepts(dynamic raw) {
    final values = raw is Iterable && raw is! String ? raw : [raw];
    return values
        .map((value) => value.toString().trim().toLowerCase())
        .where(RecommendationTaxonomy.conceptTerms.containsKey)
        .toSet()
        .toList()
      ..sort();
  }

  static double feedbackDelta(String feedbackType) => switch (feedbackType) {
        'more_like_this' => moreLikeThisStep,
        'not_for_me' => notForMeStep,
        _ => throw ArgumentError('Unsupported recommendation feedback type'),
      };

  static double _bounded(num value) =>
      (value.clamp(affinityMin, affinityMax) * 10000).round() / 10000;

  static Map<String, dynamic> emptyProfile(
    String userId, {
    required String now,
  }) =>
      {
        'userId': userId,
        'travellerId': userId,
        'affinities': <String, dynamic>{},
        'evidence': <String, dynamic>{},
        'feedbackByDestination': <String, dynamic>{},
        'learnedPreferenceVersion': '',
        'createdAt': now,
        'updatedAt': now,
      };

  static ({Map<String, dynamic> affinities, Map<String, dynamic> evidence})
      _rebuild(Map<String, dynamic> states) {
    final totals = <String, double>{};
    final evidence = <String, dynamic>{};
    for (final raw in states.values.whereType<Map>()) {
      final state = Map<String, dynamic>.from(raw);
      final feedbackType = (state['feedbackType'] ?? '').toString();
      if (!validFeedbackTypes.contains(feedbackType)) continue;
      final delta = feedbackDelta(feedbackType);
      for (final concept in canonicalConcepts(state['destinationConcepts'])) {
        totals[concept] = (totals[concept] ?? 0) + delta;
        final bucket = Map<String, dynamic>.from(
          evidence[concept] as Map? ??
              const {'positiveCount': 0, 'negativeCount': 0},
        );
        final key = feedbackType == 'more_like_this'
            ? 'positiveCount'
            : 'negativeCount';
        bucket[key] = (bucket[key] as int? ?? 0) + 1;
        evidence[concept] = bucket;
      }
    }
    final affinities = <String, dynamic>{};
    for (final entry in totals.entries) {
      final value = _bounded(entry.value);
      if (value.abs() > .0001) affinities[entry.key] = value;
    }
    return (affinities: affinities, evidence: evidence);
  }

  static PreferenceLearningUpdate applyFeedback(
    Map<String, dynamic>? current, {
    required String userId,
    required String destinationId,
    required String feedbackType,
    required dynamic destinationConcepts,
    required String recommendationGenerationId,
    required String sourceContext,
    required String now,
    required String eventId,
  }) {
    if (!validFeedbackTypes.contains(feedbackType)) {
      throw ArgumentError('Unsupported recommendation feedback type');
    }
    if (destinationId.trim().isEmpty) {
      throw ArgumentError('destinationId is required');
    }
    final concepts = canonicalConcepts(destinationConcepts);
    if (concepts.isEmpty && feedbackType!='not_for_me') {
      throw ArgumentError(
          'Reliable interest information is unavailable for this place. Try another place or adjust your preferences.');
    }
    final profile = Map<String, dynamic>.from(
      current ?? emptyProfile(userId, now: now),
    );
    final states = Map<String, dynamic>.from(
      profile['feedbackByDestination'] as Map? ?? const {},
    );
    final previous = Map<String, dynamic>.from(
      states[destinationId] as Map? ?? const {},
    );
    final previousType = (previous['feedbackType'] ?? '').toString();
    final previousConcepts = canonicalConcepts(previous['destinationConcepts']);
    if (previousType == feedbackType &&
        _sameValues(previousConcepts, concepts)) {
      return PreferenceLearningUpdate(
        profile: profile,
        event: null,
        changed: false,
      );
    }
    states[destinationId] = {
      'destinationId': destinationId,
      'feedbackType': feedbackType,
      'destinationConcepts': concepts,
      'recommendationGenerationId': recommendationGenerationId,
      'sourceContext': sourceContext,
      'eventId': eventId,
      'updatedAt': now,
    };
    final rebuilt = _rebuild(states);
    profile.addAll({
      'userId': userId,
      'travellerId': userId,
      'affinities': rebuilt.affinities,
      'evidence': rebuilt.evidence,
      'feedbackByDestination': states,
      'learnedPreferenceVersion': 'learned_$eventId',
      'createdAt': profile['createdAt'] ?? now,
      'updatedAt': now,
    });
    return PreferenceLearningUpdate(
      profile: profile,
      changed: true,
      event: {
        'feedbackEventId': eventId,
        'userId': userId,
        'travellerId': userId,
        'destinationId': destinationId,
        'recommendationGenerationId': recommendationGenerationId,
        'feedbackType': feedbackType,
        'previousFeedbackType': previousType,
        'destinationConcepts': concepts,
        'sourceContext': sourceContext,
        'supersedesEventId': (previous['eventId'] ?? '').toString(),
        'timestamp': now,
      },
    );
  }

  static PreferenceLearningUpdate reset(
    Map<String, dynamic>? current, {
    required String userId,
    required String now,
    required String eventId,
  }) {
    final currentProfile = current ?? emptyProfile(userId, now: now);
    final currentStates = Map<String, dynamic>.from(
      currentProfile['feedbackByDestination'] as Map? ?? const {},
    );
    final profile = {
      ...emptyProfile(userId, now: now),
      'createdAt': currentProfile['createdAt'] ?? now,
      'learnedPreferenceVersion': 'learned_reset_$eventId',
      'resetAt': now,
      'updatedAt': now,
    };
    return PreferenceLearningUpdate(
      profile: profile,
      changed: currentStates.isNotEmpty ||
          (currentProfile['affinities'] as Map? ?? const {}).isNotEmpty,
      event: {
        'feedbackEventId': eventId,
        'userId': userId,
        'travellerId': userId,
        'feedbackType': 'reset',
        'previousFeedbackCount': currentStates.length,
        'timestamp': now,
        'sourceContext': 'profile_reset',
      },
    );
  }

  static Map<String, dynamic> effectiveProfile(
    Map<String, dynamic> base,
    Map<String, dynamic>? learned,
  ) =>
      {
        ...base,
        'learnedAffinities': Map<String, dynamic>.from(
          learned?['affinities'] as Map? ?? const {},
        ),
        'learnedEvidence': Map<String, dynamic>.from(
          learned?['evidence'] as Map? ?? const {},
        ),
        'destinationFeedback': {for(final entry in (learned?['feedbackByDestination'] as Map? ?? {}).entries)
          entry.key: (entry.value as Map)['feedbackType']},
      };

  static String effectiveVersion(
    String baseVersion,
    Map<String, dynamic>? learned,
  ) {
    final learnedVersion =
        (learned?['learnedPreferenceVersion'] ?? '').toString();
    if (learnedVersion.isEmpty) return baseVersion;
    var hash = 0x811c9dc5;
    for (final unit in '$baseVersion|$learnedVersion'.codeUnits) {
      hash ^= unit;
      hash = (hash * 0x01000193) & 0xffffffff;
    }
    return 'effective_${hash.toRadixString(16).padLeft(8, '0')}';
  }

  static Map<String, dynamic> publicState(Map<String, dynamic>? profile) {
    final safe = profile ?? const <String, dynamic>{};
    final affinities = Map<String, dynamic>.from(
      safe['affinities'] as Map? ?? const {},
    );
    final states = Map<String, dynamic>.from(
      safe['feedbackByDestination'] as Map? ?? const {},
    );
    final currentFeedback = <String, dynamic>{};
    for (final entry in states.entries) {
      if (entry.value is! Map) continue;
      final type = (entry.value['feedbackType'] ?? '').toString();
      if (validFeedbackTypes.contains(type)) {
        currentFeedback[entry.key] = type;
      }
    }
    final tendencies = <Map<String, dynamic>>[];
    final keys = affinities.keys.toList()..sort();
    for (final concept in keys) {
      final value = double.tryParse('${affinities[concept]}') ?? 0;
      if (value.abs() < .10) continue;
      tendencies.add({
        'concept': concept,
        'label': RecommendationTaxonomy.displayNames[concept] ?? concept,
        'direction': value > 0 ? 'up' : 'down',
      });
    }
    return {
      'learnedPreferenceVersion': safe['learnedPreferenceVersion'] ?? '',
      'currentFeedback': currentFeedback,
      'tendencies': tendencies,
      'hasLearnedPreferences': currentFeedback.isNotEmpty,
      'updatedAt': safe['updatedAt'] ?? '',
    };
  }

  static bool _sameValues(List<String> left, List<String> right) {
    if (left.length != right.length) return false;
    for (var index = 0; index < left.length; index += 1) {
      if (left[index] != right[index]) return false;
    }
    return true;
  }
}
