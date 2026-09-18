CURRENT REVISION: TravelMate Enhanced Standalone + Cloud Ready

Use these files first:
- README_ENHANCED_SYSTEM.md
- NO_CABLE_AND_CLOUD_SETUP.md
- build_android_standalone.ps1
- build_android_cloud.ps1

Key behavioural change:
New Traveller account / first login -> mandatory Travel Preference questionnaire -> main TravelMate app.

Default Flutter API mode:
- no API_BASE_URL -> standalone local-first operation
- API_BASE_URL provided -> cloud Flask backend, with automatic local fallback if temporarily unreachable

The existing Chapter 3 FR1-FR13 proposal and sequence-function naming remain the design authority.
