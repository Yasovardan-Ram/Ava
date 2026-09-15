# Phase 16 — ASHRAE 55 PMV Consistency

- Centralized PMV comfort constants: -0.5 <= PMV <= +0.5.
- PPD fallback is derived from the PMV value and safely handles NaN/non-finite pythermalcomfort outputs.
- Building simulation, legacy digital twin, and optimizers use the same deterministic fallback PMV implementation.
- Legacy `simulation.js` now mirrors that fallback formula and uses zone humidity, mean radiant temperature, air velocity, metabolic rate, and clothing inputs.
- Symmetric comfort boundaries are used across backend and frontend.
- Simulation profile version bumped to invalidate stale occupant/building comfort state.
- Validation: Python compileall and JavaScript syntax checks pass.
