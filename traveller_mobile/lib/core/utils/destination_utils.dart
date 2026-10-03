class DestinationUtils {
  /// Canonical destination ID resolver used consistently across
  /// search, details, feedback submission/retrieval, and itinerary planning.
  static String resolveId(Map<String, dynamic>? item) {
    if (item == null) return '';
    final id = item['destinationId'] ??
        item['place_id'] ??
        item['data_id'] ??
        item['data_cid'] ??
        item['id'] ??
        item['title'] ??
        item['name'] ??
        '';
    return id.toString().trim();
  }

  static String resolveName(Map<String, dynamic>? item) {
    if (item == null) return 'Place';
    final name = item['title'] ?? item['name'] ?? item['destinationName'] ?? 'Place';
    return name.toString().trim();
  }
}
