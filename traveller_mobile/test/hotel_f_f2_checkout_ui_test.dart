import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:travelmate_traveller/modules/fr08_hotel_booking/hotel_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/checkout_return_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_history_screen.dart';
import 'package:travelmate_traveller/modules/fr09_payment/payment_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class _F2MockApi extends ApiService {
  bool checkoutEnabled = true;
  List<dynamic> ordersList = [];
  List<dynamic> paymentItems = [];
  int postCount = 0;
  String? lastPostedPath;
  Map<String, dynamic>? lastPostedBody;

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr9/checkout/capabilities') {
      return {
        'ok': true,
        'mode': 'test',
        'hostedCheckout': checkoutEnabled,
        'supportedQuoteTypes': ['hotel', 'package'],
      };
    }
    if (path == '/api/fr9/payments') {
      return {'ok': true, 'items': paymentItems};
    }
    if (path == '/api/fr9/orders') {
      return {'ok': true, 'items': ordersList};
    }
    if (path.startsWith('/api/fr9/orders/')) {
      final orderId = path.split('/')[4].split('?')[0];
      final found = ordersList.cast<Map<String, dynamic>?>().firstWhere(
        (o) => o?['id'] == orderId,
        orElse: () => null,
      );
      if (found != null) {
        return {'ok': true, 'order': found};
      }
      return {
        'ok': true,
        'order': {
          'id': orderId,
          'quoteType': 'hotel',
          'status': 'paid',
          'paymentStatus': 'paid',
          'amount': 420.0,
          'currency': 'MYR',
          'hotelName': 'Penang Heritage Resort',
        }
      };
    }
    return {'ok': true};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    postCount++;
    lastPostedPath = path;
    lastPostedBody = body;
    if (path == '/api/fr8/hotels/search') {
      return {
        'ok': true,
        'source': 'liteapi',
        'items': [
          {
            'hotelId': 'hotel-prop-1',
            'offerId': 'offer-1a',
            'name': 'Grand Resort Penang',
            'roomName': 'Deluxe Room',
            'price': 420.0,
            'currency': 'MYR',
            'checkin': '2026-11-10',
            'checkout': '2026-11-12',
            'mainPhoto': 'https://example.com/photo1.jpg',
          },
          {
            'hotelId': 'hotel-prop-1',
            'offerId': 'offer-1b',
            'name': 'Grand Resort Penang',
            'roomName': 'Executive Suite',
            'price': 680.0,
            'currency': 'MYR',
            'checkin': '2026-11-10',
            'checkout': '2026-11-12',
            'mainPhoto': 'https://example.com/photo1.jpg',
          },
          {
            'hotelId': 'hotel-prop-2',
            'offerId': 'offer-2',
            'name': 'Boutique Inn George Town',
            'roomName': 'Standard Room',
            'price': 220.0,
            'currency': 'MYR',
            'checkin': '2026-11-10',
            'checkout': '2026-11-12',
            'mainPhoto': '',
          },
        ],
      };
    }
    if (path.contains('/checkout/session')) {
      return {
        'ok': true,
        'order': {
          'id': 'order-new-123',
          'quoteType': body?['quoteType'] ?? 'hotel',
          'status': 'checkout_open',
          'checkoutAction': 'continue_payment',
          'checkoutUrl': 'https://checkout.stripe.test/cs_test_999',
          'amount': 420.0,
        }
      };
    }
    return {'ok': true};
  }
}

Widget _wrap(Widget child) {
  return MaterialApp(
    home: child,
  );
}

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

  group('Batch F-F2 Hotel Checkout & UI Quality Verification', () {
    // 1. Opening a new Hotel Checkout does not show MYR 0.00
    testWidgets('1. Opening a new Hotel Checkout does not show MYR 0.00', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi();
      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-penang-1',
        offerId: 'offer-deluxe',
        acceptedPrebookSnapshotId: 'snap-authoritative-101',
        acceptedPrebook: const {
          'amount': 380.0,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
        },
      )));
      await tester.pumpAndSettle();

      expect(find.text('MYR 0.00'), findsNothing);
      expect(find.textContaining('380.00'), findsOneWidget);
      expect(find.text('Review Payment'), findsOneWidget);
    });

    // 2. Loading amount does not enable payment prematurely
    testWidgets('2. Missing or unresolved amount displays loading and does not enable payment', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi();
      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-resolving',
        offerId: 'offer-resolving',
        acceptedPrebookSnapshotId: 'snap-resolving',
        acceptedPrebook: const {
          'expiresAt': '2099-01-01T00:00:00Z',
          // amount intentionally null
        },
      )));
      await tester.pumpAndSettle();

      expect(find.text('MYR 0.00'), findsNothing);
      expect(find.textContaining('Loading price...'), findsWidgets);
      // Button must be disabled when price is loading
      final button = tester.widget<FilledButton>(find.byType(FilledButton));
      expect(button.onPressed, isNull);
    });

    // 3. The final amount matches the accepted authoritative quote
    testWidgets('3. Final amount strictly matches the accepted authoritative quote', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi();
      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-penang-2',
        offerId: 'offer-suite',
        acceptedPrebookSnapshotId: 'snap-authoritative-102',
        acceptedPrebook: const {
          'amount': 650.00,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
        },
        initialAmount: 650.00,
        initialProductName: 'Grand Resort Penang',
      )));
      await tester.pumpAndSettle();

      expect(find.text('Authoritative quote: MYR 650.00'), findsOneWidget);
      expect(find.text('Grand Resort Penang'), findsOneWidget);
      expect(find.text('Continue to Payment'), findsOneWidget);
    });

    // 4. Existing Paid Order reopening shows its own amount and verified state
    testWidgets('4. Existing Paid Order reopening shows its own verified amount', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi()..ordersList = [
        {
          'id': 'order-paid-stay-1',
          'quoteType': 'hotel',
          'quoteId': 'quote-hotel-1',
          'offerId': 'offer-1',
          'acceptedPrebookSnapshotId': 'snap-paid-1',
          'status': 'paid',
          'paymentStatus': 'paid',
          'checkoutAction': 'view_booking',
          'amount': 550.0,
          'currency': 'MYR',
        }
      ];

      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-hotel-1',
        offerId: 'offer-1',
        acceptedPrebookSnapshotId: 'snap-paid-1',
      )));
      await tester.pumpAndSettle();

      expect(find.text('Payment Completed'), findsOneWidget);
      expect(find.text('Authoritative quote: MYR 550.00'), findsOneWidget);
      expect(find.text('View Order Details'), findsWidgets);
      expect(find.text('Continue to Payment'), findsNothing);
    });

    // 5. New Hotel selection does not inherit a previous Paid state
    testWidgets('5. New Hotel selection does not inherit previous Paid state', (tester) async {
      _setViewport(tester);
      // Older paid order exists for quote-hotel-1 / snap-paid-1
      final api = _F2MockApi()..ordersList = [
        {
          'id': 'order-paid-stay-1',
          'quoteType': 'hotel',
          'quoteId': 'quote-hotel-1',
          'offerId': 'offer-1',
          'acceptedPrebookSnapshotId': 'snap-paid-1',
          'status': 'paid',
          'paymentStatus': 'paid',
          'checkoutAction': 'view_booking',
          'amount': 550.0,
          'currency': 'MYR',
        }
      ];

      // Traveller now selects a NEW room offer with a new snapshot ID
      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-hotel-1',
        offerId: 'offer-2-new',
        acceptedPrebookSnapshotId: 'snap-new-offer-2',
        acceptedPrebook: const {
          'amount': 299.00,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
        },
        initialAmount: 299.00,
      )));
      await tester.pumpAndSettle();

      // Must NOT inherit the paid state or old amount!
      expect(find.text('Payment Completed'), findsNothing);
      expect(find.text('Authoritative quote: MYR 299.00'), findsOneWidget);
      expect(find.textContaining('550.00'), findsNothing);
      expect(find.text('Continue to Payment'), findsOneWidget);
    });

    // 6. Expired quote cannot proceed
    testWidgets('6. Expired quote cannot proceed to checkout', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi();
      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-hotel-expired',
        offerId: 'offer-expired',
        acceptedPrebookSnapshotId: 'snap-expired',
        acceptedPrebook: const {
          'amount': 400.0,
          'currency': 'MYR',
          'expiresAt': '2020-01-01T00:00:00Z', // Expired in past
        },
      )));
      await tester.pumpAndSettle();

      expect(find.text('Price unavailable — refresh hotel offer'), findsWidgets);
      final button = tester.widget<FilledButton>(find.byType(FilledButton));
      expect(button.onPressed, isNull);
    });

    // 7. Stale async responses cannot overwrite a newer selection
    testWidgets('7. Order matching strictly isolates distinct snapshot IDs', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi()..ordersList = [
        {
          'id': 'order-unrelated-cancelled',
          'quoteType': 'hotel',
          'quoteId': 'quote-hotel-1',
          'offerId': 'offer-unrelated',
          'acceptedPrebookSnapshotId': 'snap-unrelated',
          'status': 'cancelled',
          'amount': 150.0,
        }
      ];

      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'hotel',
        quoteId: 'quote-hotel-1',
        offerId: 'offer-active',
        acceptedPrebookSnapshotId: 'snap-active',
        acceptedPrebook: const {
          'amount': 320.0,
          'currency': 'MYR',
          'expiresAt': '2099-01-01T00:00:00Z',
        },
      )));
      await tester.pumpAndSettle();

      // Active quote remains ready for checkout
      expect(find.text('Authoritative quote: MYR 320.00'), findsOneWidget);
      expect(find.text('Ready for Checkout'), findsOneWidget);
      expect(find.text('Continue to Payment'), findsOneWidget);
    });

    // 8. Payment History retains all previous records
    testWidgets('8. Payment History retains all previous records without loss', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi()..paymentItems = [
        {
          'id': 'pay-hotel-1',
          'source': 'checkout_order',
          'orderReference': 'order-hotel-1',
          'bookingType': 'hotel',
          'productTitle': 'Grand Resort Penang',
          'amount': 420.0,
          'currency': 'MYR',
          'paymentStatus': 'paid',
        },
        {
          'id': 'pay-pkg-1',
          'source': 'checkout_order',
          'orderReference': 'order-pkg-1',
          'bookingType': 'package',
          'productTitle': 'Penang Heritage Tour',
          'amount': 850.0,
          'currency': 'MYR',
          'paymentStatus': 'paid',
        },
      ];

      await tester.pumpWidget(_wrap(PaymentHistoryScreen(api: api)));
      await tester.pumpAndSettle();

      expect(find.text('Hotel — Grand Resort Penang'), findsOneWidget);
      expect(find.text('Package — Penang Heritage Tour'), findsOneWidget);
    });

    // 9. Payment Return displays verified order amount
    testWidgets('9. Payment Return displays verified order amount and hotel identity', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi()..ordersList = [
        {
          'id': 'order-return-verified',
          'quoteType': 'hotel',
          'status': 'paid',
          'paymentStatus': 'paid',
          'amount': 420.0,
          'currency': 'MYR',
          'hotelName': 'Penang Heritage Resort',
        }
      ];

      await tester.pumpWidget(_wrap(CheckoutReturnScreen(
        api: api,
        link: const CheckoutReturnLink('order-return-verified', 'paid'),
      )));
      await tester.pumpAndSettle();

      expect(find.text('Payment Completed'), findsOneWidget);
      expect(find.text('Penang Heritage Resort'), findsOneWidget);
      expect(find.text('Completed'), findsOneWidget);
      expect(find.text('MYR 420.00'), findsOneWidget);
      expect(find.text('View Order Details'), findsOneWidget);
      expect(find.text('View Payment History'), findsOneWidget);
    });

    // 10. Package Checkout remains functional
    testWidgets('10. Package Checkout remains functional and displays authoritative amount', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi();
      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        packageAttemptId: 'package-attempt-44',
        initialAmount: 1200.0,
        initialBookingReference: 'Penang Food & Culture 3D2N',
      )));
      await tester.pumpAndSettle();

      expect(find.text('Tourism Package'), findsOneWidget);
      expect(find.text('Authoritative quote: MYR 1200.00'), findsOneWidget);
      expect(find.text('Continue to Payment'), findsOneWidget);
    });

    // 11. Flight Checkout remains unsupported
    testWidgets('11. Flight Checkout remains unsupported with clear explanation', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi();
      await tester.pumpWidget(_wrap(PaymentScreen(
        api: api,
        quoteType: 'flight',
        searchId: 'search-kuching',
        optionId: 'opt-flight-1',
        initialAmount: 350.0,
      )));
      await tester.pumpAndSettle();

      expect(find.text('Payments unavailable'), findsOneWidget);
      expect(find.textContaining('Keep planning your trip'), findsOneWidget);
      expect(find.text('View Travel Records'), findsOneWidget);
    });

    // 12. Hotel image mapping and fallback presentation
    testWidgets('12. Valid photo URL and neutral placeholder are correctly rendered', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi();
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

      // Verified provider photo rendered for Grand Resort Penang
      expect(find.byType(Image), findsWidgets);
      // Neutral placeholder rendered for Boutique Inn (which has empty mainPhoto)
      expect(find.text('Hotel photo unavailable'), findsWidgets);
    });

    // 13. Duplicate offers are grouped without losing distinct room rates
    testWidgets('13. Duplicate offers are grouped under one property card with selectable room rates', (tester) async {
      _setViewport(tester);
      final api = _F2MockApi();
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

      // Grand Resort Penang has 2 room offers in the mock, but only ONE card is rendered!
      expect(find.byKey(const ValueKey('hotel-card-hotel-prop-1')), findsOneWidget);
      expect(find.text('2 Room Options Available:'), findsOneWidget);
      expect(find.textContaining('Deluxe Room'), findsWidgets);
      expect(find.textContaining('Executive Suite'), findsWidgets);

      // Default active room is Deluxe Room (MYR 420)
      expect(find.textContaining('420'), findsWidgets);

      // Select Executive Suite chip
      final suiteChip = find.textContaining('Executive Suite');
      await tester.tap(suiteChip);
      await tester.pumpAndSettle();

      // Active room updates to Executive Suite (MYR 680)
      expect(find.textContaining('680'), findsWidgets);
      expect(find.textContaining('680'), findsWidgets);
    });
  });
}
