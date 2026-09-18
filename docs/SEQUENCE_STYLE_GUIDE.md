# TravelMate Sequence Diagram Style

- UI actions and displayed messages use normal English action labels without `()`.
- Actual validation, API, database, recommendation, itinerary, payment, and other processing operations retain function-call format.
- `alt` is reserved for genuine alternative outcomes.
- Nested alternatives are used only where the child condition depends on the parent result.
