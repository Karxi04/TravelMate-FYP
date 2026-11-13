import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
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

class _PreviewApi extends ApiService {
  int communityReads = 0;
  final bool localDemo;
  _PreviewApi({this.localDemo = false});

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (!path.endsWith('/ratings-reviews')) return {'items': <dynamic>[]};
    final community = query?['view'] == 'community' || (localDemo && query?['view'] != 'samples');
    if (community) communityReads++;
    return {
      if (localDemo) 'sampleReviewsAvailable': true,
      'result': {
        'rating': community ? 5.0 : 3.0,
        'reviews': community ? 1 : 2,
        if (!community) 'fypPreview': true,
        'user_reviews': [
          {'id': 'review', 'rating': 5, 'description': community ? 'Approved community comment.' : 'Private fixture comment.'},
        ],
      },
    };
  }
}

void main() {
  testWidgets('Private preview switches to the separate community view', (tester) async {
    final api = _PreviewApi();
    await tester.pumpWidget(MaterialApp(home: DestinationDetailsScreen(api: api,
        initialDestination: const {'destinationId': 'local_penang_hill', 'title': 'Penang Hill'})));
    await tester.pumpAndSettle();
    final toggle = find.text('View community reviews');
    await tester.scrollUntilVisible(toggle, 250);
    expect(find.text('Fictional reviews for the private FYP demonstration.'), findsOneWidget);
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Back to private FYP preview'), 180);
    expect(api.communityReads, 1);
    expect(find.text('Private fixture comment.'), findsNothing);
    expect(find.text('5.0 · 1 review'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Approved community comment.'), 180);
    expect(find.text('Approved community comment.'), findsOneWidget);
  });

  testWidgets('Local demo starts with community ratings and labels opted-in samples', (tester) async {
    final api = _PreviewApi(localDemo: true);
    await tester.pumpWidget(MaterialApp(home: DestinationDetailsScreen(api: api,
        initialDestination: const {'destinationId': 'local_penang_hill', 'title': 'Penang Hill'})));
    await tester.pumpAndSettle();
    final samples = find.text('View FYP sample reviews');
    await tester.scrollUntilVisible(samples, 220);
    expect(find.text('5.0 · 1 review'), findsOneWidget);
    await tester.ensureVisible(samples);
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -160));
    await tester.pumpAndSettle();
    await tester.tap(samples.hitTestable());
    await tester.pumpAndSettle();
    final community = find.text('View community reviews');
    await tester.scrollUntilVisible(community, 180);
    await tester.ensureVisible(find.text('FYP sample reviews · fictional demonstration content'));
    expect(find.text('FYP sample reviews · fictional demonstration content'), findsOneWidget);
    expect(find.text('3.0 · 2 reviews'), findsOneWidget);
    await tester.ensureVisible(community);
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -120));
    await tester.pumpAndSettle();
    await tester.tap(community.hitTestable());
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(samples, 180);
    expect(find.text('5.0 · 1 review'), findsOneWidget);
    expect(find.text('3.0 · 2 reviews'), findsNothing);
  });

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
