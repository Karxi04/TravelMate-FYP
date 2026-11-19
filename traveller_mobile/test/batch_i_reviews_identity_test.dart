import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travelmate_traveller/core/utils/destination_utils.dart';
import 'package:travelmate_traveller/services/review_contract.dart';
import 'package:travelmate_traveller/services/transaction_request.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/modules/fr10_feedback_rating/feedback_screen.dart';
import 'package:travelmate_traveller/widgets/local_place_rating.dart';

class _ReviewEditApi extends ApiService {
  int writes = 0;
  final record = <String, dynamic>{'id': 'owned-review', 'destinationId': 'local_penang_hill',
    'destinationName': 'Penang Hill', 'rating': 4, 'comment': 'Beautiful architecture and views.',
    'feedbackStatus': 'visible', 'moderationStatus': 'reviewed', 'editCount': 1};
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async => {'items': [{...record}]};
  @override
  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    writes++;
    record.addAll({...?body, 'editCount': 2});
    return {'ok': true, 'feedback': {...record}};
  }
}

void main() {
  testWidgets('the selected-place form also shows and enforces the exhausted allowance', (tester) async {
    final api = _ReviewEditApi(); api.record['editCount'] = 2;
    await tester.pumpWidget(MaterialApp(home: FeedbackScreen(api: api,
      initialDestination: const {'destinationId': 'local_penang_hill', 'title': 'Penang Hill'})));
    await tester.pumpAndSettle();
    final submit = find.widgetWithText(FilledButton, 'Submit review');
    await tester.scrollUntilVisible(submit, 180, scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();
    expect(tester.widget<Text>(find.byKey(const ValueKey('selected-review-allowance'))).data, 'No edits remaining');
    expect(tester.widget<FilledButton>(submit).onPressed, isNull);
    expect(api.writes, 0);
  });
  testWidgets('review editor shows the allowance and disables a third actual edit', (tester) async {
    final api = _ReviewEditApi();
    await tester.pumpWidget(MaterialApp(home: FeedbackScreen(api: api)));
    await tester.pumpAndSettle();
    final edit = find.widgetWithText(OutlinedButton, 'Edit');
    await tester.scrollUntilVisible(edit, 250, scrollable: find.byType(Scrollable).first);
    await tester.ensureVisible(edit); await tester.pumpAndSettle();
    await tester.tap(edit); await tester.pumpAndSettle();
    expect(find.descendant(of: find.byType(AlertDialog), matching: find.text('Edits remaining: 1 of 2')), findsOneWidget);
    final comment = find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField));
    await tester.enterText(comment, 'A wonderful visit with beautiful architecture.');
    await tester.tap(find.widgetWithText(FilledButton, 'Save')); await tester.pumpAndSettle();
    expect(api.writes, 1);
    expect(find.text('No edits remaining'), findsOneWidget);
    expect(tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Edit')).onPressed, isNull);
  });
  testWidgets('genuine rating is explicit and unrated state invents no score', (tester) async {
    for (final example in [
      ({'rating': 4.0, 'reviews': 1}, '4.0 (1 review)'),
      ({'rating': 4.5, 'reviews': 2}, '4.5 (2 reviews)'),
      ({'rating': 3.0, 'reviews': 4}, '3.0 (4 reviews)'),
      ({'rating': 3.0, 'reviews': 5}, '3.0 (5 reviews)'),
      ({'rating': null, 'reviews': 0}, 'Not rated yet'),
    ]) {
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: LocalReviewRatingBadge(summary: example.$1))));
      expect(find.text(example.$2), findsOneWidget);
      if (example.$1['reviews'] != 0) expect(find.byIcon(Icons.star_rounded), findsOneWidget);
    }
  });

  test('review allowance is durable record state and legacy defaults to two', () {
    expect(ReviewContract.editAllowance({}), 'Edits remaining: 2 of 2');
    expect(ReviewContract.editAllowance({'editCount': 1}), 'Edits remaining: 1 of 2');
    expect(ReviewContract.editAllowance({'editCount': 2}), 'No edits remaining');
    expect(ReviewContract.editsRemaining({'editCount': -1}), 0);
  });

  test('pagination merges same attraction aliases and keeps nearby distinct names', () {
    final first = {'destinationId': 'provider-a', 'title': 'Batu Caves', 'state': 'Selangor', 'city': 'Batu Caves', 'address': 'Batu Caves, Gombak, Selangor'};
    final next = {...first, 'destinationId': 'provider-b', 'address': 'Batu Caves, Kampung Laksamana, Selangor', 'openingHours': 'Daily 08:00-18:00'};
    final temple = {...first, 'destinationId': 'other-temple', 'title': 'Sri Venkatachalapathi Temple'};
    final distant = {...first, 'destinationId': 'different-place', 'gps_coordinates': {'latitude': 3.5, 'longitude': 101.9}};
    final pinned = {...first, 'gps_coordinates': {'latitude': 3.2379, 'longitude': 101.684}};
    final merged = DestinationUtils.uniquePlaces([first, next, temple]);
    expect(merged.length, 2);
    expect(merged.first['identityAliases'], containsAll(['provider-a', 'provider-b']));
    expect(merged.first['openingHours'], next['openingHours']);
    expect(DestinationUtils.samePlace(pinned, distant), isFalse);
    expect(DestinationUtils.samePlace(first, {...first, 'destinationId': 'elsewhere', 'state': 'Johor'}), isFalse);
    expect(DestinationUtils.samePlace({...first, 'identityAliases': 'invalid', 'normalizedGeography': 'invalid'}, next), isTrue);
  });

  test('planning identity and original input survive restart and are owner scoped', () async {
    SharedPreferences.setMockInitialValues({});
    const request = {'generationRequestId': 'one-request', 'destinationArea': 'Penang', 'budgetLimit': 800};
    await ItineraryGenerationStore.save('synthetic-owner', request);
    expect(await ItineraryGenerationStore.read('another-owner'), isNull);
    expect(await ItineraryGenerationStore.read('synthetic-owner'), request);
    await ItineraryGenerationStore.clear('synthetic-owner');
    expect(await ItineraryGenerationStore.read('synthetic-owner'), isNull);
  });
}
