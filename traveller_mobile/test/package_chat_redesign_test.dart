import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/operator_content/package_details_screen.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import 'package:travelmate_traveller/modules/fr11_chatbot_travel_assistant/database_chat_cards.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/local_place_rating.dart';
import 'package:travelmate_traveller/widgets/recommendation_card.dart';

class _MockRedesignApi extends ApiService {
  final Map<String, dynamic>? sessionResponse = null;
  final List<dynamic>? sessionsList = null;

  _MockRedesignApi();

  @override
  bool get isStandalone => false;

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr9/checkout/capabilities') {
      return {
        'ok': true,
        'mode': 'test',
        'hostedCheckout': true,
        'supportedQuoteTypes': ['hotel', 'package'],
      };
    }
    if (path == '/api/fr11/sessions') {
      return {'ok': true, 'items': sessionsList ?? []};
    }
    if (path.startsWith('/api/fr11/sessions/')) {
      return sessionResponse ?? {'ok': true, 'session': {'id': 's1', 'messages': []}};
    }
    if (path == '/api/fr5/itineraries') {
      return {
        'ok': true,
        'items': [
          {'id': 'trip-101', 'title': 'Penang Heritage Weekend', 'destinationArea': 'Penang'},
        ],
      };
    }
    if (path == '/api/fr9/orders') {
      return {'ok': true, 'items': []};
    }
    return {'ok': true, 'items': []};
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr11/chat') {
      return {
        'ok': true,
        'item': {
          'message': body?['message'] ?? '',
          'reply': 'Here are your curated recommendations for Penang!',
          'placeSuggestions': [
            {
              'id': 'place-cheong-fatt-tze',
              'title': 'Cheong Fatt Tze Mansion',
              'address': '14 Leith St, George Town, Penang',
              'category': 'Heritage',
              'rating': 4.7,
              'user_ratings_total': 1820,
            },
          ],
          'packages': [
            {
              'id': 'pkg-chat-penang',
              'title': 'Penang Heritage & Gourmet Discovery',
              'destination': 'George Town, Penang',
              'operatorName': 'Penang Heritage Tours',
              'price': 480,
              'currency': 'MYR',
              'durationDays': 3,
            },
          ],
          'advisory': 'Afternoon showers expected in George Town. Indoor heritage museums recommended.',
        },
      };
    }
    return {'ok': true};
  }
}

final _fullTestPackage = <String, dynamic>{
  'id': 'pkg_redesign_complete',
  'title': 'Langkawi Nature & Mangrove Safari',
  'destination': 'Langkawi, Kedah, Malaysia',
  'category': 'Nature & Adventure',
  'approvalStatus': 'approved',
  'isVerifiedOperator': true,
  'licenseNumber': 'KPK/LN 4021',
  'fullDescription':
      'Experience the best of Langkawi with a guided boat safari through Kilim Geoforest Park, eagle feeding observation, and private island hopping.\n\n**Day 1: Arrival & Mangrove**\nBoat tour\n**Day 2: Island Discovery**\nBeaches',
  'durationDays': 3,
  'durationNights': 2,
  'currency': 'MYR',
  'adultPrice': 550,
  'childPrice': 280,
  'originalPrice': 680,
  'promotionalPrice': 499,
  'packagePricing': {
    'base': {'participants':{'adults':2,'children':0},'amountMinor':110000,'originalSubtotal':1100,'finalPayable':1100,'promotionDiscount':0,'promotion':{}},
    'offers': [{'participants':{'adults':2,'children':0},'amountMinor':99800,'originalSubtotal':1100,'finalPayable':998,'promotionDiscount':102,
      'promotion':{'id':'approved-offer','campaignTitle':'Nature campaign','startDate':'2026-01-01','endDate':'2027-12-31','promoCode':''}}],
  },
  'promotionStart': '2026-01-01',
  'promotionEnd': '2027-12-31',
  'priceBasis': 'per_person',
  'minimumTravellers': 2,
  'maximumTravellers': 8,
  'departureDates': ['2026-12-15', '2026-12-22'],
  'departureLocation': 'Kuah Jetty, Langkawi',
  'meetingPoint': 'Langkawi Yacht Club Main Entrance',
  'departureNotes': 'Please arrive 20 minutes prior to scheduled departure.',
  'operatorName': 'Langkawi Eco Adventures',
  'operatorPhone': '+60 4-966 8899',
  'operatorEmail': 'contact@langkawieco.com.my',
  'highlights': ['Kilim Karst Geoforest', 'Eagle Watching', 'Batik Art Workshop'],
  'inclusions': ['Return boat transfers', 'Licensed nature guide', 'All entry permits', 'Buffet lunch'],
  'exclusions': ['Flight tickets', 'Travel insurance', 'Personal gear'],
  'transportTypes': ['Speedboat', 'Air-conditioned van'],
  'whatToBring': ['Sunscreen', 'Waterproof phone pouch', 'Comfortable water shoes'],
  'cancellationPolicy': 'Free cancellation up to 48 hours prior to tour departure.',
  'refundPolicy': 'Full refund within 5 business days upon verified cancellation.',
  'bookingTerms': 'Subject to maritime weather clearance and safety guidelines.',
  'importantNotes': 'Life vests provided and compulsory during all boat transit.',
  'rating': 4.8,
  'reviewCount': 34,
  'reviews': [
    {
      'author': 'Sarah Tan',
      'rating': 5.0,
      'comment': 'Exceptional guide who pointed out wild hornbills and swimming macaques. 10/10.',
    },
    {
      'author': 'Michael Wong',
      'rating': 4.5,
      'comment': 'Very well organised trip. Lunch was delicious local Malay cuisine.',
    },
  ],
  'accommodationHotel': {
    'provider': 'liteapi',
    'hotelId': 'lp_berjaya_langkawi',
    'name': 'Berjaya Langkawi Resort',
    'address': 'Karung Berkunci 200, Burau Bay',
    'city': 'Langkawi',
    'country': 'MY',
    'stars': 5.0,
    'guestRating': 8.9,
    'amenities': ['Private Beach', 'Infinity Pool', 'Spa', 'Free Wi-Fi'],
  },
  'roomType': 'Rainforest Chalet',
  'itineraryDays': [
    {
      'dayNumber': 1,
      'title': 'Kilim Geoforest Exploration',
      'description': 'Boat excursion navigating the mangrove channels, limestone formations and bat caves.',
      'activities': [
        '09:00 - Departure from Kuah Jetty',
        '10:30 - Bat Cave exploration & boardwalk walk',
        '13:00 - Floating fish farm lunch',
      ],
      'meals': ['Lunch'],
      'accommodation': 'Berjaya Langkawi Resort',
      'transportNotes': 'Private van transfer from airport',
    },
    {
      'dayNumber': 2,
      'title': 'Island Hopping & Eagle Sanctuary',
      'description': 'Cruising through the southern islands with swimming at Dayang Bunting lake.',
      'activities': [
        '08:30 - Island hopping departure',
        '11:00 - Lake of the Pregnant Maiden fresh water swim',
      ],
      'meals': ['Breakfast', 'Picnic Lunch'],
      'accommodation': 'Berjaya Langkawi Resort',
      'transportNotes': 'Speedboat transit',
    },
  ],
};

Widget _wrap(Widget child, {double width = 400, double height = 900, double textScale = 1.0}) {
  return MaterialApp(
    theme: buildInkWashTheme(),
    home: MediaQuery(
      data: MediaQueryData(
        size: Size(width, height),
        textScaler: TextScaler.linear(textScale),
      ),
      child: child,
    ),
  );
}

void main() {
  group('Part A: Tourism Package UI Redesign Presentation Tests', () {
    testWidgets('Renders elevated Hero section with verified badge, title, location and chips', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(
        item: _fullTestPackage,
        api: _MockRedesignApi(),
      )));
      await tester.pumpAndSettle();

      // Hero Elements
      expect(find.text('Approved Package'), findsOneWidget);
      expect(find.text('Langkawi Nature & Mangrove Safari'), findsWidgets);
      expect(find.text('Langkawi, Kedah, Malaysia'), findsOneWidget);
      expect(find.text('3 days · 2 nights'), findsOneWidget);
      expect(find.text('Automatic campaign offer'), findsOneWidget);
      expect(find.text('Orig. MYR 680'), findsNothing);
      expect(find.textContaining('was 1100.00'), findsOneWidget);
      expect(find.text('Up to 8 travellers'), findsOneWidget);
    });

    testWidgets('Overview tab presents package overview, highlights, verified operator and reviews', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(
        item: _fullTestPackage,
        api: _MockRedesignApi(),
      )));
      await tester.pumpAndSettle();

      // Overview Tab is default
      expect(find.text('Package overview'), findsOneWidget);
      expect(find.text('Highlights'), findsOneWidget);
      expect(find.text('Kilim Karst Geoforest'), findsOneWidget);
      expect(find.text('Eagle Watching'), findsOneWidget);

      // Verified Operator Card
      expect(find.text('Tourism Operator'), findsOneWidget);
      expect(find.text('Langkawi Eco Adventures'), findsOneWidget);
      expect(find.text('+60 4-966 8899'), findsOneWidget);
      expect(find.text('contact@langkawieco.com.my'), findsOneWidget);
      expect(find.text('License: KPK/LN 4021'), findsOneWidget);
      expect(find.text('Verified'), findsOneWidget);

      // Traveller Reviews Section
      expect(find.text('Traveller Reviews'), findsOneWidget);
      expect(find.text('4.8 (34)'), findsOneWidget);
      expect(find.text('Sarah Tan'), findsOneWidget);
      expect(find.textContaining('Exceptional guide'), findsOneWidget);
    });

    testWidgets('Itinerary tab renders day timeline, scheduled activity time badges and meal/stay/transport notes', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(
        item: _fullTestPackage,
        api: _MockRedesignApi(),
      )));
      await tester.pumpAndSettle();

      // Switch to Itinerary tab
      await tester.tap(find.text('Itinerary'));
      await tester.pumpAndSettle();

      expect(find.text('Day-by-day itinerary'), findsOneWidget);
      expect(find.text('Day 1 · Kilim Geoforest Exploration'), findsOneWidget);
      expect(find.text('Day 2 · Island Hopping & Eagle Sanctuary'), findsOneWidget);

      // Scheduled activities
      expect(find.text('Scheduled activities'), findsWidgets);
      expect(find.text('09:00'), findsOneWidget);
      expect(find.text('Departure from Kuah Jetty'), findsOneWidget);
      expect(find.text('10:30'), findsOneWidget);
      expect(find.text('Bat Cave exploration & boardwalk walk'), findsOneWidget);
      expect(find.text('Meals: Lunch'), findsOneWidget);
      expect(find.text('Stay: Berjaya Langkawi Resort'), findsAtLeastNWidgets(1));
      expect(find.text('Transport: Private van transfer from airport'), findsOneWidget);

      // Day Navigation Chips
      expect(find.text('All Days'), findsOneWidget);
      expect(find.text('Day 1'), findsOneWidget);
      expect(find.text('Day 2'), findsOneWidget);

      // Tap Day 1 chip: focuses Day 1 only
      await tester.tap(find.text('Day 1'));
      await tester.pumpAndSettle();
      expect(find.text('Day 1 · Kilim Geoforest Exploration'), findsOneWidget);
      expect(find.text('Day 2 · Island Hopping & Eagle Sanctuary'), findsNothing);

      // Tap All Days chip: restores all days
      await tester.tap(find.text('All Days'));
      await tester.pumpAndSettle();
      expect(find.text('Day 1 · Kilim Geoforest Exploration'), findsOneWidget);
      expect(find.text('Day 2 · Island Hopping & Eagle Sanctuary'), findsOneWidget);
    });

    testWidgets("What's Included tab renders green inclusions, grey exclusions and LiteAPI accommodation", (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(
        item: _fullTestPackage,
        api: _MockRedesignApi(),
      )));
      await tester.pumpAndSettle();

      // Switch to What's Included tab
      final includedTab = find.text("What's Included");
      await tester.ensureVisible(includedTab);
      await tester.pumpAndSettle();
      await tester.tap(includedTab);
      await tester.pumpAndSettle();

      expect(find.text('What is included'), findsOneWidget);
      expect(find.text('Return boat transfers'), findsOneWidget);
      expect(find.text('Licensed nature guide'), findsOneWidget);

      expect(find.text('Not included'), findsOneWidget);
      expect(find.text('Flight tickets'), findsOneWidget);
      expect(find.text('Travel insurance'), findsOneWidget);

      // LiteAPI Hotel
      expect(find.text('Hotel Information from LiteAPI'), findsOneWidget);
      expect(find.text('Berjaya Langkawi Resort'), findsOneWidget);
      expect(find.text('⭐ 5.0-Star'), findsOneWidget);
      expect(find.text('Guest Rating: 8.9/10'), findsOneWidget);
      expect(find.text('Room Configuration: Rainforest Chalet'), findsOneWidget);
      expect(find.textContaining('Selecting a property does not create or confirm a room reservation.'), findsOneWidget);
    });

    testWidgets('Policies tab presents cancellation, refund, booking terms, important notes and academic disclosure', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(
        item: _fullTestPackage,
        api: _MockRedesignApi(),
      )));
      await tester.pumpAndSettle();

      // Switch to Policies tab
      await tester.tap(find.text('Policies'));
      await tester.pumpAndSettle();

      expect(find.text('Cancellation policy'), findsOneWidget);
      expect(find.textContaining('Free cancellation up to 48 hours'), findsOneWidget);
      expect(find.text('Refund policy'), findsOneWidget);
      expect(find.textContaining('Full refund within 5 business days'), findsOneWidget);
      expect(find.text('Booking terms'), findsOneWidget);
      expect(find.text('Important notes'), findsOneWidget);
      expect(find.text('Booking arrangements'), findsOneWidget);
      expect(find.textContaining('Academic demonstration'), findsOneWidget);
    });

    testWidgets('Responsive bottom bar and booking modal work seamlessly without overflow at 320px', (tester) async {
      tester.view.physicalSize = const Size(320, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(
        TourismPackageDetailsScreen(item: _fullTestPackage, api: _MockRedesignApi()),
        width: 320,
        height: 800,
        textScale: 1.3,
      ));
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(find.byKey(const ValueKey('package-book-now-cta')), findsOneWidget);

      // Open booking sheet
      await tester.tap(find.byKey(const ValueKey('package-book-now-cta')));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('package-group-booking')), findsOneWidget);
      expect(find.byKey(const ValueKey('package-checkout-btn')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('Part B: AI Chatbot UI Redesign Presentation Tests', () {
    testWidgets('Empty discovery landing displays hero, suggestions, curated prompts and travel tools', (tester) async {
      tester.view.physicalSize = const Size(430, 950);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(ChatTab(api: _MockRedesignApi())));
      await tester.pumpAndSettle();

      // Welcome Hero
      expect(find.text('How can I help with your trip?'), findsWidgets);
      expect(find.text('Ask for ideas, itinerary changes, budget help or weather-friendly alternatives.'), findsOneWidget);

      // Suggestions Chips
      expect(find.text('Plan things to do'), findsOneWidget);
      expect(find.text('Adjust my itinerary'), findsWidgets);
      expect(find.text('Help with my budget'), findsOneWidget);
      expect(find.text('What should I do if it rains?'), findsWidgets);

      // Curated Planning Prompts
      expect(find.text('Curated planning prompts'), findsOneWidget);
      expect(find.text('Plan a 3-day cultural trip'), findsOneWidget);
      expect(find.text('Vacation on RM1,500 budget'), findsOneWidget);

      // Travel Tools
      await tester.scrollUntilVisible(find.text('Flights'), 100, scrollable: find.byType(Scrollable).first);
      expect(find.text('Travel tools'), findsOneWidget);
      expect(find.text('Flights'), findsOneWidget);
      expect(find.text('Hotels'), findsOneWidget);
      expect(find.text('Packing'), findsOneWidget);
      expect(find.text('Weather'), findsWidgets);
      expect(find.text('Trips'), findsOneWidget);
    });

    testWidgets('Chat response renders place suggestions, package cards and advisory in conversation', (tester) async {
      tester.view.physicalSize = const Size(430, 1100);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(ChatTab(api: _MockRedesignApi())));
      await tester.pumpAndSettle();

      // Tap suggestion to send message
      await tester.tap(find.text('Plan things to do'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pumpAndSettle();

      // User Message bubble
      expect(find.text('Plan things to do'), findsOneWidget);

      // Assistant Response with identity header
      expect(find.text('TravelMate Assistant'), findsWidgets);
      expect(find.text('Here are your curated recommendations for Penang!'), findsOneWidget);

      // Place suggestion card
      expect(find.text('Cheong Fatt Tze Mansion'), findsOneWidget);
      expect(find.text('Details'), findsOneWidget);
      expect(find.text('Add to trip'), findsOneWidget);

      // Tourism Package Recommendation Card in chat
      expect(find.text('Recommended Tourism Packages'), findsOneWidget);
      expect(find.text('Penang Heritage & Gourmet Discovery'), findsOneWidget);
      expect(find.text('MYR 480'), findsOneWidget);
      expect(find.text('View Package Details'), findsOneWidget);

      // Weather / Advisory Card
      expect(find.textContaining('Afternoon showers expected in George Town'), findsOneWidget);
    });

    testWidgets('Narrow 320px viewport with 1.3x text scale causes zero overflow exceptions in ChatTab', (tester) async {
      tester.view.physicalSize = const Size(320, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(_wrap(
        ChatTab(api: _MockRedesignApi()),
        width: 320,
        height: 800,
        textScale: 1.3,
      ));
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
    });
  });

  group('Part C: Readability, Progressive Disclosure, Timeline Alignment & Responsiveness', () {
    testWidgets('Scheduled activities without operator times render as honest ordered list without fake time labels', (tester) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final untimedPackage = <String, dynamic>{
        'id': 'pkg_untimed',
        'title': 'Untimed Nature Exploration',
        'destination': 'Taman Negara, Pahang',
        'priceBasis': 'per_person',
        'adultPrice': 300,
        'itineraryDays': [
          {
            'dayNumber': 1,
            'title': 'Rainforest Canopy Day',
            'description': 'Full day in the ancient jungle.',
            'activities': [
              {'name': 'Canopy Walkway Experience', 'description': 'Walk among the treetops.'},
              {'name': 'Rapid Shooting on Sungai Tembeling', 'description': 'Boat ride through river rapids.'},
              {'name': 'Night Jungle Walk', 'description': 'Spot nocturnal insects and glowing fungi.'},
            ],
          },
        ],
      };

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(
        item: untimedPackage,
        api: _MockRedesignApi(),
      )));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Itinerary'));
      await tester.pumpAndSettle();

      // Verify honest ordered step numbers are present
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);

      // Verify fake time labels are NEVER invented
      expect(find.text('Time not specified'), findsNothing);
      expect(find.text('Canopy Walkway Experience'), findsOneWidget);
      expect(find.text('Rapid Shooting on Sungai Tembeling'), findsOneWidget);
      expect(find.text('Night Jungle Walk'), findsOneWidget);
    });

    testWidgets('Very long package description, day title, activity title, activity description, and policies expand cleanly', (tester) async {
      tester.view.physicalSize = const Size(800, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final longDescription = List.filled(30, 'Extensive operator overview with essential background facts.').join(' ') + ' [END_OF_OVERVIEW]';
      final longDayTitle = List.filled(10, 'Comprehensive cultural journey through ancient heritage temples').join(' ');
      final longActTitle = List.filled(8, 'Signature guided botanical walk and rare flower exploration').join(' ');
      final longActDescription = List.filled(25, 'Detailed activity instructions regarding trail equipment and footwear.').join(' ') + ' [END_OF_ACT_DESC]';
      final longPolicy = List.filled(25, 'Official operator policy regarding cancellations and refund processing.').join(' ') + ' [END_OF_POLICY]';

      final verbosePackage = <String, dynamic>{
        'id': 'pkg_verbose',
        'title': 'Highland Expedition',
        'destination': 'Cameron Highlands, Pahang',
        'fullDescription': longDescription,
        'priceBasis': 'per_person',
        'adultPrice': 450,
        'bookingTerms': longPolicy,
        'itineraryDays': [
          {
            'dayNumber': 1,
            'title': longDayTitle,
            'description': 'Day description for expedition.',
            'activities': [
              {
                'name': longActTitle,
                'time': '08:30 AM',
                'description': longActDescription,
              },
            ],
          },
        ],
      };

      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(
        item: verbosePackage,
        api: _MockRedesignApi(),
      )));
      await tester.pumpAndSettle();

      // Progressive disclosure on Overview: Read full description
      expect(find.text('Read full description'), findsOneWidget);
      await tester.tap(find.text('Read full description'));
      await tester.pumpAndSettle();
      expect(find.textContaining('[END_OF_OVERVIEW]'), findsOneWidget);

      // Switch to Itinerary
      await tester.tap(find.text('Itinerary'));
      await tester.pumpAndSettle();

      // Activity title and time
      expect(find.text('08:30 AM'), findsOneWidget);
      expect(find.textContaining('Signature guided botanical walk'), findsOneWidget);

      // Switch to Policies
      await tester.tap(find.text('Policies'));
      await tester.pumpAndSettle();

      expect(find.text('Booking terms'), findsOneWidget);
      expect(find.text('Read more'), findsWidgets);
      await tester.tap(find.text('Read more').first);
      await tester.pumpAndSettle();
      expect(find.textContaining('[END_OF_POLICY]'), findsOneWidget);
    });

    testWidgets('original Butterworth brochure expands completely at narrow width', (tester) async {
      final fixture = jsonDecode(File(
        '../backend_api/tests/fixtures/butterworth_full_original_editor.json',
      ).readAsStringSync()) as Map;
      final form = Map<String, dynamic>.from(fixture['form'] as Map);
      final description = form['fullDescription'] as String;
      final finalParagraph = description.trim().split('\n\n').last;
      final inclusions = (form['inclusions'] as String).split('\n');
      final exclusions = (form['exclusions'] as String).split('\n');
      tester.view.physicalSize = const Size(320, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(_wrap(TourismPackageDetailsScreen(
        api: _MockRedesignApi(),
        item: {...form, 'id':'butterworth-original', 'inclusions':inclusions, 'exclusions':exclusions,
          'itinerary':[{
            'dayNumber':1, 'title':(form['itineraryTitle'] as List).first,
            'description':(form['itineraryDescription'] as List).first,
            'activities':(form['itineraryActivities'] as List).first,
          }],
        },
      ), width:320, height:1200, textScale:1.5));
      await tester.pumpAndSettle();
      final expand = find.text('Read full description');
      await Scrollable.ensureVisible(tester.element(expand), alignment: 0.5);
      await tester.pumpAndSettle();
      await tester.tap(expand);
      await tester.pumpAndSettle();
      expect(find.text(finalParagraph), findsOneWidget);
      expect(find.text('Show less'), findsWidgets);
      expect(tester.takeException(), isNull);
    });

    for (final width in [320.0, 360.0, 390.0, 430.0]) {
      testWidgets('Responsive verification at ${width}px width with 1.4x text scale produces 0 overflows', (tester) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);

        // Package screen
        await tester.pumpWidget(_wrap(
          TourismPackageDetailsScreen(item: _fullTestPackage, api: _MockRedesignApi()),
          width: width,
          height: 1000,
          textScale: 1.4,
        ));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);

        // Chat tab
        await tester.pumpWidget(_wrap(
          ChatTab(api: _MockRedesignApi()),
          width: width,
          height: 1000,
          textScale: 1.4,
        ));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('ISSUE 1 modal removes redundant disclosures, deduplicates minimum requirement, and handles narrow keyboard without overflow', (tester) async {
      tester.view.physicalSize = const Size(320, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetViewInsets);

      final modalPkg = <String, dynamic>{
        'id': 'pkg_modal_min4',
        'title': 'Cameron Tea & Mossy Forest',
        'destination': 'Cameron Highlands',
        'priceBasis': 'per_person',
        'adultPrice': 400,
        'childPrice': 200,
        'minimumTravellers': 4,
        'maximumTravellers': 10,
        'departureDates': ['2099-06-15', '2000-01-01'],
      };

      await tester.pumpWidget(_wrap(
        TourismPackageDetailsScreen(item: modalPkg, api: _MockRedesignApi()),
        width: 320,
        height: 800,
        textScale: 1.4,
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('package-book-now-cta')));
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('package-group-booking')), findsOneWidget);
      expect(find.textContaining('Academic demonstration'), findsNothing);
      expect(find.textContaining('Reviewing this package does not create'), findsNothing);
      expect(find.text('Minimum 4 travellers required. Currently selected: 1.'), findsOneWidget);
      expect(find.textContaining('Minimum requirement:'), findsNothing);
      expect(find.textContaining('Minimum group size:'), findsNothing);
      expect(tester.takeException(), isNull);

      // Simulate soft keyboard opening on promo code field
      tester.view.viewInsets = const FakeViewPadding(bottom: 260);
      await tester.pumpAndSettle();
      final promoField = find.byKey(const ValueKey('package-promo-code'));
      await tester.ensureVisible(promoField);
      await tester.enterText(promoField, 'SAVE10');
      await tester.pumpAndSettle();
      expect(find.text('SAVE10'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('ISSUE 3 LiteAPI accommodation without stars wraps cleanly at 320px 1.4x and expands long notes', (tester) async {
      tester.view.physicalSize = const Size(320, 1000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final longAccNotes = List.filled(20, 'Check-in begins at 15:00 MYT at the main wing reception.').join(' ') + ' [END_ACC_NOTES]';
      final pkgUnstarred = <String, dynamic>{
        'id': 'pkg_unstarred_hotel',
        'title': 'George Town Boutique Stay',
        'destination': 'Penang',
        'priceBasis': 'per_person',
        'adultPrice': 350,
        'transportIncluded': true,
        'guideActivitiesIncluded': false,
        'roomType': 'Heritage Courtyard Twin',
        'accommodationNotes': longAccNotes,
        'accommodationHotel': {
          'provider': 'liteapi',
          'name': 'Eighteen Heritage Inn',
          'city': 'George Town',
          'country': 'MY',
          'stars': null,
          'guestRating': 8.7,
        },
      };

      await tester.pumpWidget(_wrap(
        TourismPackageDetailsScreen(item: pkgUnstarred, api: _MockRedesignApi()),
        width: 320,
        height: 1000,
        textScale: 1.4,
      ));
      await tester.pumpAndSettle();

      final includedTab = find.text("What's Included");
      await tester.ensureVisible(includedTab);
      await tester.pumpAndSettle();
      await tester.tap(includedTab);
      await tester.pumpAndSettle();

      expect(find.text('Service arrangements'), findsOneWidget);
      expect(find.text('Star classification not supplied'), findsOneWidget);
      expect(find.text('Guest Rating: 8.7/10'), findsOneWidget);
      expect(tester.takeException(), isNull);

      final readMore = find.text('Read more').first;
      await tester.ensureVisible(readMore);
      await tester.tap(readMore);
      await tester.pumpAndSettle();
      expect(find.textContaining('[END_ACC_NOTES]'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('ISSUE 2 DatabasePackageCard and OwnedChatRecords render cleanly at 320px 1.4x', (tester) async {
      tester.view.physicalSize = const Size(320, 1000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final dbPkg = <String, dynamic>{
        'id': 'db-pkg-1',
        'title': 'Langkawi Island & Cable Car Escapade',
        'destination': 'Langkawi',
        'durationDays': 3,
        'operatorName': 'Island Horizons',
        'inclusions': ['Hotel pickup', 'Cable car ticket'],
        'serviceInclusions': {'accommodation': true, 'transport': true, 'guideActivities': false},
        'chatQuote': {
          'originalSubtotal': 600,
          'promotionDiscount': 50,
          'finalPayable': 550,
          'currency': 'MYR',
          'priceBasis': 'per_person',
          'taxIncluded': true,
          'promotion': {
            'campaignTitle': 'Seasonal Saver',
            'startDate': '2026-01-01',
            'endDate': '2099-12-31',
            'termsConditions': 'Non-refundable promotional rate.',
          },
        },
        'quoteContext': {
          'isReference': false,
          'partyKnown': true,
          'dateKnown': true,
          'participants': {'adults': 2, 'children': 0},
          'departureDate': '2030-05-01',
        },
      };
      final owned = <String, dynamic>{
        'ownedTrips': [{'title': 'Langkawi Trip', 'startDate': '2030-05-01', 'endDate': '2030-05-03'}],
        'ownedOrders': [
          {
            'title': 'Langkawi Package Order',
            'orderId': 'ord_9988',
            'paymentStatus': 'paid',
            'currency': 'MYR',
            'amount': 550,
            'statusOverview': {
              'travellerTrip': {'label': 'Created'},
              'operatorReadiness': {'label': 'Pending'},
              'supplierArrangements': {'label': 'Pending'},
            },
          },
        ],
      };

      await tester.pumpWidget(_wrap(
        Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                DatabasePackageCard(package: dbPkg, onDetails: () {}),
                OwnedChatRecords(item: owned, onTrips: () {}),
              ],
            ),
          ),
        ),
        width: 320,
        height: 1000,
        textScale: 1.4,
      ));
      await tester.pumpAndSettle();

      expect(find.text('MYR 550.00'), findsOneWidget);
      expect(find.text('View Package Details'), findsOneWidget);
      expect(find.text('Open Saved Trips'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('ISSUE 6 RecommendationCard handles long title/category, clean rating format, and stacks buttons cleanly at 320px 1.5x', (tester) async {
      LocalReviewRatings.remember('rec-long-place', {'rating': 3.8, 'reviews': 11});
      addTearDown(LocalReviewRatings.invalidate);

      tester.view.physicalSize = const Size(320, 900);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final rec = <String, dynamic>{
        'destinationId': 'rec-long-place',
        'title': 'Sultan Abdul Samad Heritage Complex & Dataran Merdeka Promenade',
        'address': 'Jalan Raja, City Centre, 50050 Kuala Lumpur, Wilayah Persekutuan Kuala Lumpur',
        'category': 'Historical Landmark & Colonial Architecture',
        'discoveryEligible': true,
        'finalScore': 88,
        'foodExperienceType': 'culinary_culture',
        'matchReasons': ['Matches your Culture interests'],
      };

      await tester.pumpWidget(_wrap(
        Scaffold(
          body: SingleChildScrollView(
            padding: AppSpacing.page,
            child: RecommendationCard(
              recommendation: rec,
              discovery: true,
              onView: () {},
              onAddToTrip: () {},
            ),
          ),
        ),
        width: 320,
        height: 900,
        textScale: 1.5,
      ));
      await tester.pumpAndSettle();

      expect(find.text('3.8 · 11 reviews'), findsOneWidget);
      expect(find.textContaining('FYP'), findsNothing);
      expect(find.text('View'), findsOneWidget);
      expect(find.text('Add to trip'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
