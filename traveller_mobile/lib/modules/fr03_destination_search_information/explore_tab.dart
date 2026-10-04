import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../theme/app_theme.dart';
import '../../core/navigation/app_shell_navigation.dart';
import 'favourites_screen.dart';
import 'destination_details_screen.dart';
import '../fr04_hybrid_recommendation/recommendation_screen.dart';
import '../fr05_smart_itinerary_budget_planner/trips_tab.dart';
import '../fr08_hotel_booking/hotel_screen.dart';

class ExploreTab extends StatefulWidget {
  final String initialQuery;
  final String initialLocation;

  const ExploreTab({
    super.key,
    this.initialQuery = '',
    this.initialLocation = 'Malaysia',
  });

  @override
  State<ExploreTab> createState() => _ExploreTabState();
}

class _ExploreTabState extends State<ExploreTab> {
  late final TextEditingController query;
  late final TextEditingController location;
  final api = ApiService();

  List<dynamic> results = [];
  bool loading = false;
  String category = 'All';
  String sort = 'relevance';
  String locationUsed = '';

  final categories = const [
    ('All', Icons.explore_outlined),
    ('Food', Icons.restaurant_outlined),
    ('Culture', Icons.museum_outlined),
    ('Nature', Icons.park_outlined),
    ('Shopping', Icons.shopping_bag_outlined),
    ('Hotels', Icons.hotel_outlined),
  ];

  final examples = const [
    'Penang attractions',
    'curry mee in Penang',
    'heritage in George Town',
    'Kuala Lumpur food',
    'nature in Kuala Lumpur',
  ];

  @override
  void initState() {
    super.initState();
    query = TextEditingController(text: widget.initialQuery);
    location = TextEditingController(text: widget.initialLocation);
    if (widget.initialQuery.trim().isNotEmpty) Future.microtask(search);
  }

  @override
  void dispose() {
    query.dispose();
    location.dispose();
    super.dispose();
  }

  Future<void> search() async {
    final text = query.text.trim();
    if (text.isEmpty) return;
    setState(() => loading = true);

    final params = <String, String>{
      'q': text,
      'location':
          location.text.trim().isEmpty ? 'Malaysia' : location.text.trim(),
    };
    if (category != 'All') params['filter'] = category.toLowerCase();
    if (sort != 'relevance') params['sort'] = sort;

    try {
      final data = await api.get('/api/fr3/destinations/search', params);
      if (!mounted) return;
      setState(() {
        results = data['results'] ?? [];
        locationUsed =
            (data['locationUsed'] ?? params['location'] ?? '').toString();
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  String destinationId(Map<String, dynamic> item) {
    return (item['place_id'] ??
            item['data_id'] ??
            item['data_cid'] ??
            item['destinationId'] ??
            item['title'] ??
            '')
        .toString();
  }

  Future<void> save(Map<String, dynamic> item) async {
    final payload = Map<String, dynamic>.from(item);
    payload['destinationId'] = destinationId(payload);
    try {
      await api.post('/api/fr3/favourites', payload);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Saved to favourites.')),
        );
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> addToItinerary(Map<String, dynamic> item) async {
    try {
      final data = await api.get('/api/fr5/itineraries');
      final trips = data['items'] as List? ?? [];

      if (trips.isEmpty) {
        if (!mounted) return;
        final go = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Create a trip first'),
            content:
                const Text('Create an itinerary before adding this place.'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Go to Trips')),
            ],
          ),
        );
        if (go == true && mounted) {
          final switched =
              AppShellNavigation.select(context, AppShellTab.trips);
          if (!switched) {
            Navigator.push(
                context, MaterialPageRoute(builder: (_) => const TripsTab()));
          }
        }
        return;
      }

      if (!mounted) return;
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(18, 0, 18, 22),
            children: [
              const Text('Add to which trip?',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
              const SizedBox(height: 9),
              ...trips.map((raw) {
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
        'activityName':
            (item['title'] ?? item['name'] ?? 'Destination').toString(),
        'destinationId': destinationId(item),
        'address': item['address'] ?? '',
        'dayNo': 1,
        'estimatedCost': item['estimatedCost'] ?? 0,
        'gps_coordinates':
            item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
        'type': item['type'] ?? item['category'] ?? '',
        'category': item['category'] ?? item['type'] ?? '',
        'description': item['description'] ?? '',
        'indoor': item['indoor'] ?? false,
        'openingHours': item['openingHours'] ?? '',
        'recommendedDurationMinutes': item['recommendedDurationMinutes'] ?? 90,
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

  Future<void> viewDetails(Map<String, dynamic> item) async {
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => DestinationDetailsScreen(
          initialDestination: Map<String, dynamic>.from(item),
        ),
      ),
    );
  }

  Widget resultCard(Map<String, dynamic> item) {
    final rating = item['rating'];
    final reason = (item['searchReason'] ?? '').toString();
    return Padding(
      padding: const EdgeInsets.only(bottom: 13),
      child: InkCard(
        padding: EdgeInsets.zero,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            InkWell(
              onTap: () => viewDetails(item),
              borderRadius:
                  const BorderRadius.vertical(top: Radius.circular(20)),
              child: Stack(
                children: [
                  TravelPlaceImage(
                    place: item,
                    height: 180,
                    width: double.infinity,
                    borderRadius:
                        const BorderRadius.vertical(top: Radius.circular(20)),
                  ),
                  Positioned(
                    top: 10,
                    right: 10,
                    child: Material(
                      color: Colors.white.withValues(alpha: .94),
                      shape: const CircleBorder(),
                      child: IconButton(
                        onPressed: () => save(item),
                        icon: const Icon(Icons.favorite_border_rounded),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Text(
                          (item['title'] ?? item['name'] ?? 'Destination')
                              .toString(),
                          style: const TextStyle(
                              fontWeight: FontWeight.w900, fontSize: 18),
                        ),
                      ),
                      if (rating != null) ...[
                        const SizedBox(width: 8),
                        TravelStatusPill(text: '★ $rating'),
                      ],
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    (item['address'] ?? item['type'] ?? '').toString(),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: InkWashColors.mutedInk),
                  ),
                  const SizedBox(height: 7),
                  Wrap(
                    spacing: 7,
                    runSpacing: 7,
                    children: [
                      TravelStatusPill(
                          text: (item['category'] ?? item['type'] ?? 'Place')
                              .toString(),
                          icon: Icons.category_outlined),
                      if ((item['openingHours'] ?? '').toString().isNotEmpty)
                        TravelStatusPill(
                            text: (item['openingHours'] ?? '').toString(),
                            icon: Icons.schedule_outlined),
                    ],
                  ),
                  if (reason.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(reason,
                        style: const TextStyle(
                            fontSize: 12,
                            color: InkWashColors.blueGrey,
                            fontWeight: FontWeight.w700)),
                  ],
                  const SizedBox(height: 11),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: () => viewDetails(item),
                          icon: const Icon(Icons.info_outline_rounded),
                          label: const Text('Details'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: () => addToItinerary(item),
                          icon: const Icon(Icons.add_location_alt_outlined),
                          label: const Text('Add to trip'),
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
    return Scaffold(
      appBar: AppBar(
        title: const Text('Explore'),
        actions: [
          IconButton(
            tooltip: 'Recommendations',
            onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (_) => const RecommendationScreen())),
            icon: const Icon(Icons.auto_awesome_outlined),
          ),
          IconButton(
            tooltip: 'Favourites',
            onPressed: () => Navigator.push(context,
                MaterialPageRoute(builder: (_) => const FavouritesScreen())),
            icon: const Icon(Icons.favorite_border_rounded),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: search,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 6, 18, 28),
          children: [
            const TravelSectionHeader(
              title: 'Discover your next place',
              subtitle:
                  'Search by city, attraction type, dish, activity or place name',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: query,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => search(),
              decoration: const InputDecoration(
                hintText: 'e.g. curry mee, Penang attractions, KL museums',
                prefixIcon: Icon(Icons.search_rounded),
              ),
            ),
            const SizedBox(height: 9),
            TextField(
              controller: location,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => search(),
              decoration: const InputDecoration(
                hintText: 'Location (optional)',
                prefixIcon: Icon(Icons.location_on_outlined),
              ),
            ),
            const SizedBox(height: 10),
            SizedBox(
              height: 37,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: examples.length,
                separatorBuilder: (_, __) => const SizedBox(width: 7),
                itemBuilder: (context, index) => ActionChip(
                  label: Text(examples[index]),
                  onPressed: () {
                    query.text = examples[index];
                    location.text = 'Malaysia';
                    search();
                  },
                ),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 42,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: categories.length,
                separatorBuilder: (_, __) => const SizedBox(width: 7),
                itemBuilder: (context, index) {
                  final item = categories[index];
                  return ChoiceChip(
                    selected: category == item.$1,
                    avatar: Icon(item.$2, size: 17),
                    label: Text(item.$1),
                    onSelected: (_) {
                      if (item.$1 == 'Hotels') {
                        Navigator.push(
                            context,
                            MaterialPageRoute(
                                builder: (_) => const HotelScreen()));
                        return;
                      }
                      setState(() => category = item.$1);
                      if (query.text.trim().isNotEmpty) search();
                    },
                  );
                },
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: loading ? null : search,
                    icon: const Icon(Icons.travel_explore_rounded),
                    label: Text(loading ? 'Searching...' : 'Search places'),
                  ),
                ),
                const SizedBox(width: 8),
                PopupMenuButton<String>(
                  initialValue: sort,
                  onSelected: (value) {
                    setState(() => sort = value);
                    if (results.isNotEmpty) search();
                  },
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 'relevance', child: Text('Relevance')),
                    PopupMenuItem(
                        value: 'rating', child: Text('Highest rating')),
                    PopupMenuItem(value: 'name', child: Text('Name')),
                  ],
                  child: Container(
                    width: 52,
                    height: 52,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: const Color(0xFFE1E1DC)),
                    ),
                    child: const Icon(Icons.sort_rounded),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),
            if (!loading && results.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Text(
                  '${results.length} places found${locationUsed.isEmpty ? '' : ' • $locationUsed'}',
                  style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      color: InkWashColors.mutedInk),
                ),
              ),
            if (loading)
              const Center(
                  child: Padding(
                      padding: EdgeInsets.all(28),
                      child: CircularProgressIndicator()))
            else if (results.isEmpty && query.text.trim().isEmpty)
              const TravelEmptyState(
                icon: Icons.map_outlined,
                title: 'Search by what you really want',
                message:
                    'You can search a specific dish, activity, attraction type or place name.',
              )
            else if (results.isEmpty)
              TravelEmptyState(
                icon: Icons.search_off_rounded,
                title: 'No strong match yet',
                message:
                    'Try a wider city, a related category, or remove one filter. For food, include the dish and city.',
                actionLabel: 'Search all Malaysia',
                onAction: () {
                  location.text = 'Malaysia';
                  setState(() => category = 'All');
                  search();
                },
              )
            else
              ...results.map(
                  (raw) => resultCard(Map<String, dynamic>.from(raw as Map))),
          ],
        ),
      ),
    );
  }
}
