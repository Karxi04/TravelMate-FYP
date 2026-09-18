# TravelMate Dynamic Usability Upgrade V3

This revision focuses on dynamic destination discovery, preference-driven Home recommendations, conversational trip planning, usable trip editing, and a complete profile editor.

## Traveller improvements

### Home
- Generates `Picked for you` places from the stored Travel Preference profile.
- Place cards include imagery, recommendation reason, Details, and Add to trip.
- Home refresh recalculates recommendations from the current stored preferences.

### Explore / destination search
- Search ranking now considers exact title, place keywords, category/type, interests, description, destination/city and dish intent.
- City is inferred from common query phrases such as Penang, George Town, Kuala Lumpur / KL and Langkawi.
- Generic words such as "attractions", "places" and "things to do" no longer dominate relevance scoring.
- Food query expansion supports dish intent including curry mee, asam laksa, char koay teow, nasi kandar, chendul, Hokkien mee, roti canai and satay.
- The built-in Malaysia catalogue has been substantially expanded for Penang and Kuala Lumpur.
- When the device is online and local results are limited, the standalone application can augment results through OpenStreetMap Nominatim without embedding a secret API key.
- Results contain Details and Add to trip actions.

### Destination details
- Detailed information remains available from search, Home, recommendation and trip pages.
- Weekly opening information and visitor information remain available.
- At least the first five available review entries are shown before View all.
- A place-related discovery image is attempted when a provider image is not available.

### TravelMate Assistant
- A trip request does not immediately return a fixed Penang itinerary.
- The assistant keeps a planning state for the current conversation and asks for missing destination, duration, interests/focus and budget.
- Saved Travel Preferences are used as supporting context.
- Kuala Lumpur planning selects Kuala Lumpur-area candidates; Penang planning selects Penang candidates.
- Generated plans vary according to city, requested interests, budget and available candidate places.
- Direct place or food queries can return place cards with Details and Add to trip.
- Multiple chat sessions and history are retained.
- Generated plans can be saved into Trips.

### Trips
- Main Trips screen shows compact cards: title, destination, budget and number of places.
- Trip details are opened on a separate screen.
- Trip title, destination, dates, traveller count and budget are editable.
- Places are added through a searchable place picker instead of typing a free-form activity.
- Multiple places can be selected and added.
- Itinerary places can be rearranged with drag handles.
- Reordering updates sequence numbers and day grouping.
- Place details can be opened directly from itinerary activities.

### Profile
- Edit Profile is a dedicated full page instead of a minimal dialog.
- Editable information includes full name, phone, date of birth, nationality, current city, gender, preferred language, emergency contact, relationship and travel bio.
- Firebase email remains visible as the account email and is not silently replaced by a local field.

## Current-app design patterns used as references
The interaction patterns were adapted to TravelMate rather than copied directly: conversational preference collection before itinerary generation, natural-language discovery, visual place cards, dedicated detail pages, compact trip summaries, and drag-to-reorder itinerary places.

## Standalone behavior
The default build still works without running the Flask backend on a laptop. When Internet is available, selected direct public services can provide additional online information. Secret-key providers remain suitable for the optional deployed backend mode.
