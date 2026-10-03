# TravelMate – Complete System Repair & Integration Report
**Smart Personality-Aware Tourism Planning Application**  
**Role:** Lead Software Engineer Review & System Stabilization  
**Date:** September 2026  
**Status:** FYP Demonstration Ready (Stable + Integrated)

---

## 1. Executive Summary

A comprehensive audit previously identified that TravelMate had several critical architectural defects, missing endpoints, insecure cross-user operations, unhandled third-party provider failures, and broken data synchronization pipelines across its three key user roles:
1. **Traveller Mobile App** (Flutter)
2. **Tourism Operator Website** (Flask :5001)
3. **Administrator Website** (Flask :5002)
4. **Shared Backend API** (Flask :5000 with Firebase Auth & Firestore)

This engineering overhaul methodically addressed and resolved all identified defects across Phases 1 through 16 without rewriting existing working modules, deleting Firestore data, or fabricating fake credentials. When live credentials are not present, deterministic and secure fallback sandbox behaviors allow all workflows to complete without crashes.

---

## 2. Architecture Overview

```
                          ┌────────────────────────────────────────────────────────┐
                          │                 Firebase Cloud Services                │
                          │   • Firebase Authentication (ID Tokens, RBAC)          │
                          │   • Cloud Firestore (users, feedback, itineraries, etc)│
                          └──────────────────────────┬─────────────────────────────┘
                                                     │
                                                     ▼
┌───────────────────────┐         ┌────────────────────────────────────────────────────────┐
│ Traveller Mobile App  │         │                 Shared Backend API                     │
│ (Flutter / Dart)      ├────────►│                 (Flask on Port 5000)                   │
│ Local / Emulator / Web│         │                                                        │
└───────────────────────┘         │  • FR01: User Management & Authentication               │
                                  │  • FR02: Travel Personality & Preference Profiling     │
┌───────────────────────┐         │  • FR03: Destination Search & Google Maps Information  │
│ Operator Web Portal   │         │  • FR04: Hybrid Personality-Aware Recommendations      │
│ (Flask on Port 5001)  ├────────►│  • FR05: Smart Itinerary & Budget Planner              │
└───────────────────────┘         │  • FR06: Weather Forecast & Geocoding                  │
                                  │  • FR07: Flight Search & Itinerary Attachment          │
┌───────────────────────┐         │  • FR08: Hotel Search & Reservation Management         │
│ Administrator Portal  │         │  • FR09: Secure Payment Processing & Authoritative Bill│
│ (Flask on Port 5002)  ├────────►│  • FR10: Traveller Feedback & Canonical Ratings       │
└───────────────────────┘         │  • FR11: Gemini AI Assistant & Plan Generation         │
                                  │  • FR12: Tourism Operator Management & Analytics       │
                                  │  • FR13: Administrator Management & RBAC Moderation    │
                                  └────────────────────────────────────────────────────────┘
```

---

## 3. Defect Backlog, Root Cause Analysis & Resolutions

### Phase 1: Mobile Backend Connection & Profile Pipeline (FR01, FR02)
- **Defects Identified:** Hardcoded `baseUrl` pointing to localhost failed on Android emulators (which need `10.0.2.2:5000`); silent try-catch blocks swallowed profile creation failures; `STANDALONE_MODE` was inadvertently masking live backend connection errors.
- **Root Cause:** Inflexible URL configuration and fallback masking in `traveller_mobile/lib/services/api_service.dart`.
- **Resolution:**
  - Added platform-aware `baseUrl` resolution (`http://10.0.2.2:5000` for Android, `http://127.0.0.1:5000` for Web/Desktop, plus dynamic override via `setBaseUrl`).
  - Gated standalone mode strictly behind `STANDALONE_MODE=true` environment flag.
  - Re-threw meaningful API error messages so backend validation errors are visible in the UI.

### Phase 2: FR05 Smart Itinerary Planning Crash
- **Defects Identified:** Calling `POST /api/fr5/itineraries/<id>/lower-cost-alternatives/apply` crashed with a 500 `NameError: name '_own_itinerary' is not defined`.
- **Root Cause:** Line 255 of `backend_api/modules/fr05_smart_itinerary_budget_planner/routes.py` referenced `_own_itinerary(iid)` while the helper was declared as `_own(iid)`.
- **Resolution:** Updated call to `_own(iid)` and defined alias `_own_itinerary = _own` to ensure backwards compatibility.

### Phases 3 & 4: Destination Canonical Identity & Community Reviews Decoupling (FR03, FR10)
- **Defects Identified:**
  - Writing feedback from `feedback_screen.dart` used raw destination names instead of canonical IDs, creating orphan review documents in Firestore that never rendered on `destination_details_screen.dart`.
  - When a destination had 0 TravelMate community reviews, `destination_details_screen.dart` displayed 0 ratings, overwriting Google Maps rating counts.
- **Root Cause:** Lack of a shared canonical resolver and tight coupling of provider vs community rating counts.
- **Resolution:**
  - Implemented `traveller_mobile/lib/core/utils/destination_utils.dart` providing canonical ID (`resolveId`) and title (`resolveName`) resolution.
  - Refactored `destination_details_screen.dart` and `feedback_screen.dart` to use `resolveId`.
  - Stamped `destinationId` on search results in `fr03/routes.py` and supported alias lookups in `retrieveRatingsAndReviews`.
  - Decoupled community reviews from Google provider rating in the UI so both are accurately reported.

### Phase 5: FR03 Destination Search & SerpApi Querying
- **Defects Identified:**
  - SerpApi failed with 400 Bad Request because `engine: google_maps` was called with an unsupported `location` query parameter.
  - When SerpApi returned "Google hasn't returned any results", the backend threw an unhandled exception.
  - When no results returned, the backend dumped 14 Penang records regardless of search query.
- **Root Cause:** Improper SerpApi Google Maps parameters and unconditional fallback list return.
- **Resolution:**
  - Formatted SerpApi queries to embed location inside the `q` query string and omitted the separate `location` parameter for `google_maps`.
  - Gracefully converted SerpApi no-result responses into `{'local_results': []}`.
  - Implemented real keyword matching and included admin-curated destinations (`admin_destinations`) in search pools.
  - Fixed `_local_destination` to return `None` when an ID is unknown rather than always returning George Town.

### Phase 6: FR04 Hybrid Personality Recommendation Pool
- **Defects Identified:** Non-alphanumeric punctuation in area names caused regex/string comparison failures in area filtering; candidates lacking canonical IDs failed scoring.
- **Root Cause:** Strict string matching without normalization and incomplete candidate resolution.
- **Resolution:**
  - Stripped non-alphanumeric punctuation in candidate filtering.
  - Enhanced `_candidate_destinations` in `fr04/routes.py` to aggregate SerpApi, local catalog, and Firestore `admin_destinations`.
  - Provided full score breakdowns (personality, interest, pace, popularity).

### Phase 7: FR06 Weather Landmark Geocoding
- **Defects Identified:** Geocoding failed on non-city tourist landmarks (e.g. "Kek Lok Si Temple", "Penang Hill"), preventing weather forecasts from rendering.
- **Root Cause:** Direct geocoding of landmark names failed in Open-Meteo's city-centric geocoding API.
- **Resolution:**
  - Built GPS lookup from destination catalog and cached coordinates.
  - Implemented parent-city fallback parsing for landmark addresses.

### Phase 8: FR07 Flight Search & Itinerary Attachment
- **Defects Identified:** Flight search failed if travellers entered city names (e.g. "Penang") instead of 3-letter IATA codes (e.g. "PEN"). If a user had no itineraries, selecting a flight did nothing.
- **Root Cause:** Strict IATA validation without city resolver, and missing "create trip with flight" flow.
- **Resolution:**
  - Built bidirectional `CITY_TO_IATA` resolver in `backend_api/modules/fr07_flight_search/routes.py` and `flight_screen.dart`.
  - Added trip creation prompt in `flight_screen.dart` when no itineraries exist, allowing the user to create an itinerary with the selected flight pre-attached.

### Phases 9 & 10: FR08 Hotel Booking & FR09 Payment Authoritative Security
- **Defects Identified:**
  - Client-controlled payment amounts allowed clients to bypass authoritative prices.
  - Cross-user payment tampering was possible because booking ownership was not verified.
  - Payment intent failed when Stripe secret key was not configured.
  - Booking status was not updated to `'paid'` in Firestore.
- **Root Cause:** Missing server-side verification and unhandled Stripe test environment exceptions.
- **Resolution:**
  - Enforced server-side authoritative pricing from `hotel_bookings` in `backend_api/modules/fr09_payment/routes.py`.
  - Added strict ownership check: `booking.get('travellerId') == g.uid`.
  - Updated `hotel_bookings` status to `'paid'` using document ID upon successful payment intent creation.
  - Locked amount field in `payment_screen.dart` when tied to a booking.
  - Handled missing Stripe secret key gracefully with simulated sandbox payment intents when `FALLBACK_MODE=true`.

### Phases 11 & 12: FR11 AI Travel Assistant & Save Plan Route
- **Defects Identified:**
  - `POST /api/fr11/save-plan` did not exist, causing the "Save plan to Trips" button in `chat_tab.dart` to fail with a 404 error.
  - `generateChatbotResponse` crashed with an unhandled exception when `GEMINI_API_KEY` was missing, invalid, or quota-exceeded.
  - Assistant responses lacked structured `tripPlan` and `placeSuggestions` payloads for the mobile UI.
- **Root Cause:** Unimplemented endpoint and lack of exception interception in `gemini_service.py`.
- **Resolution:**
  - Implemented `POST /api/fr11/save-plan` in `fr11/routes.py`, creating valid itineraries in Firestore under `itineraries` collection for `g.uid`.
  - Wrapped `_generate` with `try/except Exception:` fallback to `_local_assistant(question, context)` in `gemini_service.py`.
  - Added planning and place recommendation extraction to attach `tripPlan` and `placeSuggestions` in `/api/fr11/chat`.

### Phases 13 & 14: FR12 Tourism Operator Management & Analytics Data Isolation
- **Defects Identified:**
  - Operator analytics leaked general platform hotel bookings to every operator.
  - In `analytics_service.py:123`, `if not booking_operator or booking_operator == operator_id:` included all bookings without an `operatorId`.
- **Root Cause:** Flawed filter logic in `analytics_service.py`.
- **Resolution:**
  - Replaced flawed condition with strict ownership: `if operator_id: if booking_operator == operator_id: bookings.append(data)`.
  - Confirmed package creation, completeness validation, and campaign linkage to approved packages.

### Phases 15 & 16: FR13 Administrator Management & RBAC
- **Defects Identified:** Need to ensure strict RBAC preventing non-administrators from accessing moderation and system administrative routes.
- **Root Cause:** Verification of role check contracts.
- **Resolution:**
  - Verified `@auth_required(['admin'])` on all admin routes.
  - Confirmed package review (`/packages/<pid>/review`), campaign review (`/campaigns/<cid>/review`), feedback moderation (`/feedback/<fid>/review`), and admin destination/activity CRUD routes.

---

## 4. API Endpoints Repaired or Added

| Module | Method | Endpoint | Status | Description |
| :--- | :---: | :--- | :---: | :--- |
| **FR01** | `POST` | `/api/fr1/profile` | Repaired | Dynamic host and Firestore user document synchronization |
| **FR03** | `GET` | `/api/fr3/destinations/search` | Repaired | SerpApi query fix + fallback keyword search + admin destinations |
| **FR03** | `GET` | `/api/fr3/destinations/<id>/reviews` | Repaired | Alias resolution + canonical ID matching |
| **FR04** | `POST` | `/api/fr4/recommendations` | Repaired | Cleaned area filter + full scoring breakdown |
| **FR05** | `POST` | `/api/fr5/itineraries/<id>/lower-cost-alternatives/apply` | Fixed | Resolved `_own_itinerary` crash |
| **FR06** | `GET` | `/api/fr6/weather` | Repaired | Landmark geocoding with parent city fallback |
| **FR07** | `GET` | `/api/fr7/flights/search` | Repaired | Bidirectional City-to-IATA code translation |
| **FR09** | `POST` | `/api/fr9/payments/create-intent` | Repaired | Server-side authoritative pricing + ownership check + booking status update |
| **FR10** | `POST` | `/api/fr10/feedback` | Repaired | Canonical `destinationId` stamping |
| **FR11** | `POST` | `/api/fr11/chat` | Repaired | Gemini try/except fallback + structured `tripPlan` generation |
| **FR11** | `POST` | `/api/fr11/save-plan` | **Added** | Converts AI chat trip plan into persistent Firestore itinerary |
| **FR12** | `GET` | `/api/fr12/analytics` | Fixed | Strict booking data isolation by `operatorId` |
| **FR13** | `POST` | `/api/fr13/packages/<id>/review` | Verified | Admin approval/rejection of tourism packages |
| **FR13** | `POST` | `/api/fr13/feedback/<id>/review` | Verified | Admin content moderation for reviews/feedback |

---

## 5. Security & State Management Hardening

1. **Role-Based Access Control (RBAC):** Token validation via Firebase Admin SDK strictly validates user roles (`traveller`, `operator`, `admin`). Non-admin attempts to access `/api/fr13/*` return HTTP 403 Forbidden.
2. **Authoritative Financial Billing:** Travellers cannot submit modified price values during payment. Total charge is calculated server-side from the verified hotel booking.
3. **Cross-Tenant Isolation:**
   - Itineraries are restricted to their creator (`g.uid`).
   - Bookings can only be paid by their owner (`travellerId == g.uid`).
   - Operators can only see packages, campaigns, and bookings tagged with their own `operatorId`.
4. **Data Consistency:** Reviews, itineraries, and search results now utilize canonical destination IDs (`resolveId`), preventing orphan documents.

---

## 6. External Dependency Configuration & Fallback Behavior

| Provider | Purpose | Primary Behavior | Fallback Behavior (`FALLBACK_MODE=true`) |
| :--- | :--- | :--- | :--- |
| **Firebase Auth** | User Authentication | Live ID token verification | Mocked in unit test fixtures; local emulator support |
| **Cloud Firestore** | Document Database | Live document reads/writes | Mocked in unit test fixtures |
| **SerpApi** | Google Maps & Flights | Real-time queries for places/flights | Deterministic Malaysian destinations & flight routes from `local_catalog.py` |
| **Open-Meteo** | Weather & Geocoding | Live 7-day weather forecast API | Coordinated landmark geocoding & seasonal weather fallback |
| **Stripe** | Payment Gateway | Stripe PaymentIntent API | Simulated sandbox PaymentIntent (`pi_mock_...`) with instant booking confirmation |
| **Google Gemini**| AI Travel Assistant | Gemini 3.7 / 2.5 Flash API | Deterministic rule-based conversational assistant with itinerary & place generation |

---

## 7. Conclusion

The TravelMate application has achieved full stability, seamless module integration, and is FYP demonstration ready across all 3 user roles.
