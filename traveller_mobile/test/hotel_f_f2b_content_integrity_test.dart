import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_details_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _F2BMockApi extends ApiService {
  List<Map<String, dynamic>> ordersList = [];
  List<Map<String, dynamic>> paymentsList = [];
  bool ordersShouldFail = false;
  Map<String, dynamic>? lastPostPayload;
  String? lastPostPath;

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr9/orders') {
      if (ordersShouldFail) {
        throw Exception('Simulated 500 error fetching orders');
      }
      return {'items': ordersList};
    }
    if (path == '/api/fr9/payments') {
      return {'items': paymentsList};
    }
    if (path == '/api/fr9/checkout/capabilities') {
      return {
        'ok': true,
        'mode': 'test',
        'hostedCheckout': true,
        'supportedQuoteTypes': ['hotel', 'package'],
      };
    }
    if (path == '/api/fr5/itineraries') {
      return {'items': [{'id': 'trip-penang-1', 'title': 'Penang Heritage', 'budgetLimit': 2500}]};
    }
    return {};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    lastPostPath = path;
    lastPostPayload = body != null ? Map<String, dynamic>.from(body) : null;

    if (path == '/api/fr8/hotels/search') {
      return {
        'source': 'liteapi',
        'items': [
          // Hotel A: 2 room tiers for the SAME property
          {
            'hotelId': 'hotel-prop-alpha',
            'offerId': 'offer-alpha-standard',
            'name': 'The Royale Chulan Penang',
            'address': '1 & 2 Pengkalan Weld, George Town, Penang',
            'price': 250.0,
            'currency': 'MYR',
            'priceBasis': 'per_room_night',
            'priceStatus': 'available',
            'roomName': 'Standard Room',
            'rating': 8.6,
            'stars': 4,
            'refundable': true,
            'mainPhoto': 'https://images.example.com/royale_chulan_main.jpg',
            'roomImageUrls': ['https://images.example.com/standard_room.jpg'],
            'quoteId': 'quote-alpha-std',
          },
          {
            'hotelId': 'hotel-prop-alpha',
            'offerId': 'offer-alpha-deluxe',
            'name': 'The Royale Chulan Penang',
            'address': '1 & 2 Pengkalan Weld, George Town, Penang',
            'price': 480.0,
            'currency': 'MYR',
            'priceBasis': 'per_room_night',
            'priceStatus': 'available',
            'roomName': 'Deluxe Sea View Suite',
            'rating': 8.6,
            'stars': 4,
            'refundable': true,
            'mainPhoto': 'https://images.example.com/royale_chulan_main.jpg',
            'roomImageUrls': ['https://images.example.com/deluxe_suite.jpg'],
            'quoteId': 'quote-alpha-dlx',
          },
          // Hotel B: Different property that happens to have a similar name, different address & hotelId
          {
            'hotelId': 'hotel-prop-beta',
            'offerId': 'offer-beta-1',
            'name': 'The Royale Chulan KL',
            'address': '5 Jalan Conlay, Kuala Lumpur',
            'price': 390.0,
            'currency': 'MYR',
            'priceBasis': 'per_room_night',
            'priceStatus': 'available',
            'roomName': 'Premier Room',
            'rating': 8.8,
            'stars': 5,
            'refundable': false,
            // Image is inside imageUrls array instead of mainPhoto
            'mainPhoto': '',
            'imageUrls': ['https://images.example.com/royale_kl_facade.jpg'],
            'quoteId': 'quote-beta-1',
          },
          // Hotel C: No photo at all (tests neutral fallback)
          {
            'hotelId': 'hotel-prop-gamma',
            'offerId': 'offer-gamma-1',
            'name': 'Boutique Heritage Inn',
            'address': 'Campbell Street, George Town',
            'price': 160.0,
            'currency': 'MYR',
            'priceBasis': 'per_room_night',
            'priceStatus': 'available',
            'roomName': 'Heritage Single',
            'rating': 7.9,
            'stars': 3,
            'refundable': true,
            'mainPhoto': '',
            'imageUrls': [],
            'quoteId': 'quote-gamma-1',
          },
        ]
      };
    }

    if (path == '/api/fr8/hotels/prebook') {
      final offer = body?['offerId'];
      final amount = offer == 'offer-alpha-deluxe' ? 480.0 : 250.0;
      final roomName = offer == 'offer-alpha-deluxe' ? 'Deluxe Sea View Suite' : 'Standard Room';
      return {
        'status': 'accepted',
        'acceptedPrebook': {
          'prebookId': 'pb-$offer',
          'offerId': offer,
          'amount': amount,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
          'roomName': roomName,
        },
        'acceptedPrebookSnapshotId': 'snap-$offer',
      };
    }

    if (path == '/api/fr9/checkout/session') {
      return {
        'checkoutUrl': 'https://checkout.stripe.com/c/pay/cs_test_mock_123',
        'orderId': 'order-test-123',
        'status': 'checkout_open',
      };
    }

    return {};
  }
}

Widget _wrap(Widget child) => MaterialApp(
  home: child,
);

void _setViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('Batch F-F2B: Hotel Content Integrity, Room Offer Consistency & Native UX', () {

    // Phase A1: New Hotel / New Room displays clean authoritative quote immediately
    testWidgets('A1. New Hotel / New Room displays authoritative quote in 0ms without MYR 0.00', (tester) async {
      _setViewport(tester);
      final api = _F2BMockApi();

      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-alpha-dlx',
        offerId: 'offer-alpha-deluxe',
        acceptedPrebookSnapshotId: 'snap-offer-alpha-deluxe',
        initialAmount: 480.00,
        initialBookingReference: 'The Royale Chulan Penang - Deluxe Sea View Suite',
        acceptedPrebook: const {
          'amount': 480.00,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
        },
      )));
      await tester.pumpAndSettle();

      // Immediately visible without waiting for network or order sync
      expect(find.text('Authoritative quote: MYR 480.00'), findsOneWidget);
      expect(find.text('Ready for Checkout'), findsOneWidget);
      expect(find.text('MYR 0.00'), findsNothing);
      expect(find.text('Continue to Payment'), findsOneWidget);
    });

    // Phase A2: Same Hotel / Different Room does NOT inherit previously paid state
    testWidgets('A2. Same Hotel with Different Room does not inherit older Paid order', (tester) async {
      _setViewport(tester);
      // Older paid order exists for the Standard Room (offer-alpha-standard)
      final api = _F2BMockApi()..ordersList = [
        {
          'id': 'order-alpha-standard-paid',
          'quoteType': 'hotel',
          'quoteId': 'quote-alpha-std',
          'offerId': 'offer-alpha-standard',
          'acceptedPrebookSnapshotId': 'snap-offer-alpha-standard',
          'status': 'paid',
          'paymentStatus': 'paid',
          'amount': 250.00,
          'currency': 'MYR',
        }
      ];

      // Traveller now checks out the Deluxe Suite
      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-alpha-dlx',
        offerId: 'offer-alpha-deluxe',
        acceptedPrebookSnapshotId: 'snap-offer-alpha-deluxe',
        initialAmount: 480.00,
        initialBookingReference: 'The Royale Chulan Penang - Deluxe Sea View Suite',
        acceptedPrebook: const {
          'amount': 480.00,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
        },
      )));
      await tester.pumpAndSettle();

      // Must remain in Ready for Checkout with Deluxe amount (480.00), NOT Paid with 250.00!
      expect(find.text('Payment Completed'), findsNothing);
      expect(find.text('Ready for Checkout'), findsOneWidget);
      expect(find.text('Authoritative quote: MYR 480.00'), findsOneWidget);
      expect(find.textContaining('250.00'), findsNothing);
      expect(find.text('Continue to Payment'), findsOneWidget);
    });

    // Phase A3: Reopening Existing Paid Order strictly preserves its paid state and verified amount
    testWidgets('A3. Existing Paid Order reopening strictly matches snapshot and prevents duplicate checkout', (tester) async {
      _setViewport(tester);
      final api = _F2BMockApi()..ordersList = [
        {
          'id': 'order-alpha-deluxe-paid',
          'quoteType': 'hotel',
          'quoteId': 'quote-alpha-dlx',
          'offerId': 'offer-alpha-deluxe',
          'acceptedPrebookSnapshotId': 'snap-offer-alpha-deluxe',
          'hotelBookingAttemptId': 'attempt-hotel-alpha-deluxe',
          'status': 'paid',
          'paymentStatus': 'paid',
          'amount': 480.00,
          'currency': 'MYR',
        }
      ];

      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-alpha-dlx',
        offerId: 'offer-alpha-deluxe',
        acceptedPrebookSnapshotId: 'snap-offer-alpha-deluxe',
        hotelBookingAttemptId: 'attempt-hotel-alpha-deluxe',
        initialAmount: 480.00,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Payment Completed'), findsOneWidget);
      expect(find.text('Authoritative quote: MYR 480.00'), findsOneWidget);
      expect(find.text('View Order Details'), findsWidgets);
      expect(find.text('Continue to Payment'), findsNothing);
    });

    // Phase A4: Backend failure loading orders does not crash or reset display amount
    testWidgets('A4. Backend failure loading order history does not blank out authoritative quote', (tester) async {
      _setViewport(tester);
      final api = _F2BMockApi()..ordersShouldFail = true;

      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-alpha-dlx',
        offerId: 'offer-alpha-deluxe',
        acceptedPrebookSnapshotId: 'snap-offer-alpha-deluxe',
        initialAmount: 480.00,
        acceptedPrebook: const {
          'amount': 480.00,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
        },
      )));
      await tester.pumpAndSettle();

      // Authoritative quote remains solidly visible even when orders endpoint failed
      expect(find.text('Authoritative quote: MYR 480.00'), findsOneWidget);
      expect(find.text('Ready for Checkout'), findsOneWidget);
      expect(find.text('Continue to Payment'), findsOneWidget);
    });

    // Phase B1: Room Selection Integrity across Card -> Details -> Prebook -> Payment Review
    testWidgets('B1. Selecting Deluxe Room on card updates room offer, prebook and payment identity consistently', (tester) async {
      _setViewport(tester);
      final api = _F2BMockApi();

      await tester.pumpWidget(_wrap(HotelScreen(
        api: api,
        initialDestination: 'Penang',
        initialCheckin: '2026-11-10',
        initialCheckout: '2026-11-12',
        initialAdults: 2,
        initialChildren: 0,
      )));
      await tester.pumpAndSettle();

      // Trigger search
      final searchBtn = find.text('Search hotels');
      await tester.ensureVisible(searchBtn);
      await tester.tap(searchBtn);
      await tester.pumpAndSettle();

      // 1. Check card: The Royale Chulan Penang renders 1 card with 2 Room Options
      expect(find.byKey(const ValueKey('hotel-card-hotel-prop-alpha')), findsOneWidget);
      expect(find.text('2 Room Options Available:'), findsOneWidget);
      expect(find.textContaining('Standard Room (MYR 250'), findsOneWidget);
      expect(find.textContaining('Deluxe Sea View Suite (MYR 480'), findsOneWidget);

      // Default active is Standard Room (250)
      expect(find.textContaining('250.0 / room/night'), findsOneWidget);

      // 2. Select Deluxe Sea View Suite chip
      final deluxeChip = find.textContaining('Deluxe Sea View Suite (MYR 480');
      await tester.tap(deluxeChip);
      await tester.pumpAndSettle();

      // Card active offer price and room name update to Deluxe Sea View Suite (480)
      expect(find.textContaining('480.0 / room/night'), findsOneWidget);
      expect(find.text('Deluxe Sea View Suite'), findsOneWidget);

      // 3. Tap Validate quote to prebook the selected Deluxe Suite
      final validateBtn = find.widgetWithText(FilledButton, 'Validate quote').first;
      await tester.ensureVisible(validateBtn);
      await tester.tap(validateBtn);
      await tester.pumpAndSettle();

      // Verify prebook was called with the Deluxe offer ID
      expect(api.lastPostPayload?['offerId'], equals('offer-alpha-deluxe'));
      expect(find.text('Hotel Offer Validated'), findsOneWidget);
      expect(find.textContaining('MYR 480'), findsWidgets);

      // 4. Tap Continue to Payment on outcome sheet
      final checkoutNavBtn = find.byKey(const ValueKey('hotel-continue-payment'));
      await tester.ensureVisible(checkoutNavBtn);
      await tester.tap(checkoutNavBtn);
      await tester.pumpAndSettle();

      // Payment screen opens with Deluxe Suite quote (480.00)
      expect(find.text('Authoritative quote: MYR 480.00'), findsOneWidget);
      expect(find.textContaining('Deluxe Sea View Suite'), findsWidgets);
      expect(find.text('Ready for Checkout'), findsOneWidget);
    });

    // Phase B2: Switching room offer INSIDE HotelDetailsScreen updates selection & stay details
    testWidgets('B2. Switching room offer inside HotelDetailsScreen updates displayed price and stay details', (tester) async {
      _setViewport(tester);
      Map<String, dynamic>? selectedFromDetails;

      final hotelData = {
        'hotelId': 'hotel-prop-alpha',
        'offerId': 'offer-alpha-standard',
        'name': 'The Royale Chulan Penang',
        'price': 250.0,
        'currency': 'MYR',
        'priceStatus': 'available',
        'roomName': 'Standard Room',
        'bedType': 'Queen Bed',
        'maxOccupancy': 2,
        '_allOffers': [
          {
            'hotelId': 'hotel-prop-alpha',
            'offerId': 'offer-alpha-standard',
            'roomName': 'Standard Room',
            'price': 250.0,
            'currency': 'MYR',
            'bedType': 'Queen Bed',
            'maxOccupancy': 2,
          },
          {
            'hotelId': 'hotel-prop-alpha',
            'offerId': 'offer-alpha-deluxe',
            'roomName': 'Deluxe Sea View Suite',
            'price': 480.0,
            'currency': 'MYR',
            'bedType': 'King Bed',
            'maxOccupancy': 3,
          },
        ]
      };

      await tester.pumpWidget(_wrap(HotelDetailsScreen(
        hotel: hotelData,
        onOfferSelected: (off) => selectedFromDetails = off,
        onProceed: () {},
      )));
      await tester.pumpAndSettle();

      // Initially displays Standard Room (250)
      expect(find.text('MYR 250.0'), findsOneWidget);
      expect(find.text('Queen Bed'), findsOneWidget);

      // Tap on the Deluxe Sea View Suite in Available room types
      final deluxeOption = find.textContaining('Deluxe Sea View Suite');
      await tester.ensureVisible(deluxeOption);
      await tester.tap(deluxeOption);
      await tester.pumpAndSettle();

      // Details update to Deluxe Sea View Suite (480)
      expect(find.text('MYR 480.0'), findsOneWidget);
      expect(find.text('King Bed'), findsOneWidget);
      expect(selectedFromDetails?['offerId'], equals('offer-alpha-deluxe'));
    });

    // Phase C: Photo resolution finds alternative photo array and renders neutral placeholder when empty
    testWidgets('C1. Photo resolution finds array photos and provides neutral fallback when missing', (tester) async {
      _setViewport(tester);
      final api = _F2BMockApi();

      await tester.pumpWidget(_wrap(HotelScreen(
        api: api,
        initialDestination: 'Penang',
        initialCheckin: '2026-11-10',
        initialCheckout: '2026-11-12',
        initialAdults: 2,
        initialChildren: 0,
      )));
      await tester.pumpAndSettle();

      final searchBtn = find.text('Search hotels');
      await tester.ensureVisible(searchBtn);
      await tester.tap(searchBtn);
      await tester.pumpAndSettle();

      // Royale Chulan KL has empty mainPhoto, but has imageUrls[0] -> Image widget rendered
      expect(find.byType(Image), findsWidgets);

      // Boutique Heritage Inn has no photos at all -> Neutral fallback container rendered
      expect(find.text('Hotel photo unavailable'), findsWidgets);
    });

    // Phase D: Properties with same name but different hotelId are NOT merged
    testWidgets('D1. Two hotels with different hotelId are not merged even with similar names', (tester) async {
      _setViewport(tester);
      final api = _F2BMockApi();

      await tester.pumpWidget(_wrap(HotelScreen(
        api: api,
        initialDestination: 'Penang',
        initialCheckin: '2026-11-10',
        initialCheckout: '2026-11-12',
        initialAdults: 2,
        initialChildren: 0,
      )));
      await tester.pumpAndSettle();

      final searchBtn = find.text('Search hotels');
      await tester.ensureVisible(searchBtn);
      await tester.tap(searchBtn);
      await tester.pumpAndSettle();

      // The Royale Chulan Penang (hotel-prop-alpha) and The Royale Chulan KL (hotel-prop-beta)
      // must exist as separate property cards!
      expect(find.byKey(const ValueKey('hotel-card-hotel-prop-alpha')), findsOneWidget);
      expect(find.byKey(const ValueKey('hotel-card-hotel-prop-beta')), findsOneWidget);
      expect(find.byKey(const ValueKey('hotel-card-hotel-prop-gamma')), findsOneWidget);
    });

    // Phase E: Payment UI concise presentation
    testWidgets('E1. Checkout screen maintains concise consumer UI without repetitive technical banners', (tester) async {
      _setViewport(tester);
      final api = _F2BMockApi()..ordersList = [
        {
          'id': 'order-prior-item',
          'quoteType': 'hotel',
          'status': 'paid',
          'amount': 200.0,
          'currency': 'MYR',
        }
      ];

      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-alpha-dlx',
        offerId: 'offer-alpha-deluxe',
        acceptedPrebookSnapshotId: 'snap-offer-alpha-deluxe',
        initialAmount: 480.00,
        initialBookingReference: 'The Royale Chulan Penang - Deluxe Sea View Suite',
        acceptedPrebook: const {
          'amount': 480.00,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
        },
      )));
      await tester.pumpAndSettle();

      expect(find.text('Review Payment'), findsOneWidget);
      expect(find.text('Continue to Payment'), findsOneWidget);
      expect(find.text('Payment History'), findsOneWidget);
      expect(find.text('View Payment History'), findsOneWidget);

      // Verify no cluttered developer-style repeated labels
      expect(find.text('Paid — Stripe Test Mode'), findsNothing);
    });
  });
}
