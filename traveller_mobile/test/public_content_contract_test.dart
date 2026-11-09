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
        {'campaignTitle': 'Offer', 'reviewedBy': 'private', 'startDate':'2020-01-01','endDate':'2099-01-01'},
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

  test('public review contract preserves submittedAt and date for duplicate resolution', () {
    final legacyWithoutUpdate = PublicContentContract.review({
      'id': 'rev-legacy-1',
      'reviewKey': 'key-alice',
      'comment': 'Initial review',
      'submittedAt': '2026-01-01T10:00:00Z',
      'date': '2026-01-01T10:00:00Z',
      'rating': 4,
    });
    final newerWithoutUpdate = PublicContentContract.review({
      'id': 'rev-legacy-2',
      'reviewKey': 'key-alice',
      'comment': 'Follow-up review',
      'submittedAt': '2026-02-01T10:00:00Z',
      'date': '2026-02-01T10:00:00Z',
      'rating': 5,
    });

    final reviews = [legacyWithoutUpdate, newerWithoutUpdate];
    // Deterministic sort: fallback to submittedAt / date when updatedAt is absent
    reviews.sort((a, b) => '${b['updatedAt'] ?? b['submittedAt'] ?? b['date'] ?? ''}'
        .compareTo('${a['updatedAt'] ?? a['submittedAt'] ?? a['date'] ?? ''}'));

    final unique = <String, Map<String, dynamic>>{};
    for (final item in reviews) {
      unique.putIfAbsent('${item['reviewKey'] ?? item['id']}', () => item);
    }

    expect(unique.length, 1);
    expect(unique['key-alice']!['id'], 'rev-legacy-2');
    expect(unique['key-alice']!['comment'], 'Follow-up review');
  });
}
