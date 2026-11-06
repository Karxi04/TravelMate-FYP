# Flight airport catalogue

Traveller flight selection and new search requests are restricted to **34 Malaysian airport identities**. Search matches city, Malaysian state, airport name, spelling aliases and IATA code. For example, Subang finds SZB, Johor finds JHB, Sarawak finds its regional airports, and Sultan Haji Ahmad Shah finds KUA. London, Narita, JFK and other non-Malaysian identities are excluded.

- Canonical Traveller data: `backend_api/services/data/malaysian_airports.json`.
- Provenance, source checksum and scope: `backend_api/services/data/malaysian_airports.meta.json`.
- Flutter generated labels and aliases: `traveller_mobile/lib/modules/fr07_flight_search/flight_airport_catalog.dart`.
- Backend boundary: `MALAYSIAN_AIRPORTS` in `services/flight_airports.py`, enforced by `flightSearchValidationError` before provider calls.
- The previous 4,008-identity worldwide JSON and metadata are retained unchanged for compatibility. Their presence does not allow international Traveller search requests. Existing exact aliases still resolve to identities; non-Malaysian results are rejected at the new-search boundary.

The original identity source is [OurAirports](https://ourairports.com/data/), which publishes public-domain, community-maintained data without an accuracy guarantee. [Field definitions](https://ourairports.com/help/data-dictionary.html) explain IATA codes, municipality and ISO region fields. The Malaysian subset was checked against that source on 5 November 2026; state names come from its Malaysian region codes. Common city spellings and the Sultan Haji Ahmad Shah name are searchable aliases. [Malaysia's Ministry of Transport airport list](https://www.mot.gov.my/en/aviation/infrastructure/list-of-airports) provides official airport context.

Airport identity is separate from current passenger service and supplier availability. No bundled identity guarantees an active route, flight, fare or seat. The existing flight provider must return genuine results, an empty result or an error. This is a bounded passenger-oriented subset, not every Malaysian airstrip, military facility or private aerodrome.

Autocomplete filters the whole subset before limiting the visible suggestion list to 30 entries; users can refine a name/code and scroll matching results. Tests cover every supported IATA selection, state/name/city searches, exact Flutter/backend parity, international-code rejection, MYR requests and stale-result handling. Update the canonical subset and generated Dart map together, then rerun these tests. No extra airport API or runtime lookup is introduced.
