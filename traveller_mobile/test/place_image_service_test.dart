import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/place_image_service.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

void main() {
  test('maps nested provider photo lists without inventing image URLs', () {
    final urls = PlaceImageService.explicitImageUrlsForTesting({
      'destinationId': 'penang_hill',
      'photos': [
        {'thumbnail': 'https://images.example/thumb.jpg'},
        {'image': 'https://images.example/full.jpg'},
      ],
      'images': [
        {'url': 'https://images.example/gallery.jpg'},
      ],
      'photo': 'not-a-url',
    });

    expect(urls, [
      'https://images.example/thumb.jpg',
      'https://images.example/full.jpg',
      'https://images.example/gallery.jpg',
    ]);
  });

  test('failed provider image retries the next candidate', () async {
    final place = <String, dynamic>{
      'destinationId': 'retry-place',
      'photos': [
        'https://images.example/broken.jpg',
        'https://images.example/working.jpg',
      ],
    };

    expect(await PlaceImageService.resolve(place),
        'https://images.example/broken.jpg');
    expect(
      await PlaceImageService.retry(
        place,
        failedUrl: 'https://images.example/broken.jpg',
      ),
      'https://images.example/working.jpg',
    );
  });

  test('a sole failed URL is retried once, then exhausted', () async {
    final place = <String, dynamic>{
      'destinationId': 'transient-retry-place',
      'imageUrl': 'https://images.example/temporary.jpg',
    };

    expect(await PlaceImageService.resolve(place),
        'https://images.example/temporary.jpg');
    expect(
      await PlaceImageService.retry(
        place,
        failedUrl: 'https://images.example/temporary.jpg',
      ),
      'https://images.example/temporary.jpg',
    );
    expect(
      await PlaceImageService.retry(
        place,
        failedUrl: 'https://images.example/temporary.jpg',
      ),
      isNull,
    );
  });

  test('legacy Trip activity names retain explicit saved images', () async {
    final place = <String, dynamic>{
      'activityName': 'Legacy Penang Hill visit',
      'imageUrl': 'https://images.example/legacy-penang-hill.jpg',
    };

    expect(await PlaceImageService.resolve(place),
        'https://images.example/legacy-penang-hill.jpg');
  });

  test('known place aliases can share an authoritative image across IDs',
      () async {
    const image = 'https://images.example/george-town-shared.jpg';
    expect(
      await PlaceImageService.resolve({
        'destinationId': 'provider_george_town',
        'title': 'George Town UNESCO Heritage Area',
        'imageUrl': image,
      }),
      image,
    );
    expect(
      await PlaceImageService.resolve({
        'destinationId': 'local_george_town',
        'activityName': 'George Town Heritage Core',
        'imageUrl': image,
      }),
      image,
    );
  });

  test('a missing image is not cached permanently', () async {
    expect(
      await PlaceImageService.resolve({'destinationId': 'late-image'}),
      isNull,
    );
    expect(
      await PlaceImageService.resolve({
        'destinationId': 'late-image',
        'imageUrl': 'https://images.example/later.jpg',
      }),
      'https://images.example/later.jpg',
    );
  });

  test('fallback search candidates must match the place identity', () {
    expect(
      PlaceImageService.searchIdentityMatchesForTesting(
        'Kek Lok Si',
        'File:Kek Lok Si Temple Penang.jpg',
      ),
      isTrue,
    );
    expect(
      PlaceImageService.searchIdentityMatchesForTesting(
        'Kek Lok Si',
        'File:Unrelated Malaysian beach.jpg',
      ),
      isFalse,
    );
  });

  test('known legacy place uses an identity-checked Wikipedia summary image',
      () async {
    final resolved = PlaceImageService.wikipediaSummaryImagesForTesting(
      'George Town, Penang',
      {
        'title': 'George Town, Penang',
        'thumbnail': {
          'source': 'https://images.example/george-town.jpg',
        },
      },
    );

    expect(resolved, ['https://images.example/george-town.jpg']);
    expect(
      PlaceImageService.wikipediaSummaryImagesForTesting(
        'George Town, Penang',
        {
          'title': 'Unrelated Beach',
          'thumbnail': {'source': 'https://images.example/unrelated.jpg'},
        },
      ),
      isEmpty,
    );
  });

  testWidgets('unavailable place image shows a retry action', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(
            place: <String, dynamic>{'destinationId': 'no-image'},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('place-image-retry')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
  });

  testWidgets('compact legacy trip image fallback does not overflow',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(
            width: 70,
            height: 70,
            place: <String, dynamic>{'destinationId': 'legacy-no-photo'},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
  });

  testWidgets('retry rebuilds a sole failed network image', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 120,
            height: 120,
            child: TravelPlaceImage(
              place: <String, dynamic>{
                'destinationId': 'widget-transient-retry',
                'imageUrl': 'http://127.0.0.1:9/unavailable.jpg',
              },
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final first = tester.widget<Image>(find.byType(Image));
    final firstKey = first.key;

    await tester.tap(find.byKey(const ValueKey('place-image-retry')));
    await tester.pumpAndSettle();
    final retried = tester.widget<Image>(find.byType(Image));

    expect(retried.key, isNot(firstKey));
    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
  });
}
