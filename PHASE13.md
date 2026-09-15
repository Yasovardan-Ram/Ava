# Phase 13 – Comfort, Optimization & Simulation Reliability

## Fixed
- Building comfort is now calculated per occupant. Hot and cold occupants cannot cancel each other into a false "comfortable" room.
- Room cards show individual comfort, such as `8/10 comfortable`, instead of relying on average PMV.
- Building and floor metrics use individual occupant comfort percentages.
- HVAC optimization now prioritizes the number of individually comfortable occupants, then total discomfort and energy.
- The occupant who submitted feedback receives priority during feedback-triggered optimization.
- Zone dampers are optimized independently per occupied room and are actually applied to the HVAC state.
- Feedback room identification no longer depends entirely on Nemotron. Room IDs and room names are resolved locally as a fallback.
- Feedback actions are evaluated over a fixed 10 simulated minutes, independent of the UI playback speed, so 10x/20x playback cannot make the response jump unpredictably.
- Base simulation ticks use a 1-minute simulation step instead of a 5-minute step.
- Default building occupants are deterministic, distributed across all three floors, and use realistic moderate office activity/clothing profiles.
- Occupancy scheduling is deterministic during normal working hours instead of randomly changing every tick.
- Legacy Simulation uses deterministic occupant profiles and individual comfort from startup.
- Explicit occupant feedback is preserved as the last reported complaint instead of being overwritten every simulation tick.
- Old saved simulation states are migrated automatically to the new demo population/profile.

## Validation
- Python source compilation passed for changed backend files.
- JavaScript syntax checks passed for `building.js` and `simulation.js`.
