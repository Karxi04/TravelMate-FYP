import 'dart:math';

import 'preference_learning.dart';

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
      'restaurants',
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
      'cultural', 'museums',
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
      'parks', 'gardens',
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
      'outdoor activities', 'watersports', 'theme parks',
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

  static String normalizePhrase(dynamic value) {
    var phrase = (value ?? '').toString().toLowerCase();
    const accents = {'[àáâãäå]':'a','[èéêë]':'e','[ìíîï]':'i','[òóôõö]':'o','[ùúûü]':'u','[çč]':'c','ñ':'n','[ýÿ]':'y','š':'s','ž':'z'};
    for (final entry in accents.entries) { phrase = phrase.replaceAll(RegExp(entry.key), entry.value); }
    return phrase.replaceAll(RegExp(r'[\u0300-\u036f]'), '').replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim();
  }

  static Iterable<dynamic> _values(dynamic value) {
    if (value is Map) return ['name','title','value'].where((key)=>value[key]!=null).map((key)=>value[key]);
    if (value is Iterable && value is! String) return value;
    return normalizePhrase(value).isEmpty ? const [] : [value];
  }

  static Set<String> conceptsFor(dynamic value) {
    final concepts = <String>{};
    for (final entry in _values(value)) {
      if (entry is Map) { concepts.addAll(conceptsFor(_values(entry).toList())); continue; }
      final phrase = normalizePhrase(entry);
      final padded = ' $phrase ';
      for (final group in conceptTerms.entries) {
        final searchable = group.key == 'nature' ? padded.replaceAll(RegExp(r'\b(theme parks?|car parks?)\b'), '') : padded;
        if (group.value
            .any((term) => searchable.contains(' ${normalizePhrase(term)} '))) {
          concepts.add(group.key);
        }
      }
    }
    return concepts;
  }

  static Set<String> primaryConcepts(Map<String, dynamic> item) {
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
      'destinationType', 'types',
    ]) {
      values.addAll(_values(item[field]));
    }
    return conceptsFor(values);
  }

  static Set<String> candidateConcepts(Map<String, dynamic> item) {
    final concepts = primaryConcepts(item);
    const generic = {'food','culture','history','nature','outdoor','leisure','relaxed','social','family',
      'children','kids','shopping','photo','art','education','educational','scenic','scenery','park','market'};
    for (final clause in (item['description'] ?? '').toString().split(RegExp(r'[.;!?]'))) {
      if (RegExp(r'\b(near|nearby|close to|walking distance)\b', caseSensitive:false).hasMatch(clause)) continue;
      final phrase = ' ${normalizePhrase(clause)} ';
      for (final group in conceptTerms.entries) {
        final searchable = group.key == 'nature' ? phrase.replaceAll(RegExp(r'\b(theme parks?|car parks?)\b'), '') : phrase;
        if (group.value.difference(generic).any((term) => RegExp(r'\b'+RegExp.escape(normalizePhrase(term))+r'\b').allMatches(searchable).any((match)=>!RegExp(r'\b(no|not|without)(?: an?| any| actual| real)?\s*$').hasMatch(searchable.substring(0,match.start))))) concepts.add(group.key);
      }
    }
    return concepts;
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
  static double _number(dynamic value, [double fallback = 0]) {
    final number = double.tryParse((value ?? '').toString());
    return number != null && number.isFinite ? number : fallback;
  }

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
    final seenRatings = <String>{};
    final ordered = List<Map<String,dynamic>>.from(feedback)..sort((a,b) {
      final time = '${b['updatedAt'] ?? b['createdAt'] ?? ''}'.compareTo('${a['updatedAt'] ?? a['createdAt'] ?? ''}');
      return time != 0 ? time : '${b['id'] ?? ''}'.compareTo('${a['id'] ?? ''}');
    });
    for (final row in ordered) {
      if ((row['destinationId'] ?? '').toString() != destinationId) continue;
      final uid = (row['travellerId'] ?? '').toString();
      if (uid.isEmpty || uid == currentUserId) continue;
      final rating = _number(row['rating']);
      if (rating < 1 || rating > 5 || !seenRatings.add(uid)) continue;
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
        rating: rating,
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
    final interestSignal = Map<String, dynamic>.from(
      signals['interests'] as Map? ?? const {},
    );
    final learnedPositive = (interestSignal['learnedPositive'] as List? ?? [])
        .map((value) => value.toString())
        .where((value) => value.isNotEmpty)
        .toList();
    if (learnedPositive.isNotEmpty) {
      reasons.add(
        'Based on your recent interest in ${learnedPositive.take(2).join(', ')}',
      );
    }
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
    final primaryMatch = RecommendationTaxonomy.primaryConcepts(item).intersection(interestConcepts).isNotEmpty;
    final baseInterestScore = interestConcepts.isEmpty ? .55 :
        (matchedConcepts.isEmpty ? 0.0 : .75 + .25 * matchedConcepts.length / max(1, destinationConcepts.length)) * (primaryMatch ? 1.0 : .80);
    final learnedAffinities = Map<String, dynamic>.from(
      preferences['learnedAffinities'] as Map? ?? const {},
    );
    final matchedLearnedAffinities = <String, double>{};
    for (final concept in destinationConcepts) {
      final affinity = _number(learnedAffinities[concept]);
      if (affinity.abs() > .0001) {
        matchedLearnedAffinities[concept] = affinity.clamp(-1, 1).toDouble();
      }
    }
    final learnedMean = matchedLearnedAffinities.isEmpty
        ? 0.0
        : matchedLearnedAffinities.values.fold<double>(
              0,
              (sum, value) => sum + value,
            ) /
            matchedLearnedAffinities.length;
    final learnedAdjustment =
        PreferenceLearning.learnedInterestStrength * learnedMean;
    final interestScore = (baseInterestScore + learnedAdjustment)
        .clamp(-PreferenceLearning.learnedInterestStrength, 1)
        .toDouble();
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
    final content = (100 *
            (interestScore * .55 +
                typeScore * .15 +
                pace.score * .10 +
                budget.score * .10 +
                purpose.score * .06 +
                personality.score * .04))
        .clamp(0, 100)
        .toDouble();
    final matched = RecommendationTaxonomy.displayConcepts(matchedConcepts);
    final signals = <String, dynamic>{
      'interests': {
        'score': _round2(interestScore * 100),
        'baseScore': _round2(baseInterestScore * 100),
        'learnedAdjustment': _round2((interestScore - baseInterestScore) * 100),
        'applied': interestConcepts.isNotEmpty && destinationConcepts.isNotEmpty,
        'matched': matched,
        'learnedPositive': RecommendationTaxonomy.displayConcepts(
          matchedLearnedAffinities.entries
              .where((entry) => entry.value >= .10 && interestScore > baseInterestScore)
              .map((entry) => entry.key)
              .toSet(),
        ),
        'learnedNegative': RecommendationTaxonomy.displayConcepts(
          matchedLearnedAffinities.entries
              .where((entry) => entry.value <= -.10 && interestScore < baseInterestScore)
              .map((entry) => entry.key)
              .toSet(),
        ),
        'requestedConcepts': interestConcepts.toList()..sort(),
        'primaryCategoryMatch': primaryMatch,
      },
      'travelType': {
        'score': _round2(typeScore * 100),
        'applied': typeConcepts.isNotEmpty && destinationConcepts.isNotEmpty,
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
    const weights = {'interests':.55,'travelType':.15,'pace':.10,'budget':.10,'travelPurpose':.06,'travelPersonality':.04};
    final requested = [interestConcepts.isNotEmpty,typeConcepts.isNotEmpty,requestedPace.isNotEmpty,requestedBudget.isNotEmpty,requestedPurpose.isNotEmpty,requestedPersonality.isNotEmpty];
    var knownWeight = 0.0; var requestedWeight = 0.0; var knownScore = 0.0; var wi = 0;
    for (final entry in weights.entries) {
      if (requested[wi++]) requestedWeight += entry.value;
      if (signals[entry.key]['applied'] == true) { knownWeight += entry.value; knownScore += entry.value * (signals[entry.key]['score'] as num); }
    }
    final collaborative = _collaborativeScore(
        item, feedback, peerPreferences, preferences, currentUserId);
    final unverifiedLocal = item['ratingSource']=='unverified_local_catalog';
    final rawRating = _number(item['rating']);
    final rating = unverifiedLocal || rawRating < 1 || rawRating > 5 ? 0.0 : rawRating;
    final reviews = max(0, _number(item['reviews']));
    final popularity = rating > 0
        ? min(100.0, rating / 5 * 80 + min(20.0, reviews / 500))
        : 50.0;
    final finalScore = weightedScore(_round2(content), _round2(collaborative.score), _round2(popularity))
        .clamp(0, 100)
        .toDouble();
    item.addAll({
      'destinationId': _destinationId(item),
      'destinationConcepts': destinationConcepts.toList()..sort(),
      'matchedInterests': matched,
      'contentSignals': signals,
      'contentScore': _round2(content),
      'personalSuitabilityScore': knownWeight > 0 && !(rawInterests.isNotEmpty && (interestConcepts.isEmpty || destinationConcepts.isEmpty)) ? _round2((knownScore / knownWeight).clamp(0,100).toDouble()) : null,
      'evidenceConfidence': requestedWeight > 0 ? (knownWeight/requestedWeight*1000).round()/1000 : 0.0,
      'interestEvidenceSource': primaryMatch ? 'primary_metadata' : matchedConcepts.isNotEmpty ? 'description' : 'none',
      'scoringVersion': 'relevance_v2',
      'collaborativeScore': _round2(collaborative.score),
      'rawCollaborativeScore': _round2(collaborative.raw),
      'collaborativeConfidence': _round2(collaborative.confidence),
      'collaborativeRatingCount': collaborative.count,
      'collaborativeSource': collaborative.source,
      'popularityScore': _round2(popularity),
      'popularitySource': unverifiedLocal ? 'neutral_unverified_local_catalog' : rating > 0 ? 'provider_rating_review_count' : 'neutral_missing_rating',
      'score': _round2(finalScore),
      'finalScore': _round2(finalScore),
      'hybridRankingScore': _round2(finalScore),
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
        '${finalScore.round()}/100 hybrid ranking • ${reasons.isEmpty ? 'Limited profile evidence; neutral fallback applied' : reasons.join(' • ')}';
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
        .where((item) => (preferences['destinationFeedback'] as Map?)?[_destinationId(item)] != 'not_for_me')
        .where((item) => RecommendationTaxonomy.candidateConcepts(item).intersection(
          RecommendationTaxonomy.conceptsFor(preferences['excludedInterests'])).isEmpty)
        .map((candidate) => scoreCandidate(
              candidate: candidate,
              preferences: preferences,
              feedback: feedback,
              peerPreferences: peerPreferences,
              currentUserId: currentUserId,
            ))
        .toList()
      ..sort((a, b) {
        for (final key in ['score','rating','reviews']) {
          final bv = key != 'score' && '${b['popularitySource'] ?? ''}'.startsWith('neutral') ? 0.0 : _number(b[key]);
          final av = key != 'score' && '${a['popularitySource'] ?? ''}'.startsWith('neutral') ? 0.0 : _number(a[key]);
          final difference = bv.compareTo(av);
          if (difference != 0) return difference;
        }
        return _destinationId(a).compareTo(_destinationId(b));
      });

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
        final penalty = min(4.0, (counts[category] ?? 0) *
            (preferred.contains(category) ? 2.0 : 7.0));
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
