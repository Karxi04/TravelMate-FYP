import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/opening_hours_utils.dart';
import 'package:travelmate_traveller/modules/fr03_destination_search_information/destination_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/widgets/destination_card.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';
import 'package:travelmate_traveller/widgets/local_place_rating.dart';

const place = {
  'destinationId': 'same-place',
  'title': 'Same place',
  'rating': 4.9,
  'reviews': 9000
};

class RatingsApi extends ApiService {
  int batches = 0;
  Map<String, dynamic> cardSummary = {'rating': 4.0, 'reviews': 2};
  final requestedReviewPaths = <String>[];
  Map<String, dynamic> reviewSummary = {
    'rating': 4.0, 'reviews': 2, 'user_reviews': []
  };
  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr3/local-ratings') {
      batches++;
      return {
        'items': {
          'same-place': cardSummary
        }
      };
    }
    if (path.endsWith('/ratings-reviews')) {
      requestedReviewPaths.add(path);
      return {'result': reviewSummary};
    }
    if (path.endsWith('/nearby')) return {'items': []};
    return {
      'destination': {
        ...place,
        'hours': [
          for (final day in OpeningHoursUtils.daysOfWeek)
            {day: day == 'Sunday' ? 'Closed' : '09:00-18:00'}
        ]
      }
    };
  }
}

void main() {
  setUp(LocalReviewRatings.invalidate);
  tearDown(LocalReviewRatings.invalidate);
  test('one shared batch for many card identities; no provider fallback',
      () async {
    final api = RatingsApi();
    final values = await Future.wait([
      for (var i = 0; i < 12; i++)
        LocalReviewRatings.forPlace('same-place', api: api)
    ]);
    expect(api.batches, 1);
    expect(
        values.every((v) => v['rating'] == 4.0 && v['reviews'] == 2), isTrue);
    expect(await LocalReviewRatings.forPlace('unrated', api: api), isEmpty);
  });
  testWidgets('Penang details refreshes the opened review identity and card count',
      (tester) async {
    final api = RatingsApi();
    await tester.pumpWidget(MaterialApp(
      home: DestinationDetailsScreen(api: api, initialDestination: const {
        'destinationId': 'penang_hill',
        'title': 'Penang Hill',
      }),
    ));
    await tester.pumpAndSettle();
    // The fake details endpoint supplies a different ID. Reviews stay bound to
    // the destination the traveller actually opened.
    const path = '/api/fr3/destinations/local_penang_hill/ratings-reviews';
    expect(api.requestedReviewPaths, [path]);
    expect((await LocalReviewRatings.forPlace('penang_hill', api: api))['reviews'], 2);
    api.reviewSummary = {'rating': null, 'reviews': 0, 'user_reviews': []};
    await tester.widget<RefreshIndicator>(find.byType(RefreshIndicator)).onRefresh();
    await tester.pumpAndSettle();
    expect(api.requestedReviewPaths, [path, path]);
    expect((await LocalReviewRatings.forPlace('local_penang_hill', api: api))['reviews'], 0);
    await tester.scrollUntilVisible(find.text('No TravelMate reviews yet.'), 260);
    expect(find.text('No TravelMate reviews yet.'), findsOneWidget);
  });
  for (final entry in ['Suggestions', 'Explore', 'Nearby']) {
    testWidgets(
        '$entry card and shared Details show local-only ratings and provider weekly hours',
        (tester) async {
      LocalReviewRatings.remember('same-place', {'rating': 4.0, 'reviews': 2});
      final api = RatingsApi();
      await tester.pumpWidget(MaterialApp(home: Builder(builder: (context) {
        void view() => Navigator.push(
            context,
            MaterialPageRoute(
                builder: (_) => DestinationDetailsScreen(
                    initialDestination: place, api: api)));
        return Scaffold(
            body: SingleChildScrollView(
                child: entry == 'Suggestions'
                    ? RecommendationCard(recommendation: place, onView: view)
                    : DestinationCard(
                        destination: place,
                        onView: view,
                        compact: entry == 'Nearby')));
      })));
      await tester.pumpAndSettle();
      expect(find.text('4.0 · 2 reviews'), findsOneWidget);
      expect(find.textContaining('4.9'), findsNothing);
      await tester.ensureVisible(find.text('View'));
      await tester.tap(find.text('View'));
      await tester.pumpAndSettle();
      expect(find.textContaining('External'), findsNothing);
      final scroll = find
          .byWidgetPredicate(
              (w) => w is Scrollable && w.axisDirection == AxisDirection.down)
          .first;
      await tester.scrollUntilVisible(find.text('Monday'), 250,
          scrollable: scroll);
      expect(find.text('Monday'), findsOneWidget);
      expect(find.text('Closed'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('unrated cards never show provider stars', (tester) async {
    LocalReviewRatings.remember('same-place', {'rating': null, 'reviews': 0});
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: DestinationCard(destination: place, onView: () {}))));
    await tester.pumpAndSettle();
    expect(find.textContaining('4.9'), findsNothing);
    expect(find.byIcon(Icons.star_rounded), findsNothing);
  });
  testWidgets('private card badge refreshes approved totals without a prefix',
      (tester) async {
    final api = RatingsApi()
      ..cardSummary = {'rating': 3, 'reviews': 3, 'fypPreview': true};
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: LocalPlaceRating(place: place, api: api)),
    ));
    await tester.pumpAndSettle();
    expect(find.text('3.0 · 3 reviews'), findsOneWidget);
    expect(find.byIcon(Icons.star_rounded), findsOneWidget);
    expect(find.textContaining('FYP'), findsNothing);

    api.cardSummary = {'rating': 4.2, 'reviews': 8, 'fypPreview': true};
    LocalReviewRatings.invalidate();
    await tester.pumpAndSettle();
    expect(find.text('4.2 · 8 reviews'), findsOneWidget);
    expect(find.text('3.0 · 3 reviews'), findsNothing);
  });
  testWidgets('local rating fits a narrow compact card with large text', (tester) async {
    LocalReviewRatings.remember('same-place', {'rating':4.0,'reviews':2});
    await tester.pumpWidget(MaterialApp(home: MediaQuery(
      data: const MediaQueryData(textScaler:TextScaler.linear(1.8)),
      child: Scaffold(body:Align(alignment:Alignment.topLeft,child:SizedBox(width:320,
        child:SingleChildScrollView(child:DestinationCard(destination:place,onView:(){},compact:true))))))));
    await tester.pumpAndSettle();
    expect(find.text('4.0 · 2 reviews'),findsOneWidget);
    expect(tester.takeException(),isNull);
  });
  test('partial weekly map retains split sessions, closed and unreported days',
      () {
    final hours = OpeningHoursUtils.parse({
      'hours': [
        {
          'monday': ['09:00-12:00', '14:00-18:00']
        },
        {'tuesday': 'Closed'},
        {'wednesday': 'Open 24 hours'}
      ]
    });
    expect(hours.hasWeeklySchedule, isTrue);
    final days = Map.fromEntries(hours.weeklyHours);
    expect(days['Monday'], '9:00 AM – 12:00 PM, 2:00 PM – 6:00 PM');
    expect(days['Tuesday'], 'Closed');
    expect(days['Wednesday'], 'Open 24 hours');
    expect(days['Thursday'], 'Not available');
  });
  test(
      'periods retain split closures and overnight semantics without inferred closed days',
      () {
    final hours = OpeningHoursUtils.parse({
      'opening_hours': {
        'periods': [
          {
            'open': {'day': 1, 'time': '0900'},
            'close': {'day': 1, 'time': '1200'}
          },
          {
            'open': {'day': 1, 'time': '1400'},
            'close': {'day': 1, 'time': '1800'}
          },
          {
            'open': {'day': 5, 'time': '2100'},
            'close': {'day': 6, 'time': '0200'}
          }
        ]
      }
    });
    final days = Map.fromEntries(hours.weeklyHours);
    expect(days['Monday'], '9:00 AM – 12:00 PM, 2:00 PM – 6:00 PM');
    expect(days['Friday'], '9:00 PM – 2:00 AM (next day)');
    expect(days['Tuesday'], 'Not available');
  });
  test('general hours and transient status never become a weekday timetable',
      () {
    final always=OpeningHoursUtils.parse({'periods':[{'open':{'day':0,'time':'0000'}}]});
    expect(always.weeklyHours.every((entry)=>entry.value=='Open 24 hours'),isTrue);
    expect(always.weeklyHours.length,7);
    expect(OpeningHoursUtils.parse({'utc_offset_minutes':480},now:DateTime.utc(2026,11,1,22)).currentMalaysiaDay,'Monday');
    expect(OpeningHoursUtils.parse({'utc_offset_minutes':-480},now:DateTime.utc(2026,11,1,22)).currentMalaysiaDay,'Sunday');
    final general = OpeningHoursUtils.parse({'openingHours': '09:00-18:00'});
    expect(general.hasWeeklySchedule, isFalse);
    expect(general.genericHours, '9:00 AM – 6:00 PM');
    expect(OpeningHoursUtils.parse({'open_state': 'Closed now'}).isUnavailable,
        isTrue);
    expect(OpeningHoursUtils.parse({}).isUnavailable, isTrue);
    expect(OpeningHoursUtils.parse({'periods': []}).hasWeeklySchedule, isFalse);
    expect(
        OpeningHoursUtils.parse({
          'periods': [
            {
              'open': {'day': 1, 'time': '0900'}
            }
          ]
        }).hasWeeklySchedule,
        isFalse);
  });
}
