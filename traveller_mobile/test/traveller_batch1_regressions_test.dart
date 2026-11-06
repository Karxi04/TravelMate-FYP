import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/favourites_controller.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/explore_tab.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_airport_catalog.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

const place = <String, dynamic>{'destinationId': 'place', 'title': 'Temple'};
class BatchApi extends ApiService {
  final records = <Map<String, dynamic>>[];
  final queries = <Map<String, String>>[];
  final posts = <String>[];
  final bodies = <Map<String, dynamic>>[];
  bool showTargetTrip = false;
  final trip = <String, dynamic>{'id': 'target', 'title': 'Original trip', 'destinationArea': 'Penang', 'startDate': '2030-01-01', 'endDate': '2030-01-03', 'adults': 2, 'activities': <dynamic>[], 'selectedHotel': {'name': 'Old hotel'}, 'budgetLimit': 1000};
  bool failWrite = false;
  bool failRead = false;
  bool failFlights = false;
  Completer<void>? holdWrite;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr3/favourites') {
      if (failRead) throw const ApiException('Offline', 503, {});
      return {'items': records.map((e) => Map<String, dynamic>.from(e)).toList()};
    }
    if (path == '/api/fr7/flights/search') {
      queries.add({...?query});
      if (failFlights) throw const ApiException('Flight provider is unavailable. Try again later.', 502, {});
      return {'items': [], 'searchId': 'search'};
    }
    if (path == '/api/fr5/itineraries/target') return {'itinerary': {...trip}};
    if (path == '/api/fr5/itineraries') return {'items': showTargetTrip ? [{...trip}] : [{'id': 'other', 'title': 'Other trip'}]};
    if (path == '/api/fr3/destinations/search') return {'results': [place]};
    if (path == '/api/fr3/destinations/place') return {'destination': place};
    return {'items': [], 'result': {}};
  }
  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posts.add(path); bodies.add({...?body});
    if (holdWrite != null) await holdWrite!.future;
    if (failWrite) throw const ApiException('Save failed', 503, {});
    if (path == '/api/fr3/favourites') {
      records.removeWhere((e) => e['destinationId'] == body!['destinationId']);
      records.add({...body!, 'id': 'owner_place'});
    }
    if (path == '/api/fr8/hotels/book' && body?['itineraryId'] == 'target') { trip['selectedHotel'] = body!['selectedHotel']; trip['hotelBookingId'] = 'record'; }
    return {'ok': true, 'booking': {'id': 'record', 'itineraryAttachmentStatus': 'succeeded'}};
  }
  @override
  Future<dynamic> delete(String path) async {
    if (failWrite) throw const ApiException('Remove failed', 503, {});
    records.removeWhere((e) => path.endsWith('/${e['id']}'));
    return {'ok': true};
  }
}

Future<void> frame(WidgetTester tester, Widget child) async {
  tester.view.physicalSize = const Size(1200, 1600); tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(home: child)); await tester.pumpAndSettle();
}
Future<void> flush() async { await Future<void>.delayed(Duration.zero); }

void main() {
  test('persisted add/remove/add synchronizes controllers and reopening', () async {
    final api = BatchApi(); final explore = FavouritesController(api); final details = FavouritesController(api);
    addTearDown(explore.dispose); addTearDown(details.dispose); await flush();
    await explore.toggle(place); await flush(); expect(details.contains('place'), isTrue);
    await details.toggle(place); await flush(); expect(explore.contains('place'), isFalse);
    await explore.toggle(place); expect(api.records.length, 1);
    final reopened = FavouritesController(api); addTearDown(reopened.dispose); await flush();
    expect(reopened.contains('place'), isTrue);
  });
  test('failed mutations keep persisted state and separate account state', () async {
    final api = BatchApi(); final state = FavouritesController(api); final other = FavouritesController(BatchApi());
    addTearDown(state.dispose); addTearDown(other.dispose); await flush();
    api.failWrite = true; await expectLater(state.toggle(place), throwsA(isA<ApiException>()));
    expect(state.contains('place'), isFalse);
    api.failWrite = false; await state.toggle(place); await flush(); expect(other.contains('place'), isFalse);
    api.failWrite = true; await expectLater(state.toggle(place), throwsA(isA<ApiException>()));
    expect(state.contains('place'), isTrue);
  });
  test('pending save cannot be duplicated or falsely shown as saved', () async {
    final api = BatchApi()..holdWrite = Completer<void>(); final state = FavouritesController(api);
    addTearDown(state.dispose); await flush(); final write = state.toggle(place);
    await state.toggle(place); expect(api.posts.length, 1); expect(state.contains('place'), isFalse);
    api.holdWrite!.complete(); await write; expect(state.contains('place'), isTrue);
  });
  test('failed initial read blocks writes until retry', () async {
    final api = BatchApi()..failRead = true; final state = FavouritesController(api); addTearDown(state.dispose);
    await flush(); await expectLater(state.toggle(place), throwsA(isA<ApiException>())); expect(api.posts, isEmpty);
    api.failRead = false; await state.load(); await state.toggle(place); expect(state.contains('place'), isTrue);
  });
  testWidgets('Explore heart toggles and removal from Favourites updates Explore', (tester) async {
    final api = BatchApi(); await frame(tester, ExploreTab(api: api, initialQuery: 'temple'));
    final heart = find.byKey(const ValueKey('destination-save-place'));
    await tester.ensureVisible(heart); await tester.tap(heart); await tester.pumpAndSettle();
    expect(tester.widget<Icon>(find.byIcon(Icons.favorite_rounded)).color, Colors.red);
    await tester.tap(heart); await tester.pumpAndSettle(); expect(api.records, isEmpty);
    await tester.tap(heart); await tester.pumpAndSettle(); expect(api.records.length, 1);
    await tester.tap(find.byTooltip('Saved destinations')); await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Remove favourite')); await tester.pumpAndSettle();
    await tester.pageBack(); await tester.pumpAndSettle(); expect(find.byIcon(Icons.favorite_rounded), findsNothing);
  });
  testWidgets('Details loads saved heart and supports removal', (tester) async {
    final api = BatchApi()..records.add({...place, 'id': 'owner_place'});
    await frame(tester, DestinationDetailsScreen(api: api, initialDestination: place));
    expect(find.text('Saved'), findsOneWidget);
    await tester.tap(find.text('Saved')); await tester.pumpAndSettle(); expect(api.records, isEmpty);
    await tester.tap(find.text('Save')); await tester.pumpAndSettle(); expect(api.records.length, 1);
  });
  for (final value in ['', 'ZZZ', '123', 'KU', 'random Penang text', 'PEN']) {
    testWidgets('invalid origin "$value" prevents flight request', (tester) async {
      final api = BatchApi(); await frame(tester, FlightScreen(api: api));
      final dynamic state = tester.state(find.byType(FlightScreen)); state.from.text = value;
      await state.search(); await tester.pumpAndSettle(); expect(api.queries, isEmpty);
    });
  }
  testWidgets('airport suggestions select codes and valid MYR searches stay intact', (tester) async {
    final api = BatchApi(); await frame(tester, FlightScreen(api: api));
    final from = find.widgetWithText(TextField, 'KUL'); await tester.enterText(from, 'Kuala'); await tester.pumpAndSettle();
    await tester.tap(find.text('${flightAirportLabels['KUL']} (KUL)')); await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(FlightScreen)); expect(state.from.text, 'KUL');
    await state.search(); expect(api.queries.single['currency'], 'MYR');
    state.roundTrip = true; await state.search(); expect(api.queries.last['return_date'], isNotNull);
  });
  testWidgets('past dates, reversed returns and passenger errors prevent requests', (tester) async {
    final api = BatchApi(); await frame(tester, FlightScreen(api: api)); final dynamic state = tester.state(find.byType(FlightScreen));
    state.outbound.text = '2000-01-01'; await state.search(); expect(api.queries, isEmpty);
    state.outbound.text = '2030-02-30'; await state.search(); expect(api.queries, isEmpty);
    state.outbound.text = '2030-02-01'; state.roundTrip = true; state.returnDate.text = '2030-01-01'; await state.search();
    expect(api.queries, isEmpty); state.roundTrip = false; state.travellers.text = '1.5'; await state.search(); expect(api.queries, isEmpty);
  });
  testWidgets('hotel replacement pins the correct trip and saves details only', (tester) async {
    final api = BatchApi(); await frame(tester, HotelScreen(api: api, targetTripId: 'target'));
    final dynamic state = tester.state(find.byType(HotelScreen));
    expect((await state.chooseItinerary())['id'], 'target');
    final save = state.completeBooking({'name': 'New hotel', 'price': 200}, 'validation', 'liteapi', 'attempt');
    await tester.pumpAndSettle(); await tester.tap(find.widgetWithText(FilledButton, 'Confirm & Save Hotel Details'));
    await tester.pumpAndSettle(); await save;
    expect(api.bodies.single['itineraryId'], 'target'); expect(api.bodies.single['saveDetailsOnly'], isTrue);
    expect(api.posts, ['/api/fr8/hotels/book']);
  });
  testWidgets('cancelling trip attachment creates no hotel record', (tester) async {
    final api = BatchApi(); await frame(tester, HotelScreen(api: api)); final dynamic state = tester.state(find.byType(HotelScreen));
    final save = state.completeBooking({'name': 'New hotel', 'price': 200}, 'validation', 'liteapi', 'attempt');
    await tester.pumpAndSettle(); await tester.tap(find.widgetWithText(FilledButton, 'Confirm & Save Hotel Details')); await tester.pumpAndSettle();
    expect(find.text('Add hotel details to which Trip?'), findsOneWidget);
    Navigator.of(tester.element(find.text('Add hotel details to which Trip?'))).pop();
    await tester.pumpAndSettle(); await save; expect(api.posts, isEmpty);
  });
  testWidgets('Trip Replace forwards its ID and reopens with persisted hotel', (tester) async {
    final api = BatchApi()..showTargetTrip = true;
    await frame(tester, TripDetailsScreen(api: api, tripId: 'target', referenceDate: DateTime(2030, 1, 1)));
    await tester.scrollUntilVisible(find.text('Replace'), 300, scrollable: find.byType(Scrollable).first);
    await tester.tap(find.text('Replace')); await tester.pumpAndSettle();
    expect(tester.widget<HotelScreen>(find.byType(HotelScreen)).targetTripId, 'target');
    final dynamic state = tester.state(find.byType(HotelScreen));
    final save = state.completeBooking({'name': 'Replacement hotel', 'price': 200, 'currency': 'MYR'}, 'v', 'liteapi', 'attempt');
    await tester.pumpAndSettle(); await tester.tap(find.widgetWithText(FilledButton, 'Confirm & Save Hotel Details'));
    await tester.pumpAndSettle(); await save;
    await tester.pageBack(); await tester.pumpAndSettle();
    expect(find.text('Replacement hotel'), findsWidgets); expect(find.text('Old hotel'), findsNothing);
    await tester.pumpWidget(MaterialApp(home: TripDetailsScreen(key: UniqueKey(), api: api, tripId: 'target', referenceDate: DateTime(2030, 1, 1))));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Replacement hotel'), 300, scrollable: find.byType(Scrollable).first);
    expect(find.text('Replacement hotel'), findsWidgets); expect(api.trip['activities'], isEmpty);
  });

  testWidgets('empty search is distinct from initial state and is invalidated on edit', (tester) async {
    final api = BatchApi(); await frame(tester, FlightScreen(api: api));
    final dynamic state = tester.state(find.byType(FlightScreen));
    await state.search(); await tester.pumpAndSettle();
    expect(find.text('No flights found'), findsOneWidget);
    state.from.text = 'SIN'; await tester.pumpAndSettle();
    expect(find.text('No flights found'), findsNothing); expect(state.searchId, isEmpty);
  });
  testWidgets('provider failure shows its specific error without a no-results claim', (tester) async {
    final api = BatchApi()..failFlights = true; await frame(tester, FlightScreen(api: api));
    final dynamic state = tester.state(find.byType(FlightScreen));
    await state.search(); await tester.pumpAndSettle();
    expect(find.text('Flight provider is unavailable. Try again later.'), findsOneWidget);
    expect(find.text('No flights found'), findsNothing);
  });

}
