import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/review_contract.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/explore_tab.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/modules/fr06_weather_forecast/weather_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/room_offer_photo.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';

class AllApi extends ApiService {
  final posts = <String>[];
  final bodies = <Map<String, dynamic>>[];
  final gets = <String>[];
  final queries = <Map<String, String>>[];
  Completer<dynamic>? delayedWeather;
  Map<String, dynamic> forecast = {'current': {'temperature_2m': 29, 'apparent_temperature': 32, 'weather_code': 2, 'time': '2030-01-01T12:00'},
    'current_units': {'temperature_2m': '°C', 'apparent_temperature': '°C'},
    'daily': {'time': ['2030-01-01'], 'temperature_2m_min': [25], 'temperature_2m_max': [32], 'precipitation_probability_max': [40], 'weather_code': [61]}};
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    gets.add(path); queries.add({...?query});
    if (path == '/api/fr3/favourites' || path == '/api/fr11/sessions') return {'items': []};
    if (path == '/api/fr6/locations/search') return {'results': [{'name': 'George Town', 'admin1': 'Penang', 'country': 'Malaysia', 'latitude': 5.4, 'longitude': 100.2}]};
    if (path == '/api/fr6/weather') return delayedWeather?.future ?? Future.value({'weather': forecast});
    if (path == '/api/fr3/destinations/search') return {'results': [
      {'destinationId': 'one', 'title': 'Temple one'},
      {'destinationId': query?['offset'] == '20' ? 'three' : 'two', 'title': query?['offset'] == '20' ? 'Temple three' : 'Temple two'}],
      if (query?['offset'] == null) 'nextOffset': 20};
    if (path == '/api/fr3/destinations/one') return {'destination': {'destinationId': 'one', 'title': 'Temple one', 'description': 'A genuine provider description.', 'category': 'Temple', 'highlights': ['Wheelchair access']}, 'source': 'serpapi'};
    return {'items': [], 'result': {}};
  }
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posts.add(path); bodies.add({...?body});
    if (path == '/api/fr8/hotels/search') return {'items': [{'hotelId': 'h${body?['offset']}', 'offerId': 'o${body?['offset']}', 'name': 'Hotel', 'roomName': 'Room', 'price': 200, 'currency': 'MYR'}], 'source': 'liteapi', if (body?['offset'] == 0) 'nextOffset': 50};
    if (path == '/api/fr11/save-plan') return {'itinerary': {'id': 'trip', 'title': 'Draft'}};
    return {'session': {'id': 's', 'messages': []}};
  }
}
Future<void> frame(WidgetTester tester, Widget child, {double width = 430, double scale = 1}) async {
  tester.view.physicalSize = Size(width, 950); tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = scale;
  addTearDown(() { tester.view.resetPhysicalSize(); tester.view.resetDevicePixelRatio(); tester.platformDispatcher.clearTextScaleFactorTestValue(); });
  await tester.pumpWidget(MaterialApp(home: child)); await tester.pumpAndSettle();
}

void main() {
  for (final width in [320.0, 360.0, 430.0]) {
    testWidgets('hotel dates and guest controls fit $width at larger text', (tester) async {
      await frame(tester, HotelScreen(api: AllApi()), width: width, scale: 1.2);
      expect(tester.takeException(), isNull);
      final dynamic state = tester.state(find.byType(HotelScreen)); state.addRoom();
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('Room 2'), 250, scrollable: find.byType(Scrollable).first);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('flight cabin fits a narrow phone', (tester) async {
    await frame(tester, FlightScreen(api: AllApi()), width: 320, scale: 1.2);
    expect(tester.takeException(), isNull);
  });
  testWidgets('hotel name and pagination preserve query and invalidate on edit', (tester) async {
    final api = AllApi(); await frame(tester, HotelScreen(api: api, initialDestination: 'Penang'), width: 430);
    final dynamic state = tester.state(find.byType(HotelScreen)); state.hotelName.text = 'Heritage';
    await state.search(); await tester.pumpAndSettle();
    expect(api.bodies.first['hotelName'], 'Heritage'); expect(api.bodies.first['currency'], 'MYR');
    await state.search(loadMore: true); await tester.pumpAndSettle();
    expect(api.bodies.last['offset'], 50); expect(state.items.length, 2);
    state.hotelName.text = 'Other'; await tester.pumpAndSettle(); expect(state.items, isEmpty);
  });
  testWidgets('weather requires a selected location then displays actual optional fields', (tester) async {
    final api = AllApi(); await frame(tester, WeatherScreen(api: api));
    final dynamic state = tester.state(find.byType(WeatherScreen)); await state.search(); await tester.pumpAndSettle();
    expect(api.gets, isEmpty);
    await tester.enterText(find.byType(TextField), 'George'); await tester.pump(const Duration(milliseconds: 350)); await tester.pumpAndSettle();
    await tester.tap(find.text('George Town, Penang, Malaysia')); await tester.pumpAndSettle();
    await tester.tap(find.text('Show weather')); await tester.pumpAndSettle();
    expect(find.textContaining('Feels like: 32'), findsOneWidget); expect(find.textContaining('Humidity:'), findsNothing);
    expect(find.textContaining('Rain probability: 40%'), findsOneWidget);
  });
  testWidgets('weather discards an old response when location is edited', (tester) async {
    final api = AllApi()..delayedWeather = Completer<dynamic>(); await frame(tester, WeatherScreen(api: api));
    await tester.enterText(find.byType(TextField), 'George'); await tester.pump(const Duration(milliseconds: 350)); await tester.pumpAndSettle();
    await tester.tap(find.text('George Town, Penang, Malaysia')); await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(WeatherScreen)); final request = state.search();
    state.place.text = 'Different'; api.delayedWeather!.complete({'weather': api.forecast}); await request; await tester.pumpAndSettle();
    expect(state.weather, isNull);
  });
  testWidgets('Explore Load More deduplicates while preserving destination identity', (tester) async {
    final api = AllApi(); await frame(tester, ExploreTab(api: api, initialQuery: 'temple'), width: 1200);
    final dynamic state = tester.state(find.byType(ExploreTab));
    expect(state.results.length, 2);
    final more = find.widgetWithText(OutlinedButton, 'Load more places');
    await tester.scrollUntilVisible(more, 180, scrollable: find.byType(Scrollable).first);
    await tester.pumpAndSettle();
    await tester.tap(more.hitTestable());
    await tester.pumpAndSettle();
    expect(state.results.length, 3); expect(state.results.map((e) => e['destinationId']).toSet().length, 3);
    expect(api.queries.any((q) => q['offset'] == '20'), isTrue);
  });
  testWidgets('About displays real description and returned highlights', (tester) async {
    await frame(tester, DestinationDetailsScreen(api: AllApi(), initialDestination: const {'destinationId': 'one', 'title': 'Temple one'}));
    await tester.scrollUntilVisible(find.text('A genuine provider description.'), 250, scrollable: find.byType(Scrollable).first);
    expect(find.textContaining('Wheelchair access'), findsOneWidget);
  });
  testWidgets('a property image is not presented as a room image', (tester) async {
    await frame(tester, const Scaffold(body: RoomOfferPhoto(offer: {'mainPhoto': 'https://cdn.example/property.jpg', 'roomName': 'Suite'})));
    expect(find.byType(Image), findsNothing); expect(find.text('Room photo unavailable'), findsOneWidget);
  });
  testWidgets('a broken genuine room image shows neutral fallback', (tester) async {
    await frame(tester, const Scaffold(body: RoomOfferPhoto(offer: {'roomImageUrls': ['https://cdn.example/room.jpg'], 'roomName': 'Suite'})));
    expect(find.text('Room photo unavailable'), findsOneWidget);
  });
  test('star ratings express sentiment without changing storage', () {
    expect(ReviewContract.sentiment(1), 'Negative / poor');
    expect(ReviewContract.sentiment(3), 'Neutral / moderate');
    expect(ReviewContract.sentiment(5), 'Positive / good');
  });
  testWidgets('chat requests guided planning and saves only after confirmation', (tester) async {
    final api = AllApi(); await frame(tester, ChatTab(api: api), width: 430);
    final dynamic state = tester.state(find.byType(ChatTab)); await state.send('Plan my trip'); await tester.pumpAndSettle();
    expect(api.bodies.first['guidedPlanning'], isTrue);
    final plan = {'title': 'Draft', 'destinationArea': 'Penang', 'startDate': '2030-12-12', 'endDate': '2030-12-12',
      'budgetLimit': 100, 'activities': [{'destinationId': 'place', 'activityName': 'Selected place', 'dayNo': 1}]};
    final cancel = state.savePlan(plan); await tester.pumpAndSettle();
    expect(api.posts.where((p) => p.endsWith('save-plan')), isEmpty);
    await tester.tap(find.text('Keep editing')); await tester.pumpAndSettle(); await cancel;
    expect(api.posts.where((p) => p.endsWith('save-plan')), isEmpty);
    final save = state.savePlan(plan); await tester.pumpAndSettle();
    await tester.tap(find.text('Confirm save')); await tester.pumpAndSettle(); await save;
    expect(api.posts.where((p) => p.endsWith('save-plan')).length, 1); expect(api.bodies.last['confirmed'], isTrue);
  });
}
