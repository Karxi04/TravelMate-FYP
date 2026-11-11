import 'dart:convert';
import 'package:crypto/crypto.dart';

class ReviewContract {
  // Exact Penang IDs only. Keep in sync with backend review_destination.py.
  static const _aliases = <String, List<String>>{
    'local_penang_hill': ['penang_hill'],
    'local_kek_lok_si': ['kek_lok_si', 'ChIJZYb8XRjCSjARxD5Df-qEkCw'],
    'local_peranakan_mansion': ['peranakan_mansion', 'ChIJCWvz3I_DSjAR5hveCXjdfIs'],
    'local_wonderfood': ['wonderfood_museum', 'ChIJv4nHaI7DSjAR8peeKMlaKok'],
    'local_batu_ferringhi': ['batu_ferringhi'],
    'local_botanical_gardens': ['penang_botanic_gardens', 'ChIJWeDiIPHCSjAROzyNNz_QUx8'],
    'local_chew_jetty': ['ChIJ50W1D43DSjARlPqYV1MqscE'],
  };

  static String destinationId(String id) {
    final identity = id.trim();
    for (final entry in _aliases.entries) {
      if (entry.value.contains(identity)) return entry.key;
    }
    return identity;
  }

  static List<String> destinationIds(String id) {
    final canonical = destinationId(id);
    return [canonical, ...?_aliases[canonical]];
  }

  static double? approvedRating(Map<String, dynamic> review) {
    final rating = double.tryParse('${review['rating']}');
    return rating != null && rating.isFinite && rating >= 1 && rating <= 5
        ? rating
        : null;
  }

  static String sentiment(int rating) => rating >= 4 ? 'Positive / good' : rating == 3 ? 'Neutral / moderate' : 'Negative / poor';
  static String identity(String uid, String destination) =>
      'review_${sha256.convert(utf8.encode('$uid\u0000${destination.trim()}'))}';

  static bool valid(Map<String, dynamic> data, {bool partial = false}) {
    final allowed = {'rating', 'comment', if (!partial) ...{'destinationId', 'destinationName', 'destinationAddress'}};
    if (data.isEmpty || !data.keys.every(allowed.contains)) return false;
    if (!partial && !{'rating', 'comment', 'destinationId'}.every(data.containsKey)) return false;
    if (data.containsKey('rating') && (data['rating'] is! int || data['rating'] < 1 || data['rating'] > 5)) return false;
    if (data.containsKey('comment') && (data['comment'] is! String || data['comment'].trim().length < 5 || data['comment'].trim().length > 2000)) return false;
    return !data.containsKey('destinationId') || (data['destinationId'] is String && data['destinationId'].trim().isNotEmpty && data['destinationId'].length <= 500);
  }

  static String status(Map<String, dynamic> review) => review['feedbackStatus'] == 'removed'
      ? 'Removed by Administrator'
      : {'reviewed', 'approved'}.contains(review['moderationStatus']) ? 'Published' : 'Awaiting approval';
}
