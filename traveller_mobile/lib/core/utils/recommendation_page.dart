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
  final offset = int.tryParse('${options['offset'] ?? 0}');
  final limit = int.tryParse('${options['limit'] ?? 12}');
  if (!['hybrid_v1','personal_v2'].contains(basis) || minimum == null ||
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
      all.where((item) => recommendationQualifies(item, minimum, basis)).toList();
  final end = offset + limit;
  return {
    ...snapshot,
    'recommendationResults': qualified.skip(offset).take(limit).toList(),
    'pagination': {
      'minimumMatchScore': minimum,
      'scoreBasis': basis,
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
