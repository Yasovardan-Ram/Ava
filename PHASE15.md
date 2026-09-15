# Phase 15 — Observable Simulation & Intervention Pacing

- Slowed Building dashboard playback so 1× is human-observable while higher speeds remain available.
- Added a short post-intervention visual hold so AVA's before/after result can be inspected before normal simulation resumes.
- Preserved the selected playback speed when resuming after an AVA intervention.
- Kept physics/optimization computation fast; only dashboard presentation is paced.
- `/api/occupant-feedback` now reports whether the simulation was running before the intervention.
- Existing individual occupant comfort and closed-loop optimization logic from Phase 14 is preserved.
