import 'package:flutter/material.dart';

class RoomOfferPhoto extends StatelessWidget {
  final Map<String, dynamic> offer;
  const RoomOfferPhoto({super.key, required this.offer});
  @override
  Widget build(BuildContext context) {
    final images = (offer['roomImageUrls'] as List? ?? []).whereType<String>()
        .where((url) => url.startsWith('https://') || url.startsWith('http://')).toList();
    final fallback = Container(height: 88, alignment: Alignment.center,
      color: Theme.of(context).colorScheme.surfaceContainerLow,
      child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        Icon(Icons.bed_outlined), SizedBox(width: 8), Flexible(child: Text('Room photo unavailable'))]));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Room photos: ${offer['roomName'] ?? 'Selected room'}'),
      const SizedBox(height: 4),
      if (images.isEmpty) fallback else ClipRRect(borderRadius: BorderRadius.circular(8),
        child: Image.network(images.first, height: 110, width: double.infinity, fit: BoxFit.cover,
          loadingBuilder: (_, child, loading) => loading == null ? child : const SizedBox(height: 110, child: Center(child: CircularProgressIndicator())),
          errorBuilder: (_, __, ___) => fallback)),
    ]);
  }
}
