import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr05_smart_itinerary_budget_planner/trips_tab.dart';
import '../fr10_feedback_rating/feedback_screen.dart';

class DestinationDetailsScreen extends StatefulWidget {
  final Map<String, dynamic> initialDestination;

  const DestinationDetailsScreen({
    super.key,
    required this.initialDestination,
  });

  @override
  State<DestinationDetailsScreen> createState() =>
      _DestinationDetailsScreenState();
}

class _DestinationDetailsScreenState extends State<DestinationDetailsScreen> {
  final ApiService api = ApiService();

  late Map<String, dynamic> detail;
  Map<String, dynamic>? reviewInfo;
  List<Map<String, dynamic>> nearbyPlaces = [];
  bool loading = true;
  bool saving = false;
  bool adding = false;
  bool showAllReviews = false;
  bool showMoreVisitorInfo = false;
  String source = '';
  String reviewSource = '';
  String? loadWarning;

  @override
  void initState() {
    super.initState();
    detail = Map<String, dynamic>.from(widget.initialDestination);
    Future.microtask(loadDetails);
  }

  String destinationId(Map<String, dynamic> item) {
    return (item['place_id'] ??
            item['data_id'] ??
            item['data_cid'] ??
            item['destinationId'] ??
            item['title'] ??
            item['name'] ??
            '')
        .toString()
        .trim();
  }

  Future<void> loadDetails() async {
    final id = destinationId(detail);
    if (id.isEmpty) {
      setState(() {
        loading = false;
        loadWarning = 'Destination reference is unavailable.';
      });
      return;
    }

    setState(() {
      loading = true;
      loadWarning = null;
    });

    try {
      final encoded = Uri.encodeComponent(id);
      final detailData = await api.get('/api/fr3/destinations/$encoded');

      if (detailData['destination'] is Map) {
        detail = {
          ...detail,
          ...Map<String, dynamic>.from(detailData['destination'] as Map),
        };
      }
      source = (detailData['source'] ?? '').toString();
      loadWarning = detailData['providerWarning']?.toString();

      try {
        final reviewData = await api.get(
          '/api/fr3/destinations/$encoded/ratings-reviews',
        );
        if (reviewData['result'] is Map) {
          reviewInfo = Map<String, dynamic>.from(
            reviewData['result'] as Map,
          );
        }
        reviewSource = (reviewData['source'] ?? '').toString();
      } catch (e) {
        // Details remain usable even if review text cannot be retrieved.
        loadWarning ??= 'Ratings and reviews could not be loaded.';
      }
      try {
        final nearbyData = await api.get(
          '/api/fr3/destinations/$encoded/nearby',
          {'radiusKm': '12'},
        );
        nearbyPlaces = (nearbyData['items'] as List? ?? [])
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
      } catch (_) {
        nearbyPlaces = [];
      }
    } catch (e) {
      loadWarning = e.toString();
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> saveFavourite() async {
    final payload = Map<String, dynamic>.from(detail);
    payload['destinationId'] = destinationId(payload);

    setState(() => saving = true);
    try {
      await api.post('/api/fr3/favourites', payload);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Destination saved to favourites.')),
        );
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  Future<void> addToItinerary([Map<String, dynamic>? target]) async {
    final item = target ?? detail;
    setState(() => adding = true);
    try {
      final data = await api.get('/api/fr5/itineraries');
      final trips = data['items'] as List? ?? [];

      if (!mounted) return;

      if (trips.isEmpty) {
        final go = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Create an itinerary first'),
            content: const Text(
              'Create a trip before adding this destination to an itinerary.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Cancel'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Go to Trips'),
              ),
            ],
          ),
        );

        if (go == true && mounted) {
          Navigator.push(
            context,
            MaterialPageRoute(builder: (_) => const TripsTab()),
          );
        }
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
              const Text(
                'Add destination to trip',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 5),
              Text(
                (item['title'] ?? item['name'] ?? title).toString(),
                style: const TextStyle(color: InkWashColors.mutedInk),
              ),
              const SizedBox(height: 10),
              ...trips.map((raw) {
                final trip = Map<String, dynamic>.from(raw as Map);
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const CircleAvatar(
                    backgroundColor: InkWashColors.cream,
                    child: Icon(
                      Icons.luggage_outlined,
                      color: InkWashColors.blueGrey,
                    ),
                  ),
                  title: Text((trip['title'] ?? 'Trip').toString()),
                  subtitle: Text((trip['destinationArea'] ?? '').toString()),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: () => Navigator.pop(context, trip),
                );
              }),
            ],
          ),
        ),
      );

      if (selected == null) return;

      await api.post(
        '/api/fr5/itineraries/${selected['id']}/activities',
        {
          'activityName': (item['title'] ?? item['name'] ?? title).toString(),
          'destinationId': destinationId(item),
          'dayNo': 1,
          'estimatedCost': item['estimatedCost'] ?? 0,
          'gps_coordinates':
              item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
          'type': item['type'] ?? item['category'] ?? '',
          'category': item['category'] ?? item['type'] ?? '',
          'description': item['description'] ?? '',
          'openingHours': item['openingHours'] ?? item['open_state'] ?? '',
          'indoor': item['indoor'] ?? false,
          'recommendedDurationMinutes': item['recommendedDurationMinutes'] ?? 0,
        },
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Added to ${selected['title'] ?? 'your itinerary'}.',
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => adding = false);
    }
  }

  String get title =>
      (detail['title'] ?? detail['name'] ?? 'Destination').toString();

  String get address =>
      (detail['address'] ?? detail['location'] ?? '').toString();

  String get type =>
      (detail['type'] ?? detail['category'] ?? 'Place').toString();

  dynamic get rating => reviewInfo?['rating'] ?? detail['rating'];
  dynamic get reviewCount => reviewInfo?['reviews'] ?? detail['reviews'];

  List<String> imageUrls() {
    final urls = <String>{};

    void add(dynamic value) {
      final url = (value ?? '').toString().trim();
      if (url.startsWith('http://') || url.startsWith('https://')) {
        urls.add(url);
      }
    }

    add(detail['thumbnail']);
    add(detail['image']);
    add(detail['imageUrl']);
    add(detail['mainPhoto']);
    add(detail['main_photo']);

    final images = detail['images'];
    if (images is List) {
      for (final raw in images) {
        if (raw is Map) {
          add(raw['thumbnail']);
          add(raw['image']);
          add(raw['link']);
        } else {
          add(raw);
        }
      }
    }

    return urls.take(8).toList();
  }

  List<Map<String, dynamic>> reviewItems() {
    final raw = reviewInfo?['user_reviews'];

    if (raw is List) {
      return raw
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
    }

    if (raw is Map) {
      for (final key in ['most_relevant', 'reviews', 'items']) {
        final value = raw[key];
        if (value is List) {
          return value
              .whereType<Map>()
              .map((e) => Map<String, dynamic>.from(e))
              .toList();
        }
      }
    }

    return [];
  }

  String reviewAuthor(Map<String, dynamic> review) {
    final user = review['user'];
    if (user is Map) {
      return (user['name'] ?? user['username'] ?? 'Traveller').toString();
    }
    return (review['username'] ?? review['author'] ?? 'Traveller').toString();
  }

  String displayValue(dynamic value) {
    if (value == null) return '';
    if (value is String) return value;
    if (value is num || value is bool) return value.toString();
    if (value is List) {
      return value.map(displayValue).where((e) => e.isNotEmpty).join('\n');
    }
    if (value is Map) {
      return value.entries
          .map((e) => '${e.key}: ${displayValue(e.value)}')
          .join('\n');
    }
    return value.toString();
  }

  Widget infoRow(IconData icon, String label, String value) {
    if (value.trim().isEmpty) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: InkWashColors.paleBlue,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: InkWashColors.blueGrey, size: 20),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(
                    color: InkWashColors.mutedInk,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget sourcePill() {
    if (source.isEmpty) return const SizedBox.shrink();

    final label = switch (source) {
      'serpapi' => 'LIVE PLACE DETAILS',
      'cache' => 'SAVED PLACE DETAILS',
      'openstreetmap' => 'ONLINE MAP DETAILS',
      'local' => 'TRAVELMATE PLACE DETAILS',
      _ => 'PLACE DETAILS',
    };

    return TravelStatusPill(
      text: label,
      icon: source == 'serpapi' || source == 'openstreetmap'
          ? Icons.cloud_done_outlined
          : source == 'cache'
              ? Icons.storage_outlined
              : Icons.place_outlined,
    );
  }

  @override
  Widget build(BuildContext context) {
    final images = imageUrls();
    final reviews = reviewItems();
    final description =
        (detail['description'] ?? detail['snippet'] ?? '').toString();
    final opening = displayValue(
      detail['open_state'] ?? detail['openingHours'] ?? detail['hours'],
    );
    final phone = displayValue(detail['phone']);
    final website = displayValue(
      detail['website'] ??
          (detail['links'] is Map ? detail['links']['website'] : null),
    );
    final price = displayValue(detail['price']);
    final estimatedCost = detail['estimatedCost'];
    final duration = detail['recommendedDurationMinutes'];
    final gps = detail['gps_coordinates'] ?? detail['gpsCoordinates'];
    final gpsText = gps is Map
        ? '${gps['latitude'] ?? '-'}, ${gps['longitude'] ?? '-'}'
        : '';
    final weeklyHours = detail['weeklyHours'];
    final admission = displayValue(detail['admission']);
    final bestTime = displayValue(detail['bestTime']);
    final visitTips = detail['visitTips'] is List
        ? (detail['visitTips'] as List).map((e) => e.toString()).toList()
        : <String>[];
    final facilities = detail['facilities'] is List
        ? (detail['facilities'] as List).map((e) => e.toString()).toList()
        : <String>[];
    final visibleReviews = showAllReviews ? reviews : reviews.take(5).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Destination details'),
        actions: [
          IconButton(
            tooltip: 'Write a review',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(
                  builder: (_) => FeedbackScreen(initialDestination: detail)),
            ),
            icon: const Icon(Icons.rate_review_outlined),
          ),
          IconButton(
            tooltip: 'Save favourite',
            onPressed: saving ? null : saveFavourite,
            icon: const Icon(Icons.favorite_border_rounded),
          ),
        ],
      ),
      bottomNavigationBar: SafeArea(
        top: false,
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
          decoration: const BoxDecoration(
            color: Colors.white,
            border: Border(top: BorderSide(color: Color(0xFFE7E7E2))),
          ),
          child: Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: saving ? null : saveFavourite,
                  icon: const Icon(Icons.favorite_border_rounded),
                  label: Text(saving ? 'Saving...' : 'Favourite'),
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                flex: 2,
                child: FilledButton.icon(
                  onPressed: adding ? null : addToItinerary,
                  icon: const Icon(Icons.add_road_rounded),
                  label: Text(adding ? 'Adding...' : 'Add to itinerary'),
                ),
              ),
            ],
          ),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: loadDetails,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 6, 18, 28),
          children: [
            if (loading) ...[
              const LinearProgressIndicator(),
              const SizedBox(height: 12),
            ],
            if (images.isNotEmpty) ...[
              SizedBox(
                height: 220,
                child: PageView.builder(
                  itemCount: images.length,
                  itemBuilder: (context, index) => Padding(
                    padding: const EdgeInsets.only(right: 7),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(22),
                      child: Image.network(
                        images[index],
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => Container(
                          color: InkWashColors.paleBlue,
                          alignment: Alignment.center,
                          child: const Icon(
                            Icons.image_not_supported_outlined,
                            color: InkWashColors.blueGrey,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),
            ] else
              TravelPlaceImage(
                place: detail,
                height: 190,
                width: double.infinity,
                borderRadius: BorderRadius.circular(22),
              ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                sourcePill(),
                TravelStatusPill(
                  text: type,
                  icon: Icons.category_outlined,
                ),
                if (detail['indoor'] != null)
                  TravelStatusPill(
                    text: detail['indoor'] == true ? 'Indoor' : 'Outdoor',
                    icon: detail['indoor'] == true
                        ? Icons.home_outlined
                        : Icons.park_outlined,
                  ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              title,
              style: const TextStyle(
                fontSize: 27,
                fontWeight: FontWeight.w900,
                letterSpacing: -0.5,
              ),
            ),
            if (address.isNotEmpty) ...[
              const SizedBox(height: 5),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.location_on_outlined,
                    size: 18,
                    color: InkWashColors.mutedInk,
                  ),
                  const SizedBox(width: 5),
                  Expanded(
                    child: Text(
                      address,
                      style: const TextStyle(
                        color: InkWashColors.mutedInk,
                      ),
                    ),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                TravelStatusPill(
                  text: '${rating ?? '-'} rating',
                  icon: Icons.star_rounded,
                ),
                TravelStatusPill(
                  text: '${reviewCount ?? '-'} reviews',
                  icon: Icons.rate_review_outlined,
                ),
                if (price.isNotEmpty)
                  TravelStatusPill(
                    text: price,
                    icon: Icons.payments_outlined,
                  ),
                if (estimatedCost != null)
                  TravelStatusPill(
                    text: 'Est. RM $estimatedCost',
                    icon: Icons.account_balance_wallet_outlined,
                  ),
                if (duration != null && duration.toString() != '0')
                  TravelStatusPill(
                    text: '$duration min suggested',
                    icon: Icons.schedule_outlined,
                  ),
              ],
            ),
            if (loadWarning != null && source != 'serpapi') ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: InkWashColors.cream,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.info_outline_rounded,
                      size: 18,
                      color: InkWashColors.blueGrey,
                    ),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Some live provider details are unavailable, so TravelMate is showing the available saved information.',
                        style: TextStyle(fontSize: 12),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (description.isNotEmpty) ...[
              const SizedBox(height: 24),
              const TravelSectionHeader(title: 'About this place'),
              const SizedBox(height: 10),
              InkCard(
                child: Text(
                  description,
                  style: const TextStyle(height: 1.5),
                ),
              ),
            ],
            const SizedBox(height: 24),
            const TravelSectionHeader(
              title: 'Visitor information',
              subtitle: 'Available information returned for this destination',
            ),
            const SizedBox(height: 11),
            InkCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  infoRow(
                      Icons.schedule_outlined, 'Opening information', opening),
                  if (weeklyHours is Map) ...[
                    const Divider(height: 18),
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text('Opening days & hours',
                          style: TextStyle(fontWeight: FontWeight.w900)),
                    ),
                    const SizedBox(height: 8),
                    ...weeklyHours.entries.map((entry) => Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          child: Row(
                            children: [
                              SizedBox(
                                  width: 98,
                                  child: Text(entry.key.toString(),
                                      style: const TextStyle(
                                          fontWeight: FontWeight.w700))),
                              Expanded(
                                  child: Text(entry.value.toString(),
                                      textAlign: TextAlign.right)),
                            ],
                          ),
                        )),
                    const SizedBox(height: 4),
                    const Text(
                        'Opening schedules can change on public holidays or due to operational conditions.',
                        style: TextStyle(
                            fontSize: 11, color: InkWashColors.mutedInk)),
                  ],
                  infoRow(Icons.confirmation_number_outlined, 'Admission',
                      admission),
                  infoRow(
                      Icons.wb_sunny_outlined, 'Best visiting time', bestTime),
                  if (showMoreVisitorInfo) ...[
                    infoRow(Icons.phone_outlined, 'Phone', phone),
                    infoRow(Icons.language_outlined, 'Website', website),
                    infoRow(Icons.payments_outlined, 'Price level', price),
                    infoRow(Icons.location_searching_rounded, 'GPS coordinates',
                        gpsText),
                    if (facilities.isNotEmpty) ...[
                      const Align(
                          alignment: Alignment.centerLeft,
                          child: Text('Facilities',
                              style: TextStyle(fontWeight: FontWeight.w900))),
                      const SizedBox(height: 7),
                      Wrap(
                          spacing: 7,
                          runSpacing: 7,
                          children: facilities
                              .map((e) => Chip(label: Text(e)))
                              .toList()),
                      const SizedBox(height: 12),
                    ],
                    if (visitTips.isNotEmpty) ...[
                      const Align(
                          alignment: Alignment.centerLeft,
                          child: Text('Visitor tips',
                              style: TextStyle(fontWeight: FontWeight.w900))),
                      const SizedBox(height: 7),
                      ...visitTips.map((tip) => Padding(
                            padding: const EdgeInsets.only(bottom: 6),
                            child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  const Text('•  '),
                                  Expanded(child: Text(tip))
                                ]),
                          )),
                    ],
                  ],
                  const SizedBox(height: 4),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton.icon(
                      onPressed: () => setState(
                          () => showMoreVisitorInfo = !showMoreVisitorInfo),
                      icon: Icon(showMoreVisitorInfo
                          ? Icons.expand_less_rounded
                          : Icons.expand_more_rounded),
                      label: Text(showMoreVisitorInfo
                          ? 'Show less information'
                          : 'View more visitor information'),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            TravelSectionHeader(
              title: 'Nearby places',
              subtitle: nearbyPlaces.isEmpty
                  ? 'No nearby suggestions are available for this destination yet'
                  : 'Places close enough to combine in the same itinerary day',
            ),
            const SizedBox(height: 11),
            if (nearbyPlaces.isEmpty)
              const TravelEmptyState(
                icon: Icons.near_me_outlined,
                title: 'No nearby places found',
                message:
                    'Search results with location data will show nearby places here.',
              )
            else
              ...nearbyPlaces.take(6).map((place) {
                final nearbyId = destinationId(place);
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: InkCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          const CircleAvatar(
                            backgroundColor: InkWashColors.paleBlue,
                            child: Icon(Icons.near_me_outlined,
                                color: InkWashColors.blueGrey),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  (place['title'] ?? place['name'] ?? 'Place')
                                      .toString(),
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w900),
                                ),
                                Text(
                                  (place['nearbyReason'] ??
                                          '${place['distanceKm'] ?? '-'} km away')
                                      .toString(),
                                  style: const TextStyle(
                                      color: InkWashColors.mutedInk,
                                      fontSize: 12),
                                ),
                              ],
                            ),
                          ),
                        ]),
                        const SizedBox(height: 8),
                        Row(children: [
                          Expanded(
                            child: TravelStatusPill(
                              text: '${place['rating'] ?? '-'} rating',
                              icon: Icons.star_rounded,
                            ),
                          ),
                          TextButton(
                            onPressed: nearbyId.isEmpty
                                ? null
                                : () => Navigator.push(
                                      context,
                                      MaterialPageRoute(
                                        builder: (_) =>
                                            DestinationDetailsScreen(
                                                initialDestination: place),
                                      ),
                                    ),
                            child: const Text('Details'),
                          ),
                          FilledButton.tonal(
                            onPressed:
                                adding ? null : () => addToItinerary(place),
                            child: const Text('Add'),
                          ),
                        ]),
                      ],
                    ),
                  ),
                );
              }),
            const SizedBox(height: 24),
            TravelSectionHeader(
              title: 'Ratings & reviews',
              subtitle: reviewSource == 'travelmate_database'
                  ? 'Reviews submitted by TravelMate Travellers and moderated by the Administrator'
                  : 'TravelMate Traveller review information',
            ),
            const SizedBox(height: 11),
            InkCard(
              child: Row(
                children: [
                  Container(
                    width: 62,
                    height: 62,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: InkWashColors.cream,
                      borderRadius: BorderRadius.circular(18),
                    ),
                    child: Text(
                      '${rating ?? '-'}',
                      style: const TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                  const SizedBox(width: 13),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Overall rating',
                          style: TextStyle(fontWeight: FontWeight.w900),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '${reviewCount ?? 0} review(s)',
                          style: const TextStyle(
                            color: InkWashColors.mutedInk,
                          ),
                        ),
                        if ((reviewInfo?['review_summary'] ?? '')
                            .toString()
                            .isNotEmpty) ...[
                          const SizedBox(height: 5),
                          Text(
                            reviewInfo!['review_summary'].toString(),
                            style: const TextStyle(fontSize: 12),
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 10),
            if (reviews.isEmpty)
              const TravelEmptyState(
                icon: Icons.rate_review_outlined,
                title: 'No Traveller reviews yet',
                message:
                    'Be the first TravelMate Traveller to rate and review this place.',
              )
            else
              ...visibleReviews.map((review) {
                final body = (review['description'] ??
                        review['text'] ??
                        review['snippet'] ??
                        '')
                    .toString();
                final reviewRating = review['rating'];
                final date = (review['date'] ?? review['relative_date'] ?? '')
                    .toString();

                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: InkCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            CircleAvatar(
                              radius: 18,
                              backgroundColor: InkWashColors.paleBlue,
                              child: Text(
                                reviewAuthor(review).isEmpty
                                    ? 'T'
                                    : reviewAuthor(review)[0].toUpperCase(),
                                style: const TextStyle(
                                  color: InkWashColors.blueGrey,
                                  fontWeight: FontWeight.w900,
                                ),
                              ),
                            ),
                            const SizedBox(width: 9),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    reviewAuthor(review),
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                  if (date.isNotEmpty)
                                    Text(
                                      date,
                                      style: const TextStyle(
                                        color: InkWashColors.mutedInk,
                                        fontSize: 11,
                                      ),
                                    ),
                                ],
                              ),
                            ),
                            if (reviewRating != null)
                              TravelStatusPill(
                                text: '$reviewRating',
                                icon: Icons.star_rounded,
                              ),
                          ],
                        ),
                        if (body.isNotEmpty) ...[
                          const SizedBox(height: 9),
                          Text(body),
                        ],
                      ],
                    ),
                  ),
                );
              }),
            if (reviews.length > 5) ...[
              const SizedBox(height: 2),
              Center(
                child: TextButton.icon(
                  onPressed: () =>
                      setState(() => showAllReviews = !showAllReviews),
                  icon: Icon(showAllReviews
                      ? Icons.expand_less_rounded
                      : Icons.expand_more_rounded),
                  label: Text(showAllReviews
                      ? 'Show fewer reviews'
                      : 'View all ${reviews.length} reviews'),
                ),
              ),
            ],
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(
                    builder: (_) => FeedbackScreen(initialDestination: detail)),
              ),
              icon: const Icon(Icons.rate_review_outlined),
              label: const Text('Write a review for this place'),
            ),
          ],
        ),
      ),
    );
  }
}
