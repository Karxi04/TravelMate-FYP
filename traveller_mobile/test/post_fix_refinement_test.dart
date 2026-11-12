import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/core/operator_content/package_text_block.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_screen.dart';
import 'package:travelmate_traveller/modules/fr07_flight_search/flight_airport_catalog.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/services/api_service.dart';

class RefineApi extends ApiService {
  final flightQueries = <Map<String, String>>[];
  final posts = <String>[];
  final session = {
    'id': 's',
    'title': 'Planning',
    'messages': [
      {
        'message': '12 Dec until 16 Dec',
        'reply': 'What is your budget?',
        'source': 'travelmate-assistant'
      }
    ]
  };
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr11/sessions')
      return {
        'items': [session]
      };
    if (path == '/api/fr11/sessions/s') return {'session': session};
    if (path == '/api/fr7/flights/search') {
      flightQueries.add({...?query});
      return {'items': [], 'searchId': 'search'};
    }
    if (path == '/api/fr9/checkout/capabilities')
      return {'supportedQuoteTypes': []};
    if (path == '/api/fr3/destinations/place')
      return {
        'source': 'serpapi',
        'destination': {
          'destinationId': 'place',
          'title': 'A real place',
          'description': 'An actual returned description.',
          'category': 'Museum',
          'address': 'George Town, Penang',
          'rating': 4.5,
          'reviews': 20
        }
      };
    return {'items': [], 'result': {}};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posts.add(path);
    return {'ok': true};
  }
}

Future<void> frame(WidgetTester tester, Widget child,
    {double width = 430, double scale = 1}) async {
  tester.view.physicalSize = Size(width, 1100);
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.textScaleFactorTestValue = scale;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.platformDispatcher.clearTextScaleFactorTestValue();
  });
  await tester.pumpWidget(MaterialApp(home: child));
  await tester.pumpAndSettle();
}

Future<void> show(WidgetTester tester, Finder target) async {
  if (target.evaluate().isNotEmpty) {
    await tester.ensureVisible(target.first);
    await tester.pumpAndSettle();
    return;
  }
  final scrollable = find
      .byWidgetPredicate(
          (w) => w is Scrollable && w.axisDirection == AxisDirection.down)
      .first;
  tester.state<ScrollableState>(scrollable).position.jumpTo(0);
  await tester.pumpAndSettle();
  for (var i = 0; i < 60; i++) {
    if (target.evaluate().isNotEmpty) {
      await tester.ensureVisible(target.first);
      await tester.pumpAndSettle();
      return;
    }
    await tester.drag(scrollable, const Offset(0, -250));
    await tester.pumpAndSettle();
  }
  fail('Could not scroll to $target');
}

void main() {
  testWidgets('guided question remains visible without repeated helper content',
      (tester) async {
    await frame(tester, ChatTab(api: RefineApi()));
    expect(find.text('What is your budget?'), findsOneWidget);
    expect(find.text('Using saved travel guidance'), findsNothing);
    expect(
        find.text('Check live details before making bookings.'), findsNothing);
  });
  testWidgets('expanded catalog finds a specific airport and sends its code',
      (tester) async {
    final api = RefineApi();
    await frame(tester, FlightScreen(api: api));
    await tester.enterText(find.widgetWithText(TextField, 'KUL'), 'Kuching');
    await tester.pumpAndSettle();
    await tester.tap(find.text('${flightAirportLabels['KCH']} (KCH)'));
    await tester.pumpAndSettle();
    final dynamic state = tester.state(find.byType(FlightScreen));
    expect(state.from.text, 'KCH');
    await state.search();
    await tester.pumpAndSettle();
    expect(api.flightQueries.single['departure_id'], 'KCH');
    expect(api.flightQueries.single['currency'], 'MYR');
  });
  testWidgets(
      'expanded Malaysian choices retain invalid-input and stale-result protections',
      (tester) async {
    final api = RefineApi();
    await frame(tester, FlightScreen(api: api));
    final dynamic state = tester.state(find.byType(FlightScreen));
    state.from.text = 'SZB';
    state.to.text = 'KBR';
    await state.search();
    await tester.pumpAndSettle();
    expect(api.flightQueries.single['arrival_id'], 'KBR');
    state.to.text = 'ZZZ';
    await tester.pumpAndSettle();
    expect(state.searchId, isEmpty);
    await state.search();
    await tester.pumpAndSettle();
    expect(api.flightQueries.length, 1);
  });
  testWidgets('About keeps facts and omits raw supporting labels',
      (tester) async {
    await frame(
        tester,
        DestinationDetailsScreen(api: RefineApi(), initialDestination: const {
          'destinationId': 'place',
          'title': 'A real place'
        }));
    await show(tester, find.text('An actual returned description.'));
    expect(find.text('Category: Museum'), findsOneWidget);
    expect(find.text('Location: George Town, Penang'), findsOneWidget);
    expect(find.textContaining('Source rating:'), findsNothing);
    expect(find.textContaining('Destination information:'), findsNothing);
  });
  testWidgets('long text expands without losing the original operator value',
      (tester) async {
    final text =
        List.filled(35, 'Operator-provided details with useful information.')
                .join(' ') +
            ' FINAL_OPERATOR_TEXT';
    await frame(
        tester,
        Scaffold(
            body: SingleChildScrollView(child: PackageTextBlock(text: text))),
        width: 320,
        scale: 1.4);
    expect(tester.widget<Text>(find.text(text)).maxLines, 4);
    await tester.tap(find.text('Read more'));
    await tester.pumpAndSettle();
    expect(tester.widget<Text>(find.text(text)).maxLines, isNull);
    expect(find.text('Show less'), findsOneWidget);
    await tester.ensureVisible(find.text('Show less'));
    await tester.tap(find.text('Show less'));
    await tester.pumpAndSettle();
    expect(tester.widget<Text>(find.text(text)).maxLines, 4);
    expect(tester.takeException(), isNull);
  });
  for (final width in [320.0, 430.0]) {
    testWidgets(
        'package full description, lengthy lists and itinerary remain accessible at $width',
        (tester) async {
      final description =
          'A short operator introduction.\n\n**Day 1: Arrival**\n' +
              List.filled(30, 'A detailed operator sentence.').join(' ') +
              ' FINAL_DESCRIPTION';
      final dayDescription =
          List.filled(30, 'Day-specific operator information.').join(' ') +
              ' FINAL_DAY';
      final dayTitle =
          List.filled(12, 'A detailed operator day heading').join(' ');
      final policy = List.filled(30, 'An operator booking policy.').join(' ') +
          ' FINAL_POLICY';
      final item = <String, dynamic>{
        'id': 'package',
        'title': 'A heritage holiday',
        'destination': 'Penang',
        'fullDescription': description,
        'durationDays': 1,
        'durationNights': 0,
        'currency': 'MYR',
        'adultPrice': 100,
        'priceBasis': 'per_person',
        'highlights': List.generate(8, (i) => 'Highlight $i'),
        'inclusions': ['Guide'],
        'bookingTerms': policy,
        'itineraryDays': [
          {
            'dayNumber': 1,
            'title': dayTitle,
            'description': dayDescription,
            'activities': [
              {
                'name': 'A walking visit',
                'time':
                    '09:00 - 12:00 local time, subject to the operator schedule',
                'description': dayDescription
              }
            ]
          }
        ]
      };
      final before = jsonEncode(item);
      final api = RefineApi();
      await frame(tester, TourismPackageDetailsScreen(item: item, api: api),
          width: width, scale: 1.2);
      await show(tester, find.text('Read full description'));
      await tester.tap(find.text('Read full description'));
      await tester.pumpAndSettle();
      expect(find.text('A short operator introduction.'), findsOneWidget);
      expect(tester.widget<Text>(find.textContaining('FINAL_DESCRIPTION')).maxLines, isNull);
      await show(tester, find.text('Highlights'));
      await tester.tap(find.text('Highlights'));
      await tester.pumpAndSettle();
      await show(tester, find.text('Highlight 7'));
      expect(find.text('Highlight 7'), findsOneWidget);
      await show(tester, find.text('Itinerary'));
      await tester.tap(find.text('Itinerary'));
      await tester.pumpAndSettle();
      await show(tester, find.text('Day 1 · $dayTitle'));
      await tester.tap(find.text('Day 1 · $dayTitle'));
      await tester.pumpAndSettle();
      expect(tester.widget<Text>(find.text('Day 1 · $dayTitle')).maxLines, isNull);
      await show(tester, find.text(dayDescription));
      final day = find
          .ancestor(
              of: find.text(dayDescription).first,
              matching: find.byType(PackageTextBlock))
          .first;
      await tester
          .tap(find.descendant(of: day, matching: find.text('Read more')));
      await tester.pumpAndSettle();
      expect(
          tester
              .widget<Text>(
                  find.descendant(of: day, matching: find.text(dayDescription)))
              .maxLines,
          isNull);
      await show(tester, find.text('Policies'));
      await tester.tap(find.text('Policies'));
      await tester.pumpAndSettle();
      final policyBlock = find.ancestor(
          of: find.text(policy), matching: find.byType(PackageTextBlock));
      await show(tester,
          find.descendant(of: policyBlock, matching: find.text('Read more')));
      await tester.tap(
          find.descendant(of: policyBlock, matching: find.text('Read more')));
      await tester.pumpAndSettle();
      expect(tester.widget<Text>(find.text(policy)).maxLines, isNull);
      expect(jsonEncode(item), before);
      expect(api.posts, isEmpty);
      expect(tester.takeException(), isNull);
    });
  }
}
