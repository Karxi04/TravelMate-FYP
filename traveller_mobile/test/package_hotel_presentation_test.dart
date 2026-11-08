import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _MockApi extends ApiService {
  final Map<String, dynamic>? trip;
  _MockApi({this.trip});

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path.startsWith('/api/fr5/trips/') || path.startsWith('/api/fr5/itineraries/')) {
      return {'ok': true, 'trip': trip ?? {}, 'itinerary': trip ?? {}};
    }
    return {'ok': true};
  }
}

Widget _wrap(Widget child) {
  return MaterialApp(
    home: child,
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('TourismPackageDetailsScreen Hotel Presentation', () {
    testWidgets('renders verified partner hotel card with separate stars and guest rating', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final packageItem = {
        'id': 'pkg_test_hotel',
        'title': 'Penang Heritage Getaway',
        'destination': 'Penang',
        'durationDays': 3,
        'adultPrice': 450.0,
        'currency': 'MYR',
        'inclusions': ['Breakfast', 'City tour'],
        'roomType': 'Deluxe Heritage Suite',
        'accommodationNotes': 'Check-in 3 PM, check-out 12 PM',
        'accommodationHotel': {
          'provider': 'liteapi',
          'hotelId': 'lp_e_and_o',
          'name': 'Eastern & Oriental Hotel',
          'address': '10 Farquhar Street',
          'city': 'George Town',
          'country': 'MY',
          'stars': 5.0,
          'guestRating': 9.2,
          'mainPhoto': 'https://example.com/e_and_o.jpg',
          'amenities': ['Free Wi-Fi', 'Swimming Pool', 'Spa'],
          'reservationStatus': 'not_created',
        },
      };

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(item: packageItem, api: _MockApi())));
      await tester.pumpAndSettle();

      // Switch to What's Included tab
      final inclusionsTab = find.text("What's Included");
      expect(inclusionsTab, findsOneWidget);
      await tester.tap(inclusionsTab);
      await tester.pumpAndSettle();

      // Check verified badge
      expect(find.text('Hotel Information from LiteAPI'), findsOneWidget);
      // Check hotel name
      expect(find.text('Eastern & Oriental Hotel'), findsOneWidget);
      // Check address
      expect(find.text('10 Farquhar Street, George Town, MY'), findsOneWidget);
      // Check stars
      expect(find.text('⭐ 5.0-Star'), findsOneWidget);
      // Check guest rating
      expect(find.text('Guest Rating: 9.2/10'), findsOneWidget);
      // Check room type
      expect(find.text('Room Configuration: Deluxe Heritage Suite'), findsOneWidget);
      // Check disclaimer
      expect(
        find.text('Hotel information is provided for package planning. Selecting a property does not create or confirm a room reservation.'),
        findsOneWidget,
      );
    });

    testWidgets('renders "Star classification not supplied" when hotel stars is null', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final packageItem = {
        'id': 'pkg_null_stars',
        'title': 'Boutique Stay Tour',
        'destination': 'Penang',
        'durationDays': 2,
        'adultPrice': 250.0,
        'currency': 'MYR',
        'accommodationHotel': {
          'provider': 'liteapi',
          'hotelId': 'lp_boutique',
          'name': 'Muntri Heritage Boutique Villa',
          'address': 'Muntri Street',
          'city': 'George Town',
          'country': 'MY',
          'stars': null,
          'guestRating': 8.5,
          'amenities': ['Wi-Fi'],
          'reservationStatus': 'not_created',
        },
      };

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(item: packageItem, api: _MockApi())));
      await tester.pumpAndSettle();

      // Switch to What's Included tab
      await tester.tap(find.text("What's Included"));
      await tester.pumpAndSettle();

      expect(find.text('Star classification not supplied'), findsOneWidget);
      expect(find.text('Guest Rating: 8.5/10'), findsOneWidget);
      // Must not render fake Standard fallback
      expect(find.textContaining('Standard Hotel'), findsNothing);
    });

    testWidgets('renders legacy manual accommodation cleanly without crash', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final legacyItem = {
        'id': 'pkg_legacy',
        'title': 'Classic Country Retreat',
        'destination': 'Cameron Highlands',
        'durationDays': 2,
        'adultPrice': 200.0,
        'currency': 'MYR',
        'accommodationName': 'Strawberry Park Resort',
        'accommodationCategory': '4-Star Resort',
        'roomType': 'Standard Chalet',
        'accommodationNotes': 'Includes steamboat dinner voucher',
      };

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(item: legacyItem, api: _MockApi())));
      await tester.pumpAndSettle();

      await tester.tap(find.text("What's Included"));
      await tester.pumpAndSettle();

      expect(find.text('Accommodation'), findsOneWidget);
      expect(find.textContaining('Strawberry Park Resort'), findsOneWidget);
      expect(find.textContaining('4-Star Resort'), findsOneWidget);
      expect(find.text('Hotel Information from LiteAPI'), findsNothing);
    });
  });

  group('PackageTripDetailsScreen Hotel Presentation', () {
    testWidgets('renders partner hotel from package snapshot with honest supplier status', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final tripData = {
        'id': 'trip_hotel_snap_001',
        'title': 'Penang 3D2N Cultural Escape',
        'destinationArea': 'Penang',
        'tripDays': 3,
        'tripType': 'package',
        'packageTrip': true,
        'checkoutOrderId': 'order_hotel_001',
        'paidTotal': 900.0,
        'currency': 'MYR',
        'supplierReservationStatus': 'operator_attested',
        'packageSnapshot': {
          'title': 'Penang 3D2N Cultural Escape',
          'destination': 'Penang',
          'durationDays': 3,
          'accommodation': {
            'accommodationName': 'Eastern & Oriental Hotel',
            'roomType': 'Superior Heritage Suite',
            'accommodationNotes': 'Early check-in subject to availability',
            'accommodationHotel': {
              'provider': 'liteapi',
              'hotelId': 'lp_e_and_o',
              'name': 'Eastern & Oriental Hotel',
              'address': '10 Farquhar Street',
              'city': 'George Town',
              'country': 'MY',
              'stars': 5.0,
              'guestRating': 9.2,
              'amenities': ['Free Wi-Fi', 'Pool'],
              'reservationStatus': 'not_created',
            },
          },
        },
      };

      await tester.pumpWidget(_wrap(
        PackageTripDetailsScreen(
          tripId: 'trip_hotel_snap_001',
          initialTrip: tripData,
          api: _MockApi(trip: tripData),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Accommodation Details'), findsOneWidget);
      expect(find.text('Hotel Information from LiteAPI'), findsOneWidget);
      expect(find.text('Eastern & Oriental Hotel'), findsOneWidget);
      expect(find.text('⭐ 5.0-Star'), findsOneWidget);
      expect(find.text('Guest Rating: 9.2/10'), findsOneWidget);
      expect(find.text('Room Configuration: Superior Heritage Suite'), findsOneWidget);
      expect(
        find.textContaining('Hotel information is provided for package planning. Selecting a property does not create or confirm a room reservation. External supplier reservation is managed separately by the operator (Status: operator_attested).'),
        findsOneWidget,
      );
    });

    testWidgets('renders legacy trip snapshot without accommodationHotel gracefully', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final legacyTripData = {
        'id': 'trip_legacy_001',
        'title': 'Langkawi Island Adventure',
        'destinationArea': 'Langkawi',
        'tripDays': 2,
        'tripType': 'package',
        'packageTrip': true,
        'checkoutOrderId': 'order_legacy_001',
        'paidTotal': 500.0,
        'currency': 'MYR',
        'supplierReservationStatus': 'confirmed',
        'packageSnapshot': {
          'title': 'Langkawi Island Adventure',
          'accommodation': {
            'accommodationName': 'Pelangi Beach Resort',
            'accommodationCategory': '5-Star Beachfront',
            'roomType': 'Garden View Deluxe',
            'accommodationNotes': 'Check-in 2 PM',
          },
        },
      };

      await tester.pumpWidget(_wrap(
        PackageTripDetailsScreen(
          tripId: 'trip_legacy_001',
          initialTrip: legacyTripData,
          api: _MockApi(trip: legacyTripData),
        ),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Accommodation'), findsOneWidget);
      expect(find.text('Pelangi Beach Resort'), findsOneWidget);
      expect(find.text('5-Star Beachfront'), findsOneWidget);
      expect(find.text('Room Configuration: Garden View Deluxe'), findsOneWidget);
      expect(find.text('LiteAPI Verified'), findsNothing);
    });

    testWidgets('explicitly excluded accommodation hides a suggested property', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(item: {
        'id': 'not-included', 'title': 'Self-guided visit',
        'accommodationIncluded': false, 'transportIncluded': false,
        'guideActivitiesIncluded': false,
        'accommodationHotel': {'name': 'Suggested Property'},
      }, api: _MockApi())));
      await tester.pumpAndSettle();
      await tester.tap(find.text("What's Included"));
      await tester.pumpAndSettle();
      expect(find.text('Accommodation not included'), findsOneWidget);
      expect(find.text('Suggested Property'), findsNothing);
      expect(find.text('Operator-arranged transportation not included'), findsOneWidget);
      expect(find.text('Guide / reserved activities not included'), findsOneWidget);
    });

    testWidgets('purchased exclusion hides suggested accommodation on the saved trip', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final trip = <String, dynamic>{
        'id': 'excluded-stay', 'title': 'Self-guided visit', 'tripDays': 1,
        'packageTrip': true, 'tripType': 'package', 'paidTotal': 100,
        'currency': 'MYR', 'packageSnapshot': {
          'accommodationIncluded': false,
          'accommodation': {'accommodationName': 'Suggested Property'},
        },
      };
      await tester.pumpWidget(_wrap(PackageTripDetailsScreen(
        tripId: 'excluded-stay', initialTrip: trip, api: _MockApi(trip: trip),
      )));
      await tester.pumpAndSettle();
      expect(find.text('Accommodation not included'), findsOneWidget);
      expect(find.text('Suggested Property'), findsNothing);
    });
  });
}
