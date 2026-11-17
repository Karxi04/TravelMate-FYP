import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/explore_tab.dart';
import 'package:travelmate_traveller/modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'chat_action_audit_test.dart' show frame, tap;
import 'location_chat_reliability_test.dart' show LocationApi;
import 'malaysia_location_coverage_test.dart' show source, dto;

final sourceAlma = (source['places'] as List)
    .firstWhere((r) => r['name'] == 'Alma' && r['state'] == 'Penang') as Map;
final alma = {
  ...dto(sourceAlma),
  'latitude': sourceAlma['latitude'],
  'longitude': sourceAlma['longitude'],
  'coordinateStatus': 'verified_locality'
};
final nearbyPlace = <String, dynamic>{
  'destinationId': 'nearby_fixture',
  'title': 'Recorded nearby attraction',
  'city': 'Bukit Mertajam',
  'address': 'Bukit Mertajam, Penang, Malaysia',
  'type': 'Culture',
  'discoveryEligible': true,
  'discoveryMatchedConcepts': ['culture'],
  'destinationConcepts': ['culture'],
  'finalScore': 70,
  'nearbyDistanceKm': 1.2
};

class NearbyRecommendationApi extends LocationApi {
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr4/locations')
      return {
        'locations': [alma]
      };
    return super.get(path, query);
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr4/recommendations/generate') {
      pool.clear();
      if (body?['geographicMode'] == 'nearby') pool.add({...nearbyPlace});
      final data = await super.post(path, body);
      data['snapshot']['canonicalDestinationScope'] = {
        ...alma,
        if (body?['geographicMode'] == 'nearby') ...{
          'geographicMode': 'nearby',
          'originScopeKey': alma['scopeKey'],
          'scopeKey': '${alma['scopeKey']}:nearby:10km'
        }
      };
      data['snapshot']['nearbyAvailable'] = true;
      data['snapshot']['searchMessage'] =
          'No attractions could be verified within this exact locality.';
      return data;
    }
    return super.post(path, body);
  }
}

class NearbyExploreApi extends ApiService {
  final searches = <Map<String, String>>[];
  bool fail = false;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr3/favourites') return {'items': []};
    if (path == '/api/fr3/destinations/search') {
      searches.add({...?query});
      if (fail)
        throw const ApiException('Place search is temporarily unavailable.',
            502, {'code': 'destination_provider_unavailable'});
      final nearby = query?['geographicMode'] == 'nearby';
      return {
        'ok': true,
        'results': nearby
            ? [
                {...nearbyPlace}
              ]
            : [],
        'source': 'serpapi',
        'searchStatus': nearby ? 'matches' : 'no_exact_locality_matches',
        'searchMessage':
            'Places were returned, but none could be verified within this exact locality.',
        'canonicalDestinationScope': alma,
        'nearbyAvailable': true,
        'locationUsed': alma['canonicalName'],
        'queryInterpretation': 'locality'
      };
    }
    return {'ok': true, 'items': []};
  }
}

void main() {
  testWidgets(
      'Alma strict search and explicit nearby search remain separate, preserving postal city',
      (tester) async {
    final api = NearbyRecommendationApi();
    await frame(tester, RecommendationScreen(api: api));
    await tester.enterText(find.byType(TextField).first, 'Alma');
    await tester.pumpAndSettle();
    expect(api.generatedBodies, isEmpty);
    await tap(tester, find.text('Alma, Penang, Malaysia'));
    expect(api.generatedBodies, isEmpty);
    await tap(tester, find.text('Refresh for you'));
    expect(api.generatedBodies, hasLength(1));
    expect(api.generatedBodies.single.containsKey('geographicMode'), isFalse);
    expect(find.textContaining('within this exact locality'), findsOneWidget);
    await tap(tester, find.text('Explore nearby places (10 km)'));
    expect(api.generatedBodies, hasLength(2));
    expect(api.generatedBodies.last['geographicMode'], 'nearby');
    expect(api.generatedBodies.last['destinationScopeKey'], alma['scopeKey']);
    expect(
        api.generatedBodies.last.containsKey('previousGenerationId'), isFalse);
    expect(find.text('Nearby · Bukit Mertajam · 1.2 km straight-line'),
        findsOneWidget);
    await tap(tester, find.text('Search exact locality'));
    expect(api.generatedBodies, hasLength(3));
    expect(api.generatedBodies.last.containsKey('geographicMode'), isFalse);
  });
  testWidgets(
      'Explore explains strict rejection and nearby action sends one explicit search',
      (tester) async {
    final api = NearbyExploreApi();
    await frame(tester, ExploreTab(api: api));
    await tester.enterText(find.byType(TextField).first, 'Alma');
    await tester.pumpAndSettle();
    expect(api.searches, isEmpty);
    await tap(tester, find.text('Search places'));
    expect(api.searches, hasLength(1));
    expect(api.searches.single.containsKey('geographicMode'), isFalse);
    expect(find.text('No verified matches in this locality'), findsOneWidget);
    await tap(tester, find.text('Explore nearby places (10 km)'));
    expect(api.searches, hasLength(2));
    expect(api.searches.last['geographicMode'], 'nearby');
    expect(api.searches.last['location'], alma['canonicalName']);
    expect(api.searches.last['q'], 'tourist attractions');
    expect(find.text('Nearby · Bukit Mertajam · 1.2 km straight-line'),
        findsOneWidget);
  });
  testWidgets(
      'Explore provider outage stays an error rather than an empty result',
      (tester) async {
    final api = NearbyExploreApi()..fail = true;
    await frame(tester, ExploreTab(api: api));
    await tester.enterText(find.byType(TextField).first, 'Alma');
    await tester.pumpAndSettle();
    await tap(tester, find.text('Search places'));
    expect(find.text('Places couldn’t be loaded'), findsOneWidget);
    expect(find.text('No places found'), findsNothing);
    expect(api.searches, hasLength(1));
  });
}
