# TravelMate API Route Map

The Flutter app, Operator website and Administrator website all call the shared backend on port 5000.

## System
- `GET /api/health`
- `GET /api/config-status` (Administrator authentication required)

## FR1 User Management
- `POST /api/fr1/profile`
- `GET /api/fr1/me`
- `PUT /api/fr1/me`

## FR2 Travel Preference
- `GET /api/fr2/preferences`
- `PUT /api/fr2/preferences`

## FR3 Destination Search and Information
- Destination search/details through SerpApi adapters
- Favourite destination CRUD through Firestore
- Ratings/reviews and nearby places for selected destinations

## FR4 Hybrid Recommendation
- Generate/retrieve a simple explainable recommendation list using preference and destination data

## FR5 Smart Itinerary and Budget Planner
- Itinerary create/list/update/delete
- Add itinerary activity
- Budget comparison, lower-cost suggestions and apply-selected-alternative endpoint

## FR6 Weather Forecast
- Destination geocoding through Open-Meteo
- Current + seven-day forecast

## FR7 Flight Search
- Flight search through SerpApi Google Flights
- Traveller-count pricing for search results

## FR8 Hotel Booking
- Place search through LiteAPI / Nuitee Connect
- Hotel rate search
- Prebook
- Book adapter
- Firestore booking record
- Room quantity support
- Car rental search/select adapter and itinerary attachment

## FR9 Payment
- Create Stripe PaymentIntent
- Sandbox convenience payment workflow
- Store payment record in Firestore
- Retry/cancel stored payment records

## FR10 Feedback and Rating
- Submit/list/update/delete Traveller feedback

## FR11 Chatbot Travel Assistant
- Gemini interaction
- Firestore chat history
- Chat session create/list/read/delete
- Clear chat history

## FR12 Tourism Operator Management
- Tourism package CRUD
- Submit package for Administrator approval
- Promotional campaign CRUD
- Submit campaign for review
- Business analytics

## FR13 Administrator Management
- List/update user account role/status
- Destination CRUD
- Activity CRUD
- Approve/reject package
- Approve/reject promotional content
- Moderate Traveller feedback
- Booking/payment record review
- System report summary with report type, date range and keyword filters
- CSV/PDF report export

For exact method/path combinations, open each module's `routes.py`.
