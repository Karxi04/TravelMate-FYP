import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/package_pricing.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/core/operator_content/campaign_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/public_content_contract.dart';

Map<String, dynamic> pricing(
        {String id = 'automatic',
        num finalAmount = 85,
        String code = '',
        String start = '2020-01-01',
        String end = '2099-01-01'}) =>
    {
      'pricingVersion': 'campaigns_v1',
      'priceBasis': 'per_person',
      'participants': {'adults': 1, 'children': 0, 'total': 1},
      'originalSubtotal': 100,
      'finalPayable': finalAmount,
      'promotionDiscount': 100 - finalAmount,
      'amountMinor': (finalAmount * 100).round(),
      'currency': 'MYR',
      'promotion': {
        'id': id,
        'campaignTitle': 'Heritage saving',
        'promoCode': code,
        'startDate': start,
        'endDate': end,
        'termsConditions': 'Standard package inclusions apply.'
      }
    };
Map<String, dynamic> package() => {
      'id': 'p1',
      'title': 'Penang Heritage',
      'adultPrice': 100,
      'childPrice': 50,
      'priceBasis': 'per_person',
      'currency': 'MYR',
      'departureDates': ['2027-01-10'],
      'packagePricing': {
        'base': {
          ...pricing(finalAmount: 100),
          'promotion': <String, dynamic>{}
        },
        'offers': [pricing()]
      }
    };

class OfferApi extends ApiService {
  final calls = <String>[];
  final bodies = <Map<String, dynamic>>[];
  @override
  bool get isStandalone => false;
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path.endsWith('/capabilities'))
      return {
        'ok': true,
        'hostedCheckout': true,
        'mode': 'test',
        'supportedQuoteTypes': ['package']
      };
    return {'ok': true, 'items': []};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    calls.add(path);
    bodies.add({...?body});
    if (path.endsWith('/quote') &&
        (body?['participants'] as Map?)?['adults'] == 2) {
      return {
        'ok': true,
        'quote': {
          'quoteToken': 'two-adults',
          'price': 170,
          'pricingBreakdown': {
            ...pricing(),
            'participants': {'adults': 2, 'children': 0, 'total': 2},
            'originalSubtotal': 200,
            'promotionDiscount': 30,
            'finalPayable': 170,
            'amountMinor': 17000
          }
        }
      };
    }
    if (path.endsWith('/quote'))
      return {
        'ok': true,
        'quote': {
          'quoteToken': 'authoritative-token',
          'price': 85,
          'pricingBreakdown': pricing()
        }
      };
    if (path == '/api/fr15/package-checkout-attempts')
      return {
        'ok': true,
        'attempt': {
          'id': 'attempt',
          'amount': 85,
          'pricingBreakdown': pricing()
        }
      };
    throw StateError('No provider session is allowed in this test');
  }
}

void main() {
  test('display selects only server-priced active automatic offer in Malaysia',
      () {
    final p = package();
    final offers = p['packagePricing']['offers'] as List;
    offers.addAll(<Map<String, dynamic>>[
      pricing(id: 'expired', finalAmount: 1, end: '2026-11-08'),
      pricing(id: 'future', finalAmount: 2, start: '2026-11-10'),
      pricing(id: 'coupon', finalAmount: 3, code: 'SAVE')
    ]);
    final now = DateTime.parse('2026-11-08T16:00:00Z');
    expect(PackagePricing.current(p, now: now)!['finalPayable'], 85);
    expect(
        PackagePricing.current(p,
            now: DateTime.parse('2100-01-01'))!['finalPayable'],
        100);
    expect(PackagePricing.label(p), contains('was 100.00'));
  });
  test('legacy manual fields never imply campaign savings', () {
    final p = PublicContentContract.package({
      'adultPrice': 100,
      'promotionalPrice': 1,
      'originalPrice': 999,
      'promotionStart': '2020-01-01',
      'promotionEnd': '2099-01-01'
    });
    expect(p.containsKey('promotionalPrice'), isFalse);
    expect(PackagePricing.label(p), contains('100.00'));
    expect(PackagePricing.label(p), isNot(contains('was')));
  });
  test('minimum-party display keeps total basis rather than fake unit rate',
      () {
    final p = package();
    p['packagePricing']['base']['participants'] = {'adults': 4, 'children': 0};
    p['packagePricing']['offers'][0]
        ['participants'] = {'adults': 4, 'children': 0};
    expect(PackagePricing.label(p), contains('/ 4 adults'));
  });
  testWidgets(
      'refresh price and checkout use quote token without client amount',
      (tester) async {
    tester.view.physicalSize = const Size(900, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = OfferApi();
    await tester.pumpWidget(MaterialApp(
        home: TourismPackageDetailsScreen(item: package(), api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('was 100.00'), findsOneWidget);
    await tester.tap(find.text('Select travellers & date'));
    await tester.pumpAndSettle();
    final refresh = find.byKey(const ValueKey('refresh-package-price'));
    await tester.ensureVisible(refresh);
    await tester.tap(refresh);
    await tester.pumpAndSettle();
    expect(api.calls.last, endsWith('/quote'));
    expect(find.text('Group total: MYR 85'), findsOneWidget);
    expect(find.textContaining('Standard package inclusions apply.'),
        findsWidgets);
    final checkout = find.byKey(const ValueKey('package-checkout-btn'));
    await tester.ensureVisible(checkout);
    await tester.tap(checkout);
    await tester.pumpAndSettle();
    expect(api.bodies.last['quoteToken'], 'authoritative-token');
    expect(api.bodies.last.containsKey('amount'), isFalse);
    expect(api.calls.where((x) => x.contains('/checkout/session')), isEmpty);
    expect(find.text('Final payable: MYR 85.00'), findsOneWidget);
  });
  testWidgets('automatic offer details remain readable at narrow width',
      (tester) async {
    tester.view.physicalSize = const Size(360, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final p = package();
    await tester.pumpWidget(MaterialApp(
        home: CampaignDetailsScreen(item: {
      'campaignTitle': 'Heritage saving',
      'discountType': 'percentage',
      'discountValue': 15,
      'startDate': '2020-01-01',
      'endDate': '2099-01-01',
      'packagePricing': p['packagePricing']
    })));
    await tester.pumpAndSettle();
    expect(find.textContaining('Applied automatically'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
      'changing participants automatically loads their authoritative total',
      (tester) async {
    tester.view.physicalSize = const Size(900, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = OfferApi();
    await tester.pumpWidget(MaterialApp(
        home: TourismPackageDetailsScreen(item: package(), api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Select travellers & date'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('package-adults-add')));
    await tester.pumpAndSettle();
    expect(api.bodies.last['participants'], {'adults': 2, 'children': 0});
    expect(api.calls.last, endsWith('/quote'));
    expect(find.text('Group total: MYR 170'), findsOneWidget);
    expect(find.text('Promotional savings: MYR 30'), findsOneWidget);
    expect(
        api.calls.where((path) => path.contains('/checkout/session')), isEmpty);
  });
}
