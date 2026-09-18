# TravelMate V3.1 – Unique Place Image Resolution

This revision removes the LoremFlickr image generator used by V3.

## Why V3 showed the same image for different places
V3 converted destination titles/categories into LoremFlickr tags. The remote service could return the same photo for multiple different queries, and the returned image did not reliably represent the actual destination.

## New image resolution flow
1. Use a provider-supplied image URL when one exists.
2. Search English Wikipedia for the specific place/dish and use the lead image.
3. Search Wikimedia Commons when Wikipedia does not provide a suitable image.
4. Avoid assigning the same resolved URL to two different place cards in the same app session when another candidate exists.
5. If no reliable image can be found, show a category-specific TravelMate fallback instead of an unrelated random photo.

The image resolver is shared by Home, Explore, Recommendations, Destination Details, Trips, and Assistant place cards through `TravelPlaceImage`.

No backend is required for image lookup. An Internet connection is required for online images.
