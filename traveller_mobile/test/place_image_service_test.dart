import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/place_image_service.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

final Uint8List kTestPngBytes = Uint8List.fromList(<int>[
  0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
  0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
  0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00,
  0x0A, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
  0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49,
  0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
]);

class MockTestHttpOverrides extends HttpOverrides {
  static final Map<String, List<int>> urlResponses = <String, List<int>>{};
  static final Set<String> failingUrls = <String>{};
  static final List<String> requestedUrls = <String>[];

  static void reset() {
    urlResponses.clear();
    failingUrls.clear();
    requestedUrls.clear();
    failingUrls.addAll(['broken', 'unavailable', 'fabricated']);
  }

  @override
  HttpClient createHttpClient(SecurityContext? context) {
    return _MockTestHttpClient();
  }
}

class _MockTestHttpClient implements HttpClient {
  _MockTestHttpClient();

  @override
  bool autoUncompress = true;
  @override
  Duration? connectionTimeout;
  @override
  Duration idleTimeout = const Duration(seconds: 15);
  @override
  int? maxConnectionsPerHost;
  @override
  String? userAgent;

  @override
  Future<HttpClientRequest> getUrl(Uri url) async {
    MockTestHttpOverrides.requestedUrls.add(url.toString());
    return _MockTestHttpClientRequest(url);
  }

  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async {
    MockTestHttpOverrides.requestedUrls.add(url.toString());
    return _MockTestHttpClientRequest(url);
  }

  @override
  void close({bool force = false}) {}

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _MockTestHttpClientRequest implements HttpClientRequest {
  final Uri url;
  _MockTestHttpClientRequest(this.url);

  @override
  final HttpHeaders headers = _MockTestHttpHeaders();

  @override
  Future addStream(Stream<List<int>> stream) => Future<void>.value();

  @override
  Future flush() => Future<void>.value();

  @override
  Future<HttpClientResponse> get done => close();

  @override
  void add(List<int> data) {}

  @override
  void write(Object? object) {}

  @override
  void writeAll(Iterable objects, [String separator = ""]) {}

  @override
  void writeln([Object? object = ""]) {}

  @override
  void writeCharCode(int charCode) {}

  @override
  Encoding encoding = utf8;

  @override
  Future<HttpClientResponse> close() async {
    final urlStr = url.toString();
    final isFailing = MockTestHttpOverrides.failingUrls.contains(urlStr) ||
        MockTestHttpOverrides.failingUrls.contains('*') ||
        MockTestHttpOverrides.failingUrls.any((f) => urlStr.contains(f));

    if (isFailing) {
      return _MockTestHttpClientResponse(statusCode: 404, body: const []);
    }

    for (final entry in MockTestHttpOverrides.urlResponses.entries) {
      if (urlStr == entry.key ||
          urlStr.contains(entry.key) ||
          entry.key.contains(url.path)) {
        return _MockTestHttpClientResponse(statusCode: 200, body: entry.value);
      }
    }

    // Default response for Wikipedia API queries is empty JSON (not image bytes)
    if (url.host.contains('wikipedia.org')) {
      final emptyJson = utf8.encode(jsonEncode({
        'title': '',
        'query': {'pages': []},
      }));
      return _MockTestHttpClientResponse(statusCode: 200, body: emptyJson);
    }

    return _MockTestHttpClientResponse(statusCode: 200, body: kTestPngBytes);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _MockTestHttpClientResponse extends Stream<List<int>>
    implements HttpClientResponse {
  @override
  final int statusCode;
  final List<int> body;
  _MockTestHttpClientResponse({required this.statusCode, required this.body});

  @override
  int get contentLength => body.length;

  @override
  String get reasonPhrase => 'OK';

  @override
  bool get isRedirect => false;

  @override
  bool get persistentConnection => false;

  @override
  List<RedirectInfo> get redirects => const <RedirectInfo>[];

  @override
  List<Cookie> get cookies => const <Cookie>[];

  @override
  HttpClientResponseCompressionState get compressionState =>
      HttpClientResponseCompressionState.notCompressed;

  @override
  final HttpHeaders headers = _MockTestHttpHeaders();

  @override
  StreamSubscription<List<int>> listen(
    void Function(List<int> event)? onData, {
    Function? onError,
    void Function()? onDone,
    bool? cancelOnError,
  }) {
    return Stream<List<int>>.value(body).listen(
      onData,
      onError: onError,
      onDone: onDone,
      cancelOnError: cancelOnError,
    );
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _MockTestHttpHeaders implements HttpHeaders {
  @override
  List<String>? operator [](String name) => const [];

  @override
  String? value(String name) => null;

  @override
  void add(String name, Object value, {bool preserveHeaderCase = false}) {}

  @override
  void set(String name, Object value, {bool preserveHeaderCase = false}) {}

  @override
  void forEach(void Function(String name, List<String> values) action) {}

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

Future<void> pumpTravelImage(
  WidgetTester tester, {
  Duration duration = const Duration(milliseconds: 50),
  int steps = 15,
}) async {
  for (int i = 0; i < steps; i++) {
    await tester.pump(duration);
  }
}

void main() {
  setUp(() {
    PlaceImageService.resetForTesting();
    PaintingBinding.instance.imageCache.clear();
    PaintingBinding.instance.imageCache.clearLiveImages();
    MockTestHttpOverrides.reset();
    HttpOverrides.global = MockTestHttpOverrides();
  });

  tearDown(() {
    HttpOverrides.global = null;
  });

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

  test('markFailedAndResolve skips failed candidate and advances immediately',
      () async {
    final place = <String, dynamic>{
      'destinationId': 'auto-advance-place',
      'photos': [
        'https://images.example/broken1.jpg',
        'https://images.example/candidate2.jpg',
      ],
    };

    expect(await PlaceImageService.resolve(place),
        'https://images.example/broken1.jpg');
    expect(
      await PlaceImageService.markFailedAndResolve(
        place,
        failedUrl: 'https://images.example/broken1.jpg',
      ),
      'https://images.example/candidate2.jpg',
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
        'Petronas Twin Towers & KLCC',
        'Petronas Towers',
      ),
      isTrue,
    );
    expect(
      PlaceImageService.searchIdentityMatchesForTesting(
        'Batu Caves Temple',
        'Batu Caves',
      ),
      isTrue,
    );
    expect(
      PlaceImageService.searchIdentityMatchesForTesting(
        'Merdeka Square & Sultan Abdul Samad Building',
        'Merdeka Square, Kuala Lumpur',
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

  test('Wikipedia logo and SVG-derived candidates are rejected in summary resolution',
      () {
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting(
        'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Petronas_Towers_Logo.svg/320px-Petronas_Towers_Logo.svg.png',
      ),
      isTrue,
    );
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting('Petronas_Towers_Logo.svg'),
      isTrue,
    );
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting('File:Flag_of_Malaysia.svg'),
      isTrue,
    );
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting('File:Location_map_Malaysia.png'),
      isTrue,
    );
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting('File:Kuala_Lumpur_transit_map.png'),
      isTrue,
    );
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting('File:Coat_of_arms_of_Malaysia.png'),
      isTrue,
    );

    final resolved = PlaceImageService.wikipediaSummaryImagesForTesting(
      'Petronas Towers',
      {
        'title': 'Petronas Towers',
        'thumbnail': {
          'source':
              'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Petronas_Towers_Logo.svg/320px-Petronas_Towers_Logo.svg.png',
        },
        'originalimage': {
          'source':
              'https://upload.wikimedia.org/wikipedia/commons/c/c3/Petronas_Towers_Logo.svg',
        },
      },
    );

    expect(resolved, isEmpty);
  });

  test('genuine verified attraction photographs are accepted by photo filter', () {
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting(
        'File:Petronas twin towers at night.jpg',
      ),
      isFalse,
    );
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting(
        'File:Gombak Selangor Batu-Caves-01.jpg',
      ),
      isFalse,
    );
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting(
        'File:Kuala Lumpur Malaysia Sultan-Abdul-Samad-Building-01.jpg',
      ),
      isFalse,
    );
    expect(
      PlaceImageService.looksLikeNonPhotoForTesting(
        'https://upload.wikimedia.org/wikipedia/commons/b/b8/File:Penang_Hill.jpg',
      ),
      isFalse,
    );
  });

  test('existing three priority photos remain eligible and preferred', () async {
    final klccPlace = <String, dynamic>{
      'destinationId': 'local_klcc',
      'title': 'Petronas Twin Towers & KLCC',
      'imageUrl':
          'https://upload.wikimedia.org/wikipedia/commons/8/85/Petronas_twin_towers_at_night.jpg',
    };
    final batuPlace = <String, dynamic>{
      'destinationId': 'local_batu_caves',
      'title': 'Batu Caves Temple',
      'imageUrl':
          'https://upload.wikimedia.org/wikipedia/commons/0/00/Gombak_Selangor_Batu-Caves-01.jpg',
    };
    final merdekaPlace = <String, dynamic>{
      'destinationId': 'local_merdeka_square',
      'title': 'Merdeka Square & Sultan Abdul Samad Building',
      'imageUrl':
          'https://upload.wikimedia.org/wikipedia/commons/4/4c/Kuala_Lumpur_Malaysia_Sultan-Abdul-Samad-Building-01.jpg',
    };

    expect(
      await PlaceImageService.resolve(klccPlace),
      'https://upload.wikimedia.org/wikipedia/commons/8/85/Petronas_twin_towers_at_night.jpg',
    );
    expect(
      await PlaceImageService.resolve(batuPlace),
      'https://upload.wikimedia.org/wikipedia/commons/0/00/Gombak_Selangor_Batu-Caves-01.jpg',
    );
    expect(
      await PlaceImageService.resolve(merdekaPlace),
      'https://upload.wikimedia.org/wikipedia/commons/4/4c/Kuala_Lumpur_Malaysia_Sultan-Abdul-Samad-Building-01.jpg',
    );
  });

  test('existing successful provider image remains preferred over fallback',
      () async {
    const providerPhoto = 'https://images.example/google-places-lead.jpg';
    final place = <String, dynamic>{
      'destinationId': 'google_penang_hill',
      'title': 'Penang Hill',
      'imageUrl': providerPhoto,
    };

    final resolved = await PlaceImageService.resolve(place);
    expect(resolved, providerPhoto);
  });

  test('destination with null image URLs advances directly to dynamic fallback',
      () async {
    MockTestHttpOverrides.urlResponses['Kek'] = utf8.encode(jsonEncode({
      'title': 'Kek Lok Si',
      'thumbnail': {
        'source': 'https://images.example/kek-lok-si-wiki.jpg',
      },
    }));

    final place = <String, dynamic>{
      'destinationId': 'kek_lok_si_null_images',
      'title': 'Kek Lok Si Temple',
      'imageUrl': null,
      'thumbnail': null,
    };

    final resolved = await PlaceImageService.resolve(place);
    expect(resolved, 'https://images.example/kek-lok-si-wiki.jpg');
  });

  testWidgets('valid explicit image succeeds without showing fallback placeholder',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(
            place: <String, dynamic>{
              'destinationId': 'valid-explicit-dest',
              'imageUrl': 'https://images.example/valid-photo.jpg',
            },
          ),
        ),
      ),
    );
    await pumpTravelImage(tester);

    expect(find.byType(Image), findsOneWidget);
    expect(find.byKey(const ValueKey('place-image-retry')), findsNothing);
  });

  testWidgets('invalid explicit image advances to fallback candidate automatically',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(
            place: <String, dynamic>{
              'destinationId': 'broken-to-fallback-dest',
              'photos': [
                'https://images.example/broken-lead.jpg',
                'https://images.example/working-secondary.jpg',
              ],
            },
          ),
        ),
      ),
    );
    await pumpTravelImage(tester);

    expect(find.byType(Image), findsOneWidget);
    final imageWidget = tester.widget<Image>(find.byType(Image));
    expect(
      (imageWidget.image as NetworkImage).url,
      'https://images.example/working-secondary.jpg',
    );
  });

  testWidgets('two broken explicit URLs advance and do not create infinite retry loop',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(
            place: <String, dynamic>{
              'destinationId': 'two-broken-urls-dest',
              'thumbnail': 'https://images.example/broken-thumb.jpg',
              'imageUrl': 'https://images.example/broken-full.jpg',
              'title': 'Nonexistent Place ABCXYZ',
            },
          ),
        ),
      ),
    );
    await pumpTravelImage(tester);

    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
    expect(find.byType(Image), findsNothing);
  });

  testWidgets('historical chat entry with broken URLs recovers candidate',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(
            place: <String, dynamic>{
              'destinationId': 'hist_chat_card',
              'title': 'Batu Caves Temple',
              'address': 'Gombak, Selangor',
              'imageUrl':
                  'https://upload.wikimedia.org/fabricated/broken_batu.jpg',
              'thumbnail': 'https://images.example/batu-caves-recovered.jpg',
            },
          ),
        ),
      ),
    );
    await pumpTravelImage(tester);

    expect(find.byType(Image), findsOneWidget);
    final imageWidget = tester.widget<Image>(find.byType(Image));
    expect(
      (imageWidget.image as NetworkImage).url,
      'https://images.example/batu-caves-recovered.jpg',
    );
  });

  testWidgets('all image candidates fail results in stable placeholder with retry action',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(
            place: <String, dynamic>{
              'destinationId': 'all-fail-dest',
              'imageUrl': 'https://images.example/broken-only.jpg',
            },
          ),
        ),
      ),
    );
    await pumpTravelImage(tester);

    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
    expect(find.byType(Image), findsNothing);
  });

  testWidgets('rebuilding widget does not trigger repeated network resolution',
      (tester) async {
    final place = <String, dynamic>{
      'destinationId': 'rebuild-test-dest',
      'imageUrl': 'https://images.example/stable-rebuild.jpg',
    };

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(place: place),
        ),
      ),
    );
    await pumpTravelImage(tester);

    final initialCount = MockTestHttpOverrides.requestedUrls.length;

    // Trigger parent rebuild with same destination identity
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(place: Map<String, dynamic>.from(place)),
        ),
      ),
    );
    await pumpTravelImage(tester);

    expect(MockTestHttpOverrides.requestedUrls.length, initialCount);
    expect(find.byType(Image), findsOneWidget);
  });

  testWidgets('destination change resets resolution state for new destination',
      (tester) async {
    final placeA = <String, dynamic>{
      'destinationId': 'dest_alpha',
      'imageUrl': 'https://images.example/broken-alpha.jpg',
    };
    final placeB = <String, dynamic>{
      'destinationId': 'dest_beta',
      'imageUrl': 'https://images.example/working-beta.jpg',
    };

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(place: placeA),
        ),
      ),
    );
    await pumpTravelImage(tester);
    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);

    // Switch to Destination B
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(place: placeB),
        ),
      ),
    );
    await pumpTravelImage(tester);

    expect(find.byType(Image), findsOneWidget);
    final imageWidget = tester.widget<Image>(find.byType(Image));
    expect(
      (imageWidget.image as NetworkImage).url,
      'https://images.example/working-beta.jpg',
    );
  });

  testWidgets('different destinations do not share failure state', (tester) async {
    final place1 = <String, dynamic>{
      'destinationId': 'dest_one',
      'imageUrl': 'https://images.example/broken-dest-one.jpg',
    };
    final place2 = <String, dynamic>{
      'destinationId': 'dest_two',
      'imageUrl': 'https://images.example/dest-two-photo.jpg',
    };

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              TravelPlaceImage(place: place1),
              TravelPlaceImage(place: place2),
            ],
          ),
        ),
      ),
    );
    await pumpTravelImage(tester);

    // Place 1 failed to stable placeholder
    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
    // Place 2 succeeded
    expect(find.byType(Image), findsOneWidget);
    final imageWidget = tester.widget<Image>(find.byType(Image));
    expect(
      (imageWidget.image as NetworkImage).url,
      'https://images.example/dest-two-photo.jpg',
    );
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
    await pumpTravelImage(tester);

    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
  });

  testWidgets('manual retry on placeholder re-attempts image after network recovers',
      (tester) async {
    const testUrl = 'https://images.example/temporary-offline.jpg';
    MockTestHttpOverrides.failingUrls.add(testUrl);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(
            place: <String, dynamic>{
              'destinationId': 'retry-recover-dest',
              'imageUrl': testUrl,
            },
          ),
        ),
      ),
    );
    await pumpTravelImage(tester);

    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
    expect(find.byType(Image), findsNothing);

    // Simulate network restored
    MockTestHttpOverrides.failingUrls.remove(testUrl);

    await tester.tap(find.byKey(const ValueKey('place-image-retry')));
    await pumpTravelImage(tester);

    expect(find.byType(Image), findsOneWidget);
    final imageWidget = tester.widget<Image>(find.byType(Image));
    expect((imageWidget.image as NetworkImage).url, testUrl);
  });

  testWidgets('retry attempts are strictly bounded to maximum attempts',
      (tester) async {
    final place = <String, dynamic>{
      'destinationId': 'five-broken-urls-dest',
      'photos': [
        'https://images.example/broken-1.jpg',
        'https://images.example/broken-2.jpg',
        'https://images.example/broken-3.jpg',
        'https://images.example/broken-4.jpg',
        'https://images.example/broken-5.jpg',
      ],
    };

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TravelPlaceImage(place: place),
        ),
      ),
    );
    await pumpTravelImage(tester, steps: 20);

    // After exhausting bounded auto-retries, settles on stable neutral placeholder
    expect(find.byKey(const ValueKey('place-image-retry')), findsOneWidget);
    expect(find.byType(Image), findsNothing);
  });
}
