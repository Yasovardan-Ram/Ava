# AVA Phase 5 — Advanced Digital Twin Simulation

Phase 5 extends the existing Phase 4 digital twin without rebuilding earlier functionality.

## Added

- Equipment health degradation: compressor efficiency, fan health, and overall HVAC health now drift gradually.
- Rare automatic HVAC fault injection during long-running simulation, with real events in the audit timeline.
- Sensor anomaly simulation: temperature/humidity telemetry bias can be injected and decays over time.
- Room-to-room thermal interaction: zones on the same floor exchange a small amount of heat instead of behaving as isolated boxes.
- Occupancy surge disturbance injection using real occupant objects.
- Stuck-damper and window-open disturbances.
- Energy anomaly tracking caused by degraded equipment efficiency.
- New Phase 5 Fault Lab controls in the Digital Twin UI.
- Equipment health and sensor anomaly metrics in the live metrics strip.
- New event types: sensor anomaly, equipment degradation, energy anomaly, and room interaction.
- Fixed the legacy `night` scenario weather condition from unsupported `clear` to supported `sunny`.

## API

`POST /api/disturbance`

Supported `kind` values:

- `hvac_degradation`
- `sensor_drift`
- `occupancy_surge`
- `stuck_damper`
- `window_open`

## Validation

- `node --check app/static/building.js` — passed
- `node --check app/static/simulation.js` — passed
- `python -m compileall -q app` — passed

A full runtime simulation could not be executed in the build environment because Flask is not installed there. Run the project in the same Python environment used for the Flask server for end-to-end verification.

## Design direction

The goal is a more credible closed-loop digital twin: changing weather, occupancy, equipment condition, sensor quality, and zone coupling can create observable events that AVA can monitor and act on. This aligns with current HVAC digital-twin work emphasizing dynamic weather/occupancy variation, fault diagnosis, and closed-loop optimization. See the 2026 state-of-the-art review and recent occupant-centric / predictive-maintenance research for context.
