# Ava

NLP-based HVAC Digital Twin — Flask app for closed-loop comfort and energy optimization.

## Run

```bash
uv run main.py
```

Dev server starts at `http://127.0.0.1:5000` with debug mode.

## Prerequisites

1. Copy `.env.example` to `.env` and set `NIM_API_KEY` to your Nvidia NIM API key
2. `uv sync` to install dependencies

## Structure

- `app/__init__.py` — app factory (`create_app`)
- `app/routes.py` — Flask Blueprint with API endpoints (`/api/complaint`, `/api/zone-state`, `/api/history`, `/api/reset`)
- `app/models.py` — `ZoneState` dataclass + JSON persistence (`data/zone_state.json`, `data/history.json`)
- `app/nlp/extractor.py` — Nvidia NIM integration, extracts structured HVAC constraints from free-text complaints
- `app/simulation/digital_twin.py` — pythermalcomfort wrapper, PMV/PPD assessment, thermal simulation
- `app/optimizer/hvac_optimizer.py` — Scipy SLSQP optimizer, minimizes energy cost subject to PMV ∈ [-0.5, 0.5]
- `app/templates/` — Jinja2 templates (base.html, index.html)
- `app/static/` — CSS, JS (Chart.js for energy history)
- `data/` — Runtime JSON state (gitignored)

## Key Dependencies

- `flask` — web framework
- `pythermalcomfort` — PMV/PPD calculation per ISO 7730
- `scipy` — HVAC setpoint optimization (SLSQP)
- `openai` — Nvidia NIM API client (OpenAI-compatible)
- `python-dotenv` — `.env` file loading

## Data Flow (per complaint)

```
User text → NIM API (structured JSON) → pythermalcomfort PMV calc → Scipy optimizer → Digital twin sim → Persist → Dashboard
```

## NIM Model

`nvidia/nemotron-3.5-lightning-30b-a3b` with `guided_json` for schema-constrained output.

## PMV Reference

- PMV ∈ [-0.5, +0.5] = comfortable (ASHRAE 55 compliant)
- PMV = 0 → neutral, PPD = 5%
- PMV = ±0.5 → PPD ≈ 10%

## Conventions

- Package manager: **uv** (not pip)
- Python >=3.12.2
- Blueprints for route organization
- Templates extend `base.html`
- Zone state persisted as JSON in `data/` (gitignored)
- NLP cache: in-memory dict, resets on restart
