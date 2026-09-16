from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.storage import get_json, put_json, delete_key, append_history as storage_append_history, load_history as storage_load_history, clear_history as storage_clear_history


import os
DATA_DIR = Path(os.environ.get("AVA_RUNTIME_DIR", "/tmp/ava_runtime" if os.environ.get("VERCEL") else str(Path(__file__).resolve().parent.parent.parent / "data")))
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
    payload = get_json("legacy_zone_state")
    if payload is not None:
        return ZoneState.from_dict(payload)
    state = ZoneState.from_dict(DEFAULT_STATE.to_dict())
    put_json("legacy_zone_state", state.to_dict())
    return state

def save_state(state: ZoneState) -> None:
    put_json("legacy_zone_state", state.to_dict())

def append_history(entry: dict) -> None:
    entry = dict(entry)
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    storage_append_history({"legacy": True, **entry}, limit=1000)

def load_history() -> list[dict]:
    return [e for e in storage_load_history() if e.get("legacy")]


def reset_state() -> ZoneState:
    state = ZoneState.from_dict(DEFAULT_STATE.to_dict())
    put_json("legacy_zone_state", state.to_dict())
    return state
