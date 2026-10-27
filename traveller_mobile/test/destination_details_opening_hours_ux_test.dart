import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/opening_hours_utils.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

class _MockDetailsApi extends ApiService {
  final Map<String, dynamic> Function(String path) handler;

  _MockDetailsApi(this.handler);

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    return handler(path);
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    return {'ok': true};
  }
}

Widget _app(Widget home) => MaterialApp(
      theme: buildInkWashTheme(),
      home: home,
    );

Future<void> _pumpDestination(
  WidgetTester tester, {
  required Map<String, dynamic> initial,
  required ApiService api,
  double textScaleFactor = 1.0,
}) async {
  tester.view.physicalSize = const Size(430, 950);
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = textScaleFactor;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.platformDispatcher.clearTextScaleFactorTestValue();
  });

  await tester.pumpWidget(_app(
    DestinationDetailsScreen(
      initialDestination: initial,
      api: api,
    ),
  ));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 150));
}

Finder _verticalScroll() => find.byWidgetPredicate(
      (widget) =>
          widget is Scrollable && widget.axisDirection == AxisDirection.down,
    );

Future<void> _scrollIntoView(WidgetTester tester, Finder finder) async {
  final scrollable = _verticalScroll();
  if (scrollable.evaluate().isNotEmpty) {
    await tester.scrollUntilVisible(
      finder,
      250,
      scrollable: scrollable.first,
      maxScrolls: 20,
    );
    await tester.pump();
  }
}

void main() {
  group('Batch 21E-D1: Destination Details Opening Hours & Fallback UX', () {
    // 1. Complete weekly hours
    testWidgets('1. Complete weekly hours renders 7-day Monday to Sunday timetable', (tester) async {
      final initial = {
        'id': 'place_weekly',
        'title': 'Kek Lok Si Temple',
        'address': 'Air Itam, Penang',
        'weeklyHours': {
          'Monday': '9:00 AM – 6:00 PM',
          'Tuesday': '9:00 AM – 6:00 PM',
          'Wednesday': '9:00 AM – 6:00 PM',
          'Thursday': '9:00 AM – 6:00 PM',
          'Friday': '9:00 AM – 6:00 PM',
          'Saturday': '9:00 AM – 3:00 PM',
          'Sunday': 'Closed',
        },
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'serpapi',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      expect(find.text('Visit information'), findsOneWidget);
      expect(find.text('Weekly schedule'), findsOneWidget);
      expect(find.text('Monday'), findsOneWidget);
      expect(find.text('Tuesday'), findsOneWidget);
      expect(find.text('Wednesday'), findsOneWidget);
      expect(find.text('Thursday'), findsOneWidget);
      expect(find.text('Friday'), findsOneWidget);
      expect(find.text('Saturday'), findsOneWidget);
      expect(find.text('Sunday'), findsOneWidget);
      expect(find.text('9:00 AM – 3:00 PM'), findsOneWidget);
      expect(find.text('Closed'), findsOneWidget);
      expect(find.text('Hours may change on public holidays.'), findsOneWidget);
    });

    // 2. Provider weekday string format
    testWidgets('2. Provider weekday string format parses weekday_text list', (tester) async {
      final initial = {
        'id': 'place_text',
        'title': 'Batu Caves',
        'address': 'Gombak, Selangor',
        'opening_hours': {
          'weekday_text': [
            'Monday: 7:00 AM – 9:00 PM',
            'Tuesday: 7:00 AM – 9:00 PM',
            'Wednesday: 7:00 AM – 9:00 PM',
            'Thursday: 7:00 AM – 9:00 PM',
            'Friday: 7:00 AM – 9:00 PM',
            'Saturday: 7:00 AM – 9:00 PM',
            'Sunday: 7:00 AM – 9:00 PM',
          ],
        },
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'serpapi',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      expect(find.text('Monday'), findsOneWidget);
      expect(find.text('Sunday'), findsOneWidget);
      expect(find.text('7:00 AM – 9:00 PM'), findsWidgets);
    });

    // 3. Single generic opening-hours string
    testWidgets('3. Single generic opening-hours string displays General opening hours', (tester) async {
      final initial = {
        'id': 'local_petronas',
        'title': 'Petronas Twin Towers',
        'address': 'Kuala Lumpur City Centre',
        'openingHours': '09:00-20:00',
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'local',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      expect(find.text('General opening hours'), findsOneWidget);
      expect(find.text('9:00 AM – 8:00 PM'), findsOneWidget);
      expect(find.text('Hours for individual days or holidays may vary.'), findsOneWidget);
      // Ensure it does NOT copy across all 7 days
      expect(find.text('Monday'), findsNothing);
      expect(find.text('Sunday'), findsNothing);
    });

    // 4. Missing opening hours
    testWidgets('4. Missing opening hours shows neutral not-available state', (tester) async {
      final initial = {
        'id': 'place_missing',
        'title': 'Hidden Gem Forest',
        'address': 'Pahang',
        'openingHours': 'Unavailable',
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'local',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      expect(find.text('Opening hours not available'), findsOneWidget);
      expect(find.text('Check with the attraction before visiting.'), findsOneWidget);
      expect(find.text('Monday'), findsNothing);
    });

    // 5. Explicitly closed day
    testWidgets('5. Explicitly closed day shows distinguishable closed style', (tester) async {
      final initial = {
        'id': 'place_closed',
        'title': 'National Art Gallery',
        'address': 'Kuala Lumpur',
        'weeklyHours': {
          'Monday': 'Closed',
          'Tuesday': '10:00 AM – 6:00 PM',
          'Wednesday': '10:00 AM – 6:00 PM',
          'Thursday': '10:00 AM – 6:00 PM',
          'Friday': '10:00 AM – 6:00 PM',
          'Saturday': '10:00 AM – 6:00 PM',
          'Sunday': '10:00 AM – 6:00 PM',
        },
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'serpapi',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      final closedWidget = tester.widget<Text>(find.text('Closed'));
      expect(closedWidget.style?.fontStyle, FontStyle.italic);
      expect(closedWidget.style?.color, AppColors.textSecondary);
    });

    // 6. Split opening periods
    testWidgets('6. Split opening periods format properly', (tester) async {
      final initial = {
        'id': 'place_split',
        'title': 'Heritage Bistro',
        'address': 'Melaka',
        'weeklyHours': {
          'Monday': '11:00-14:30, 17:30-22:00',
          'Tuesday': '11:00-14:30, 17:30-22:00',
          'Wednesday': '11:00-14:30, 17:30-22:00',
          'Thursday': '11:00-14:30, 17:30-22:00',
          'Friday': '11:00-14:30, 17:30-22:00',
          'Saturday': '11:00-14:30, 17:30-22:00',
          'Sunday': 'Closed',
        },
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'serpapi',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      expect(find.text('11:00 AM – 2:30 PM, 5:30 PM – 10:00 PM'), findsWidgets);
    });

    // 7. Overnight opening period
    testWidgets('7. Overnight opening period formats across midnight correctly', (tester) async {
      final initial = {
        'id': 'place_night',
        'title': 'Jalan Alor Night Market',
        'address': 'Bukit Bintang, Kuala Lumpur',
        'openingHours': '16:00-02:00',
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'local',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      expect(find.text('4:00 PM – 2:00 AM'), findsOneWidget);
    });

    // 8. Malformed provider hours
    testWidgets('8. Malformed provider hours handle corrupt data without crashing', (tester) async {
      final initial = {
        'id': 'place_malformed',
        'title': 'Corrupt Data Place',
        'address': 'Penang',
        'weeklyHours': {
          'bad_key': 999999,
          'nested': {'foo': 'bar'},
          'invalid': null,
        },
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'cache',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      // Graceful fallback to unavailable
      expect(find.text('Opening hours not available'), findsOneWidget);
    });

    // 9. Large-text layout
    testWidgets('9. Large-text layout scales without RenderFlex overflow', (tester) async {
      final initial = {
        'id': 'place_largetext',
        'title': 'Peranakan Mansion',
        'address': 'Church Street, George Town, Penang',
        'weeklyHours': {
          'Monday': '9:30 AM – 5:00 PM',
          'Tuesday': '9:30 AM – 5:00 PM',
          'Wednesday': '9:30 AM – 5:00 PM',
          'Thursday': '9:30 AM – 5:00 PM',
          'Friday': '9:30 AM – 5:00 PM',
          'Saturday': '9:30 AM – 5:00 PM',
          'Sunday': '9:30 AM – 5:00 PM',
        },
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'serpapi',
          });

      await _pumpDestination(tester, initial: initial, api: api, textScaleFactor: 2.0);

      expect(find.text('Peranakan Mansion'), findsOneWidget);

      await _scrollIntoView(tester, find.text('Visit information'));

      expect(tester.takeException(), isNull);
      expect(find.text('Monday'), findsOneWidget);
    });

    // 10. Current-day highlighting
    testWidgets('10. Current-day highlighting labels current Malaysia day with Today', (tester) async {
      final initial = {
        'id': 'place_today',
        'title': 'Aquaria KLCC',
        'address': 'Kuala Lumpur',
        'weeklyHours': {
          'Monday': '10:00 AM – 8:00 PM',
          'Tuesday': '10:00 AM – 8:00 PM',
          'Wednesday': '10:00 AM – 8:00 PM',
          'Thursday': '10:00 AM – 8:00 PM',
          'Friday': '10:00 AM – 8:00 PM',
          'Saturday': '10:00 AM – 8:00 PM',
          'Sunday': '10:00 AM – 8:00 PM',
        },
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'serpapi',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      final currentMalaysiaDay = OpeningHoursUtils.currentMalaysiaDay();
      expect(find.text(currentMalaysiaDay), findsOneWidget);
      expect(find.text('Today'), findsOneWidget);
    });

    // 11. Chatbot destination with valid local details and failed optional enrichment
    testWidgets('11. Chatbot destination with valid local details does NOT show yellow warning banner', (tester) async {
      final initial = {
        'id': 'local_batu_caves',
        'title': 'Batu Caves',
        'address': 'Gombak, Selangor',
        'category': 'Culture',
        'description': 'Limestone caves and Hindu shrine temple.',
        'openingHours': '06:00-21:00',
      };

      // Backend returns providerWarning because optional SerpApi lookup failed
      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'local',
            'providerWarning': 'SerpApi quota exceeded or key unavailable',
          });

      await _pumpDestination(tester, initial: initial, api: api);

      // Usable details render normally
      expect(find.text('Batu Caves'), findsOneWidget);
      expect(find.text('Gombak, Selangor'), findsWidgets);
      // Yellow warning banner MUST NOT be present
      expect(
        find.text('Some live details are unavailable. TravelMate is showing the reliable information already available.'),
        findsNothing,
      );
      // Neutral fallback attribution badge is present
      expect(find.text('Fallback source'), findsOneWidget);
    });

    // 12. Cached destination without provider data
    testWidgets('12. Cached destination renders normally without disruptive warning', (tester) async {
      final initial = {
        'id': 'cached_place',
        'title': 'Merdeka Square',
        'address': 'Kuala Lumpur',
        'category': 'Historical',
        'openingHours': 'Open 24 hours',
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'cache',
          });

      await _pumpDestination(tester, initial: initial, api: api);

      expect(find.text('Merdeka Square'), findsOneWidget);
      expect(find.text('Cached source'), findsOneWidget);
      expect(
        find.text('Some live details are unavailable. TravelMate is showing the reliable information already available.'),
        findsNothing,
      );
    });

    // 13. Genuine essential details failure
    testWidgets('13. Genuine essential details failure displays retryable error state', (tester) async {
      final initial = {
        'id': 'broken_id',
      };

      final api = _MockDetailsApi((path) {
        throw Exception('500 Internal Server Error');
      });

      await _pumpDestination(tester, initial: initial, api: api);

      expect(find.byType(AppErrorState), findsOneWidget);
      expect(find.text('Destination details unavailable'), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
    });

    // 14. Material pricing/booking warning preserved
    testWidgets('14. Material pricing/booking warning is preserved in Visit Information', (tester) async {
      final initial = {
        'id': 'place_with_warning',
        'title': 'Petronas Twin Towers Skybridge',
        'address': 'Kuala Lumpur',
        'openingHours': '09:00-20:00',
        'bookingWarning': 'Advance booking is required. Same-day tickets are limited.',
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'local',
          });

      await _pumpDestination(tester, initial: initial, api: api);
      await _scrollIntoView(tester, find.text('Visit information'));

      expect(
        find.text('Advance booking is required. Same-day tickets are limited.'),
        findsOneWidget,
      );
    });

    // 15. Chatbot-to-Destination Details navigation
    testWidgets('15. Chatbot-to-Destination Details preserves destination identity and back nav', (tester) async {
      final place = {
        'id': 'chatbot_sugg_1',
        'name': 'The TOP Penang',
        'location': 'George Town, Penang',
        'category': 'Sightseeing',
        'openingHours': '10:00-22:00',
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': place,
            'source': 'local',
          });

      await tester.pumpWidget(MaterialApp(
        theme: buildInkWashTheme(),
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: ElevatedButton(
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => DestinationDetailsScreen(
                      initialDestination: place,
                      api: api,
                    ),
                  ),
                ),
                child: const Text('Open Details'),
              ),
            ),
          ),
        ),
      ));

      await tester.tap(find.text('Open Details'));
      await tester.pumpAndSettle();

      expect(find.byType(DestinationDetailsScreen), findsOneWidget);
      expect(find.text('The TOP Penang'), findsOneWidget);

      await tester.pageBack();
      await tester.pumpAndSettle();

      expect(find.byType(DestinationDetailsScreen), findsNothing);
      expect(find.text('Open Details'), findsOneWidget);
    });

    // 16. Explore-to-Destination Details navigation
    testWidgets('16. Explore-to-Destination Details preserves identity and back nav', (tester) async {
      final place = {
        'destinationId': 'explore_place_2',
        'title': 'Penang Botanic Gardens',
        'address': 'George Town, Penang',
        'category': 'Nature',
        'openingHours': '05:00-20:00',
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': place,
            'source': 'local',
          });

      await tester.pumpWidget(MaterialApp(
        theme: buildInkWashTheme(),
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: ElevatedButton(
                onPressed: () => Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => DestinationDetailsScreen(
                      initialDestination: place,
                      api: api,
                    ),
                  ),
                ),
                child: const Text('View from Explore'),
              ),
            ),
          ),
        ),
      ));

      await tester.tap(find.text('View from Explore'));
      await tester.pumpAndSettle();

      expect(find.byType(DestinationDetailsScreen), findsOneWidget);
      expect(find.text('Penang Botanic Gardens'), findsOneWidget);

      await tester.pageBack();
      await tester.pumpAndSettle();

      expect(find.byType(DestinationDetailsScreen), findsNothing);
    });

    // 17. Existing image fallback unchanged
    testWidgets('17. Existing image fallback renders cleanly without errors', (tester) async {
      final initial = {
        'id': 'place_no_img',
        'title': 'Penang Hill Railway',
        'address': 'Air Itam, Penang',
        'imageUrl': 'http://invalid-or-unreachable-image.org/nonexistent.jpg',
        'openingHours': '06:30-23:00',
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': initial,
            'source': 'local',
          });

      await _pumpDestination(tester, initial: initial, api: api);

      expect(tester.takeException(), isNull);
      expect(find.text('Penang Hill Railway'), findsOneWidget);
    });

    // 18. Historical saved destination compatibility
    testWidgets('18. Historical saved destination compatibility with legacy payload', (tester) async {
      final legacy = {
        'destinationName': 'Sultan Abdul Samad Building',
        'location': 'Kuala Lumpur',
        'open_state': '10:00 AM – 6:00 PM',
        'isFavourite': true,
      };

      final api = _MockDetailsApi((path) => {
            'ok': true,
            'destination': legacy,
            'source': 'cache',
          });

      await _pumpDestination(tester, initial: legacy, api: api);

      expect(find.text('Sultan Abdul Samad Building'), findsOneWidget);
      expect(find.text('Saved'), findsOneWidget);

      await _scrollIntoView(tester, find.text('Visit information'));

      expect(find.text('General opening hours'), findsOneWidget);
      expect(find.text('10:00 AM – 6:00 PM'), findsOneWidget);
    });
  });
}
