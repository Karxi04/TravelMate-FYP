String _locationText(Object? value) =>
    '$value'.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim();

List<Map<String, dynamic>> matchingMalaysianLocations(
    List<Map<String, dynamic>> catalogue, String query) {
  final q = _locationText(query);
  if (q.isEmpty) return [];
  final tokens = q.split(' ');
  int rank(Map<String, dynamic> row) {
    final names = [
      row['city'] ?? row['state'] ?? row['canonicalName'],
      ...?row['aliases'] as List?
    ].map(_locationText).toList();
    if (names.contains(q)) return 0;
    if (names.any((name) => name.startsWith(q))) return 1;
    final words = _locationText(row['canonicalName']).split(' ');
    if (tokens.every((token) => words.any((word) => word.startsWith(token))))
      return 2;
    if (tokens.every((token) =>
        _locationText('${row['canonicalName']} ${names.join(' ')}')
            .contains(token))) return 3;
    return 4;
  }

  final result = <MapEntry<int, Map<String, dynamic>>>[];
  for (final row in catalogue) {
    if (row['country'] != null && row['country'] != 'Malaysia') continue;
    final score = rank(row);
    if (score < 4) result.add(MapEntry(score, row));
  }
  result.sort((a, b) {
    final comparison = a.key.compareTo(b.key);
    final population = ((b.value['population'] as num?) ?? 0)
        .compareTo((a.value['population'] as num?) ?? 0);
    return comparison != 0
        ? comparison
        : population != 0
            ? population
            : '${a.value['canonicalName']}'
                .compareTo('${b.value['canonicalName']}');
  });
  return result.take(30).map((entry) => entry.value).toList();
}
