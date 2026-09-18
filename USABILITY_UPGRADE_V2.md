# TravelMate Usability Upgrade V2

This revision keeps the proposed FR1–FR13 structure and upgrades the Traveller application around real user workflows.

## Traveller upgrades

1. **Personal details page**
   - Profile card opens a dedicated page.
   - Shows email, phone, date of birth, nationality, preferred language, emergency contact, role, status and member-since date.
   - Editable fields are saved through the existing FR1 profile contract.

2. **More relevant personalised recommendations**
   - Recommendation scoring uses interests, travel type, budget, pace, purpose, personality and sleeping/comfort preference.
   - Destination area is used as a hard candidate filter when a specific area is entered.
   - UI shows the profile factors used and a match explanation.

3. **Destination reviews**
   - Standalone destination records provide at least eight review entries.
   - Destination Details initially shows five reviews and supports View All.

4. **Deeper destination information**
   - Opening days and hours.
   - Admission information.
   - Best visiting time.
   - Visitor tips and facilities.
   - Contact/location fields when available.
   - Direct link to write a review for the selected place.

5. **Separate Flight Details and Hotel Details pages**
   - Flight details: route, date, duration, stops, cabin, aircraft, terminals, baggage, fare/change/refund information and meal information.
   - Hotel details: description, room, bed, room size, board, check-in/out, amenities, cancellation policy and house rules.
   - Selection / booking continues from the detail page.

6. **Card-payment process**
   - Cardholder, card number, expiry, CVC and billing email.
   - Luhn validation and expiry validation.
   - Authorisation/loading stage, success receipt and transaction history.
   - Full card number and CVC are never persisted.
   - The FYP build does not charge real money.

7. **Improved destination search**
   - Weighted title/category/type/keyword/interest/description/location matching.
   - Query synonym expansion for food, history, nature, adventure, shopping, family, photography, indoor and beach searches.
   - Results are ranked by search relevance rather than returning unrelated places when the query is weak.

8. **Travel Assistant with conversation history**
   - Multiple named chat sessions.
   - Drawer-based history similar to a persistent chat history bar.
   - New chat, open old chat and delete chat.
   - Trip-plan intent detection.
   - Generates a preference-aware multi-day plan and allows Save Plan to Trips.

9. **Logical Feedback & Rating flow**
   - Traveller searches and chooses a TravelMate place.
   - No destination ID typing.
   - Star-rating UI.
   - Destination name/address saved with feedback.
   - Existing reviews can open Place Details, edit or delete.

## Standalone and cloud behaviour

The app remains usable without a laptop backend because these functions are implemented in `StandaloneApiService` and persisted locally. When a public Flask backend is configured, `ApiService` uses it first and falls back locally if a provider route is unavailable.
