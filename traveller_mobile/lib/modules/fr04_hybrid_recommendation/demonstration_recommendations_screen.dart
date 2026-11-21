import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/recommendation_card.dart';
import '../../theme/app_theme.dart';

/// Read-only simulation: never uses generation/save/learning endpoints.
class DemonstrationRecommendationsScreen extends StatefulWidget {
  final ApiService api;
  const DemonstrationRecommendationsScreen({super.key, required this.api});
  @override
  State<DemonstrationRecommendationsScreen> createState() => _DemonstrationRecommendationsScreenState();
}

class _DemonstrationRecommendationsScreenState extends State<DemonstrationRecommendationsScreen> {
  String profile = 'current', area = 'Penang';
  bool loading = false;
  int requestVersion = 0;
  String? error;
  List<Map<String, dynamic>> profiles = [], items = [];
  List<String> areas = ['Penang'];
  @override
  void initState() { super.initState(); load(); }

  Future<void> load() async {
    if (loading) return;
    final version = ++requestVersion;
    setState(() { loading = true; error = null; items = []; });
    try {
      final data = await widget.api.get('/api/fr4/recommendations/demonstration',
          {'profileKey': profile, 'destinationArea': area});
      if (!mounted || version != requestVersion) return;
      if (data['recommendationEvidenceMode'] != 'demonstration' || data['synthetic'] != true) {
        throw StateError('Demonstration evidence could not be verified.');
      }
      final received = (data['recommendations'] as List).map((r) => Map<String, dynamic>.from(r as Map)).toList();
      if (received.any((r) => r['synthetic'] != true || r['recommendationEvidenceMode'] != 'demonstration')) {
        throw StateError('Mixed recommendation evidence is not allowed.');
      }
      setState(() {
        profiles = (data['profiles'] as List).map((r) => Map<String, dynamic>.from(r as Map)).toList();
        areas = (data['areas'] as List).map((r) => '$r').toList();
        items = received;
      });
    } catch (_) {
      if (mounted && version == requestVersion) setState(() => error =
          'Demonstration review data could not be loaded. No saved recommendations were changed.');
    } finally {
      if (mounted && version == requestVersion) setState(() => loading = false);
    }
  }

  void details(Map<String, dynamic> item) => showDialog<void>(context: context, builder: (context) => AlertDialog(
    title: Text('${item['title']}'),
    content: Text('Demonstration review data\n${item['address'] ?? ''}\n'
        'This attraction uses its existing destination identity. The scores on this screen use simulated travellers and approved example reviews.'),
    actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
  ));

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Demonstration reviews')),
    body: RefreshIndicator(onRefresh: load, child: ListView(padding: AppSpacing.page, children: [
      const InkCard(child: Text('Demonstration review data\nSimulated traveller profiles and approved example reviews. '
          'These read-only results do not change your preferences or genuine saved recommendations.')),
      const SizedBox(height: AppSpacing.md),
      if (profiles.isNotEmpty) DropdownButtonFormField<String>(
        initialValue: profile, isExpanded: true,
        decoration: const InputDecoration(labelText: 'Preferences for this simulation'),
        items: profiles.map((r) => DropdownMenuItem(value: '${r['key']}',
            child: Text('${r['label']}', maxLines: 2, overflow: TextOverflow.ellipsis))).toList(),
        onChanged: loading ? null : (value) { profile = value!; load(); }),
      const SizedBox(height: AppSpacing.md),
      DropdownButtonFormField<String>(initialValue: area, isExpanded: true,
        decoration: const InputDecoration(labelText: 'Review area'),
        items: areas.map((r) => DropdownMenuItem(value: r, child: Text(r))).toList(),
        onChanged: loading ? null : (value) { area = value!; load(); }),
      const SizedBox(height: AppSpacing.md),
      if (loading) const Center(child: CircularProgressIndicator()),
      if (error != null) ...[Text(error!), TextButton(onPressed: load, child: const Text('Retry'))],
      if (!loading && error == null && items.isEmpty) const Text('No approved demonstration reviews are available.'),
      for (final item in items) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: RecommendationCard(recommendation: item, onView: () => details(item))),
    ])),
  );
}
