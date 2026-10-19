import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/core/operator_content/package_gallery_viewer.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

class _MockGalleryApi extends ApiService {
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr9/orders') {
      return {'ok': true, 'items': []};
    }
    return {'ok': true, 'items': []};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    return {'ok': true, 'attempt': <String, dynamic>{}};
  }
}

const _basePackage = <String, dynamic>{
  'id': 'pkg-penang-gallery',
  'title': 'Penang Heritage & Gourmet Tour',
  'destination': 'George Town, Penang',
  'durationDays': 2,
  'durationNights': 1,
  'currency': 'MYR',
  'priceBasis': 'per_person',
  'adultPrice': 350.0,
  'childPrice': 180.0,
  'departureDates': ['2027-04-10'],
  'fullDescription': 'Explore vibrant street art and authentic culinary heritage.',
};

void main() {
  test('extractPhotos filters duplicates, invalid URLs, and preserves ordering', () {
    final item = {
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': [
        'https://example.com/cover.jpg', // Duplicate of cover
        'https://example.com/g1.jpg',
        'https://example.com/g2.jpg',
        'https://example.com/g1.jpg', // Duplicate gallery
        'invalid-url-string',
        '',
        'http://172.20.10.5:5000/api/public/package-images/pkg_photo.jpg',
      ],
    };

    final photos = PackageGalleryCarousel.extractPhotos(item);

    expect(photos, [
      'https://example.com/cover.jpg',
      'https://example.com/g1.jpg',
      'https://example.com/g2.jpg',
      'http://172.20.10.5:5000/api/public/package-images/pkg_photo.jpg',
    ]);
  });

  testWidgets('1. Package with Cover and three Gallery images renders carousel and counter',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': [
        'https://example.com/g1.jpg',
        'https://example.com/g2.jpg',
        'https://example.com/g3.jpg',
      ],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    // Carousel is present
    expect(find.byKey(const ValueKey('package-gallery-carousel')), findsOneWidget);

    // Counter displays 1/4
    expect(find.byKey(const ValueKey('package-gallery-counter')), findsOneWidget);
    expect(find.text('1/4'), findsOneWidget);

    // All slides are present in PageView
    expect(find.byKey(const ValueKey('package-gallery-slide-0')), findsOneWidget);
  });

  testWidgets('2. Cover-only Package renders cover without gallery controls',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': <String>[],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    // Cover image is present
    expect(find.byKey(const ValueKey('package-cover-image')), findsOneWidget);

    // No carousel PageView and NO gallery counter controls
    expect(find.byKey(const ValueKey('package-gallery-carousel')), findsNothing);
    expect(find.byKey(const ValueKey('package-gallery-counter')), findsNothing);
  });

  testWidgets('3. No valid image URLs falls back gracefully to TravelPlaceImage',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': '',
      'imageUrl': '',
      'galleryImages': [],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    // Standard TravelPlaceImage fallback is rendered
    expect(find.byType(TravelPlaceImage), findsOneWidget);
    expect(find.byKey(const ValueKey('package-gallery-carousel')), findsNothing);
    expect(find.byKey(const ValueKey('package-gallery-counter')), findsNothing);
  });

  testWidgets('4. Duplicate image URLs are filtered and deduplicated',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/repeated.jpg',
      'galleryImages': [
        'https://example.com/repeated.jpg',
        'https://example.com/photo2.jpg',
        'https://example.com/repeated.jpg',
      ],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    // 2 unique images => counter shows 1/2
    expect(find.byKey(const ValueKey('package-gallery-counter')), findsOneWidget);
    expect(find.text('1/2'), findsOneWidget);
  });

  testWidgets('5. Gallery item ordering is strictly preserved and swiping updates counter',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': [
        'https://example.com/photoA.jpg',
        'https://example.com/photoB.jpg',
      ],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    expect(find.text('1/3'), findsOneWidget);

    // Swipe left to advance to next photo
    await tester.fling(
      find.byKey(const ValueKey('package-gallery-carousel')),
      const Offset(-400, 0),
      1000,
    );
    await tester.pumpAndSettle();

    // Counter updates to 2/3
    expect(find.text('2/3'), findsOneWidget);
  });

  testWidgets('6. Tapping an image opens the Fullscreen viewer with pinch-to-zoom and counter',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': [
        'https://example.com/g1.jpg',
        'https://example.com/g2.jpg',
      ],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    // Tap first slide to open fullscreen viewer
    await tester.tap(find.byKey(const ValueKey('package-gallery-slide-0')));
    await tester.pumpAndSettle();

    // Fullscreen viewer is active
    expect(find.byType(PackageGalleryFullscreenViewer), findsOneWidget);
    expect(find.byKey(const ValueKey('gallery-fullscreen-pageview')), findsOneWidget);
    expect(find.byKey(const ValueKey('gallery-fullscreen-close')), findsOneWidget);
    expect(find.byKey(const ValueKey('gallery-fullscreen-counter')), findsOneWidget);
    expect(find.text('1 / 3'), findsOneWidget);

    // InteractiveViewer is present for pinch-to-zoom
    expect(find.byType(InteractiveViewer), findsOneWidget);
  });

  testWidgets('7. Fullscreen viewer close button dismisses back to details screen',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': ['https://example.com/g1.jpg'],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    // Open fullscreen
    await tester.tap(find.byKey(const ValueKey('package-gallery-slide-0')));
    await tester.pumpAndSettle();
    expect(find.byType(PackageGalleryFullscreenViewer), findsOneWidget);

    // Tap close button
    await tester.tap(find.byKey(const ValueKey('gallery-fullscreen-close')));
    await tester.pumpAndSettle();

    // Fullscreen viewer is dismissed, back on details screen
    expect(find.byType(PackageGalleryFullscreenViewer), findsNothing);
    expect(find.byType(TourismPackageDetailsScreen), findsOneWidget);
  });

  testWidgets('8. Image load failure fallback displays placeholder gracefully without crashing',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: PackageGalleryCarousel(
          photos: ['http://127.0.0.1:9/broken_image.jpg'],
          title: 'Test Package',
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('package-cover-image')), findsOneWidget);
  });

  testWidgets('9. Booking Bottom Sheet still opens smoothly with gallery present',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': ['https://example.com/g1.jpg'],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    // Tap booking action button
    final ctaFinder = find.byKey(const ValueKey('package-book-now-cta'));
    expect(ctaFinder, findsOneWidget);
    await tester.tap(ctaFinder);
    await tester.pumpAndSettle();

    // Modal is opened
    expect(find.text('Select Travellers & Date'), findsOneWidget);
    expect(find.text('Adults: 1'), findsOneWidget);
  });

  testWidgets('10. Pricing and departure controls remain fully functional with gallery present',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': ['https://example.com/g1.jpg'],
    });

    await tester.pumpWidget(MaterialApp(
      home: TourismPackageDetailsScreen(item: item, api: api),
    ));
    await tester.pumpAndSettle();

    // Check pricing display
    expect(find.text('MYR 350'), findsAtLeastNWidgets(1));

    // Open modal and change adult count
    await tester.tap(find.byKey(const ValueKey('package-book-now-cta')));
    await tester.pumpAndSettle();

    // Increment adults (from 1 to 2) using exact button key
    final addAdult = find.byKey(const ValueKey('package-adults-add'));
    expect(addAdult, findsOneWidget);
    await tester.tap(addAdult);
    await tester.pumpAndSettle();

    expect(find.text('Adults: 2'), findsOneWidget);
    expect(find.text('Group total: MYR 700'), findsOneWidget);
  });

  testWidgets('11. Responsive layout prevents overflow across 360px, 390px, 412px and 440px widths',
      (tester) async {
    final api = _MockGalleryApi();
    final item = Map<String, dynamic>.from(_basePackage)..addAll({
      'heroImage': 'https://example.com/cover.jpg',
      'galleryImages': [
        'https://example.com/g1.jpg',
        'https://example.com/g2.jpg',
        'https://example.com/g3.jpg',
      ],
    });

    for (final width in [360.0, 390.0, 412.0, 440.0]) {
      tester.view.physicalSize = Size(width, 2400);
      tester.view.devicePixelRatio = 1.0;

      await tester.pumpWidget(MaterialApp(
        theme: ThemeData(useMaterial3: true),
        home: MediaQuery(
          data: MediaQueryData(
            size: Size(width, 2400),
            textScaler: const TextScaler.linear(1.5),
          ),
          child: TourismPackageDetailsScreen(
            key: ValueKey('gallery_responsive_$width'),
            item: item,
            api: api,
          ),
        ),
      ));
      await tester.pumpAndSettle();

      final error = tester.takeException();
      expect(error, isNull, reason: 'Overflow occurred at width $width');
      expect(find.byKey(const ValueKey('package-gallery-carousel')), findsOneWidget);
    }

    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
}
