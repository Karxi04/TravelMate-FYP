import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class ItineraryApi extends ApiService {
  Map<String, dynamic>? created;
  bool selected = false;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr5/itineraries') return {'items': []};
    return {
      'searchId': 'owned',
      'source': 'serpapi',
      'items': [
        {
          'optionId': 'option',
          'airline': 'Fixture',
          'flightNumber': 'F1',
          'arrivalAirport': 'PEN',
          'outboundDate': '2027-11-09',
          'price': 190,
          'currency': 'MYR',
          'checkoutEligible': true,
          'priceBasis': 'single_adult_whole_one_way_itinerary'
        }
      ]
    };
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr5/itineraries') {
      created = body;
      return {
        'itinerary': {'id': 'trip', 'title': body!['title']}
      };
    }
    if (path == '/api/fr7/flights/select') selected = true;
    return {};
  }
}

void main() {
  testWidgets('flight creates valid destination itinerary before attachment',
      (tester) async {
    tester.view.physicalSize = const Size(1080, 2424);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = ItineraryApi();
    await tester.pumpWidget(MaterialApp(
        home: FlightScreen(api: api, initialOutboundDate: '2027-11-09')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Search flights'));
    await tester.tap(find.text('Search flights'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Select'));
    await tester.tap(find.text('Select'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Create Itinerary'));
    await tester.pumpAndSettle();
    expect(api.created!['destinationArea'], 'PEN');
    expect(api.created!['startDate'], '2027-11-09');
    expect(api.created!['travellerCount'], 1);
    expect(api.selected, isTrue);
  });
}
