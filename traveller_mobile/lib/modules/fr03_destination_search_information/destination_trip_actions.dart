import 'package:flutter/material.dart';

import '../../core/navigation/app_shell_navigation.dart';
import '../../core/utils/destination_utils.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr05_smart_itinerary_budget_planner/activity_payload_helper.dart';
import '../fr05_smart_itinerary_budget_planner/trips_tab.dart';

Future<bool> addDestinationToTrip({
  required BuildContext context,
  required ApiService api,
  required Map<String, dynamic> destination,
  bool resumeAfterCreation = false,
}) async {
  try {
    final data = await api.get('/api/fr5/itineraries');
    final trips = (data['items'] as List? ?? const [])
        .whereType<Map>()
        .map((trip) => Map<String, dynamic>.from(trip))
        .where((trip) =>
            !resumeAfterCreation ||
            (trip['tripType'] != 'package' && trip['packageTrip'] != true))
        .toList();

    if (!context.mounted) return false;
    Map<String, dynamic>? selected;
    if (trips.isEmpty) {
      final openTrips = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Create a trip first'),
          content: const Text(
            'Create a trip before adding this place to your itinerary.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Not now'),
            ),
            PrimaryButton(
              label: 'Go to Trips',
              onPressed: () => Navigator.pop(dialogContext, true),
            ),
          ],
        ),
      );
      if (openTrips == true && context.mounted) {
        if (resumeAfterCreation) {
          selected = await Navigator.push<Map<String, dynamic>>(
              context,
              MaterialPageRoute(
                  builder: (_) => TripsTab(
                      api: api,
                      selectForActivity: true,
                      initialDestination: (destination['city'] ??
                              destination['state'] ??
                              destination['address'] ??
                              '')
                          .toString())));
        } else {
          final switched =
              AppShellNavigation.select(context, AppShellTab.trips);
          if (!switched) {
            await Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => TripsTab(api: api)),
            );
          }
        }
      }
      if (!resumeAfterCreation || selected == null) return false;
    }

    selected ??= await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.md,
            0,
            AppSpacing.md,
            AppSpacing.lg,
          ),
          children: [
            Text(
              'Add to a trip',
              style: Theme.of(sheetContext).textTheme.headlineSmall,
            ),
            const SizedBox(height: AppSpacing.xxs),
            Text(
              DestinationUtils.resolveName(destination),
              style: Theme.of(sheetContext)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.sm),
            ...trips.map(
              (trip) => ListTile(
                contentPadding: EdgeInsets.zero,
                minVerticalPadding: AppSpacing.xs,
                leading: const CircleAvatar(
                  backgroundColor: AppColors.primarySoft,
                  child: Icon(Icons.luggage_outlined),
                ),
                title: Text((trip['title'] ?? 'Trip').toString()),
                subtitle: (trip['destinationArea'] ?? '').toString().isEmpty
                    ? null
                    : Text(trip['destinationArea'].toString()),
                trailing: const Icon(Icons.chevron_right_rounded),
                onTap: () => Navigator.pop(sheetContext, trip),
              ),
            ),
          ],
        ),
      ),
    );

    if (selected == null) return false;
    if (!context.mounted) return false;
    final chosenDay = await promptTripDaySelection(
      context: context,
      trip: selected,
    );
    if (chosenDay == null) return false;

    final payload = buildActivityPayload(
      destination,
      dayNo: chosenDay,
    );
    payload['activityName'] = DestinationUtils.resolveName(destination);
    payload['destinationId'] = DestinationUtils.resolveId(destination);

    final response = await api.post(
        '/api/fr5/itineraries/${selected['id']}/activities', payload);
    if (response is Map && response['ok'] == false) {
      throw ApiException(
          (response['error'] ?? 'The place was not added. Please retry.')
              .toString(),
          400,
          Map<String, dynamic>.from(response));
    }

    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Added to ${selected['title'] ?? 'your trip'} (Day $chosenDay)',
          ),
        ),
      );
    }
    return true;
  } catch (error) {
    if (context.mounted) showError(context, error);
    return false;
  }
}
