import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr10_feedback_rating/feedback_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/review_contract.dart';

class ReviewApi extends ApiService {
  int submissions = 0;
  List<Map<String, dynamic>> items = [];
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async => {'items': items};
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    submissions++;
    await Future<void>.delayed(const Duration(milliseconds: 50));
    final review = {'id': 'review', ...?body, 'moderationStatus': 'pending_review', 'feedbackStatus': 'visible'};
    items = [review];
    return {'ok': true, 'feedback': review};
  }
}

void main() {
  test('review identity matches backend and safe input rejects metadata spoofing', () {
    expect(ReviewContract.identity('owner', 'synthetic-place'),
        'review_97ae84dea9cd4a877c1397e1cac7d0194daf2c5df7ca99657376eed9ff7dbdde');
    expect(ReviewContract.valid({'rating': 5, 'comment': 'Lovely visit', 'destinationId': 'place'}), isTrue);
    expect(ReviewContract.valid({'rating': 5, 'comment': 'Lovely visit', 'travellerId': 'other'}, partial: true), isFalse);
    expect(ReviewContract.status({'moderationStatus': 'pending_review'}), 'Awaiting approval');
    expect(ReviewContract.status({'moderationStatus': 'reviewed'}), 'Published');
  });

  testWidgets('submission is single-flight and shows real pending state', (tester) async {
    final api = ReviewApi();
    await tester.pumpWidget(MaterialApp(home: FeedbackScreen(api: api,
        initialDestination: const {'destinationId': 'synthetic-place', 'title': 'Synthetic Place'})));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'Beautiful views and a peaceful visit.');
    await tester.ensureVisible(find.text('Submit review'));
    await tester.tap(find.text('Submit review'));
    await tester.tap(find.text('Submit review'), warnIfMissed: false);
    await tester.pumpAndSettle();
    expect(api.submissions, 1);
    expect(find.text('Your review is awaiting approval.'), findsOneWidget);
    expect(api.items.single['moderationStatus'], 'pending_review');
  });
}
