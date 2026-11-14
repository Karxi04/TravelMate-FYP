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
  int reads = 0;
  final bool localDemo;
  final bool oldServer;
  _PreviewApi({this.localDemo = true, this.oldServer = false});

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (!path.endsWith('/ratings-reviews')) return {'items': <dynamic>[]};
    if (oldServer && query?['view'] == 'samples') {
      reads++;
      return {'result': {'rating': 3.0, 'reviews': 1, 'fypPreview': true, 'user_reviews': [
        {'id': 'sample', 'rating': 3, 'description': 'Previously available sample.'},
      ]}};
    }
    expect(query, {'view': 'unified'});
    reads++;
    return {
      if (oldServer) 'sampleReviewsAvailable': true,
      'result': {
        'rating': 5.0,
        'reviews': 1,
        if (localDemo && !oldServer) 'sampleSummary': {'rating': 3.0, 'reviews': 3},
        'user_reviews': [
          {'id': 'review', 'rating': 5, 'description': 'Approved community comment.',
           'date': '2026-11-11T09:00:00+08:00'},
          if (localDemo && !oldServer)
            for (var i = 1; i <= 3; i++)
              {'id': 'sample-$i', 'rating': 3, 'source': 'sample',
               'description': 'Sample comment $i.'},
        ],
      },
    };
  }
}

void main() {
  testWidgets('older local Backend samples still appear in one Local Reviews section', (tester) async {
    final api = _PreviewApi(oldServer: true);
    await tester.pumpWidget(MaterialApp(home: DestinationDetailsScreen(api: api,
        initialDestination: const {'destinationId': 'local_penang_hill', 'title': 'Penang Hill'})));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Local Reviews'), 220);
    expect(find.text('3.0 · 1 review'), findsOneWidget);
    expect(find.text('5.0 · 1 review'), findsOneWidget);
    expect(find.text('View community reviews'), findsNothing);
    await tester.scrollUntilVisible(find.text('Previously available sample.'), 140);
    expect(find.text('Sample review'), findsOneWidget);
    expect(api.reads, 2);
  });
  testWidgets('unified reviews disclose sample source and expand without another request', (tester) async {
    final api = _PreviewApi();
    await tester.pumpWidget(MaterialApp(home: DestinationDetailsScreen(api: api,
        initialDestination: const {'destinationId': 'local_penang_hill', 'title': 'Penang Hill'})));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Local Reviews'), 220);
    expect(find.text('5.0 · 1 review'), findsOneWidget);
    expect(find.text('3.0 · 3 reviews'), findsOneWidget);
    expect(find.text('Community reviews'), findsOneWidget);
    expect(find.text('Demonstration reviews'), findsOneWidget);
    expect(find.textContaining('FYP'), findsNothing);
    expect(find.text('View community reviews'), findsNothing);
    await tester.scrollUntilVisible(find.text('Nov 11, 2026'), 150);
    expect(find.text('2026-11-11T09:00:00+08:00'), findsNothing);
    expect(find.text('Sample comment 3.'), findsNothing);
    final all = find.text('View all 4 reviews');
    await tester.scrollUntilVisible(all, 180);
    await tester.ensureVisible(all);
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -120));
    await tester.pumpAndSettle();
    await tester.tap(all.hitTestable());
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Sample comment 3.'), 150);
    expect(find.text('Sample comment 3.'), findsOneWidget);
    final fewer = find.text('Show fewer reviews');
    await tester.scrollUntilVisible(fewer, 150);
    await tester.ensureVisible(fewer);
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -120));
    await tester.pumpAndSettle();
    await tester.tap(fewer.hitTestable());
    await tester.pumpAndSettle();
    expect(find.text('Sample comment 3.'), findsNothing);
    expect(api.reads, 1);
  });

  testWidgets('ordinary authenticated response shows only community reviews', (tester) async {
    await tester.pumpWidget(MaterialApp(home: DestinationDetailsScreen(
        api: _PreviewApi(localDemo: false),
        initialDestination: const {'destinationId': 'local_penang_hill', 'title': 'Penang Hill'})));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Local Reviews'), 220);
    expect(find.text('5.0 · 1 review'), findsOneWidget);
    expect(find.text('Demonstration reviews'), findsNothing);
    expect(find.text('Sample review'), findsNothing);
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
