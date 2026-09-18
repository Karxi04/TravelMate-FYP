# IMPORTANT — Sequence Diagram / Code Naming Consistency

This revision synchronises the **actual source-code function names** with the revised 53 sequence diagrams.

Examples: `validateRequiredInformation()`, `createUserAccount()`, `authenticateCredentials()`, `retrieveRecord()`, `storeRecord()`, `retrieveDestinationResults()`, `applyContentBasedFiltering()`, `calculateBudget()`, `retrieveSevenDayForecast()`, `retrieveFlightOptions()`, `retrieveHotelOffers()`, `processSandboxPayment()`, `generateChatbotResponse()`, `submitForApproval()`, `approve()`, `reject()`, `generateReport()` and `exportReport()`.

See:
- `docs/SEQUENCE_FUNCTION_CONSISTENCY.csv`
- `docs/SEQUENCE_FUNCTION_INDEX.md`
- `docs/sequence_diagrams/`

---

# TravelMate Real Usable MVP — Ink Wash Theme

This package is a working development baseline for the actual FYP system, not only Chapter 4 mock screens.

## Three separate frontends

1. **Traveller** — Flutter mobile application
2. **Tourism Operator** — separate Flask website (port 5001)
3. **Administrator** — separate Flask website (port 5002)

All three use one shared Flask REST backend (port 5000), Firebase Authentication and Firestore.

## Theme

All interfaces follow the supplied Ink Wash palette:

- `#4A4A4A`
- `#CBCBCB`
- `#FFFFE3`
- `#6D8196`

See `docs/THEME.md`.

## Implemented module coverage

### Traveller
- FR1 User Management
- FR2 Travel Preference
- FR3 Destination Search and Information with favourites, ratings/reviews and nearby places
- FR4 Hybrid Recommendation
- FR5 Smart Itinerary and Budget Planner with budget comparison and applicable lower-cost alternatives
- FR6 Weather Forecast
- FR7 Flight Search with traveller-count pricing
- FR8 Hotel Search / Prebook / Booking and Car Rental Search
- FR9 Stripe Sandbox Payment with retry/cancel actions
- FR10 Feedback and Rating
- FR11 Gemini Chatbot with chat sessions/history

### Tourism Operator Website
- FR1 Register/Login/Reset/Profile/Logout
- FR12 Tourism Package CRUD + submit/status
- Promotional Campaign CRUD + submit/review state
- Business Analytics

### Administrator Website
- FR1 Login / user account control
- FR13 user account management
- Package approval/rejection
- Promotional-content approval/rejection
- Traveller-feedback moderation
- Destination/activity management
- Booking/payment record review
- System report criteria + CSV/PDF export

## Read these files in order

1. `docs/SETUP_FIREBASE.md`
2. `docs/HOW_FIRESTORE_IS_LINKED.md`
3. `docs/SETUP_EXTERNAL_APIS.md`
4. `docs/RUN_ORDER_WINDOWS.md`
5. `docs/HOW_TO_TEST_THE_MVP.md`
6. `docs/FIRESTORE_DATA_MODEL.md`
7. `docs/API_ROUTE_MAP.md`
8. `docs/README_ENHANCED_SYSTEM.md`

## Important

The ZIP intentionally contains no private credentials. You must add your own Firebase service-account file and API keys to local `.env` files.
