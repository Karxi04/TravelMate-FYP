import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/recommendation_page.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'core_personalization_notifications_test.dart' show RecsApi;

class DiscoveryApi extends RecsApi {
  final expansions = <Map>[];
  Completer<dynamic>? expansion;
  bool failExpansion = false;
  DiscoveryApi() {
    pool.removeRange(13, pool.length);
  }
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path.endsWith('/generate') && body?['expandCandidates'] == true) {
      expansions.add({...body!});
      if (expansion != null) return expansion!.future;
      if (failExpansion) throw Exception('Synthetic unavailable provider');
      final extra = List.generate(
          5,
          (i) => {
                'destinationId': 'new_$i',
                'title': 'Additional place $i',
                'discoveryEligible': true,
                'destinationConcepts': ['culture'],
                'finalScore': 65,
                'type': 'Culture',
              });
      final page = recommendationPage({
        'requestedDestination': 'Penang',
        'recommendationResults': [...pool, ...extra],
      }, {
        'discoveryMode': recommendationDiscoveryMode,
        'offset': pool.length
      });
      return {
        'ok': true,
        'recommendationGenerationId': 'expanded_1',
        'snapshot': page,
        'recommendations': page['recommendationResults'],
        'pagination': page['pagination'],
        'discoveryMessage': 'Found 5 additional matching places.'
      };
    }
    return super.post(path, body);
  }
}

Future<void> open(WidgetTester tester, DiscoveryApi api) async {
  await tester.pumpWidget(MaterialApp(
      theme: buildInkWashTheme(),
      home: RecommendationScreen(api: api, initialDestination: 'Penang')));
  await tester.pumpAndSettle();
}

Future<void> press(WidgetTester tester, String text) async {
  await tester.scrollUntilVisible(find.text(text), 500,
      scrollable: find.byType(Scrollable).first);
  await tester.tap(find.text(text));
  await tester.pumpAndSettle();
}

Future<void> checkCard(WidgetTester tester, String title, double delta) async {
  await tester.scrollUntilVisible(find.text(title), delta,
      scrollable: find.byType(Scrollable).first);
  expect(find.text(title), findsOneWidget);
}

void main() {
  test(
      'continuation preserves visible order and deduplicates provider identities',
      () {
    final previous = [
      {'destinationId': 'a'},
      {'place_id': 'b'}
    ];
    final merged = appendRecommendationResults(previous, [
      {'destinationId': 'b'},
      {'id': 'c'},
      {'id': ''}
    ]);
    expect(merged.length, 3);
    expect(merged.first['destinationId'], 'a');
    expect(merged.last['id'], 'c');
    expect(previous.length, 2);
  });

  testWidgets(
      'load more reads the same generation and discover appends new cards',
      (tester) async {
    final api = DiscoveryApi();
    await open(tester, api);
    expect(api.generations, 0);
    await press(tester, 'Load more matching places');
    expect(api.reads.last['generationId'], 'generation_0');
    expect(api.reads.last['offset'], '12');
    expect(api.expansions, isEmpty);
    await press(tester, 'Discover more places');
    expect(api.expansions, hasLength(1));
    expect(api.expansions.single['previousGenerationId'], 'generation_0');
    expect(api.expansions.single['displayedDestinationIds'], hasLength(13));
    await checkCard(tester, 'Fixture place 0', -500);
    await checkCard(tester, 'Fixture place 12', 500);
    await checkCard(tester, 'Additional place 0', 500);
    await checkCard(tester, 'Found 5 additional matching places.', 500);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'failed discovery preserves existing cards and generation context',
      (tester) async {
    final api = DiscoveryApi()..failExpansion = true;
    await open(tester, api);
    await press(tester, 'Load more matching places');
    await press(tester, 'Discover more places');
    await checkCard(tester, 'Fixture place 0', -500);
    await checkCard(tester, 'Fixture place 12', 500);
    expect(find.text('Additional place 0'), findsNothing);
    expect(api.expansions.single['previousGenerationId'], 'generation_0');
    expect(tester.takeException(), isNull);
  });

  testWidgets('rapid discover taps issue one generation request',
      (tester) async {
    final api = DiscoveryApi();
    await open(tester, api);
    await press(tester, 'Load more matching places');
    api.expansion = Completer<dynamic>();
    await tester.scrollUntilVisible(find.text('Discover more places'), 500,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Discover more places'));
    await tester.tap(find.text('Discover more places'));
    await tester.pump();
    expect(api.expansions, hasLength(1));
    api.expansion!.complete({
      'ok': true,
      'recommendationGenerationId': 'no-change',
      'recommendations': [],
      'pagination': {
        'discoveryMode': recommendationDiscoveryMode,
        'hasMore': false,
        'nextOffset': null
      },
      'discoveryMessage': 'No additional places.'
    });
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
