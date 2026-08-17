from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STATE_FILE = DATA_DIR / "zone_state.json"
HISTORY_FILE = DATA_DIR / "history.json"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ZoneState:
    temperature: float = 28.0
    humidity: float = 60.0
    air_velocity: float = 0.08
    mean_radiant_temp: float = 28.0
    metabolic_rate: float = 1.2
    clothing_insulation: float = 0.5
    hvac_setpoint: float = 18.0
    fan_speed: float = 0.5
    outdoor_temp: float = 35.0
    zone_name: str = "Room A"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ZoneState:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


DEFAULT_STATE = ZoneState()


def load_state() -> ZoneState:
    _ensure_data_dir()
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return ZoneState.from_dict(json.load(f))
    save_state(DEFAULT_STATE)
    return DEFAULT_STATE


def save_state(state: ZoneState) -> None:
    _ensure_data_dir()
    with open(STATE_FILE, "w") as f:
        json.dump(state.to_dict(), f, indent=2)


def append_history(entry: dict) -> None:
    _ensure_data_dir()
    history: list[dict] = []
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            history = json.load(f)
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    history.append(entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def load_history() -> list[dict]:
    _ensure_data_dir()
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


def reset_state() -> ZoneState:
    save_state(DEFAULT_STATE)
    return DEFAULT_STATE
