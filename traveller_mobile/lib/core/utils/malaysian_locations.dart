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

  final result = catalogue.where((row) => rank(row) < 4).toList();
  result.sort((a, b) {
    final comparison = rank(a).compareTo(rank(b));
    return comparison != 0
        ? comparison
        : '${a['canonicalName']}'.compareTo('${b['canonicalName']}');
  });
  return result.take(30).toList();
}
