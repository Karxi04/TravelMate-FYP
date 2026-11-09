import 'recommendation_taxonomy.dart';

bool recommendationQualifies(Map item, num minimum, [String scoreBasis = 'hybrid_v1']) {
  final score = double.tryParse('${scoreBasis == 'personal_v2' ? item['personalSuitabilityScore'] : item['finalScore'] ?? item['score'] ?? 0}');
  return score != null &&
      score.isFinite &&
      score >= 0 &&
      score <= 100 &&
      score >= minimum;
}

/// Filter the real score before slicing one immutable ranked generation.
Map<String, dynamic> recommendationPage(
    Map<String, dynamic> snapshot, Map options) {
  final minimum = double.tryParse('${options['minimumMatchScore'] ?? 0}');
  final basis = options['scoreBasis'] ?? 'hybrid_v1';
  final discovery = options['discoveryMode'];
  final offset = int.tryParse('${options['offset'] ?? 0}');
  final limit = int.tryParse('${options['limit'] ?? 12}');
  if (![null,'',recommendationDiscoveryMode].contains(discovery) || !['hybrid_v1','personal_v2'].contains(basis) || minimum == null ||
      !minimum.isFinite ||
      minimum < 0 ||
      minimum > 100 ||
      offset == null ||
      offset < 0 ||
      offset > 200 ||
      limit == null ||
      limit < 1 ||
      limit > 50) {
    throw ArgumentError('Invalid recommendation threshold or page.');
  }
  final all = (snapshot['recommendationResults'] as List? ?? [])
      .whereType<Map>()
      .toList();
  final qualified =
      all.where((item) => discovery == recommendationDiscoveryMode ? item['discoveryEligible'] == true : recommendationQualifies(item, minimum, basis)).toList();
  final end = offset + limit;
  return {
    ...snapshot,
    'recommendationResults': qualified.skip(offset).take(limit).toList(),
    'pagination': {
      'minimumMatchScore': minimum,
      'scoreBasis': basis,
      'discoveryMode': discovery, 'thresholdApplied': discovery != recommendationDiscoveryMode,
      'offset': offset,
      'limit': limit,
      'candidateCount': all.length,
      'qualifiedCount': qualified.length,
      'personalEvidenceCount': all.where((item)=>item['personalSuitabilityScore'] is num).length,
      'nextOffset': end < qualified.length ? end : null,
      'hasMore': end < qualified.length,
      'providerHasMore': snapshot['providerHasMore'] == true
    }
  };
}

/// An older server must not masquerade as a valid zero personal-match result.
void validateRecommendationResponse(Map data, String basis) {
  if (basis != 'personal_v2' || data['stale'] == true) return;
  final rows = (data['recommendations'] as List? ?? []).whereType<Map>();
  final page = data['pagination'];
  if (page is! Map || page['scoreBasis'] != basis || page['personalEvidenceCount'] is! num ||
      rows.any((row) => !row.containsKey('personalSuitabilityScore'))) {
    throw StateError('Personal match is unavailable from this backend version. Update/restart the backend and refresh recommendations.');
  }
}

const recommendationDiscoveryMode = 'relevant_v1';

Map<String,dynamic> discoveryAnnotations(Map item, Map preference) {
  final concepts = (item['destinationConcepts'] as List? ?? []).map((value)=>value.toString()).toSet();
  var requested = RecommendationTaxonomy.conceptsFor(preference['interests'] ?? []);
  final hasInterests = (preference['interests'] as List? ?? []).isNotEmpty;
  if (requested.isEmpty && !hasInterests) requested = RecommendationTaxonomy.conceptsFor(preference['travelType']);
  var matched = concepts.intersection(requested);
  if (requested.isEmpty && !hasInterests) {
    final affinities = preference['learnedAffinities'] as Map? ?? {};
    matched = concepts.where((key)=>affinities[key] is num && affinities[key] >= .1).toSet();
  }
  final excluded = concepts.intersection(RecommendationTaxonomy.conceptsFor(preference['excludedInterests'] ?? []));
  final did = '${item['destinationId'] ?? item['id'] ?? ''}';
  final rejected = (preference['destinationFeedback'] as Map? ?? {})[did] == 'not_for_me';
  final eligible = matched.isNotEmpty && excluded.isEmpty && !rejected;
  String? foodType;
  if (matched.contains('food')) {
    final text = RecommendationTaxonomy.normalizePhrase(['title','name','category','type','interests'].map((key)=>item[key] ?? '').join(' '));
    foodType = RegExp(r'\bmuseum\b').hasMatch(text) ? 'food_museum'
        : RegExp(r'\bcooking (class|school|workshop|experience)\b').hasMatch(text) ? 'cooking'
        : RegExp(r'\b(hawker|restaurant|cafe|kopitiam|food (court|street|market))\b').hasMatch(text) ? 'dining'
        : RegExp(r'\b(spice|spices|garden)\b').hasMatch(text) ? 'culinary_culture' : 'food_related';
  }
  return {'discoveryEligible':eligible,'discoveryMatchedConcepts':eligible ? (matched.toList()..sort()) : <String>[],'foodExperienceType':foodType};
}

void validateDiscoveryResponse(Map data) {
  if (data['stale'] == true) return;
  if (data['ok'] == false || data['pagination'] is! Map ||
      data['pagination']['discoveryMode'] != recommendationDiscoveryMode) {
    throw StateError('Recommendation discovery is unavailable.');
  }
}
