import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/main.dart';

void main() {
  testWidgets(
      'startup failure shows a retryable error instead of a blank screen',
      (tester) async {
    await tester.pumpWidget(TravelMateApp(
      initialize: () async => throw StateError('fixture failure'),
    ));
    await tester.pumpAndSettle();

    expect(
        find.text(
            'TravelMate could not start. Check the app configuration and try again.'),
        findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
  });
}
