# TravelMate API Route Map

Source-backed reference, audited 20 November 2026. Exact paths below are derived from route decorators and imported Blueprint prefixes. This is an inventory, not a runtime acceptance claim.

## Contracts and safety

- The authenticated Flutter client and both portals use the shared Flask API. Firebase ID tokens, server-side role checks, tenant ownership, CSRF on portal mutations and existing rate limits remain required.
- HTTP GET does **not** guarantee side-effect-free operation. Notification inbox GET reconciles genuine events and can persist/queue them; order reconciliation and provider/cache-backed reads may also write. Assistant read-only questions use owner-scoped read services instead of these routes.
- Financial truth comes from package_pricing.py / FR15 and FR09 hosted Stripe Test Checkout. A quote, selected room, paid test order or return URL alone is not supplier reservation confirmation. Paid snapshots are not repriced by later edits.
- Generic FR05 PUT accepts optional expectedItineraryRevision. Current Trip Details sends its loaded revision; stale409 does not write. The server also compare-and-sets the original record at commit. Older clients omitting the revision keep compatibility but cannot detect every long-open stale screen.
- Authenticated object mutation APIs reject non-object JSON after authentication. Packing retains its own bounded16KiB stream parser and JSON shape check. Multipart image upload and signed unauthenticated Stripe webhook keep their existing contracts.
- Car Rental UI is retired. Historical rental cost fields and legacy standalone compatibility code are not new live rental functionality. Smart Packing is the supported replacement.
- Standalone local simulation is a separate capability subset: it does not provide all Backend features (including cloud packing/history/provider settlement). Do not infer live provider capabilities from simulated data.
- Admin data-loading helpers currently cap lists at500 and expose a limited-data condition. Reported totals must respect that scope.

## Backend methods and paths

### backend_api/app.py

- `GET /api/health` — `health`
- `GET /api/config-status` — `config_status`

### backend_api/modules/traveller_notifications.py

- `GET /api/traveller/notifications` — `notifications`
- `GET /api/traveller/notifications/<notification_id>` — `notification_detail`
- `POST /api/traveller/notifications/devices` — `device_registration`
- `DELETE /api/traveller/notifications/devices` — `device_unregistration`
- `POST /api/traveller/notifications/devices/unregister` — `device_unregistration`
- `PATCH /api/traveller/notifications/<notification_id>` — `mark_read`

### backend_api/modules/fr01_user_management/routes.py

- `POST /api/fr1/profile` — `create_or_update_profile`
- `GET /api/fr1/me` — `me`
- `PUT /api/fr1/me` — `update_me`

### backend_api/modules/fr02_travel_preference/routes.py

- `GET /api/fr2/preferences` — `get_preferences`
- `PUT /api/fr2/preferences` — `save_preferences`

### backend_api/modules/fr03_destination_search_information/routes.py

- `GET /api/fr3/local-ratings` — `local_ratings`
- `GET /api/fr3/destinations/search` — `search_destinations`
- `GET /api/fr3/destinations/<path:place_id>` — `destination_details`
- `GET /api/fr3/destinations/<path:place_id>/ratings-reviews` — `ratings_reviews`
- `GET /api/fr3/destinations/<path:place_id>/nearby` — `nearby_places`
- `GET /api/fr3/favourites` — `favourites`
- `POST /api/fr3/favourites` — `save_favourite`
- `DELETE /api/fr3/favourites/<path:doc_id>` — `delete_favourite`

### backend_api/modules/fr04_hybrid_recommendation/routes.py

- `GET /api/fr4/preference-feedback` — `get_preference_feedback`
- `POST /api/fr4/preference-feedback` — `submit_preference_feedback`
- `DELETE /api/fr4/preference-feedback` — `reset_preference_feedback`
- `POST /api/fr4/recommendations/generate` — `generate`
- `GET /api/fr4/recommendations` — `get_recommendations`
- `GET /api/fr4/locations` — `supported_locations`
- `GET /api/fr4/locations/search` — `location_lookup`
- `GET /api/fr4/settings` — `recommendation_settings`
- `PUT /api/fr4/settings` — `save_recommendation_settings`

### backend_api/modules/fr05_smart_itinerary_budget_planner/expense_routes.py

- `GET /api/fr5/itineraries/<iid>/expenses` — `expenses`
- `PATCH /api/fr5/itineraries/<iid>/expenses` — `expenses`

### backend_api/modules/fr05_smart_itinerary_budget_planner/packing_routes.py

- `GET /api/fr5/itineraries/<iid>/packing-checklist` — `packing_checklist`
- `POST /api/fr5/itineraries/<iid>/packing-checklist` — `packing_checklist`
- `PATCH /api/fr5/itineraries/<iid>/packing-checklist` — `packing_checklist`

### backend_api/modules/fr05_smart_itinerary_budget_planner/routes.py

- `GET /api/fr5/itineraries/<iid>/history` — `itinerary_history`
- `GET /api/fr5/itineraries` — `list_itineraries`
- `GET /api/fr5/itineraries/<iid>` — `get_itinerary_route`
- `POST /api/fr5/itineraries` — `create_itinerary_route`
- `PUT /api/fr5/itineraries/<iid>` — `update_itinerary_route`
- `POST /api/fr5/itineraries/<iid>/flight-adjustment/preview` — `flight_adjustment_preview`
- `POST /api/fr5/itineraries/<iid>/flight-adjustment/apply` — `flight_adjustment_apply`
- `POST /api/fr5/itineraries/<iid>/hotel-selection/remove` — `remove_hotel_selection`
- `POST /api/fr5/itineraries/<iid>/intercity-transfer` — `confirm_intercity_transfer`
- `POST /api/fr5/itineraries/<iid>/activities` — `add_activity_route`
- `DELETE /api/fr5/itineraries/<iid>/activities/<activity_id>` — `remove_activity_route`
- `PUT /api/fr5/itineraries/<iid>/activities/<activity_id>` — `update_activity_route`
- `POST /api/fr5/itineraries/<iid>/activities/rearrange` — `rearrange_activity_route`
- `GET /api/fr5/itineraries/<iid>/budget` — `budget_comparison`
- `POST /api/fr5/itineraries/<iid>/lower-cost-alternatives/discover` — `discover_cost_alternatives`
- `POST /api/fr5/itineraries/<iid>/lower-cost-alternatives` — `lower_cost_alternatives`
- `GET /api/fr5/itineraries/<iid>/budget-replan` — `budget_replan_state`
- `POST /api/fr5/itineraries/<iid>/budget-replan/preview` — `budget_replan`
- `POST /api/fr5/itineraries/<iid>/budget-replan/apply` — `budget_replan`
- `POST /api/fr5/itineraries/<iid>/lower-cost-alternatives/preview` — `apply_lower_cost_alternative`
- `POST /api/fr5/itineraries/<iid>/lower-cost-alternatives/apply` — `apply_lower_cost_alternative`
- `GET /api/fr5/personalised-trips/status` — `personalised_generation_status`
- `POST /api/fr5/personalised-trips/generate` — `generate_personalised_trip_route`
- `POST /api/fr5/itineraries/<iid>/generate` — `generate_itinerary_route`
- `POST /api/fr5/itineraries/<iid>/save` — `save_itinerary_route`
- `DELETE /api/fr5/itineraries/<iid>` — `delete_itinerary_route`

### backend_api/modules/fr06_weather_forecast/routes.py

- `GET /api/fr6/locations` — `local_locations`
- `GET /api/fr6/locations/search` — `location_search`
- `GET /api/fr6/weather` — `weather`

### backend_api/modules/fr07_flight_search/routes.py

- `GET /api/fr7/flights/search` — `search_flights`
- `POST /api/fr7/flights/returns` — `search_flight_returns`
- `POST /api/fr7/flights/compare` — `compare_flights`
- `POST /api/fr7/flights/details` — `flight_details`
- `POST /api/fr7/flights/select` — `select_flight`
- `POST /api/fr7/itineraries/<iid>/flight-selection/remove` — `remove_flight_selection`

### backend_api/modules/fr08_hotel_booking/routes.py

- `GET /api/fr8/places/search` — `places`
- `POST /api/fr8/hotels/search` — `hotels_search`
- `POST /api/fr8/hotels/compare` — `compare_hotels`
- `POST /api/fr8/hotels/prebook` — `hotel_prebook`
- `GET /api/fr8/hotels/compatible-trips` — `hotel_compatible_trips`
- `POST /api/fr8/hotels/book` — `hotel_book`
- `GET /api/fr8/bookings/attempts/<attempt_id>` — `reconcile_booking`
- `GET /api/fr8/bookings` — `bookings`
- `POST /api/fr8/car-rentals/search` — `car_rentals_search`
- `POST /api/fr8/car-rentals/select` — `select_car_rental`

### backend_api/modules/fr09_payment/routes.py

- `GET /api/fr9/checkout/capabilities` — `checkout_capabilities`
- `POST /api/fr9/package-checkout-attempts/<attempt_id>/checkout/session` — `create_package_checkout_session`
- `POST /api/fr9/checkout/session` — `create_checkout_session`
- `GET /api/fr9/checkout/return/<outcome>` — `checkout_return`
- `GET /api/fr9/orders` — `list_orders`
- `GET /api/fr9/orders/<order_id>` — `get_order`
- `GET /api/fr9/orders/<order_id>/reconcile` — `reconcile_order`
- `POST /api/fr9/webhooks/stripe` — `stripe_webhook`
- `POST /api/fr9/payments/create-intent` — `create_payment_intent`
- `POST /api/fr9/payments/process` — `process_payment`
- `GET /api/fr9/payments/attempts/<attempt_id>` — `reconcile_payment`
- `POST /api/fr9/payments/<payment_id>/retry` — `retry_payment`
- `POST /api/fr9/payments/<payment_id>/cancel` — `cancel_payment`
- `GET /api/fr9/payments` — `list_payments`

### backend_api/modules/fr10_feedback_rating/routes.py

- `GET /api/fr10/feedback` — `own_feedback`
- `POST /api/fr10/feedback` — `submit_feedback`
- `PUT /api/fr10/feedback/<fid>` — `update_feedback`
- `DELETE /api/fr10/feedback/<fid>` — `delete_feedback`

### backend_api/modules/fr11_chatbot_travel_assistant/routes.py

- `POST /api/fr11/chat` — `chat`
- `GET /api/fr11/chat-requests/<identity>` — `chat_request_status`
- `POST /api/fr11/save-plan` — `save_plan`
- `GET /api/fr11/sessions` — `sessions`
- `POST /api/fr11/sessions` — `create_session`
- `GET /api/fr11/sessions/<session_id>` — `get_session`
- `DELETE /api/fr11/sessions/<session_id>` — `delete_session`
- `GET /api/fr11/history` — `history`
- `DELETE /api/fr11/history` — `clear_history`
- `GET /api/fr11/packages/<package_id>` — `package_details`

### backend_api/modules/fr12_tourism_operator_management/hotel_routes.py

- `GET /api/fr12/hotels/search` — `search_operator_hotels`
- `GET /api/fr12/hotels/<hotel_id>` — `operator_hotel_detail`

### backend_api/modules/fr12_tourism_operator_management/routes.py

- `GET /api/fr12/packages` — `packages`
- `GET /api/fr12/bookings` — `package_bookings`
- `GET /api/fr12/bookings/<order_reference>` — `package_booking_detail`
- `POST /api/fr12/bookings/<order_reference>/fulfillment` — `update_booking_fulfillment`
- `POST /api/fr12/bookings/<order_reference>/confirm-fulfillment` — `confirm_booking_fulfillment`
- `POST /api/fr12/bookings/<order_reference>/decline` — `decline_booking_fulfillment`
- `GET /api/fr12/booking-clarifications` — `booking_clarification_queue`
- `POST /api/fr12/bookings/<order_reference>/clarifications` — `propose_booking_clarification`
- `POST /api/fr12/bookings/<order_reference>/clarifications/review` — `review_booking_clarification`
- `POST /api/fr12/packages` — `create_package_route`
- `PUT /api/fr12/packages/<pid>` — `update_package`
- `DELETE /api/fr12/packages/<pid>` — `delete_package`
- `POST /api/fr12/packages/<pid>/submit` — `submit_package`
- `POST /api/fr12/packages/<pid>/archive` — `archive_package`
- `POST /api/fr12/packages/<pid>/restore` — `restore_package`
- `GET /api/fr12/campaigns` — `campaigns`
- `POST /api/fr12/campaigns` — `create_campaign_route`
- `PUT /api/fr12/campaigns/<cid>` — `update_campaign`
- `DELETE /api/fr12/campaigns/<cid>` — `delete_campaign`
- `POST /api/fr12/campaigns/<cid>/submit` — `submit_campaign`
- `GET /api/fr12/analytics` — `analytics`
- `GET /api/fr12/reports/export` — `export_report`
- `POST /api/fr12/package-images/upload` — `upload_package_image`
- `DELETE /api/fr12/package-images/<filename>` — `delete_package_image`

### backend_api/modules/fr13_administrator_management/routes.py

- `GET /api/fr13/users` — `users`
- `PUT /api/fr13/users/<uid>` — `update_user`
- `GET /api/fr13/packages/pending` — `pending_packages`
- `GET /api/fr13/packages` — `review_packages`
- `GET /api/fr13/packages/<pid>` — `package_details`
- `POST /api/fr13/packages/<pid>/review` — `review_package`
- `POST /api/fr13/packages/<pid>/suspend` — `suspend_package`
- `GET /api/fr13/campaigns/pending` — `pending_campaigns`
- `GET /api/fr13/campaigns` — `campaigns`
- `GET /api/fr13/campaigns/<cid>` — `campaign_details`
- `POST /api/fr13/campaigns/<cid>/review` — `review_campaign`
- `GET /api/fr13/feedback` — `all_feedback`
- `GET /api/fr13/feedback/<fid>/history` — `feedback_history`
- `POST /api/fr13/feedback/<fid>/review` — `review_feedback`
- `DELETE /api/fr13/feedback/<fid>` — `remove_feedback`
- `GET /api/fr13/destinations` — `destinations`
- `POST /api/fr13/destinations` — `create_destination`
- `PUT /api/fr13/destinations/<did>` — `update_destination`
- `DELETE /api/fr13/destinations/<did>` — `delete_destination`
- `GET /api/fr13/activities` — `activities`
- `POST /api/fr13/activities` — `create_activity`
- `PUT /api/fr13/activities/<aid>` — `update_activity`
- `DELETE /api/fr13/activities/<aid>` — `delete_activity`
- `GET /api/fr13/bookings` — `booking_records`
- `GET /api/fr13/payments` — `payment_records`
- `GET /api/fr13/reports/summary` — `report_summary`
- `GET /api/fr13/reports/export.pdf` — `export_report_pdf`
- `GET /api/fr13/reports/export` — `export_report`
- `GET /api/fr13/reports/export.csv` — `export_report_csv`
- `GET /api/fr13/reports/export.xlsx` — `export_report_xlsx`

### backend_api/modules/fr15_package_checkout/routes.py

- `POST /api/fr15/package-checkout-attempts` — `create_attempt`
- `GET /api/fr15/package-checkout-attempts/<attempt_id>` — `get_attempt`
- `POST /api/fr15/package-checkout-attempts/quote` — `quote_package`

### backend_api/modules/shared_public_content/routes.py

- `GET /api/public/tourism-packages` — `tourism_packages`
- `GET /api/public/promotional-campaigns` — `promotional_campaigns`
- `GET /api/public/package-images/<filename>` — `serve_package_image`

## Related clients and evidence

Operator/Admin app.py and module routes proxy authenticated calls and render their own pages; their routes are not additional public Backend APIs. Dynamic client calls, scripts, webhooks and server-to-server invocations mean lack of a literal Flutter match does not prove an orphan.

The full audit inventories250method/path declarations across Backend170, Operator47 and Administrator33. All137literal non-standalone Flutter API calls match a declared Backend family after resolving imported Blueprint prefixes. This static match does not prove payload compatibility or successful runtime behavior.

Audit outputs (workbook, requirement matrix, source inventory and regression logs) are stored separately under D:/workspace/TravelMate/verification/full-system-audit-20261120. Current manual/device/browser acceptance remains pending.
