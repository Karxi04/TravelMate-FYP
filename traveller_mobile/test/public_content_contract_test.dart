import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/public_content_contract.dart';

void main() {
  test('public contract strips private package and nested fields', () {
    final result = PublicContentContract.package({
      'id': 'pkg-1',
      'title': 'Penang',
      'operatorId': 'private',
      'itineraryDays': [
        {'title': 'Day 1', 'description': 'Walk', 'secret': 'private'},
      ],
      'activeCampaigns': [
        {'campaignTitle': 'Offer', 'reviewedBy': 'private'},
      ],
    });
    expect(result['title'], 'Penang');
    expect(result.containsKey('operatorId'), isFalse);
    expect(result['itineraryDays'][0].containsKey('secret'), isFalse);
    expect(result['activeCampaigns'][0].containsKey('reviewedBy'), isFalse);
  });

  test('public review contract keeps display fields without author identity', () {
    final result = PublicContentContract.review({
      'id': 'review-1',
      'comment': 'Great',
      'travellerName': 'Traveller',
      'travellerId': 'private',
      'moderationStatus': 'pending_review',
    });
    expect(result['comment'], 'Great');
    expect(result.containsKey('travellerId'), isFalse);
    expect(result.containsKey('moderationStatus'), isFalse);
  });
}
