import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../widgets/local_place_rating.dart';
import 'destination_details_screen.dart';

class FavouritesScreen extends StatefulWidget {
  const FavouritesScreen({super.key});
  @override
  State<FavouritesScreen> createState() => _FavouritesScreenState();
}

class _FavouritesScreenState extends State<FavouritesScreen> {
  final api = ApiService();
  List<dynamic> items = [];
  bool loading = true;
  String? loadError;

  Future<void> load() async {
    if (mounted) setState(() { loading = true; loadError = null; });
    try {
      final data = await api.get('/api/fr3/favourites');
      if (mounted) setState(() => items = data['items'] ?? []);
    } catch (e) {
      if (mounted) setState(() => loadError = 'We couldn’t load your saved places.');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> remove(String id) async {
    try {
      await api.delete('/api/fr3/favourites/$id');
      await load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  void initState() { super.initState(); Future.microtask(load); }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Favourite Destinations')),
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(padding: const EdgeInsets.all(18), children: [
          if (loading) const AppLoadingState(message: 'Loading saved places…'),
          if (!loading && loadError != null) AppErrorState(message: loadError!, onRetry: load),
          if (!loading && loadError == null && items.isEmpty)
            const TravelEmptyState(icon: Icons.favorite_border_rounded, title: 'No saved places yet', message: 'Save destinations from Explore to find them here.'),
          ...items.map((raw) {
            final item = Map<String, dynamic>.from(raw as Map);
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: InkCard(
                child: Row(
                  children: [
                    TravelPlaceImage(place: item, width: 92, height: 92, borderRadius: const BorderRadius.horizontal(left: Radius.circular(18))),
                    const SizedBox(width: 10),
                    Expanded(child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  onTap: () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => DestinationDetailsScreen(
                        initialDestination: item,
                      ),
                    ),
                  ),
                  title: Text(
                    (item['title'] ?? item['name'] ?? 'Destination').toString(),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  subtitle: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text((item['address'] ?? '').toString()),
                      LocalPlaceRating(place:item),
                      const SizedBox(height: 3),
                      const Text(
                        'Tap to view full details',
                        style: TextStyle(fontSize: 12),
                      ),
                    ],
                  ),
                  trailing: IconButton(
                    tooltip: 'Remove favourite',
                    onPressed: () => remove(item['id'].toString()),
                    icon: const Icon(Icons.delete_outline),
                  ),
                )),
                  ],
                ),
              ),
            );
          }),
        ]),
      ),
    );
  }
}
