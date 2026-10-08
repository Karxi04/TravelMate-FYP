import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/standalone_api_service.dart';
import 'package:travelmate_traveller/core/utils/malaysian_locality.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('standalone hotel samples keep their real demo locality', () async {
    final service = StandaloneApiService(uidOverride: 'locality_test', memoryStore: {});
    for (final destination in ['Penang', 'George Town', 'Kuala Lumpur', 'Singapore']) {
      final response = await service.post('/api/fr8/hotels/search', {
        'destination': destination, 'checkin': '2026-11-01', 'checkout': '2026-11-03',
      });
      final items = response['items'] as List;
      expect(items.isNotEmpty, destination == 'Penang' || destination == 'George Town');
      for (final item in items) {
        final validated = MalaysianLocality.validateCandidate(
          Map<String, dynamic>.from(item as Map), MalaysianLocality.normalizeScope(destination),
        );
        expect(validated['geographicEligibility']['eligible'], isTrue);
        expect(item['address'], 'George Town, Penang, Malaysia');
        expect(item['rateSource'], 'sample_fixture');
        expect(item['transactionMode'], 'local_demo');
      }
    }
  });

  test('same standalone payment attempt returns the same transaction',
      () async {
    final service = StandaloneApiService(
      uidOverride: 'transaction_test_user',
      memoryStore: {},
    );
    final payload = {
      'paymentAttemptId': 'payment_attempt_standalone',
      'bookingId': 'DEMO-BOOKING',
      'amount': 42.0,
    };

    final first = await service.post('/api/fr9/payments/process', payload);
    final second = await service.post('/api/fr9/payments/process', payload);

    expect(first['payment']['id'], second['payment']['id']);
    expect(second['reused'], isTrue);
    await expectLater(
      service.post(
        '/api/fr9/payments/${first['payment']['id']}/cancel',
        const {},
      ),
      throwsA(isA<Exception>()),
    );
  });

  test('same standalone hotel attempt keeps prebook and confirmation',
      () async {
    final service = StandaloneApiService(
      uidOverride: 'hotel_test_user',
      memoryStore: {},
    );
    const attemptId = 'hotel_attempt_standalone';
    final search = await service.post('/api/fr8/hotels/search', {
      'destination': 'Penang',
      'checkin': '2026-11-01',
      'checkout': '2026-11-03',
    });
    final offer = Map<String, dynamic>.from((search['items'] as List).first as Map);
    final prebookPayload = {
      'hotelBookingAttemptId': attemptId,
      'offerId': offer['offerId'],
      'quoteId': offer['quoteId'],
    };
    final firstPrebook =
        await service.post('/api/fr8/hotels/prebook', prebookPayload);
    final secondPrebook =
        await service.post('/api/fr8/hotels/prebook', prebookPayload);
    expect(firstPrebook['result']['validationId'],
        secondPrebook['result']['validationId']);

    final bookingPayload = {
      'hotelBookingAttemptId': attemptId,
      'validationId': firstPrebook['result']['validationId'],
      'selectedHotel': {'name': 'Demo Hotel', 'price': 88.0},
      'hotelCost': 88.0,
    };
    final firstBooking =
        await service.post('/api/fr8/hotels/book', bookingPayload);
    final secondBooking =
        await service.post('/api/fr8/hotels/book', bookingPayload);

    expect(firstBooking['booking']['bookingReference'],
        secondBooking['booking']['bookingReference']);
    expect(
        firstBooking['booking']['confirmationLabel'], 'Simulated confirmation');
    expect(secondBooking['reused'], isTrue);
  });
}
