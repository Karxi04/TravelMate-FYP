import 'package:flutter_test/flutter_test.dart';

import '../lib/services/standalone_api_service.dart';

void main() {
  test('standalone flight sample is explicit and selection survives remove',
      () async {
    final service = StandaloneApiService(uidOverride: 'pu3a', memoryStore: {});
    final search = await service.get('/api/fr7/flights/search', {
      'departure_id': 'KUL',
      'arrival_id': 'PEN',
      'outbound_date': '2026-11-01',
      'traveller_count': '2',
    }) as Map<String, dynamic>;
    expect(search['source'], 'sample_fixture');
    expect(search['sourceLabel'], contains('not a current schedule'));
    final flight =
        Map<String, dynamic>.from((search['items'] as List).first as Map);

    final created = await service.post('/api/fr5/itineraries', {
      'title': 'PU-3A Penang',
      'destinationArea': 'Penang, Malaysia',
      'startDate': '2026-11-01',
      'endDate': '2026-11-04',
      'travellerCount': 2,
      'budgetLimit': 2000,
    }) as Map<String, dynamic>;
    final id = (created['id'] ?? created['itinerary']['id']).toString();
    final selected = await service.post('/api/fr7/flights/select', {
      'itineraryId': id,
      'flight': flight,
    }) as Map<String, dynamic>;
    expect(selected['itinerary']['flightPriceBasis'], 'sample_itinerary_total');
    expect(selected['budget']['flight'], greaterThan(0));

    final removed =
        await service.post('/api/fr7/itineraries/$id/flight-selection/remove')
            as Map<String, dynamic>;
    expect(removed['itinerary']['selectedFlight'], isNull);
    expect(removed['itinerary']['selectedHotel'], isNull);
  });

  test('standalone flight adjustment previews before idempotent apply',
      () async {
    final service = StandaloneApiService(
      uidOverride: 'pu3b',
      memoryStore: {},
    );
    final created = await service.post('/api/fr5/itineraries', {
      'title': 'PU-3B Penang',
      'destinationArea': 'Penang, Malaysia',
      'startDate': '2026-11-01',
      'endDate': '2026-11-04',
      'travellerCount': 1,
      'budgetLimit': 2000,
    }) as Map<String, dynamic>;
    final id = (created['id'] ?? created['itinerary']['id']).toString();
    final search = await service.get('/api/fr7/flights/search', {
      'departure_id': 'KUL',
      'arrival_id': 'PEN',
      'outbound_date': '2026-11-01',
      'traveller_count': '1',
    }) as Map<String, dynamic>;
    await service.post('/api/fr7/flights/select', {
      'itineraryId': id,
      'flight':
          Map<String, dynamic>.from((search['items'] as List).first as Map),
    });

    final preview = await service.post(
      '/api/fr5/itineraries/$id/flight-adjustment/preview',
    ) as Map<String, dynamic>;
    final previewId = (preview['preview']['previewId']).toString();
    expect(preview['preview']['canApply'], isTrue);
    final before =
        await service.get('/api/fr5/itineraries') as Map<String, dynamic>;
    final beforeTrip =
        (before['items'] as List).firstWhere((item) => item['id'] == id);
    expect(beforeTrip['flightAdjustmentStatus'], isNull);

    final first = await service.post(
      '/api/fr5/itineraries/$id/flight-adjustment/apply',
      {'previewId': previewId},
    ) as Map<String, dynamic>;
    final second = await service.post(
      '/api/fr5/itineraries/$id/flight-adjustment/apply',
      {'previewId': previewId},
    ) as Map<String, dynamic>;
    expect(first['itinerary']['flightAdjustmentStatus'], 'applied');
    expect(second['idempotent'], isTrue);
  });
}
