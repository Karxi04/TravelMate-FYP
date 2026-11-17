import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'chat_action_audit_test.dart' show frame;
import 'core_personalization_notifications_test.dart' show RecsApi;

class CoverageApi extends RecsApi {
  @override
  Map response(Map options) {
    final data = super.response(options);
    data['snapshot']['coverageNotice'] =
        'No verified eligible candidates for: Photography. The geographic scope has not been expanded.';
    return data;
  }
}

void main() {
  testWidgets('missing interest coverage is explicit without fabricating cards',
      (tester) async {
    final api = CoverageApi()..pool.clear();
    await frame(tester, RecommendationScreen(api: api));
    expect(
        find.textContaining('No verified eligible candidates for: Photography'),
        findsOneWidget);
    expect(api.generations, 0);
    await tester.enterText(find.byType(TextField).first, 'Kulim');
    await tester.pumpAndSettle();
    expect(find.textContaining('No verified eligible candidates for: Photography'),findsNothing);
  });
}
