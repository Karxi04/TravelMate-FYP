import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../fr02_travel_preference/preferences_screen.dart';
import '../fr03_destination_search_information/favourites_screen.dart';
import '../fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import '../fr05_smart_itinerary_budget_planner/trip_expenses_screen.dart';
import '../fr05_smart_itinerary_budget_planner/trips_tab.dart';
import '../fr05_smart_itinerary_budget_planner/packing_trip_selector_screen.dart';
import '../fr09_payment/payment_history_screen.dart';

/// Fixed internal destinations only. Chat cannot supply URLs, mutations or checkout actions.
class PersonalAssistantActions extends StatelessWidget {
  final List actions;
  final ApiService api;
  const PersonalAssistantActions(
      {super.key, required this.actions, required this.api});

  @override
  Widget build(BuildContext context) => Wrap(
        spacing: 8,
        runSpacing: 8,
        children: actions.whereType<Map>().take(6).map((action) {
          final id = action['tripId'];
          final validTrip = id is String &&
              id.length <= 200 &&
              RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(id);
          final (String, Widget)? destination = switch (action['kind']) {
            'trip' when validTrip => (
                'Open Trip Details',
                TripDetailsScreen(tripId: id, api: api)
              ),
            'budget' when validTrip => (
                'Open Trip Budget',
                TripExpensesScreen(tripId: id, api: api)
              ),
            'trips' => ('Open Trips', TripsTab(api: api)),
            'payments' => (
                'Open Payment History',
                PaymentHistoryScreen(api: api)
              ),
            'preferences' => ('Open Preferences', PreferencesScreen(api: api)),
            'saved' => ('Open Saved Places', FavouritesScreen(api: api)),
            'packing' => (
                'Open Smart Packing',
                PackingTripSelectorScreen(api: api)
              ),
            _ => null,
          };
          if (destination == null) return const SizedBox.shrink();
          return ActionChip(
            label: Text(destination.$1),
            onPressed: () => Navigator.push(context,
                MaterialPageRoute<void>(builder: (_) => destination.$2)),
          );
        }).toList(),
      );
}
