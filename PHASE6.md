# AVA Phase 6 — Reliability, interaction fixes, and real-world modeling simplification

## Completed
- Removed duplicate Phase 5 UI blocks/IDs that could prevent later controls from binding.
- Restored the AVA Autonomy controls that the JavaScript expected.
- Added additional bottom scroll space to the building twin so all three floors can be scrolled comfortably.
- Disabled occupant-detail entrance animation during live refreshes.
- Removed clothing from the occupant-facing UI. Clothing is now treated as a fixed 0.5 clo indoor modeling baseline rather than an inferred real-world input.
- Added deterministic occupant-feedback parsing for common phrases when Nemotron is unavailable or unreachable.
- Added fallback handling for malformed/empty Nemotron responses so feedback does not become an HTTP 500.
- Preserved Nemotron as the primary parser when `NIM_API_KEY` is available.
- Kept API errors JSON-compatible through the application's existing Flask error handlers.

## Validation performed
- Python compilation of all application modules.
- JavaScript syntax checks for `building.js` and `simulation.js`.
- HTML duplicate-ID check.
- Static JavaScript DOM-reference check; only `open-feedback` remains dynamic because it is created after an occupant is selected.
- Local fallback parser smoke tests for too-cold, too-hot, stuffy, and comfortable feedback.

## Modeling note
Thermal comfort calculations still use PMV/PPD, which mathematically includes clothing insulation. AVA does not ask the user to report clothing; it uses a fixed indoor baseline of 0.5 clo so the model remains usable for a real deployment where clothing is not reliably observable.
