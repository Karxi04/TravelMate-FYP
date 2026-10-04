import 'dart:math';

/// Small, explainable taxonomy shared by standalone recommendation scoring.
/// It intentionally mirrors the Flask engine rather than using an opaque model.
class RecommendationTaxonomy {
  static const Map<String, Set<String>> conceptTerms = {
    'food': {
      'food',
      'local food',
      'local cuisine',
      'cuisine',
      'restaurant',
      'hawker',
      'street food',
      'cafe',
      'coffee shop',
      'food market',
      'food court',
      'culinary',
    },
    'culture': {
      'culture',
      'local culture',
      'heritage',
      'history',
      'historical',
      'museum',
      'temple',
      'mosque',
      'church',
      'architecture',
      'historic site',
      'religion',
      'religious',
      'art',
      'gallery',
    },
    'nature': {
      'nature',
      'park',
      'beach',
      'garden',
      'botanic',
      'botanical',
      'forest',
      'hiking',
      'outdoor',
      'scenery',
      'scenic',
      'wildlife',
      'hill',
      'waterfall',
    },
    'shopping': {
      'shopping',
      'mall',
      'market',
      'retail',
      'bazaar',
      'night market',
      'shopping centre',
      'shopping center',
    },
    'adventure': {
      'adventure',
      'hiking',
      'watersport',
      'water sport',
      'outdoor activity',
      'cycling',
      'theme park',
      'climbing',
      'kayak',
    },
    'leisure': {
      'leisure',
      'entertainment',
      'nightlife',
      'spa',
      'relaxation',
      'relaxed',
      'beach',
      'theme park',
    },
    'photography': {
      'photography',
      'photo',
      'scenic',
      'scenery',
      'viewpoint',
      'architecture',
      'street art',
    },
    'family': {
      'family',
      'children',
      'kids',
      'wildlife',
      'education',
      'educational',
      'theme park',
      'aquarium',
      'zoo',
    },
    'social': {
      'social',
      'nightlife',
      'event',
      'festival',
      'night market',
      'food market',
    },
  };

  static const Map<String, String> displayNames = {
    'food': 'Food and local cuisine',
    'culture': 'Culture and heritage',
    'nature': 'Nature and outdoors',
    'shopping': 'Shopping',
    'adventure': 'Adventure',
    'leisure': 'Leisure and entertainment',
    'photography': 'Photography',
    'family': 'Family-friendly experiences',
    'social': 'Social experiences',
  };

  static String normalizePhrase(dynamic value) => (value ?? '')
      .toString()
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .trim();

  static Iterable<dynamic> _values(dynamic value) {
    if (value is Iterable && value is! String) return value;
    return normalizePhrase(value).isEmpty ? const [] : [value];
  }

  static Set<String> conceptsFor(dynamic value) {
    final concepts = <String>{};
    for (final entry in _values(value)) {
      final phrase = normalizePhrase(entry);
      final padded = ' $phrase ';
      for (final group in conceptTerms.entries) {
        if (group.value
            .any((term) => padded.contains(' ${normalizePhrase(term)} '))) {
          concepts.add(group.key);
        }
      }
    }
    return concepts;
  }

  static Set<String> candidateConcepts(Map<String, dynamic> item) {
    final values = <dynamic>[];
    for (final field in const [
      'interests',
      'tags',
      'categories',
      'category',
      'type',
      'subtype',
      'title',
      'name',
      'description',
    ]) {
      values.addAll(_values(item[field]));
    }
    return conceptsFor(values);
  }

  static List<String> displayConcepts(Iterable<String> concepts) {
    final values = concepts.toSet().toList()..sort();
    return values.map((value) => displayNames[value] ?? value).toList();
  }

  static String normalizeBudget(dynamic value) {
    final phrase = normalizePhrase(value);
    if (['budget', 'free', 'cheap', 'low cost'].any(phrase.contains)) {
      return 'budget';
    }
    if (['premium', 'luxury', 'expensive'].any(phrase.contains)) {
      return 'premium';
    }
    if (['moderate', 'mid range', 'standard'].any(phrase.contains)) {
      return 'moderate';
    }
    return '';
  }

  static String normalizePace(dynamic value) {
    final phrase = normalizePhrase(value);
    if (['packed', 'active', 'fast'].any(phrase.contains)) return 'active';
    if (['relaxed', 'slow', 'easy'].any(phrase.contains)) return 'relaxed';
    if (phrase.contains('moderate') || phrase.contains('balanced')) {
      return 'moderate';
    }
    return '';
  }

  static String normalizePurpose(dynamic value) {
    final phrase = normalizePhrase(value);
    if (phrase.contains('family')) return 'family';
    if (phrase.contains('solo')) return 'solo';
    if (phrase.contains('business') || phrase.contains('work')) {
      return 'business';
    }
    if (phrase.contains('education') || phrase.contains('study')) {
      return 'educational';
    }
    if (phrase.contains('holiday') ||
        phrase.contains('vacation') ||
        phrase.contains('leisure')) {
      return 'holiday';
    }
    return '';
  }

  static String normalizePersonality(dynamic value) {
    final phrase = normalizePhrase(value);
    for (final value in const [
      'explorer',
      'planner',
      'social',
      'relaxed',
      'balanced'
    ]) {
      if (phrase.contains(value)) return value;
    }
    return '';
  }
}

class RecommendationScoring {
  static double _number(dynamic value, [double fallback = 0]) =>
      double.tryParse((value ?? '').toString()) ?? fallback;

  static double _round2(double value) => (value * 100).roundToDouble() / 100;

  static String _destinationId(Map<String, dynamic> item) =>
      (item['destinationId'] ??
              item['place_id'] ??
              item['data_id'] ??
              item['id'] ??
              item['title'] ??
              item['name'] ??
              '')
          .toString();

  static double weightedScore(
    double content,
    double collaborative,
    double popularity,
  ) =>
      content * .60 + collaborative * .30 + popularity * .10;

  static double _conceptCompatibility(
    Set<String> preferred,
    Set<String> supported, {
    double neutral = .55,
  }) {
    if (preferred.isEmpty) return neutral;
    if (supported.isEmpty) return .45;
    return preferred.intersection(supported).length / max(1, preferred.length);
  }

  static Set<String> _normalizedValues(
      dynamic value, String Function(dynamic) normalizer) {
    final values = value is Iterable && value is! String ? value : [value];
    return values.map(normalizer).where((value) => value.isNotEmpty).toSet();
  }

  static ({double score, bool applied}) _matrixSuitability(
    String requested,
    Set<String> supported,
    Map<String, double> matrix,
  ) {
    if (requested.isEmpty || supported.isEmpty) {
      return (score: .55, applied: false);
    }
    return (
      score: supported
          .map((value) => matrix['$requested:$value'] ?? .35)
          .reduce(max),
      applied: true,
    );
  }

  static ({double score, bool applied}) _budgetSuitability(
      String requested, Map<String, dynamic> item) {
    final supported = _normalizedValues(
      item['budgetLevel'] ?? item['budgetRange'],
      RecommendationTaxonomy.normalizeBudget,
    );
    return _matrixSuitability(requested, supported, const {
      'budget:budget': 1,
      'budget:moderate': .60,
      'budget:premium': .20,
      'moderate:budget': .90,
      'moderate:moderate': 1,
      'moderate:premium': .65,
      'premium:budget': .85,
      'premium:moderate': .95,
      'premium:premium': 1,
    });
  }

  static ({double score, bool applied}) _paceSuitability(
      String requested, Map<String, dynamic> item) {
    final supported =
        _normalizedValues(item['pace'], RecommendationTaxonomy.normalizePace);
    return _matrixSuitability(requested, supported, const {
      'relaxed:relaxed': 1,
      'relaxed:moderate': .72,
      'relaxed:active': .35,
      'moderate:relaxed': .82,
      'moderate:moderate': 1,
      'moderate:active': .75,
      'active:relaxed': .45,
      'active:moderate': .82,
      'active:active': 1,
    });
  }

  static ({double score, bool applied}) _exactSuitability(
    String requested,
    dynamic rawSupported,
    String Function(dynamic) normalizer, {
    bool broadHoliday = false,
    bool broadBalanced = false,
  }) {
    final supported = _normalizedValues(rawSupported, normalizer);
    if (requested.isEmpty || supported.isEmpty) {
      return (score: .55, applied: false);
    }
    if (broadHoliday && requested == 'holiday') {
      return (score: supported.contains('holiday') ? 1 : .78, applied: true);
    }
    if (broadBalanced && requested == 'balanced') {
      return (score: .85, applied: true);
    }
    return (
      score: supported.contains(requested) ? 1 : .35,
      applied: true,
    );
  }

  static Map<String, dynamic> _signal(
          double score, bool applied, String requested) =>
      {
        'score': _round2(score * 100),
        'applied': applied,
        'requested': requested,
      };

  static double _setSimilarity(Set<String> left, Set<String> right) {
    final union = left.union(right);
    return union.isEmpty ? 0 : left.intersection(right).length / union.length;
  }

  static double _profileMatch(
      Map<String, dynamic> peer,
      Map<String, dynamic> current,
      String field,
      String Function(dynamic) normalizer) {
    final left = normalizer(peer[field]);
    final right = normalizer(current[field]);
    return left.isNotEmpty && left == right ? 1 : 0;
  }

  static ({
    double score,
    double raw,
    double confidence,
    int count,
    String source
  }) _collaborativeScore(
    Map<String, dynamic> item,
    List<Map<String, dynamic>> feedback,
    Map<String, Map<String, dynamic>> peerPreferences,
    Map<String, dynamic> currentPreference,
    String currentUserId,
  ) {
    final destinationId = _destinationId(item);
    final currentInterests =
        RecommendationTaxonomy.conceptsFor(currentPreference['interests']);
    final values = <({double rating, double similarity})>[];
    for (final row in feedback) {
      if ((row['destinationId'] ?? '').toString() != destinationId) continue;
      final uid = (row['travellerId'] ?? '').toString();
      if (uid.isEmpty || uid == currentUserId) continue;
      final peer = peerPreferences[uid];
      if (peer == null) continue;
      final peerInterests =
          RecommendationTaxonomy.conceptsFor(peer['interests']);
      final similarity = .60 * _setSimilarity(currentInterests, peerInterests) +
          .15 *
              _setSimilarity(
                  RecommendationTaxonomy.conceptsFor(peer['travelType']),
                  RecommendationTaxonomy.conceptsFor(
                      currentPreference['travelType'])) +
          .10 *
              _profileMatch(peer, currentPreference, 'travelPace',
                  RecommendationTaxonomy.normalizePace) +
          .10 *
              _profileMatch(peer, currentPreference, 'travelPurpose',
                  RecommendationTaxonomy.normalizePurpose) +
          .05 *
              _profileMatch(peer, currentPreference, 'travelPersonality',
                  RecommendationTaxonomy.normalizePersonality);
      if (similarity < .25) continue;
      values.add((
        rating: _number(row['rating']).clamp(0, 5).toDouble(),
        similarity: similarity,
      ));
    }
    if (values.isEmpty) {
      return (
        score: 50,
        raw: 50,
        confidence: 0,
        count: 0,
        source: 'neutral cold-start baseline (no similar traveller evidence)',
      );
    }
    final totalWeight =
        values.fold<double>(0, (sum, value) => sum + value.similarity);
    final average = values.fold<double>(
            0, (sum, value) => sum + value.rating * value.similarity) /
        max(.0001, totalWeight);
    final raw = average / 5 * 100;
    final confidence = min(1.0, totalWeight / 3);
    return (
      score: 50 + (raw - 50) * confidence,
      raw: raw,
      confidence: confidence,
      count: values.length,
      source: '${values.length} similar traveller rating(s)',
    );
  }

  static List<String> _reasons(Map<String, dynamic> item, double popularity) {
    final reasons = <String>[];
    final matches = (item['matchedInterests'] as List? ?? [])
        .map((value) => value.toString())
        .toList();
    if (matches.isNotEmpty) {
      reasons.add('Matches your ${matches.take(2).join(', ')} interests');
    }
    final signals =
        Map<String, dynamic>.from(item['contentSignals'] as Map? ?? const {});
    const primaryLabels = {
      'travelType': 'travel style',
      'pace': 'travel pace',
      'budget': 'budget preference',
    };
    for (final entry in primaryLabels.entries) {
      final signal =
          Map<String, dynamic>.from(signals[entry.key] as Map? ?? const {});
      if (signal['applied'] == true && _number(signal['score']) >= 80) {
        reasons.add('Fits your ${entry.value}');
      }
    }
    if (_number(item['collaborativeConfidence']) >= .25 &&
        _number(item['rawCollaborativeScore']) >= 70) {
      reasons.add('Highly rated by similar travellers');
    }
    const secondaryLabels = {
      'travelPurpose': 'travel purpose',
      'travelPersonality': 'traveller personality',
    };
    for (final entry in secondaryLabels.entries) {
      final signal =
          Map<String, dynamic>.from(signals[entry.key] as Map? ?? const {});
      if (signal['applied'] == true && _number(signal['score']) >= 80) {
        reasons.add('Fits your ${entry.value}');
      }
    }
    if (popularity >= 85) reasons.add('Popular and well reviewed');
    return reasons.take(5).toList();
  }

  static Map<String, dynamic> scoreCandidate({
    required Map<String, dynamic> candidate,
    required Map<String, dynamic> preferences,
    List<Map<String, dynamic>> feedback = const [],
    Map<String, Map<String, dynamic>> peerPreferences = const {},
    String currentUserId = '',
  }) {
    final item = Map<String, dynamic>.from(candidate);
    final destinationConcepts = RecommendationTaxonomy.candidateConcepts(item);
    final rawInterests = preferences['interests'] as List? ?? const [];
    final interestGroups = rawInterests
        .map(RecommendationTaxonomy.conceptsFor)
        .where((group) => group.isNotEmpty)
        .toList();
    final interestConcepts = interestGroups
        .fold<Set<String>>(<String>{}, (all, group) => all..addAll(group));
    final typeConcepts =
        RecommendationTaxonomy.conceptsFor(preferences['travelType']);
    final matchedConcepts = interestConcepts.intersection(destinationConcepts);
    final primaryConcepts = RecommendationTaxonomy.conceptsFor([
      item['title'],
      item['name'],
      item['type'],
    ]);
    final primaryMatch =
        primaryConcepts.intersection(interestConcepts).isNotEmpty;
    final matchedGroupCount = interestGroups
        .where((group) => group.intersection(destinationConcepts).isNotEmpty)
        .length;
    final interestScore = interestGroups.isEmpty
        ? .55
        : (matchedGroupCount / interestGroups.length) *
            (primaryMatch ? 1.0 : .80);
    final typeScore =
        _conceptCompatibility(typeConcepts, destinationConcepts, neutral: .60);
    final requestedPace =
        RecommendationTaxonomy.normalizePace(preferences['travelPace']);
    final requestedBudget =
        RecommendationTaxonomy.normalizeBudget(preferences['budgetRange']);
    final requestedPurpose =
        RecommendationTaxonomy.normalizePurpose(preferences['travelPurpose']);
    final requestedPersonality = RecommendationTaxonomy.normalizePersonality(
        preferences['travelPersonality']);
    final pace = _paceSuitability(requestedPace, item);
    final budget = _budgetSuitability(requestedBudget, item);
    final purpose = _exactSuitability(requestedPurpose, item['purpose'],
        RecommendationTaxonomy.normalizePurpose,
        broadHoliday: true);
    final personality = _exactSuitability(requestedPersonality,
        item['personality'], RecommendationTaxonomy.normalizePersonality,
        broadBalanced: true);
    final content = 100 *
        (interestScore * .55 +
            typeScore * .15 +
            pace.score * .10 +
            budget.score * .10 +
            purpose.score * .06 +
            personality.score * .04);
    final matched = RecommendationTaxonomy.displayConcepts(matchedConcepts);
    final signals = <String, dynamic>{
      'interests': {
        'score': _round2(interestScore * 100),
        'applied': interestConcepts.isNotEmpty,
        'matched': matched,
        'requestedConcepts': interestConcepts.toList()..sort(),
        'primaryCategoryMatch': primaryMatch,
      },
      'travelType': {
        'score': _round2(typeScore * 100),
        'applied': typeConcepts.isNotEmpty,
        'matched': RecommendationTaxonomy.displayConcepts(
            typeConcepts.intersection(destinationConcepts)),
      },
      'pace': _signal(pace.score, pace.applied, requestedPace),
      'budget': _signal(budget.score, budget.applied, requestedBudget),
      'travelPurpose':
          _signal(purpose.score, purpose.applied, requestedPurpose),
      'travelPersonality':
          _signal(personality.score, personality.applied, requestedPersonality),
    };
    final collaborative = _collaborativeScore(
        item, feedback, peerPreferences, preferences, currentUserId);
    final explicitPopularity = _number(item['popularity'], -1);
    final rating = _number(item['rating']).clamp(0, 5).toDouble();
    final reviews = max(0, _number(item['reviews']));
    final popularity = explicitPopularity >= 0
        ? explicitPopularity.clamp(0, 100).toDouble()
        : min(100.0, rating / 5 * 80 + min(20.0, reviews / 500));
    final finalScore = weightedScore(content, collaborative.score, popularity)
        .clamp(0, 100)
        .toDouble();
    item.addAll({
      'destinationId': _destinationId(item),
      'destinationConcepts': destinationConcepts.toList()..sort(),
      'matchedInterests': matched,
      'contentSignals': signals,
      'contentScore': _round2(content),
      'collaborativeScore': _round2(collaborative.score),
      'rawCollaborativeScore': _round2(collaborative.raw),
      'collaborativeConfidence': _round2(collaborative.confidence),
      'collaborativeRatingCount': collaborative.count,
      'collaborativeSource': collaborative.source,
      'popularityScore': _round2(popularity),
      'score': _round2(finalScore),
      'finalScore': _round2(finalScore),
      'scoreBreakdown': {
        'contentWeight': .60,
        'collaborativeWeight': .30,
        'popularityWeight': .10,
        'content': _round2(content),
        'collaborative': _round2(collaborative.score),
        'popularity': _round2(popularity),
      },
    });
    final reasons = _reasons(item, popularity);
    final reason =
        '${finalScore.round()}% match • ${reasons.isEmpty ? 'Limited profile evidence; neutral fallback applied' : reasons.join(' • ')}';
    item['matchReasons'] = reasons;
    item['reason'] = reason;
    item['recommendationReason'] = reason;
    return item;
  }

  static List<Map<String, dynamic>> rankCandidates({
    required List<Map<String, dynamic>> candidates,
    required Map<String, dynamic> preferences,
    List<Map<String, dynamic>> feedback = const [],
    Map<String, Map<String, dynamic>> peerPreferences = const {},
    String currentUserId = '',
    int limit = 12,
  }) {
    final scored = candidates
        .map((candidate) => scoreCandidate(
              candidate: candidate,
              preferences: preferences,
              feedback: feedback,
              peerPreferences: peerPreferences,
              currentUserId: currentUserId,
            ))
        .toList()
      ..sort((a, b) => _number(b['score']).compareTo(_number(a['score'])));

    final unique = <Map<String, dynamic>>[];
    final seenIds = <String>{};
    final seenNames = <String>{};
    for (final item in scored) {
      final id = RecommendationTaxonomy.normalizePhrase(_destinationId(item));
      final name =
          RecommendationTaxonomy.normalizePhrase(item['title'] ?? item['name']);
      if ((id.isNotEmpty && seenIds.contains(id)) ||
          (name.isNotEmpty && seenNames.contains(name))) {
        continue;
      }
      if (id.isNotEmpty) seenIds.add(id);
      if (name.isNotEmpty) seenNames.add(name);
      unique.add(item);
    }

    final preferred =
        RecommendationTaxonomy.conceptsFor(preferences['interests']);
    final remaining = unique.map(Map<String, dynamic>.from).toList();
    final selected = <Map<String, dynamic>>[];
    final counts = <String, int>{};
    while (remaining.isNotEmpty && selected.length < limit) {
      var bestIndex = 0;
      var bestAdjusted = double.negativeInfinity;
      var bestCategory = 'general';
      var bestPenalty = 0.0;
      for (var index = 0; index < remaining.length; index++) {
        final item = remaining[index];
        final concepts = (item['destinationConcepts'] as List? ?? [])
            .map((value) => value.toString())
            .toSet();
        final preferredMatches = concepts.intersection(preferred).toList()
          ..sort();
        final allConcepts = concepts.toList()..sort();
        final category = preferredMatches.isNotEmpty
            ? preferredMatches.first
            : (allConcepts.isNotEmpty ? allConcepts.first : 'general');
        final penalty = (counts[category] ?? 0) *
            (preferred.contains(category) ? 2.0 : 7.0);
        final adjusted = _number(item['score']) - penalty;
        if (adjusted > bestAdjusted) {
          bestIndex = index;
          bestAdjusted = adjusted;
          bestCategory = category;
          bestPenalty = penalty;
        }
      }
      final chosen = remaining.removeAt(bestIndex);
      chosen['diversityCategory'] = bestCategory;
      chosen['diversityAdjustedScore'] = _round2(bestAdjusted);
      if (bestPenalty > 0) {
        chosen['diversityReason'] = 'Light category repetition penalty applied';
      }
      selected.add(chosen);
      counts[bestCategory] = (counts[bestCategory] ?? 0) + 1;
    }
    for (var index = 0; index < selected.length; index++) {
      selected[index]['rankNo'] = index + 1;
    }
    return selected;
  }
}
