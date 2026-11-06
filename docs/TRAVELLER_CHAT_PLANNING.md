# Traveller guided chat planning

The Flutter chat requests `guidedPlanning: true`. Both Flask and explicit standalone mode collect a Malaysian destination, dates or duration, an actual calendar range, budget, traveller count and travel interests. Saved interests and travel style may satisfy preference questions; missing essential trip details are not fabricated. Duration-only answers lead to a calendar-date question.

## Dates

Explicit ranges include `12 Dec until 16 Dec`, `12 Dec to 16 Dec`, long month names, `12 to 16 December`, `12–16 Dec`, full day/month/year pairs and ISO pairs. `5 days` and `4 nights` both imply five calendar itinerary days. Ambiguous slash-date order, invalid/reversed/past dates and recognized ranges longer than fourteen days request clarification. Missing years use the next upcoming occurrence in the Malaysian calendar, including December–January rollover.

Dates are authoritative over conflicting duration. On 5 November 2026, `12 Dec until 16 Dec` means 12–16 December 2026: five itinerary days and four nights. The exact dates persist through later budget/traveller answers, plan generation, saving and reopening. Corrections invalidate the older active draft.

## Structured drafts and saving

The response and persisted chat message include `tripPlan` only when structured destination data exists. Flutter renders its actual summary, preferences and expandable dated days, with supplied visit durations/details. Unsupported travel-time estimates are omitted. The planner does not repeat attractions just to fill slots, and geographical filtering prevents another state's attractions from entering the selected destination.

An incomplete itinerary is labelled as such; missing days/slots are not invented and incomplete previews cannot be saved. If the local catalogue lacks coverage, Flask can use the existing destination-provider service when configured, then apply the same geographical checks. Without sufficient genuine data, the reply explains the coverage gap instead of claiming a complete draft exists. Standalone mode can use its existing destination catalogue and cached place results; it does not invent provider coverage.

The active structured draft remains in chat planning state. Requests such as `show my plan`, `where the trips` and `show the itinerary` redisplay it. Date/destination/budget/traveller/preference changes invalidate older drafts. Historical cards remain visible as earlier drafts with saving disabled.

`Save plan to Trips` opens an explicit review/confirmation dialog. The existing authenticated save endpoint receives the accepted plan and optional chat-session context. Session-bound saves reject stale drafts and foreign sessions. Atomic deterministic itinerary creation prevents duplicate saves of the same accepted draft. Success is displayed only after the response contains a persisted itinerary identity. Pending/failed saves are distinguished; confirmed saved drafts expose Trips navigation. Existing legacy clients without chat-session context retain their endpoint contract.

## Regression contract

`backend_api/tests/test_android_three_regressions.py` exercises real Flask chat/save/reopen routes with synthetic auth/storage/provider boundaries. Its accepted Johor plan is compared with `traveller_mobile/test/fixtures/fr11_guided_contract.json`; the Flutter tests render that actual route response at a narrow phone width and verify all five dated days and the save action. Separate standalone tests cover the same multi-turn planning, follow-up, correction and save/reopen lifecycle.

Widget/API test success does not constitute physical Android acceptance. A rebuilt application and matching backend runtime are required for manual checks. Do not restart unrelated/protected services, overwrite the owner's installed application, or use production Firebase or real bookings for isolated verification.
