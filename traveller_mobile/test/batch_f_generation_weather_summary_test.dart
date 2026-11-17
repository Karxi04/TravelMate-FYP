import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';
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
  WeatherApi({this.catalogue = const [alma, sabah, kk]});
  final List<Map<String, dynamic>> catalogue;
  Map<String, dynamic> forecastData = {
    'current': {'temperature_2m': 30}
  };
  Completer<dynamic>? forecast;
  Completer<dynamic>? more;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    calls.add(path);
    queries.add({...?query});
    if (path == '/api/fr6/locations') return {'results': catalogue};
    if (path == '/api/fr6/locations/search')
      return more?.future ?? {'results': []};
    if (path == '/api/fr6/weather')
      return forecast?.future ?? {'weather': forecastData};
    throw StateError('Unexpected request');
  }
}

Future<void> open(WidgetTester tester, WeatherApi api) async {
  await tester.pumpWidget(MaterialApp(home: WeatherScreen(api: api)));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
      'independent applicable ticket products retain distinct costs at one venue',
      () {
    Map<String, dynamic> ticket(String product, int cost) =>
        place('Venue', 'same', {
          'unitPrice': cost,
          'estimatedCost': cost,
          'costProvenance': 'verified_ticket',
          'pricingUnit': 'per_person',
          'priceSourceUrl': 'https://example.test/tickets',
          'priceVerifiedAt': '2026-11-17',
          'pricingEvidence': {
            'applicability': 'applicable',
            'ticketProductId': product
          }
        });
    final a = ticket('entry', 10),
        b = {...ticket('independent', 20), 'independentSubAttraction': true};
    expect(consolidateGeneratedCandidates([a, b]).length, 2);
    expect(
        consolidateGeneratedCandidates([a, Map<String, dynamic>.from(a)])
            .length,
        1);
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
    expect(find.text('Choose a locality in Sabah'), findsOneWidget);
    expect(api.calls.where((p) => p.endsWith('/weather')), isEmpty);
    await tester.tap(find.text('Kota Kinabalu, Sabah, Malaysia').hitTestable());
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show weather'));
    await tester.pumpAndSettle();
    expect(api.queries.last['locationId'], kk['id']);
  });
  testWidgets('forecast uses the correct date dash and Celsius symbols',
      (tester) async {
    final api = WeatherApi()
      ..forecastData = {
        'timezone_abbreviation': '+08',
        'current': {
          'time': '2026-11-17T15:15',
          'wind_speed_10m': 9,
          'precipitation': 2
        },
        'current_units': {'wind_speed_10m': 'km/h', 'precipitation': 'mm'},
        'daily': {
          'time': ['2026-11-17'],
          'weather_code': [61],
          'temperature_2m_min': [24.3],
          'temperature_2m_max': [30.7],
          'precipitation_probability_max': [85],
        },
      };
    await open(tester, api);
    expect(find.text('Choose a Malaysian city or locality.'), findsOneWidget);
    expect(find.textContaining('Open-Meteo'), findsNothing);
    await tester.enterText(find.byType(TextField), 'Alma');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Alma, Penang, Malaysia'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show weather'));
    await tester.pumpAndSettle();
    expect(find.text('2026-11-17 \u2014 Rain or showers'), findsOneWidget);
    expect(find.text('Low: 24.3 \u00b0C'), findsOneWidget);
    expect(find.text('High: 30.7 \u00b0C'), findsOneWidget);
    expect(find.text('Rain probability: 85%'), findsOneWidget);
    expect(find.text('Wind: 9 km/h'), findsOneWidget);
    expect(find.text('Precipitation: 2 mm'), findsOneWidget);
    expect(find.text('Updated: 2026-11-17T15:15 +08'), findsOneWidget);
  });

  for (final region in [
    'Johor',
    'Kedah',
    'Kelantan',
    'Melaka',
    'Negeri Sembilan',
    'Pahang',
    'Penang',
    'Perak',
    'Perlis',
    'Sabah',
    'Sarawak',
    'Selangor',
    'Terengganu',
    'Kuala Lumpur',
    'Putrajaya',
    'Labuan',
  ]) {
    testWidgets('exact $region leads to a verified locality choice',
        (tester) async {
      final geography = await tester.runAsync(MalaysiaWeather.load);
      final actual = geography!.catalogue;
      final points = actual.where((row) => row['admin1'] == region).toList();
      final api = WeatherApi(catalogue: [
        ...points,
        {
          'name': region,
          'label': 'Unrelated match',
          'admin1': 'Other',
          'country': 'Malaysia',
          'population': 99999999
        },
        {
          'name': region,
          'label': 'Foreign match',
          'admin1': region,
          'country': 'Other'
        },
      ]);
      await open(tester, api);
      await tester.enterText(
          find.byType(TextField), region == 'Penang' ? 'Pulau Pinang' : region);
      await tester.pumpAndSettle();
      expect(find.text('Unrelated match'), findsNothing);
      expect(find.text('Foreign match'), findsNothing);
      final stateOption = find.text('$region, Malaysia');
      expect(stateOption, findsOneWidget);
      await tester.tap(stateOption);
      await tester.pumpAndSettle();
      expect(find.text('Choose a locality in $region'), findsOneWidget);
      expect(api.calls, ['/api/fr6/locations']);
      final list = find.byType(ListView).last;
      final choice =
          find.descendant(of: list, matching: find.byType(ListTile)).first;
      final label = (tester.widget<ListTile>(choice).title as Text).data;
      final point = points.firstWhere(
          (row) => row['label'] == label && row['requiresCity'] != true);
      await tester.tap(choice);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Show weather'));
      await tester.pumpAndSettle();
      expect(api.queries.last['locationId'], point['id']);
      expect(api.queries.last['locationName'], label);
      expect(find.text('Something went wrong'), findsNothing);
    });
  }

  test(
      'F02 merges separated hill pins and aliases while retaining a separate viewpoint',
      () {
    final rows = [
      place('Penang Hill', 'summit'),
      place('Bukit Bendera', 'alias', {
        'gps_coordinates': {'latitude': 5.40846, 'longitude': 100.27733}
      }),
      place('Penang Hill Lower Station', 'station', {
        'gps_coordinates': {'latitude': 5.40846, 'longitude': 100.27733}
      }),
      place('Penang Hill Viewing Area', 'viewpoint',
          {'independentSubAttraction': true}),
      place('Bukit Bendera', 'repeat', {'intentionalRepeat': true}),
    ];
    final result = consolidateGeneratedCandidates(rows);
    expect(result.map((row) => row['destinationId']),
        ['summit', 'viewpoint', 'repeat']);
    expect(result.first['supportingAccess'].single['destinationId'], 'station');
  });

  test(
      'F09 through F11 select richer coherent prose and recognise sparse categories',
      () {
    final summary = destinationSummary({
      'description': 'Scenic attraction.',
      'editorial_summary': {
        'overview': 'A hill resort above George Town.',
        'details':
            'Its forest trails connect parts of the hill. The funicular links the stations. The upper station has a viewing deck.'
      },
    });
    expect(summary['text'],
        'A hill resort above George Town. Its forest trails connect parts of the hill. The funicular links the stations.');
    expect(summary['additionalText'], 'The upper station has a viewing deck.');
    expect(
        destinationSummary(
            {'title': 'Town Lookout', 'type': 'Scenic spot'})['text'],
        'Town Lookout is listed as a scenic spot.');
    expect(
        destinationSummary({
          'metadataConflict': true,
          'description': 'Conflicting description.'
        })['text'],
        contains('unavailable'));
  });

  test(
      'standalone personalised generation saves only one Hill visit and its unit cost',
      () async {
    final rows = [
      place('Penang Hill', 'summit', {
        'estimatedCost': 12,
        'unitPrice': 12,
        'pricingUnit': 'per_person',
        'costProvenance': 'catalog_estimate'
      }),
      place('Bukit Bendera', 'base-pin', {
        'estimatedCost': 12,
        'gps_coordinates': {'latitude': 5.40846, 'longitude': 100.27733}
      }),
      place('Penang Hill Lower Station', 'station'),
      place('Penang Hill Viewing Area', 'viewpoint',
          {'independentSubAttraction': true}),
    ];
    final snapshot = {
      'travellerId': 'f1',
      'recommendationGenerationId': 'rec-hill',
      'requestedDestination': 'Penang',
      'recommendationResults': rows
    };
    final encoded = jsonEncode([snapshot]);
    final memory = {'travelmate_f1_recommendation_snapshots': encoded};
    final service =
        StandaloneApiService(uidOverride: 'f1', memoryStore: memory);
    final response = await http.runWithClient(
        () => service.post('/api/fr5/personalised-trips/generate', {
              'title': 'Penang visit',
              'destinationArea': 'Penang',
              'startDate': '2027-01-10',
              'endDate': '2027-01-12',
              'travellerCount': 2,
              'budgetLimit': 1000,
              'recommendationGenerationId': 'rec-hill',
              'generationRequestId': 'f1-standalone-generation',
            }),
        () => MockClient((_) async => http.Response('{}', 503)));
    expect(response['ok'], isTrue, reason: response.toString());
    final saved = (await service.get(
        '/api/fr5/itineraries/' + response['tripId'].toString()))['itinerary'];
    final activities = (saved['activities'] as List).cast<Map>();
    expect(activities.map((row) => row['destinationId']).toSet(),
        {'summit', 'viewpoint'});
    final hill =
        activities.firstWhere((row) => row['destinationId'] == 'summit');
    expect(hill['supportingAccess'].single['destinationId'], 'station');
    expect(hill['unitPrice'], 12);
    expect(hill['pricingUnit'], 'per_person');
    expect(memory['travelmate_f1_recommendation_snapshots'], encoded);
  });

  testWidgets(
      'empty forecast remains an unavailable state for the selected point',
      (tester) async {
    final api = WeatherApi()..forecastData = {};
    await open(tester, api);
    await tester.enterText(find.byType(TextField), 'Alma');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Alma, Penang, Malaysia'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Show weather'));
    await tester.pumpAndSettle();
    expect(
        find.text(
            'No weather observations or forecast are available for this location.'),
        findsOneWidget);
    expect(find.textContaining('Temperature:'), findsNothing);
    expect(api.queries.last['locationId'], alma['id']);
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
