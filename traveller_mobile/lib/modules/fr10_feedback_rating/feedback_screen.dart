import 'package:flutter/material.dart';

import '../../core/utils/destination_utils.dart';
import '../../services/api_service.dart';
import '../../services/review_contract.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr03_destination_search_information/destination_details_screen.dart';

class FeedbackScreen extends StatefulWidget {
  final Map<String, dynamic>? initialDestination;
  final ApiService? api;

  const FeedbackScreen({super.key, this.initialDestination, this.api});

  @override
  State<FeedbackScreen> createState() => _FeedbackScreenState();
}

class _FeedbackScreenState extends State<FeedbackScreen> {
  final comment = TextEditingController();
  late final ApiService api;
  List<dynamic> items = [];
  Map<String, dynamic>? selectedPlace;
  int rating = 5;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    if (widget.initialDestination != null) {
      selectedPlace = Map<String, dynamic>.from(widget.initialDestination!);
    }
    Future.microtask(load);
  }

  String placeId(Map<String, dynamic> p) => DestinationUtils.resolveId(p);

  String placeName(Map<String, dynamic> p) => DestinationUtils.resolveName(p);

  Future<void> load() async {
    try {
      final data = await api.get('/api/fr10/feedback');
      if (mounted) setState(() {
        items = data['items'] ?? [];
        final existing = items.where((item) => item['destinationId'] == (selectedPlace == null ? null : placeId(selectedPlace!)));
        if (existing.isNotEmpty && comment.text.isEmpty) {
          comment.text = existing.first['comment'] ?? '';
          rating = int.tryParse('${existing.first['rating']}') ?? 5;
        }
      });
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<Map<String, dynamic>?> choosePlace() async {
    final search = TextEditingController();
    List<dynamic> results = [];
    bool loading = false;
    bool searchedOnce = false;

    return showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setLocal) {
          Future<void> runSearch() async {
            setLocal(() {
              loading = true;
              searchedOnce = true;
            });
            try {
              final data = await api.get('/api/fr3/destinations/search', {
                'q': search.text.trim().isEmpty ? 'attractions' : search.text.trim(),
                'location': 'Malaysia',
              });
              setLocal(() => results = data['results'] ?? []);
            } catch (e) {
              if (sheetContext.mounted) showError(sheetContext, e);
            } finally {
              if (sheetContext.mounted) setLocal(() => loading = false);
            }
          }

          if (results.isEmpty && !loading && !searchedOnce) {
            Future.microtask(runSearch);
          }

          return SafeArea(
            child: SizedBox(
              height: MediaQuery.of(sheetContext).size.height * .76,
              child: Padding(
                padding: EdgeInsets.fromLTRB(18, 0, 18, MediaQuery.of(sheetContext).viewInsets.bottom + 18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Choose a place to review', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 5),
                    const Text('Search by place name, category or travel interest.', style: TextStyle(color: InkWashColors.mutedInk)),
                    const SizedBox(height: 12),
                    TextField(
                      controller: search,
                      textInputAction: TextInputAction.search,
                      onSubmitted: (_) => runSearch(),
                      decoration: InputDecoration(
                        hintText: 'e.g. Penang Hill, food, museum...',
                        prefixIcon: const Icon(Icons.search_rounded),
                        suffixIcon: IconButton(onPressed: runSearch, icon: const Icon(Icons.arrow_forward_rounded)),
                      ),
                    ),
                    const SizedBox(height: 12),
                    if (loading) const LinearProgressIndicator(),
                    const SizedBox(height: 6),
                    Expanded(
                      child: ListView.separated(
                        itemCount: results.length,
                        separatorBuilder: (_, __) => const Divider(),
                        itemBuilder: (context, index) {
                          final p = Map<String, dynamic>.from(results[index] as Map);
                          return ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const CircleAvatar(backgroundColor: InkWashColors.paleBlue, child: Icon(Icons.place_outlined, color: InkWashColors.blueGrey)),
                            title: Text(placeName(p), style: const TextStyle(fontWeight: FontWeight.w800)),
                            subtitle: Text((p['address'] ?? p['category'] ?? '').toString(), maxLines: 2, overflow: TextOverflow.ellipsis),
                            trailing: const Icon(Icons.chevron_right_rounded),
                            onTap: () => Navigator.pop(sheetContext, p),
                          );
                        },
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Future<void> selectPlace() async {
    final p = await choosePlace();
    if (p != null && mounted) setState(() => selectedPlace = p);
  }

  Future<void> submit() async {
    if (busy) return;
    if (selectedPlace == null) {
      showError(context, 'Choose the destination or place you want to review.');
      return;
    }
    if (comment.text.trim().length < 5 || comment.text.trim().length > 2000) {
      showError(context, 'Write a short comment about your experience.');
      return;
    }
    setState(() => busy = true);
    try {
      final place = selectedPlace!;
      final existing = items.where((item) => item['destinationId'] == placeId(place));
      final response = existing.isNotEmpty
          ? await api.put('/api/fr10/feedback/${existing.first['id']}', {'rating': rating, 'comment': comment.text.trim()})
          : await api.post('/api/fr10/feedback', {
        'destinationId': placeId(place),
        'destinationName': placeName(place),
        'destinationAddress': (place['address'] ?? '').toString(),
        'rating': rating,
        'comment': comment.text.trim(),
      });
      comment.clear();
      setState(() {
        rating = 5;
        selectedPlace = null;
      });
      await load();
      if (mounted) {
        final review = response is Map && response['feedback'] is Map ? Map<String, dynamic>.from(response['feedback']) : <String, dynamic>{};
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(ReviewContract.status(review) == 'Published' ? 'Your review is published.' : 'Your review is awaiting approval.')));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  void dispose() {
    comment.dispose();
    super.dispose();
  }

  Future<void> edit(Map<String, dynamic> item) async {
    int newRating = int.tryParse('${item['rating']}') ?? 5;
    final newComment = TextEditingController(text: (item['comment'] ?? '').toString());
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setLocal) => AlertDialog(
          title: Text('Update review for ${item['destinationName'] ?? 'place'}'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: List.generate(5, (i) {
                  final star = i + 1;
                  return IconButton(
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
                    onPressed: () => setLocal(() => newRating = star),
                    icon: Icon(star <= newRating ? Icons.star_rounded : Icons.star_border_rounded, color: InkWashColors.blueGrey),
                  );
                }),
              ),
              const SizedBox(height: 8),
              TextField(controller: newComment, maxLines: 5, decoration: const InputDecoration(labelText: 'Your review')),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(context, {'rating': newRating, 'comment': newComment.text.trim()}), child: const Text('Save')),
          ],
        ),
      ),
    );
    if (result == null) return;
    try {
      await api.put('/api/fr10/feedback/${item['id']}', result);
      await load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> remove(String id) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete review?'),
        content: const Text('This removes your rating and review from your TravelMate records.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await api.delete('/api/fr10/feedback/$id');
      await load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ratings & reviews')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
        children: [
          const TravelSectionHeader(title: 'Review a place', subtitle: 'Choose a real destination from TravelMate instead of entering a destination ID.'),
          const SizedBox(height: 12),
          if (selectedPlace == null)
            InkWell(
              onTap: selectPlace,
              borderRadius: BorderRadius.circular(20),
              child: const TravelEmptyState(icon: Icons.place_outlined, title: 'Choose a destination or place', message: 'Tap here to search TravelMate places before writing your review.'),
            )
          else
            InkCard(
              color: InkWashColors.cream,
              child: Row(
                children: [
                  const CircleAvatar(backgroundColor: Colors.white, child: Icon(Icons.place_rounded, color: InkWashColors.blueGrey)),
                  const SizedBox(width: 11),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(placeName(selectedPlace!), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
                        Text((selectedPlace!['address'] ?? '').toString(), style: const TextStyle(color: InkWashColors.mutedInk, fontSize: 12)),
                      ],
                    ),
                  ),
                  TextButton(onPressed: selectPlace, child: const Text('Change')),
                ],
              ),
            ),
          const SizedBox(height: 16),
          const Text('Your rating', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
          const SizedBox(height: 4),
          Row(
            children: List.generate(5, (i) {
              final star = i + 1;
              return IconButton(
                padding: const EdgeInsets.only(right: 5),
                constraints: const BoxConstraints(minWidth: 42, minHeight: 42),
                onPressed: () => setState(() => rating = star),
                icon: Icon(star <= rating ? Icons.star_rounded : Icons.star_border_rounded, color: InkWashColors.blueGrey, size: 30),
              );
            }),
          ),
          const SizedBox(height: 8),
          TextField(controller: comment, maxLines: 5, decoration: const InputDecoration(labelText: 'Tell other travellers about your experience', hintText: 'What did you like? What should other travellers know?')),
          const SizedBox(height: 12),
          FilledButton.icon(onPressed: busy ? null : submit, icon: const Icon(Icons.rate_review_outlined), label: Text(busy ? 'Submitting...' : 'Submit review')),
          const SizedBox(height: 24),
          const TravelSectionHeader(title: 'My reviews', subtitle: 'View, update or remove your own reviews.'),
          const SizedBox(height: 10),
          if (items.isEmpty) const TravelEmptyState(icon: Icons.reviews_outlined, title: 'No reviews yet', message: 'Your submitted destination reviews will appear here.'),
          ...items.map((raw) {
            final item = Map<String, dynamic>.from(raw as Map);
            return Padding(
              padding: const EdgeInsets.only(bottom: 9),
              child: InkCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text((item['destinationName'] ?? item['destinationId'] ?? 'Place').toString(), style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16))),
                        Row(children: List.generate(5, (i) => Icon(i < (int.tryParse('${item['rating']}') ?? 0) ? Icons.star_rounded : Icons.star_border_rounded, size: 17, color: InkWashColors.blueGrey))),
                      ],
                    ),
                    if ((item['destinationAddress'] ?? '').toString().isNotEmpty) Text((item['destinationAddress']).toString(), style: const TextStyle(color: InkWashColors.mutedInk, fontSize: 12)),
                    const SizedBox(height: 7),
                    TravelStatusPill(
                      text: ReviewContract.status(item),
                      icon: (item['feedbackStatus'] ?? 'visible').toString() == 'removed'
                          ? Icons.block_outlined
                          : Icons.verified_user_outlined,
                    ),
                    const SizedBox(height: 8),
                    Text((item['comment'] ?? '').toString()),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        if ((item['destinationId'] ?? '').toString().isNotEmpty)
                          OutlinedButton.icon(
                            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => DestinationDetailsScreen(initialDestination: {
                              'destinationId': item['destinationId'],
                              'place_id': item['destinationId'],
                              'title': item['destinationName'] ?? item['destinationId'],
                              'address': item['destinationAddress'] ?? '',
                            }))),
                            icon: const Icon(Icons.info_outline_rounded),
                            label: const Text('Place details'),
                          ),
                        OutlinedButton.icon(
                          onPressed: (item['feedbackStatus'] ?? 'visible').toString() == 'removed' ? null : () => edit(item),
                          icon: const Icon(Icons.edit_outlined),
                          label: const Text('Edit'),
                        ),
                        OutlinedButton.icon(onPressed: () => remove(item['id'].toString()), icon: const Icon(Icons.delete_outline), label: const Text('Delete')),
                      ],
                    ),
                  ],
                ),
              ),
            );
          }),
        ],
      ),
    );
  }
}
