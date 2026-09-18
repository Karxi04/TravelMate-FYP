import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../modules/fr03_destination_search_information/explore_tab.dart';
import '../../modules/fr03_destination_search_information/destination_details_screen.dart';
import '../../modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import '../../modules/fr06_weather_forecast/weather_screen.dart';
import '../../modules/fr07_flight_search/flight_screen.dart';
import '../../modules/fr08_hotel_booking/hotel_screen.dart';
import '../../modules/fr08_hotel_booking/car_rental_screen.dart';
import '../operator_content/package_details_screen.dart';
import '../operator_content/campaign_details_screen.dart';

class HomeTab extends StatefulWidget {
  const HomeTab({super.key});

  @override
  State<HomeTab> createState() => _HomeTabState();
}

class _HomeTabState extends State<HomeTab> {
  final api = ApiService();
  final searchController = TextEditingController();
  Map<String, dynamic>? profile;
  Map<String, dynamic>? preferences;
  List<dynamic> trips = [];
  List<dynamic> recommendations = [];
  List<dynamic> tourismPackages = [];
  List<dynamic> promotionalCampaigns = [];
  bool loadingForYou = false;
  bool loadingSharedContent = false;

  Future<void> loadSummary() async {
    try {
      final p = await api.get('/api/fr1/me');
      final t = await api.get('/api/fr5/itineraries');
      final pref = await api.get('/api/fr2/preferences');
      Map<String, dynamic>? prefMap;
      if (pref['preferences'] is Map) {
        prefMap = Map<String, dynamic>.from(pref['preferences'] as Map);
      }
      if (!mounted) return;
      setState(() {
        profile = p['profile'] is Map
            ? Map<String, dynamic>.from(p['profile'] as Map)
            : null;
        preferences = prefMap;
        trips = t['items'] as List? ?? [];
      });
      await refreshForYou();
      await loadSharedContent();
    } catch (_) {}
  }

  Future<void> refreshForYou() async {
    if (loadingForYou) return;
    setState(() => loadingForYou = true);
    try {
      final data = await api.post('/api/fr4/recommendations/generate', {
        'destinationArea': 'Malaysia',
      });
      if (!mounted) return;
      setState(() => recommendations = data['recommendations'] as List? ?? []);
    } catch (_) {
      try {
        final data = await api.get('/api/fr4/recommendations');
        if (mounted) {
          setState(
              () => recommendations = data['recommendations'] as List? ?? []);
        }
      } catch (_) {}
    } finally {
      if (mounted) setState(() => loadingForYou = false);
    }
  }

  Future<void> loadSharedContent() async {
    if (loadingSharedContent) return;
    setState(() => loadingSharedContent = true);
    try {
      final packagesData = await api.get('/api/public/tourism-packages');
      final campaignsData = await api.get('/api/public/promotional-campaigns');
      if (!mounted) return;
      final loadedCampaigns = campaignsData['items'] as List? ?? [];
      final loadedPackages = (packagesData['items'] as List? ?? []).map((raw) {
        final package = Map<String, dynamic>.from(raw as Map);
        final pid = (package['id'] ?? '').toString();
        package['activeCampaigns'] = loadedCampaigns
            .where((c) => c is Map && (c['packageId'] ?? '').toString() == pid)
            .toList();
        return package;
      }).toList();
      setState(() {
        tourismPackages = loadedPackages;
        promotionalCampaigns = loadedCampaigns;
      });
    } catch (_) {
      // Shared content is optional on Home when the database has no approved records yet.
    } finally {
      if (mounted) setState(() => loadingSharedContent = false);
    }
  }

  Future<void> addPackageToTrip(Map<String, dynamic> item) async {
    final packagePlace = <String, dynamic>{
      'destinationId': 'package_${item['id'] ?? item['packageTitle'] ?? ''}',
      'title': item['packageTitle'] ?? 'Tourism package',
      'address': item['destinationName'] ?? '',
      'estimatedCost': item['price'] ?? 0,
      'gps_coordinates':
          item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
      'type': item['type'] ?? item['category'] ?? 'Tourism package',
      'category': 'Tourism package',
      'description': item['description'] ?? '',
      'openingHours': item['openingHours'] ?? '',
      'indoor': item['indoor'] ?? false,
      'recommendedDurationMinutes': item['recommendedDurationMinutes'] ?? 180,
      'packageId': item['id'] ?? '',
    };
    await addToTrip(packagePlace);
  }

  Widget tourismPackageCard(Map<String, dynamic> item) {
    return SizedBox(
      width: 285,
      child: InkCard(
        padding: EdgeInsets.zero,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          TravelPlaceImage(
            place: {
              'title': item['packageTitle'] ??
                  item['destinationName'] ??
                  'Tourism package',
              'imageUrl': item['imageUrl'] ?? item['bannerImageUrl'] ?? '',
              'category': 'Tourism package',
            },
            height: 135,
            width: double.infinity,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(13, 11, 13, 13),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                const Expanded(
                    child: TravelStatusPill(
                        text: 'OPERATOR PACKAGE',
                        icon: Icons.verified_outlined)),
                const SizedBox(width: 6),
                Text('RM ${item['price'] ?? 0}',
                    style: const TextStyle(fontWeight: FontWeight.w900)),
              ]),
              const SizedBox(height: 8),
              Text((item['packageTitle'] ?? 'Tourism package').toString(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w900)),
              const SizedBox(height: 3),
              Text((item['destinationName'] ?? '').toString(),
                  style: const TextStyle(
                      color: InkWashColors.mutedInk, fontSize: 12)),
              if ((item['operatorName'] ?? '').toString().isNotEmpty)
                Text('By ${item['operatorName']}',
                    style: const TextStyle(
                        color: InkWashColors.mutedInk, fontSize: 11)),
              const SizedBox(height: 9),
              Row(children: [
                Expanded(
                    child: OutlinedButton(
                  onPressed: () => open(TourismPackageDetailsScreen(
                      item: item, onAddToTrip: () => addPackageToTrip(item))),
                  child: const Text('Details'),
                )),
                const SizedBox(width: 7),
                Expanded(
                    child: FilledButton(
                        onPressed: () => addPackageToTrip(item),
                        child: const Text('Add to trip'))),
              ]),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget campaignCard(Map<String, dynamic> item) {
    final discount = (item['discountValue'] ?? '').toString();
    final discountType = (item['discountType'] ?? '').toString();
    final badge = discount.isEmpty
        ? 'PROMOTION'
        : (discountType == 'percentage'
            ? '$discount% OFF'
            : 'SAVE RM $discount');
    return SizedBox(
      width: 275,
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => open(CampaignDetailsScreen(item: item)),
        child: InkCard(
          color: InkWashColors.cream,
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            TravelStatusPill(text: badge, icon: Icons.local_offer_outlined),
            const SizedBox(height: 9),
            Text((item['campaignTitle'] ?? 'Travel promotion').toString(),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style:
                    const TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
            if ((item['packageTitle'] ?? '').toString().isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(item['packageTitle'].toString(),
                  style: const TextStyle(color: InkWashColors.mutedInk))
            ],
            if ((item['promoCode'] ?? '').toString().isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('Code: ${item['promoCode']}',
                  style: const TextStyle(fontWeight: FontWeight.w800))
            ],
            const Spacer(),
            const Align(
                alignment: Alignment.centerRight,
                child: Icon(Icons.chevron_right_rounded)),
          ]),
        ),
      ),
    );
  }

  @override
  void initState() {
    super.initState();
    Future.microtask(loadSummary);
  }

  String get firstName {
    final value = (profile?['name'] ?? '').toString().trim();
    if (value.isNotEmpty) return value.split(' ').first;
    final email = FirebaseAuth.instance.currentUser?.email ?? '';
    return email.contains('@') ? email.split('@').first : 'Traveller';
  }

  String get preferenceSummary {
    final interests =
        (preferences?['interests'] as List? ?? []).take(3).join(', ');
    final pace = (preferences?['travelPace'] ?? '').toString();
    if (interests.isEmpty && pace.isEmpty)
      return 'Built from your saved travel profile';
    return [
      if (interests.isNotEmpty) interests,
      if (pace.isNotEmpty) '$pace pace'
    ].join(' • ');
  }

  void open(Widget screen) {
    Navigator.push(context, MaterialPageRoute(builder: (_) => screen))
        .then((_) => loadSummary());
  }

  String destinationId(Map<String, dynamic> item) =>
      (item['destinationId'] ?? item['place_id'] ?? item['title'] ?? '')
          .toString();

  Future<void> addToTrip(Map<String, dynamic> item) async {
    try {
      final data = await api.get('/api/fr5/itineraries');
      final available = data['items'] as List? ?? [];
      if (!mounted) return;
      if (available.isEmpty) {
        final go = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Create a trip first'),
            content: const Text(
                'Create a trip, then you can add recommended places directly from Home.'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Not now')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Create trip')),
            ],
          ),
        );
        if (go == true && mounted) open(const TripsTab());
        return;
      }
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(18, 0, 18, 22),
            children: [
              const Text('Add place to trip',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
              const SizedBox(height: 8),
              ...available.map((raw) {
                final trip = Map<String, dynamic>.from(raw as Map);
                return ListTile(
                  leading: const CircleAvatar(
                      backgroundColor: InkWashColors.cream,
                      child: Icon(Icons.luggage_outlined)),
                  title: Text((trip['title'] ?? 'Trip').toString()),
                  subtitle: Text((trip['destinationArea'] ?? '').toString()),
                  onTap: () => Navigator.pop(context, trip),
                );
              }),
            ],
          ),
        ),
      );
      if (selected == null) return;
      await api.post('/api/fr5/itineraries/${selected['id']}/activities', {
        'activityName': (item['title'] ?? item['name'] ?? 'Place').toString(),
        'destinationId': destinationId(item),
        'address': item['address'] ?? '',
        'estimatedCost': item['estimatedCost'] ?? 0,
        'gps_coordinates':
            item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
        'type': item['type'] ?? item['category'] ?? '',
        'category': item['category'] ?? item['type'] ?? '',
        'description': item['description'] ?? '',
        'indoor': item['indoor'] ?? false,
        'openingHours': item['openingHours'] ?? '',
        'recommendedDurationMinutes': item['recommendedDurationMinutes'] ?? 90,
        'dayNo': 1,
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Added to ${selected['title'] ?? 'trip'}')),
        );
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Widget personalisedPlaceCard(Map<String, dynamic> item) {
    return SizedBox(
      width: 270,
      child: InkCard(
        padding: EdgeInsets.zero,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TravelPlaceImage(
              place: item,
              height: 145,
              width: double.infinity,
              borderRadius:
                  const BorderRadius.vertical(top: Radius.circular(20)),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(13, 11, 13, 13),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    (item['title'] ?? item['name'] ?? 'Place').toString(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w900),
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      const Icon(Icons.star_rounded,
                          size: 16, color: InkWashColors.blueGrey),
                      const SizedBox(width: 3),
                      Text('${item['rating'] ?? '-'}'),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          (item['category'] ?? item['type'] ?? '').toString(),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: InkWashColors.mutedInk, fontSize: 12),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 7),
                  Text(
                    (item['reason'] ??
                            'Recommended from your saved preferences')
                        .toString(),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: InkWashColors.mutedInk, fontSize: 12),
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: () => open(DestinationDetailsScreen(
                              initialDestination: item)),
                          child: const Text('Details'),
                        ),
                      ),
                      const SizedBox(width: 7),
                      Expanded(
                        child: FilledButton(
                          onPressed: () => addToTrip(item),
                          child: const Text('Add to trip'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final latestTrip =
        trips.isNotEmpty ? Map<String, dynamic>.from(trips.first as Map) : null;

    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: loadSummary,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(18, 14, 18, 28),
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('TRAVELMATE',
                            style: TextStyle(
                                color: InkWashColors.blueGrey,
                                fontWeight: FontWeight.w900,
                                letterSpacing: 1.0)),
                        const SizedBox(height: 3),
                        Text('Where to next, $firstName?',
                            style: const TextStyle(
                                fontSize: 27,
                                fontWeight: FontWeight.w900,
                                color: InkWashColors.ink)),
                      ],
                    ),
                  ),
                  CircleAvatar(
                    radius: 24,
                    backgroundColor: InkWashColors.cream,
                    child: Text(firstName[0].toUpperCase(),
                        style: const TextStyle(
                            fontWeight: FontWeight.w900,
                            color: InkWashColors.charcoal)),
                  ),
                ],
              ),
              const SizedBox(height: 18),
              TextField(
                controller: searchController,
                textInputAction: TextInputAction.search,
                onSubmitted: (value) => open(ExploreTab(
                    initialQuery:
                        value.trim().isEmpty ? 'attractions' : value.trim(),
                    initialLocation: 'Malaysia')),
                decoration: const InputDecoration(
                  hintText: 'Search places, dishes, culture, nature...',
                  prefixIcon: Icon(Icons.search_rounded),
                ),
              ),
              const SizedBox(height: 16),
              InkCard(
                color: InkWashColors.cream,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const TravelStatusPill(
                        text: 'PERSONALISED PLANNING',
                        icon: Icons.auto_awesome_rounded),
                    const SizedBox(height: 10),
                    const Text('Plan around your travel style',
                        style: TextStyle(
                            fontSize: 22, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 5),
                    Text(preferenceSummary),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        FilledButton.icon(
                            onPressed: () => open(const RecommendationScreen()),
                            icon: const Icon(Icons.auto_awesome_rounded),
                            label: const Text('All recommendations')),
                        OutlinedButton.icon(
                            onPressed: () =>
                                open(const PersonalizedPlanningScreen()),
                            icon: const Icon(Icons.auto_fix_high_rounded),
                            label: const Text('Build a plan')),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              TravelSectionHeader(
                title: 'Picked for you',
                subtitle: preferenceSummary,
                actionLabel: 'Refresh',
                onAction: refreshForYou,
              ),
              const SizedBox(height: 11),
              if (loadingForYou && recommendations.isEmpty)
                const SizedBox(
                    height: 180,
                    child: Center(child: CircularProgressIndicator()))
              else if (recommendations.isEmpty)
                TravelEmptyState(
                  icon: Icons.auto_awesome_outlined,
                  title: 'Complete your travel preferences',
                  message:
                      'Your saved preferences are used to rank places for this section.',
                  actionLabel: 'Explore places',
                  onAction: () =>
                      open(const ExploreTab(initialLocation: 'Malaysia')),
                )
              else
                SizedBox(
                  height: 360,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: recommendations.take(8).length,
                    separatorBuilder: (_, __) => const SizedBox(width: 11),
                    itemBuilder: (context, index) {
                      final item = Map<String, dynamic>.from(
                          recommendations[index] as Map);
                      return personalisedPlaceCard(item);
                    },
                  ),
                ),
              const SizedBox(height: 24),
              TravelSectionHeader(
                title: 'Featured tourism packages',
                subtitle:
                    'Approved packages published by TravelMate Tourism Operators',
                actionLabel: tourismPackages.isEmpty
                    ? null
                    : '${tourismPackages.length} available',
              ),
              const SizedBox(height: 11),
              if (loadingSharedContent && tourismPackages.isEmpty)
                const SizedBox(
                    height: 170,
                    child: Center(child: CircularProgressIndicator()))
              else if (tourismPackages.isEmpty)
                const TravelEmptyState(
                  icon: Icons.card_travel_outlined,
                  title: 'No approved packages yet',
                  message:
                      'Tourism packages will appear here after a Tourism Operator submits them and an Administrator approves them.',
                )
              else
                SizedBox(
                  height: 335,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: tourismPackages.take(8).length,
                    separatorBuilder: (_, __) => const SizedBox(width: 11),
                    itemBuilder: (context, index) => tourismPackageCard(
                        Map<String, dynamic>.from(
                            tourismPackages[index] as Map)),
                  ),
                ),
              const SizedBox(height: 24),
              if (promotionalCampaigns.isNotEmpty) ...[
                const TravelSectionHeader(
                  title: 'Current promotions',
                  subtitle:
                      'Administrator-approved offers from Tourism Operators',
                ),
                const SizedBox(height: 11),
                SizedBox(
                  height: 205,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: promotionalCampaigns.take(8).length,
                    separatorBuilder: (_, __) => const SizedBox(width: 11),
                    itemBuilder: (context, index) => campaignCard(
                        Map<String, dynamic>.from(
                            promotionalCampaigns[index] as Map)),
                  ),
                ),
                const SizedBox(height: 24),
              ],
              const TravelSectionHeader(
                  title: 'Plan & compare',
                  subtitle: 'Useful travel tools in one place'),
              const SizedBox(height: 11),
              TravelQuickAction(
                  icon: Icons.flight_takeoff_rounded,
                  label: 'Flights',
                  subtitle: 'Search, compare and inspect flight details',
                  onTap: () => open(const FlightScreen())),
              const SizedBox(height: 9),
              TravelQuickAction(
                  icon: Icons.hotel_rounded,
                  label: 'Hotels',
                  subtitle: 'Search, compare and continue a hotel booking',
                  onTap: () => open(const HotelScreen())),
              const SizedBox(height: 9),
              TravelQuickAction(
                  icon: Icons.directions_car_outlined,
                  label: 'Car rentals',
                  subtitle: 'Compare rental cars and attach cost to a trip',
                  onTap: () => open(const CarRentalScreen())),
              const SizedBox(height: 9),
              TravelQuickAction(
                  icon: Icons.cloud_outlined,
                  label: 'Weather',
                  subtitle: 'Current conditions and 7-day forecast',
                  onTap: () => open(const WeatherScreen())),
              const SizedBox(height: 24),
              TravelSectionHeader(
                title: 'Your trip',
                subtitle: latestTrip == null
                    ? 'Start your first itinerary'
                    : 'Continue your latest itinerary',
                actionLabel: 'All trips',
                onAction: () => open(const TripsTab()),
              ),
              const SizedBox(height: 11),
              if (latestTrip == null)
                TravelEmptyState(
                  icon: Icons.luggage_outlined,
                  title: 'No trip yet',
                  message:
                      'Create a trip and add recommended or searched places.',
                  actionLabel: 'Create trip',
                  onAction: () => open(const TripsTab()),
                )
              else
                InkWell(
                  borderRadius: BorderRadius.circular(20),
                  onTap: () => open(const TripsTab()),
                  child: InkCard(
                    child: Row(
                      children: [
                        Container(
                          width: 52,
                          height: 52,
                          decoration: BoxDecoration(
                              color: InkWashColors.paleBlue,
                              borderRadius: BorderRadius.circular(15)),
                          child: const Icon(Icons.route_rounded,
                              color: InkWashColors.blueGrey),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                  (latestTrip['title'] ?? 'My trip').toString(),
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w900,
                                      fontSize: 17)),
                              Text(
                                  (latestTrip['destinationArea'] ?? '')
                                      .toString(),
                                  style: const TextStyle(
                                      color: InkWashColors.mutedInk)),
                              const SizedBox(height: 6),
                              Text(
                                  'RM ${latestTrip['budgetLimit'] ?? 0} • ${(latestTrip['activities'] as List? ?? []).length} places',
                                  style: const TextStyle(
                                      fontSize: 12,
                                      fontWeight: FontWeight.w700)),
                            ],
                          ),
                        ),
                        const Icon(Icons.chevron_right_rounded),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
