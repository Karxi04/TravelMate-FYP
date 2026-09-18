import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr03_destination_search_information/destination_details_screen.dart';

class RecommendationScreen extends StatefulWidget {
  final String initialDestination;
  const RecommendationScreen(
      {super.key, this.initialDestination = 'Penang, Malaysia'});

  @override
  State<RecommendationScreen> createState() => _RecommendationScreenState();
}

class _RecommendationScreenState extends State<RecommendationScreen> {
  final api = ApiService();
  late final TextEditingController destination;
  List<dynamic> items = [];
  bool busy = false;
  String source = '';
  Map<String, dynamic> engine = {};
  Map<String, dynamic> preferences = {};

  @override
  void initState() {
    super.initState();
    destination = TextEditingController(text: widget.initialDestination);
    Future.microtask(loadExisting);
  }

  Future<void> loadExisting() async {
    try {
      final data = await api.get('/api/fr4/recommendations');
      final prefData = await api.get('/api/fr2/preferences');
      if (!mounted) return;
      setState(() {
        items = data['recommendations'] ?? [];
        source = (data['source'] ?? '').toString();
        engine = data['engine'] is Map
            ? Map<String, dynamic>.from(data['engine'] as Map)
            : {};
        preferences = prefData['preferences'] is Map
            ? Map<String, dynamic>.from(prefData['preferences'] as Map)
            : {};
      });
    } catch (_) {}
  }

  Future<void> generate() async {
    setState(() => busy = true);
    try {
      final data = await api.post('/api/fr4/recommendations/generate', {
        'destinationArea': destination.text.trim(),
      });
      if (!mounted) return;
      setState(() {
        items = data['recommendations'] ?? [];
        source = (data['source'] ?? '').toString();
        engine = data['engine'] is Map
            ? Map<String, dynamic>.from(data['engine'] as Map)
            : {};
      });
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> addToItinerary(Map<String, dynamic> item) async {
    try {
      final data = await api.get('/api/fr5/itineraries');
      final trips = data['items'] as List? ?? [];
      if (!mounted) return;
      if (trips.isEmpty) {
        showError(context, 'Create an itinerary in Trips first.');
        return;
      }
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(18, 0, 18, 20),
            children: [
              const Text('Add recommendation to trip',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
              const SizedBox(height: 10),
              ...trips.map((raw) {
                final trip = Map<String, dynamic>.from(raw as Map);
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const CircleAvatar(
                    backgroundColor: InkWashColors.cream,
                    child: Icon(Icons.luggage_outlined,
                        color: InkWashColors.blueGrey),
                  ),
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
        'destinationId':
            (item['destinationId'] ?? item['place_id'] ?? '').toString(),
        'address': item['address'] ?? '',
        'dayNo': 1,
        'estimatedCost': item['estimatedCost'] ?? 0,
        'gps_coordinates':
            item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
        'type': item['type'] ?? item['category'] ?? '',
        'category': item['category'] ?? item['type'] ?? '',
        'description': item['description'] ?? '',
        'openingHours': item['openingHours'] ?? '',
        'indoor': item['indoor'] ?? false,
        'recommendedDurationMinutes': item['recommendedDurationMinutes'] ?? 90,
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text('Added to ${selected['title'] ?? 'itinerary'}')),
        );
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Widget scoreBar(String label, dynamic value) {
    final score = double.tryParse((value ?? 0).toString()) ?? 0;
    return Padding(
      padding: const EdgeInsets.only(top: 5),
      child: Row(
        children: [
          SizedBox(
              width: 92,
              child: Text(label, style: const TextStyle(fontSize: 12))),
          Expanded(
            child: LinearProgressIndicator(
              value: score.clamp(0, 100).toDouble() / 100.0,
              minHeight: 7,
              borderRadius: BorderRadius.circular(20),
              backgroundColor: InkWashColors.softGrey.withValues(alpha: .35),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
              width: 42,
              child: Text(score.toStringAsFixed(0),
                  textAlign: TextAlign.right,
                  style: const TextStyle(
                      fontSize: 12, fontWeight: FontWeight.w700))),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('For You')),
      body: RefreshIndicator(
        onRefresh: generate,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 6, 18, 28),
          children: [
            const TravelSectionHeader(
              title: 'Hybrid recommendations',
              subtitle:
                  'Content matching + collaborative filtering + weighted scoring + ranking',
            ),
            const SizedBox(height: 12),
            if (preferences.isNotEmpty) ...[
              InkCard(
                color: InkWashColors.cream,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Recommendation profile',
                        style: TextStyle(fontWeight: FontWeight.w900)),
                    const SizedBox(height: 7),
                    Wrap(
                      spacing: 7,
                      runSpacing: 7,
                      children: [
                        TravelStatusPill(
                            text:
                                (preferences['travelPersonality'] ?? 'Balanced')
                                    .toString(),
                            icon: Icons.psychology_outlined),
                        TravelStatusPill(
                            text: (preferences['travelType'] ?? 'Mixed')
                                .toString(),
                            icon: Icons.explore_outlined),
                        TravelStatusPill(
                            text: (preferences['budgetRange'] ?? 'Moderate')
                                .toString(),
                            icon: Icons.account_balance_wallet_outlined),
                        TravelStatusPill(
                            text: (preferences['travelPace'] ?? 'Moderate')
                                .toString(),
                            icon: Icons.speed_rounded),
                      ],
                    ),
                    if (preferences['interests'] is List) ...[
                      const SizedBox(height: 8),
                      Text(
                          'Interests: ${(preferences['interests'] as List).join(', ')}',
                          style: const TextStyle(
                              fontSize: 12, color: InkWashColors.charcoal)),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 12),
            ],
            TextField(
              controller: destination,
              decoration: const InputDecoration(
                labelText: 'Destination area',
                prefixIcon: Icon(Icons.location_on_outlined),
              ),
            ),
            const SizedBox(height: 10),
            FilledButton.icon(
              onPressed: busy ? null : generate,
              icon: const Icon(Icons.auto_awesome_rounded),
              label: Text(
                  busy ? 'Generating...' : 'Generate personalised ranking'),
            ),
            if (source.isNotEmpty) ...[
              const SizedBox(height: 10),
              TravelStatusPill(
                text: source == 'serpapi'
                    ? 'LIVE DESTINATION DATA'
                    : 'PERSONALISED DESTINATION DATA',
                icon: source == 'serpapi'
                    ? Icons.cloud_done_outlined
                    : Icons.auto_awesome_outlined,
              ),
            ],
            const SizedBox(height: 18),
            if (items.isEmpty)
              const TravelEmptyState(
                icon: Icons.auto_awesome_outlined,
                title: 'No ranking yet',
                message:
                    'Complete Travel Preferences, enter a destination area and generate your recommendation list.',
              ),
            ...items.map((raw) {
              final item = Map<String, dynamic>.from(raw as Map);
              final breakdown = item['scoreBreakdown'] is Map
                  ? Map<String, dynamic>.from(item['scoreBreakdown'] as Map)
                  : <String, dynamic>{};
              return Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: InkCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Container(
                            width: 48,
                            height: 48,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              color: InkWashColors.cream,
                              borderRadius: BorderRadius.circular(15),
                            ),
                            child: Text('#${item['rankNo'] ?? '-'}',
                                style: const TextStyle(
                                    fontWeight: FontWeight.w900)),
                          ),
                          const SizedBox(width: 11),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                    (item['title'] ??
                                            item['name'] ??
                                            'Destination')
                                        .toString(),
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w900,
                                        fontSize: 17)),
                                const SizedBox(height: 3),
                                Text(
                                    (item['address'] ?? item['type'] ?? '')
                                        .toString(),
                                    style: const TextStyle(
                                        color: InkWashColors.mutedInk)),
                              ],
                            ),
                          ),
                          TravelStatusPill(
                              text: '${item['score'] ?? 0}% match',
                              icon: Icons.insights_rounded),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Text((item['reason'] ?? '').toString()),
                      scoreBar('Content 60%',
                          breakdown['content'] ?? item['contentScore']),
                      scoreBar(
                          'Collaborative 30%',
                          breakdown['collaborative'] ??
                              item['collaborativeScore']),
                      scoreBar('Popularity 10%',
                          breakdown['popularity'] ?? item['popularityScore']),
                      const SizedBox(height: 11),
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              'Rating ${item['rating'] ?? '-'} • ${(item['collaborativeSource'] ?? '').toString()}',
                              style: const TextStyle(
                                fontSize: 12,
                                color: InkWashColors.mutedInk,
                              ),
                            ),
                          ),
                          TextButton.icon(
                            onPressed: () => Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => DestinationDetailsScreen(
                                  initialDestination: item,
                                ),
                              ),
                            ),
                            icon: const Icon(Icons.info_outline_rounded,
                                size: 18),
                            label: const Text('Details'),
                          ),
                          const SizedBox(width: 5),
                          FilledButton.tonalIcon(
                            onPressed: () => addToItinerary(item),
                            icon: const Icon(Icons.add_road_rounded, size: 18),
                            label: const Text('Add'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              );
            }),
          ],
        ),
      ),
    );
  }
}
