List<String> _facts(dynamic value) {
  if (value is Map) value = value['overview'] ?? value['snippet'];
  if (value is! String) return [];
  final text = value
      .replaceAll(RegExp(r'<[^>]*>'), '')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  final unsafe = RegExp(
      r'\b(ignore|instructions?|system prompt|reviews?|rated|rating|best time|crowd|accessible|accessibility|open daily|opens?|closes?|hours?|tickets?|admission|free entry|RM\s*\d|MYR|\d{1,2}:\d{2})\b',
      caseSensitive: false);
  return text
      .split(RegExp(r'(?<=[.!?])\s+'))
      .where((s) => s.length >= 8 && s.length <= 350 && !unsafe.hasMatch(s))
      .toList();
}

Map<String, dynamic> destinationSummary(Map<String, dynamic> place) {
  final server = place['placeSummary'];
  if (server is Map &&
      server['source'] == 'recorded_public_facts' &&
      server['text'] is String) {
    return Map<String, dynamic>.from(server);
  }
  for (final key in ['description', 'editorial_summary', 'snippet', 'about']) {
    final facts = _facts(place[key]).toSet().toList();
    if (facts.isNotEmpty)
      return {
        'text': facts.take(3).join(' '),
        'additionalText': facts.skip(3).take(3).join(' ')
      };
  }
  final category =
      '${place['category'] ?? place['type'] ?? ''}'.trim().toLowerCase();
  final title = '${place['title'] ?? place['name'] ?? ''}'.trim();
  const allowed = {
    'museum',
    'temple',
    'mosque',
    'beach',
    'park',
    'garden',
    'shopping mall',
    'shopping',
    'nature reserve',
    'art gallery',
    'historical landmark',
    'tourist attraction'
  };
  return {
    'text': allowed.contains(category) &&
            title.isNotEmpty &&
            title.length <= 150 &&
            place['metadataConflict'] != true
        ? '$title is listed as a $category.'
        : 'More information about this place is unavailable from the current source.',
    'additionalText': ''
  };
}
