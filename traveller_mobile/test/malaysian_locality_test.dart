import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/malaysian_locality.dart';

void main() {
  final penang = MalaysianLocality.normalizeScope('Penang, Malaysia');

  test('normalizes Penang, Pulau Pinang and Georgetown aliases', () {
    expect(penang['scopeKey'], 'my:penang');
    expect(MalaysianLocality.normalizeScope('Pulau Pinang')['scopeKey'],
        'my:penang');
    final georgetown = MalaysianLocality.normalizeScope('Georgetown');
    expect(georgetown['state'], 'Penang');
    expect(georgetown['city'], 'George Town');
  });

  test('accepts Penang island and mainland localities', () {
    for (final locality in [
      'George Town',
      'Batu Ferringhi',
      'Bayan Lepas',
      'Tanjung Bungah',
      'Butterworth',
      'Bukit Mertajam',
    ]) {
      final result = MalaysianLocality.validateCandidate(
          {'address': '$locality, Malaysia'}, penang);
      expect(result['geographicEligibility']['eligible'], isTrue,
          reason: locality);
      expect(result['normalizedGeography']['state'], 'Penang');
    }
  });

  test('rejects other Malaysian states before recommendation scoring', () {
    for (final address in [
      'Kuala Lumpur, Malaysia',
      'Petaling Jaya, Selangor, Malaysia',
      'Shah Alam, Selangor, Malaysia',
      'Ipoh, Perak, Malaysia',
      'Johor Bahru, Johor, Malaysia',
      'Alor Setar, Kedah, Malaysia',
    ]) {
      final result =
          MalaysianLocality.validateCandidate({'address': address}, penang);
      expect(result['geographicEligibility']['eligible'], isFalse,
          reason: address);
    }
  });

  test('does not use a misleading place name as geographic proof', () {
    final result = MalaysianLocality.validateCandidate({
      'title': 'Penang Seafood Restaurant',
      'address': 'Kuala Lumpur, Malaysia',
    }, penang);

    expect(result['geographicEligibility']['eligible'], isFalse);
    expect(result['normalizedGeography']['state'], 'Kuala Lumpur');
  });

  test('coordinates override conflicting Penang address text', () {
    final result = MalaysianLocality.validateCandidate({
      'title': 'Penang Museum',
      'address': 'George Town, Penang, Malaysia',
      'gps_coordinates': {'latitude': 3.1579, 'longitude': 101.7116},
    }, penang);

    expect(result['geographicEligibility']['eligible'], isFalse);
    expect(result['normalizedGeography']['evidence'], 'coordinates');
    expect(result['normalizedGeography']['state'], 'Kuala Lumpur');
    expect(result['normalizedGeography']['conflict'], isTrue);
  });

  test('missing locality metadata remains unresolved and excluded', () {
    final result = MalaysianLocality.validateCandidate(
        {'title': 'Popular Attraction'}, penang);

    expect(result['geographicEligibility']['eligible'], isFalse);
    expect(result['geographicEligibility']['reason'],
        'unresolved_candidate_geography');
  });
}
