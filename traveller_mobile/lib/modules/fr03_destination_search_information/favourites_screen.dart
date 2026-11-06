import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../widgets/local_place_rating.dart';
import 'destination_details_screen.dart';
import 'favourites_controller.dart';

class FavouritesScreen extends StatefulWidget {
  final ApiService? api;
  const FavouritesScreen({super.key, this.api});
  @override
  State<FavouritesScreen> createState() => _FavouritesScreenState();
}

class _FavouritesScreenState extends State<FavouritesScreen> {
  late final ApiService api;
  late final FavouritesController favourites;
  void _changed() { if (mounted) setState(() {}); }

  Future<void> remove(Map<String, dynamic> item) async {
    try {
      await favourites.toggle(item);
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    favourites = FavouritesController(api)..addListener(_changed);
  }

  @override
  void dispose() {
    favourites.removeListener(_changed);
    favourites.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Favourite Destinations')),
      body: RefreshIndicator(
        onRefresh: favourites.load,
        child: ListView(padding: const EdgeInsets.all(18), children: [
          if (!favourites.loaded && favourites.error == null) const AppLoadingState(message: 'Loading saved places…'),
          if (favourites.error != null) AppErrorState(message: favourites.error!, onRetry: favourites.load),
          if (favourites.loaded && favourites.error == null && favourites.items.isEmpty)
            const TravelEmptyState(icon: Icons.favorite_border_rounded, title: 'No saved places yet', message: 'Save destinations from Explore to find them here.'),
          ...favourites.items.map((raw) {
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
                        api: api,
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
                    onPressed: favourites.busyIds.contains(item['destinationId']) || favourites.error != null ? null : () => remove(item),
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
