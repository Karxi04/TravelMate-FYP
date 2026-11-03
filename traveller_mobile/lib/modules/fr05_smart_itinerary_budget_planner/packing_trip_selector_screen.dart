import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'packing_checklist_screen.dart';
import 'personalized_planning_screen.dart';

class PackingTripSelectorScreen extends StatefulWidget {
  final ApiService? api;
  final String? initialTripId;

  const PackingTripSelectorScreen({
    super.key,
    this.api,
    this.initialTripId,
  });

  @override
  State<PackingTripSelectorScreen> createState() => _PackingTripSelectorScreenState();
}

class _PackingTripSelectorScreenState extends State<PackingTripSelectorScreen> {
  late final ApiService _api;
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _trips = [];

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? ApiService();
    _loadTrips();
  }

  Future<void> _loadTrips() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }

    try {
      final res = await _api.get('/api/fr5/itineraries');
      if (!mounted) return;

      List<Map<String, dynamic>> items = [];
      if (res is Map && res['items'] is List) {
        items = (res['items'] as List)
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
      } else if (res is List) {
        items = res.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
      }

      setState(() {
        _trips = items;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = userFacingApiError(e);
      });
    }
  }

  void _openChecklist(Map<String, dynamic> trip) {
    final tripId = (trip['id'] ?? trip['tripId'] ?? '').toString();
    final title = (trip['title'] ?? 'Trip').toString();
    final dest = (trip['destinationArea'] ?? trip['destination'] ?? '').toString();
    final duration = trip['durationDays'] as int?;

    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => PackingChecklistScreen(
          tripId: tripId,
          tripTitle: title,
          destination: dest,
          durationDays: duration,
          api: _api,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return TravelMatePageScaffold(
      appBar: AppBar(
        title: const Text('Select Trip for Packing'),
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const AppLoadingState(message: 'Loading your trips…');
    }

    if (_error != null) {
      return AppErrorState(
        title: 'Trips unavailable',
        message: _error!,
        retryLabel: 'Try again',
        onRetry: _loadTrips,
      );
    }

    if (_trips.isEmpty) {
      return Center(
        child: InkCard(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.luggage_outlined, size: 56, color: AppColors.primary),
              const SizedBox(height: AppSpacing.md),
              Text(
                'No Saved Trips Found',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: AppSpacing.xs),
              const Text(
                'You don\'t have any saved trips yet. Create or save an itinerary first to generate a personalized packing checklist.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: AppSpacing.lg),
              PrimaryButton(
                label: 'Plan a Trip',
                icon: Icons.add_rounded,
                onPressed: () {
                  Navigator.pushReplacement(
                    context,
                    MaterialPageRoute(
                      builder: (_) => PersonalizedPlanningScreen(api: _api),
                    ),
                  );
                },
              ),
            ],
          ),
        ),
      );
    }

    return ListView(
      children: [
        const AppSectionHeader(
          title: 'Your Saved Trips',
          subtitle: 'Choose a trip to view or customize its packing checklist.',
        ),
        const SizedBox(height: AppSpacing.sm),
        ..._trips.map((trip) {
          final title = (trip['title'] ?? 'Trip').toString();
          final dest = (trip['destinationArea'] ?? trip['destination'] ?? '').toString();
          final start = (trip['startDate'] ?? '').toString();
          final end = (trip['endDate'] ?? '').toString();
          final dateText = [start, end].where((s) => s.isNotEmpty).join(' to ');

          return Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: () => _openChecklist(trip),
              child: InkCard(
                child: Row(
                  children: [
                    Container(
                      width: 44,
                      height: 44,
                      decoration: BoxDecoration(
                        color: AppColors.primary.withAlpha(20),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Icon(Icons.checklist_rounded, color: AppColors.primary),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            title,
                            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                  fontWeight: FontWeight.bold,
                                ),
                          ),
                          if (dest.isNotEmpty) ...[
                            const SizedBox(height: 2),
                            Text(
                              dest,
                              style: const TextStyle(
                                color: AppColors.textSecondary,
                                fontSize: 13,
                              ),
                            ),
                          ],
                          if (dateText.isNotEmpty) ...[
                            const SizedBox(height: 2),
                            Text(
                              dateText,
                              style: const TextStyle(
                                color: AppColors.textSecondary,
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    const Icon(Icons.chevron_right_rounded, color: AppColors.textSecondary),
                  ],
                ),
              ),
            ),
          );
        }),
      ],
    );
  }
}
