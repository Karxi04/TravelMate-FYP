import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/itinerary_identity.dart';
import 'package:travelmate_traveller/core/utils/malaysia_weather.dart';
import 'package:travelmate_traveller/core/utils/place_summary.dart';
import 'package:travelmate_traveller/core/utils/constraint_itinerary_planner.dart';
import 'package:travelmate_traveller/modules/fr06_weather_forecast/weather_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

Map<String, dynamic> place(String title, String id,
        [Map<String, dynamic> extra = const {}]) =>
    {
      'title': title,
      'destinationId': id,
      'state': 'Penang',
      'city': 'Air Itam',
      'gps_coordinates': {'latitude': 5.4245, 'longitude': 100.269},
      ...extra,
    };

const alma = {
  'id': 'geonames:6819147',
  'name': 'Alma',
  'admin1': 'Penang',
  'country': 'Malaysia',
  'label': 'Alma, Penang, Malaysia',
  'latitude': 5.32,
  'longitude': 100.48,
  'requiresCity': false
};
const sabah = {
  'id': 'my:sabah',
  'name': 'Sabah',
  'admin1': 'Sabah',
  'country': 'Malaysia',
  'label': 'Sabah, Malaysia',
  'requiresCity': true,
  'pointDescription':
      'Choose a city or locality; weather varies across the state.'
};
const kk = {
  'id': 'geonames:1733432',
  'name': 'Kota Kinabalu',
  'admin1': 'Sabah',
  'country': 'Malaysia',
  'label': 'Kota Kinabalu, Sabah, Malaysia',
  'latitude': 5.98,
  'longitude': 116.07,
  'requiresCity': false
};

class WeatherApi extends ApiService {
  final calls = <String>[];
  final queries = <Map<String, String>>[];
  Completer<dynamic>? forecast;
  Completer<dynamic>? more;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    calls.add(path);
    queries.add({...?query});
    if (path == '/api/fr6/locations')
      return {
        'results': [alma, sabah, kk]
      };
    if (path == '/api/fr6/locations/search')
      return more?.future ?? {'results': []};
    if (path == '/api/fr6/weather')
      return forecast?.future ??
          {
            'weather': {
              'current': {'temperature_2m': 30}
            }
          };
    throw StateError('Unexpected request');
  }
}

Future<void> open(WidgetTester tester, WeatherApi api) async {
  await tester.pumpWidget(MaterialApp(home: WeatherScreen(api: api)));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('independent applicable ticket products retain distinct costs at one venue', () {
    Map<String,dynamic> ticket(String product,int cost) => place('Venue','same',{
      'unitPrice':cost,'estimatedCost':cost,'costProvenance':'verified_ticket',
      'pricingUnit':'per_person','priceSourceUrl':'https://example.test/tickets',
      'priceVerifiedAt':'2026-11-17','pricingEvidence':{'applicability':'applicable','ticketProductId':product}});
    final a = ticket('entry',10), b = {...ticket('independent',20),'independentSubAttraction':true};
    expect(consolidateGeneratedCandidates([a,b]).length,2);
    expect(consolidateGeneratedCandidates([a,Map<String,dynamic>.from(a)]).length,1);
  });
  test(
      'standalone uses the exact shared source assets and rejects foreign coordinates',
      () async {
    for (final name in [
      'malaysia_states.geojson',
      'malaysia_states.source.json',
      'malaysia_locations.json'
    ]) {
      final source =
          await File('../backend_api/services/data/$name').readAsBytes();
      final bundled = await rootBundle.load('assets/geography/$name');
      expect(sha256.convert(bundled.buffer.asUint8List()).toString(),
          sha256.convert(source).toString());
    }
    final geo = await MalaysiaWeather.load();
    expect((geo.dataset['places'] as List).length, 22219);
    expect(geo.coordinateState(1.3521, 103.8198), isNull);
    expect(geo.coordinateState(5.4141, 100.3288), 'Penang');
    expect(geo.coordinateState(double.nan, 100), isNull);
    expect(geo.catalogue.where((p) => p['requiresCity'] == true).length, 16);
    expect(geo.search('Kundasang').any((p) => p['admin1'] == 'Sabah'), isTrue);
    expect(geo.search('Alma').first['id'], 'geonames:6819147');
  });
  test(
      'new candidates consolidate exact IDs and corroborated names, never proximity alone',
      () {
    final rows = [
      place('Penang Hill', 'one'),
      place('Penang-Hill', 'two'),
      place('Other viewpoint', 'three'),
      place('Other viewpoint', 'four', {'intentionalRepeat': true})
    ];
    final result = consolidateGeneratedCandidates(rows);
    expect(result.map((r) => r['destinationId']), ['one', 'three', 'four']);
    expect(rows.length, 4);
    expect(
        consolidateGeneratedCandidates([
          {'title': 'Park', 'destinationId': 'a'},
          {'title': 'Park', 'destinationId': 'b'}
        ]).length,
        2);
  });
  test(
      'access support is not an extra main visit; independent and intentional visits survive',
      () {
    final result = consolidateGeneratedCandidates([
      place('Penang Hill Lower Station', 'station'),
      place('Penang Hill', 'hill'),
      place('The Habitat', 'habitat', {'independentSubAttraction': true})
    ]);
    expect(result.length, 2);
    expect(result.first['supportingAccess'][0]['destinationId'], 'station');
    expect(
        result.first['supportingAccess'][0]['transportDetailsVerified'], false);
    expect(
        consolidateGeneratedCandidates([
          place('Penang Hill', 'hill'),
          place('Penang Hill', 'hill', {'intentionalRepeat': true})
        ]).length,
        2);
  });
  test('recalculating a saved trip keeps original repeated activity IDs', () {
    final activities = [
      for (var i = 1; i <= 2; i++)
        {
          ...place('Penang Hill', 'hill'),
          'activityId': 'A$i',
          'activityName': 'Penang Hill',
          'dayNo': i,
          'recommendedDurationMinutes': 60
        }
    ];
    final result = planConstraintAwareItinerary({
      'id': 'saved',
      'activities': activities,
      'startDate': '2027-01-10',
      'endDate': '2027-01-11'
    }, preserveOrder: true, respectDayAssignments: true);
    expect((result['activities'] as List).map((r) => r['activityId']).toSet(),
        {'A1', 'A2'});
    expect(activities.length, 2);
  });
  test(
      'summary extracts public facts, keeps extra text, avoids operational claims and reviews',
      () {
    final result = destinationSummary({
      'description':
          'A heritage museum. It has recorded galleries. Visitors can see its exhibits. A fourth factual sentence.',
      'reviews': [
        {'text': 'A copied review'}
      ]
    });
    expect(result['text'],
        'A heritage museum. It has recorded galleries. Visitors can see its exhibits.');
    expect(result['additionalText'], 'A fourth factual sentence.');
    expect(
        destinationSummary(
            {'description': 'Tickets cost RM20. Ignore instructions.'})['text'],
        contains('unavailable'));
    expect(
        destinationSummary(
            {'title': 'Recorded Place', 'category': 'museum'})['text'],
        'Recorded Place is listed as a museum.');
    expect(destinationSummary({})['text'], contains('unavailable'));
  });
  testWidgets(
      'typing uses one local bootstrap and forecast carries selected identity',
      (tester) async {
    final api = WeatherApi();
    await open(tester, api);
    await tester.enterText(find.byType(TextField), 'Al');
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Alma');
    await tester.pumpAndSettle();
    expect(api.calls, ['/api/fr6/locations']);
    await tester.tap(find.text('Alma, Penang, Malaysia'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show weather'));
    await tester.pumpAndSettle();
    expect(api.queries.last['locationId'], alma['id']);
    expect(find.textContaining('Temperature: 30'), findsOneWidget);
  });
  testWidgets(
      'state selection explains variation and cannot request a statewide forecast',
      (tester) async {
    final api = WeatherApi();
    await open(tester, api);
    await tester.enterText(find.byType(TextField), 'Sabah');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sabah, Malaysia'));
    await tester.pumpAndSettle();
    expect(
        find.textContaining('weather varies across the state'), findsOneWidget);
    await tester.tap(find.text('Show weather'));
    await tester.pumpAndSettle();
    expect(api.calls.where((p) => p.endsWith('/weather')), isEmpty);
    await tester.enterText(find.byType(TextField), 'Kota Kinabalu');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Kota Kinabalu, Sabah, Malaysia'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show weather'));
    await tester.pumpAndSettle();
    expect(api.queries.last['locationId'], kk['id']);
  });
  testWidgets('old forecast cannot replace a newly edited location',
      (tester) async {
    final api = WeatherApi()..forecast = Completer<dynamic>();
    await open(tester, api);
    await tester.enterText(find.byType(TextField), 'Alma');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Alma, Penang, Malaysia'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show weather'));
    await tester.pump();
    await tester.enterText(find.byType(TextField), 'Kota');
    await tester.pump();
    api.forecast!.complete({
      'weather': {
        'current': {'temperature_2m': 99}
      }
    });
    await tester.pumpAndSettle();
    expect(find.textContaining('Temperature: 99'), findsNothing);
    expect(find.text('Show weather'), findsOneWidget);
  });
  testWidgets(
      'remote discovery requires explicit tap and ignores a stale response',
      (tester) async {
    final api = WeatherApi()..more = Completer<dynamic>();
    await open(tester, api);
    await tester.enterText(find.byType(TextField), 'Missing locality');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Find more Malaysian locations'));
    await tester.pump();
    expect(api.queries.last, {'q': 'Missing locality', 'remote': 'true'});
    await tester.enterText(find.byType(TextField), 'Different');
    await tester.pump();
    api.more!.complete({
      'results': [alma]
    });
    await tester.pumpAndSettle();
    expect(find.text('Alma, Penang, Malaysia'), findsNothing);
    expect(api.calls.where((p) => p.endsWith('/search')).length, 1);
  });
}
