List<String> _distinct(Iterable<String> sentences) {
  final seen = <String>{};
  return sentences
      .where((sentence) => seen.add(
          sentence.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim()))
      .toList();
}

List<String> _facts(dynamic value) {
  if (value is Map) {
    return _distinct(['overview', 'description', 'details', 'text', 'snippet']
        .map((key) => value[key])
        .whereType<String>()
        .expand(_facts));
  }
  if (value is! String) return [];
  final text = (value.length > 16000 ? value.substring(0, 16000) : value)
      .replaceAll('&amp;', '&')
      .replaceAll('&quot;', '"')
      .replaceAll('&#39;', "'")
      .replaceAll('&nbsp;', ' ')
      .replaceAll(RegExp(r'<[^>]*>'), ' ')
      .trim();
  final unsafe = RegExp(
      r'\b(ignore|instructions?|system prompt|reviews?|rated|rating|best time|crowd(?:ed|s)?|'
      r'accessible|accessibility|open daily|opens?|closes?|hours?|tickets?|admission|free entry|'
      r'RM\s*\d|MYR|\d{1,2}:\d{2})\b|'
      r'^(discover the magic|a must.visit|an unforgettable experience|book now)\b',
      caseSensitive: false);
  return _distinct(text
      .split(RegExp(r'(?<=[.!?])\s+|\n\s*\n'))
      .map((s) => s.replaceAll(RegExp(r'\s+'), ' ').trim())
      .where((s) => s.length >= 8 && !unsafe.hasMatch(s)));
}

Map<String, dynamic> destinationSummary(Map<String, dynamic> place) {
  final server = place['placeSummary'];
  if (server is Map &&
      server['source'] == 'recorded_public_facts' &&
      server['text'] is String) {
    return Map<String, dynamic>.from(server);
  }
  if (place['metadataConflict'] != true) {
    var facts = <String>[];
    for (final key in [
      'descriptionDetails',
      'description',
      'editorial_summary',
      'summary',
      'snippet',
      'about'
    ]) {
      final candidate = _facts(place[key]);
      if (candidate.length > facts.length ||
          (candidate.length == facts.length &&
              candidate.join(' ').length > facts.join(' ').length)) {
        facts = candidate;
      }
    }
    if (facts.isNotEmpty) {
      return {
        'text': facts.take(3).join(' '),
        'additionalText': facts.skip(3).join(' ')
      };
    }

    const categories = {
      'museum': 'a museum',
      'temple': 'a temple',
      'mosque': 'a mosque',
      'beach': 'a beach',
      'park': 'a park',
      'garden': 'a garden',
      'shopping mall': 'a shopping mall',
      'shopping': 'a shopping destination',
      'nature reserve': 'a nature reserve',
      'art gallery': 'an art gallery',
      'historical landmark': 'a historical landmark',
      'tourist attraction': 'a visitor attraction',
      'scenic attraction': 'a scenic attraction',
      'scenic spot': 'a scenic spot',
      'places of interest': 'a point of interest',
      'point of interest': 'a point of interest',
      'national park': 'a national park',
      'hiking area': 'a hiking area',
      'observation deck': 'an observation deck',
      'botanical garden': 'a botanical garden',
      'nature scenic attraction': 'a scenic nature attraction',
    };
    final title = (place['title'] ?? place['name'] ?? '').toString().trim();
    for (final field in ['category', 'type']) {
      final key = (place[field] ?? '')
          .toString()
          .toLowerCase()
          .replaceAll(RegExp(r'[^a-z]+'), ' ')
          .trim();
      final category = categories[key];
      if (category != null && title.isNotEmpty && title.length <= 150) {
        return {'text': '$title is listed as $category.', 'additionalText': ''};
      }
    }
  }
  return {
    'text':
        'More information about this place is unavailable from the current source.',
    'additionalText': ''
  };
}
