import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/malaysian_locations.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'chat_action_audit_test.dart' show frame, tap, copy;
import 'location_chat_reliability_test.dart' show LocationApi;

final source = jsonDecode(
    File('../backend_api/services/data/malaysia_locations.json')
        .readAsStringSync()) as Map;
Map<String, dynamic> dto(Map row) {
  final duplicates = (source['places'] as List)
      .where((r) =>
          r['name'] == row['name'] &&
          r['state'] == row['state'] &&
          r['kind'] == row['kind'])
      .toList();
  var name = '${row['name']}${row['kind'] == 'district' ? ' District' : ''}';
  final district = duplicates.length > 1 && row['district'] != null
      ? ', ${row['district']}'
      : '';
  return {
    'country': 'Malaysia',
    'city': row['name'],
    'state': row['state'],
    'district': row['district'],
    'kind': row['kind'],
    'canonicalName': '$name$district, ${row['state']}, Malaysia',
    'scopeKey': 'my:geonames:${row['id']}',
    'locationId': 'geonames:${row['id']}',
    'aliases': row['aliases'],
    'population': row['population'],
  };
}

final rawInstant = <Map<String, dynamic>>[
  for (final state in (source['counts']['byState'] as Map).keys)
    {
      'country': 'Malaysia',
      'state': state,
      'kind': 'state',
      'canonicalName': '$state, Malaysia',
      'scopeKey': 'my:${'$state'.toLowerCase().replaceAll(' ', '_')}',
      'aliases': [state]
    },
  for (final row in source['places'] as List)
    if (row['fast'] == true && row['name'] != row['state']) dto(row as Map),
];
final instant = rawInstant
    .where((row) =>
        rawInstant
            .where((other) => other['canonicalName'] == row['canonicalName'])
            .length ==
        1)
    .toList();
final kulim = dto(
    (source['places'] as List).firstWhere((r) => r['id'] == '1734393') as Map);

class CatalogueApi extends LocationApi {
  int lookups = 0;
  bool lookupFails = false;
  Completer<dynamic>? lookupGate;
  List<Map<String, dynamic>> extra = [];
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr4/locations') {
      catalogueReads++;
      return {'locations': instant};
    }
    if (path == '/api/fr4/locations/search') {
      lookups++;
      if (lookupFails) throw StateError('Isolated lookup unavailable');
      return lookupGate?.future ??
          Future.value({'ok': true, 'locations': extra});
    }
    return super.get(path, query);
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    final data = await super.post(path, body);
    if (path == '/api/fr4/recommendations/generate') {
      data['snapshot']['canonicalDestinationScope'] = copy(kulim);
    }
    return data;
  }
}

void main() {
  for (final query in [
    'kulim',
    'alma',
    'machang',
    'sungai',
    'bukit mer',
    'kota',
    'Macang Bubuk'
  ]) {
    test(
        'sourced instant catalogue matches $query with unique Malaysian identities',
        () {
      final rows = matchingMalaysianLocations(instant, query);
      expect(rows, isNotEmpty);
      expect(rows.every((r) => r['country'] == 'Malaysia'), isTrue);
      expect(rows.map((r) => r['scopeKey']).toSet().length, rows.length);
      if (query == 'kulim') expect(rows.first['state'], 'Kedah');
      if (query == 'alma' || query == 'Macang Bubuk')
        expect(rows.first['state'], 'Penang');
      if (query == 'machang') {
        expect(
            rows.any((row) =>
                row['city'] == 'Machang Bubok' && row['state'] == 'Penang'),
            isTrue);
        expect(rows.first['state'], 'Kelantan');
      }
    });
  }
  test('foreign rows never become autocomplete suggestions', () {
    expect(
        matchingMalaysianLocations([
          ...instant,
          {
            'country': 'Singapore',
            'city': 'Singapore',
            'canonicalName': 'Singapore',
            'scopeKey': 'sg'
          }
        ], 'singapore'),
        isEmpty);
  });
  testWidgets(
      'Kulim selection submits its source identity only on explicit keyboard search',
      (tester) async {
    final api = CatalogueApi();
    await frame(tester, RecommendationScreen(api: api));
    await tester.enterText(find.byType(TextField).first, 'kulim');
    await tester.pumpAndSettle();
    expect(api.generatedBodies, isEmpty);
    expect(api.lookups, 0);
    await tap(tester, find.text('Kulim, Kedah, Malaysia'));
    expect(api.generatedBodies, isEmpty);
    await tester.showKeyboard(find.byType(TextField).first);
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();
    expect(api.generatedBodies.single['destinationArea'],
        'Kulim, Kedah, Malaysia');
    expect(api.generatedBodies.single['destinationLocationId'],
        'geonames:1734393');
  });
  testWidgets(
      'extended lookup and selection never generate recommendations automatically',
      (tester) async {
    final record = (source['places'] as List)
        .firstWhere((r) => r['fast'] == false && r['state'] == 'Penang') as Map;
    final api = CatalogueApi()..extra = [dto(record)];
    await frame(tester, RecommendationScreen(api: api));
    await tester.enterText(
        find.byType(TextField).first, record['name'] as String);
    await tester.pumpAndSettle();
    expect(api.lookups, 0);
    await tap(tester, find.text('Find more Malaysian locations'));
    expect(api.lookups, 1);
    expect(api.generatedBodies, isEmpty);
    await tap(
        tester,
        find
            .widgetWithText(ListTile, dto(record)['canonicalName'] as String)
            .last);
    final dynamic state = tester.state(find.byType(RecommendationScreen));
    expect(state.selectedLocation['locationId'], 'geonames:${record['id']}');
    expect(state.destination.text, dto(record)['canonicalName']);
    expect(api.generatedBodies, isEmpty);
  });
  testWidgets('late lookup cannot replace a newly typed destination',
      (tester) async {
    final api = CatalogueApi()..lookupGate = Completer<dynamic>();
    await frame(tester, RecommendationScreen(api: api));
    await tester.enterText(find.byType(TextField).first, 'Unlisted area');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Find more Malaysian locations'));
    await tester.pump();
    await tester.enterText(find.byType(TextField).first, 'Alma');
    await tester.pump();
    api.lookupGate!.complete({
      'locations': [kulim]
    });
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(RecommendationScreen));
    expect(state.destination.text, 'Alma');
    expect(state.lookupMatches, isEmpty);
    expect(state.selectedLocation, isNull);
    expect(api.generatedBodies, isEmpty);
  });
  testWidgets('lookup outage retains local suggestions and never generates',
      (tester) async {
    final api = CatalogueApi()..lookupFails = true;
    await frame(tester, RecommendationScreen(api: api));
    await tester.enterText(find.byType(TextField).first, 'Unlisted fixture');
    await tester.pumpAndSettle();
    await tap(tester, find.text('Find more Malaysian locations'));
    expect(find.textContaining('Additional location lookup is unavailable'),
        findsOneWidget);
    expect(api.lookups, 1);
    await tester.enterText(find.byType(TextField).first, 'Kulim');
    await tester.pumpAndSettle();
    expect(find.text('Kulim, Kedah, Malaysia'), findsOneWidget);
    expect(api.lookups, 1);
    expect(api.generatedBodies, isEmpty);
  });
  testWidgets(
      'empty Kulim results broaden to Kedah only after a deliberate action',
      (tester) async {
    final api = CatalogueApi();
    api.pool.clear();
    await frame(tester, RecommendationScreen(api: api));
    final dynamic state = tester.state(find.byType(RecommendationScreen));
    state.chooseLocation(kulim);
    await tester.pumpAndSettle();
    await state.generate();
    await tester.pumpAndSettle();
    expect(api.generatedBodies, hasLength(1));
    await tap(tester, find.text('Use wider area: Kedah (then search again)'));
    expect(state.destination.text, 'Kedah, Malaysia');
    expect(api.generatedBodies, hasLength(1));
    expect(state.selectedLocation['kind'], 'state');
  });
}
