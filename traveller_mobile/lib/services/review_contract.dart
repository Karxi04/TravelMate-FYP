import 'dart:convert';
import 'package:crypto/crypto.dart';

class ReviewContract {
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
