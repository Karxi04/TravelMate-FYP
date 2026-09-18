import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import 'destination_details_screen.dart';

class FavouritesScreen extends StatefulWidget {
  const FavouritesScreen({super.key});
  @override
  State<FavouritesScreen> createState() => _FavouritesScreenState();
}

class _FavouritesScreenState extends State<FavouritesScreen> {
  final api = ApiService();
  List<dynamic> items = [];

  Future<void> load() async {
    try {
      final data = await api.get('/api/fr3/favourites');
      setState(() => items = data['items'] ?? []);
    } catch (e) {
      if (mounted) showError(context, e);
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
          if (items.isEmpty) const InkCard(child: Text('No favourite destinations yet.')),
          ...items.map((raw) {
            final item = Map<String, dynamic>.from(raw as Map);
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: InkCard(
                child: ListTile(
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
                ),
              ),
            );
          }),
        ]),
      ),
    );
  }
}
