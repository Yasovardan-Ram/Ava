from __future__ import annotations

import json
import math
import random
import uuid
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.storage import get_json, put_json, delete_key, append_history as storage_append_history, load_history as storage_load_history, clear_history as storage_clear_history


DATA_DIR = Path(os.environ.get("AVA_RUNTIME_DIR", "/tmp/ava_runtime" if os.environ.get("VERCEL") else str(Path(__file__).resolve().parent.parent.parent / "data")))
BUILDING_STATE_FILE = DATA_DIR / "building_state.json"
BUILDING_HISTORY_FILE = DATA_DIR / "building_history.json"
SIMULATION_PROFILE_VERSION = 15


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class RoomType(Enum):
    RECEPTION = "reception"
    LOBBY = "lobby"
    CONFERENCE = "conference"
    OFFICE = "office"
    OPEN_WORKSPACE = "open_workspace"
    MEETING = "meeting"
    SERVER = "server"
    LOUNGE = "lounge"
    TRAINING = "training"


class Orientation(Enum):
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NONE = "none"


class WeatherCondition(Enum):
    SUNNY = "sunny"
    CLOUDY = "cloudy"
    RAIN = "rain"
    STORM = "storm"
    WINTER = "winter"
    HEAT_WAVE = "heat_wave"


class HVACMode(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    FAILURE = "failure"


class EventType(Enum):
    OCCUPANCY_SURGE = "occupancy_surge"
    MEETING_START = "meeting_start"
    ROOM_EMPTY = "room_empty"
    WINDOW_OPENED = "window_opened"
    DOOR_OPENED = "door_opened"
    HVAC_FAULT = "hvac_fault"
    HEAT_WAVE = "heat_wave"
    RAIN_START = "rain_start"
    WEATHER_CHANGE = "weather_change"
    HUMIDITY_SPIKE = "humidity_spike"
    UNEXPECTED_OCCUPANCY = "unexpected_occupancy"
    REDUCED_CAPACITY = "reduced_capacity"
    SENSOR_ANOMALY = "sensor_anomaly"
    EQUIPMENT_DEGRADATION = "equipment_degradation"
    ENERGY_ANOMALY = "energy_anomaly"
    ROOM_INTERACTION = "room_interaction"


@dataclass
class Occupant:
    id: str
    name: str
    room_id: str
    activity: str
    metabolic_rate: float
    clothing_insulation: float
    preferred_temp: float
    comfort_tolerance: float
    current_comfort: float
    feedback: str = ""
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Occupant:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Room:
    id: str
    floor: int
    name: str
    room_type: RoomType
    area: float
    volume: float
    temperature: float
    humidity: float
    air_velocity: float
    mean_radiant_temp: float
    orientation: Orientation
    window_area: float
    occupancy: int
    max_occupancy: int
    hvac_state: dict
    supply_temp: float
    airflow: float
    fan_speed: float
    thermal_load: float
    pmv: float
    ppd: float
    comfort_status: str
    energy_consumption: float
    target_comfort_min: float = -0.5
    target_comfort_max: float = 0.5
    doors_open: bool = False
    windows_open: bool = False
    solar_gain: float = 0.0
    occupants_list: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["room_type"] = self.room_type.value
        d["orientation"] = self.orientation.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Room:
        d = d.copy()
        d["room_type"] = RoomType(d.get("room_type", "office"))
        d["orientation"] = Orientation(d.get("orientation", "none"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Weather:
    outdoor_temp: float
    humidity: float
    wind_speed: float
    condition: WeatherCondition
    time_of_day: float
    solar_intensity: float
    # Optional autonomous-weather state used by the configurable AVA twin.
    # The fixed Demo Building leaves these at their defaults, preserving its
    # stable Phase 17 behaviour.
    dynamic_elapsed: float = 0.0
    dynamic_next_change: float = 0.0
    dynamic_target: WeatherCondition | None = None
    dynamic_transition: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["condition"] = self.condition.value
        if self.dynamic_target is not None:
            d["dynamic_target"] = self.dynamic_target.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Weather:
        d = d.copy()
        d["condition"] = WeatherCondition(d.get("condition", "sunny"))
        if d.get("dynamic_target"):
            d["dynamic_target"] = WeatherCondition(d["dynamic_target"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class HVACSystem:
    mode: HVACMode
    total_capacity: float
    current_load: float
    supply_temp: float
    main_fan_speed: float
    floor_capacities: dict[int, float]
    zone_dampers: dict[str, float]
    energy_consumption: float
    failure_zones: list[str] = field(default_factory=list)
    failure_severity: dict[str, float] = field(default_factory=dict)
    equipment_health: float = 1.0
    compressor_efficiency: float = 1.0
    fan_health: float = 1.0
    sensor_bias: dict[str, dict[str, float]] = field(default_factory=dict)
    energy_anomaly: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> HVACSystem:
        d = d.copy()
        d["mode"] = HVACMode(d.get("mode", "auto"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BuildingEvent:
    id: str
    timestamp: str
    event_type: EventType
    description: str
    affected_rooms: list[str]
    severity: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> BuildingEvent:
        d = d.copy()
        d["event_type"] = EventType(d.get("event_type", "occupancy_surge"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SimulationClock:
    current_time: float
    speed_multiplier: float
    is_running: bool
    day_length_seconds: float = 86400.0
    start_time: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SimulationClock:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BuildingState:
    floors: list[int] = field(default_factory=lambda: [1, 2, 3])
    rooms: dict[str, Room] = field(default_factory=dict)
    weather: Weather | None = None
    hvac: HVACSystem | None = None
    occupants: dict[str, Occupant] = field(default_factory=dict)
    clock: SimulationClock | None = None
    events: list[BuildingEvent] = field(default_factory=list)
    metrics_history: list[dict] = field(default_factory=list)
    baseline_metrics: dict = field(default_factory=dict)
    ava_metrics: dict = field(default_factory=dict)
    simulation_profile_version: int = SIMULATION_PROFILE_VERSION
    dynamic_weather: bool = False

    def to_dict(self) -> dict:
        return {
            "floors": self.floors,
            "rooms": {k: v.to_dict() for k, v in self.rooms.items()},
            "weather": self.weather.to_dict() if self.weather else None,
            "hvac": self.hvac.to_dict() if self.hvac else None,
            "occupants": {k: v.to_dict() for k, v in self.occupants.items()},
            "clock": self.clock.to_dict() if self.clock else None,
            "events": [e.to_dict() for e in self.events],
            "metrics_history": self.metrics_history,
            "baseline_metrics": self.baseline_metrics,
            "ava_metrics": self.ava_metrics,
            "simulation_profile_version": self.simulation_profile_version,
            "dynamic_weather": self.dynamic_weather,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BuildingState:
        state = cls()
        state.floors = d.get("floors", [1, 2, 3])
        state.rooms = {k: Room.from_dict(v) for k, v in d.get("rooms", {}).items()}
        state.weather = Weather.from_dict(d["weather"]) if d.get("weather") else None
        state.hvac = HVACSystem.from_dict(d["hvac"]) if d.get("hvac") else None
        state.occupants = {k: Occupant.from_dict(v) for k, v in d.get("occupants", {}).items()}
        state.clock = SimulationClock.from_dict(d["clock"]) if d.get("clock") else None
        state.events = [BuildingEvent.from_dict(e) for e in d.get("events", [])]
        state.metrics_history = d.get("metrics_history", [])
        state.baseline_metrics = d.get("baseline_metrics", {})
        state.ava_metrics = d.get("ava_metrics", {})
        state.simulation_profile_version = int(d.get("simulation_profile_version", 0))
        state.dynamic_weather = bool(d.get("dynamic_weather", False))
        return state


def create_default_building() -> BuildingState:
    state = BuildingState()

    rooms_config = [
        {"id": "101", "floor": 1, "name": "Reception", "type": RoomType.RECEPTION, "area": 40, "volume": 120, "orientation": Orientation.NORTH, "window_area": 8, "max_occ": 4},
        {"id": "102", "floor": 1, "name": "Lobby", "type": RoomType.LOBBY, "area": 60, "volume": 180, "orientation": Orientation.EAST, "window_area": 12, "max_occ": 8},
        {"id": "103", "floor": 1, "name": "Conference Room", "type": RoomType.CONFERENCE, "area": 35, "volume": 105, "orientation": Orientation.SOUTH, "window_area": 6, "max_occ": 12},
        {"id": "104", "floor": 1, "name": "Office 101", "type": RoomType.OFFICE, "area": 20, "volume": 60, "orientation": Orientation.WEST, "window_area": 4, "max_occ": 2},
        {"id": "105", "floor": 1, "name": "Office 102", "type": RoomType.OFFICE, "area": 20, "volume": 60, "orientation": Orientation.WEST, "window_area": 4, "max_occ": 2},
        {"id": "201", "floor": 2, "name": "Office 201", "type": RoomType.OFFICE, "area": 20, "volume": 60, "orientation": Orientation.NORTH, "window_area": 4, "max_occ": 2},
        {"id": "202", "floor": 2, "name": "Office 202", "type": RoomType.OFFICE, "area": 20, "volume": 60, "orientation": Orientation.NORTH, "window_area": 4, "max_occ": 2},
        {"id": "203", "floor": 2, "name": "Meeting Room", "type": RoomType.MEETING, "area": 30, "volume": 90, "orientation": Orientation.EAST, "window_area": 5, "max_occ": 8},
        {"id": "204", "floor": 2, "name": "Open Workspace", "type": RoomType.OPEN_WORKSPACE, "area": 80, "volume": 240, "orientation": Orientation.SOUTH, "window_area": 15, "max_occ": 16},
        {"id": "205", "floor": 2, "name": "Office 205", "type": RoomType.OFFICE, "area": 20, "volume": 60, "orientation": Orientation.WEST, "window_area": 4, "max_occ": 2},
        {"id": "301", "floor": 3, "name": "Office 301", "type": RoomType.OFFICE, "area": 20, "volume": 60, "orientation": Orientation.NORTH, "window_area": 4, "max_occ": 2},
        {"id": "302", "floor": 3, "name": "Office 302", "type": RoomType.OFFICE, "area": 20, "volume": 60, "orientation": Orientation.NORTH, "window_area": 4, "max_occ": 2},
        {"id": "303", "floor": 3, "name": "Server Room", "type": RoomType.SERVER, "area": 25, "volume": 75, "orientation": Orientation.NONE, "window_area": 0, "max_occ": 1},
        {"id": "304", "floor": 3, "name": "Lounge", "type": RoomType.LOUNGE, "area": 40, "volume": 120, "orientation": Orientation.SOUTH, "window_area": 8, "max_occ": 8},
        {"id": "305", "floor": 3, "name": "Training Room", "type": RoomType.TRAINING, "area": 50, "volume": 150, "orientation": Orientation.WEST, "window_area": 10, "max_occ": 20},
    ]

    base_temp = 24.0
    for rc in rooms_config:
        # Start the demo near the comfort band so AVA can demonstrate improvement
        # instead of spending the first several simulation minutes recovering a
        # randomly overheated/overcooled building.
        temp_variation = random.uniform(-0.3, 0.3)
        room = Room(
            id=rc["id"],
            floor=rc["floor"],
            name=rc["name"],
            room_type=rc["type"],
            area=rc["area"],
            volume=rc["volume"],
            temperature=round(base_temp + temp_variation, 1),
            humidity=50.0,
            air_velocity=0.12,
            mean_radiant_temp=round(base_temp + temp_variation, 1),
            orientation=rc["orientation"],
            window_area=rc["window_area"],
            occupancy=0,
            max_occupancy=rc["max_occ"],
            hvac_state={"damper": 0.5, "valve": 0.5},
            supply_temp=22.0,
            airflow=0.5,
            fan_speed=0.5,
            thermal_load=0.0,
            pmv=0.0,
            ppd=5.0,
            comfort_status="neutral",
            energy_consumption=0.0,
            doors_open=False,
            windows_open=False,
        )
        state.rooms[rc["id"]] = room

    state.weather = Weather(
        outdoor_temp=35.0,
        humidity=50.0,
        wind_speed=5.0,
        condition=WeatherCondition.SUNNY,
        time_of_day=14.0,
        solar_intensity=800.0,
    )

    state.hvac = HVACSystem(
        mode=HVACMode.AUTO,
        total_capacity=15000.0,
        current_load=0.0,
        supply_temp=22.0,
        main_fan_speed=0.5,
        floor_capacities={1: 4000.0, 2: 5000.0, 3: 4000.0},
        zone_dampers={room_id: 0.5 for room_id in state.rooms.keys()},
        energy_consumption=0.0,
    )

    state.clock = SimulationClock(
        current_time=14.0 * 3600,
        speed_multiplier=1.0,
        is_running=True,
    )

    occupant_names = [
        ("Arun", 22.5, 0.5), ("Priya", 23.0, 0.5), ("Rahul", 22.0, 0.5),
        ("Sneha", 23.5, 0.5), ("Vikram", 22.5, 0.5), ("Anita", 23.0, 0.5),
        ("Karan", 22.0, 0.5), ("Meera", 23.5, 0.5), ("Rohit", 22.5, 0.5),
        ("Pooja", 23.0, 0.5), ("Amit", 22.5, 0.5), ("Deepa", 23.5, 0.5),
        ("Sanjay", 22.0, 0.5), ("Neha", 23.0, 0.5), ("Raj", 22.5, 0.5),
        ("Kavya", 23.0, 0.5), ("Manoj", 22.5, 0.5), ("Divya", 23.5, 0.5),
        ("Nikhil", 22.0, 0.5), ("Asha", 23.0, 0.5), ("Varun", 22.5, 0.5),
        ("Isha", 23.5, 0.5), ("Arjun", 22.5, 0.5), ("Riya", 23.0, 0.5),
        ("Aditya", 22.0, 0.5), ("Nandini", 23.5, 0.5), ("Karthik", 22.5, 0.5),
        ("Maya", 23.0, 0.5), ("Suresh", 22.5, 0.5), ("Tara", 23.5, 0.5),
        ("Dev", 22.0, 0.5), ("Ananya", 23.0, 0.5), ("Vivek", 22.5, 0.5),
        ("Shreya", 23.5, 0.5), ("Rohan", 22.5, 0.5), ("Pallavi", 23.0, 0.5),
        ("Aarav", 22.0, 0.5), ("Ira", 23.5, 0.5), ("Kabir", 22.5, 0.5),
        ("Mira", 23.0, 0.5), ("Yash", 22.5, 0.5), ("Diya", 23.5, 0.5),
    ]

    activities = [
        ("Typing", 1.1, 0.5), ("Meeting", 1.1, 0.5), ("Reading", 1.0, 0.5),
        ("Focus Work", 1.1, 0.5), ("Video Call", 1.1, 0.5), ("Presenting", 1.2, 0.5),
    ]

    occupant_idx = 0
    for room_id, room in state.rooms.items():
        # Keep every floor represented. The schedule can later scale these
        # counts up/down, but the initial state is deterministic and useful.
        if room.room_type == RoomType.SERVER:
            num_occupants = 1
        elif room.room_type == RoomType.OPEN_WORKSPACE:
            num_occupants = 8
        elif room.room_type == RoomType.TRAINING:
            num_occupants = 6
        elif room.room_type == RoomType.CONFERENCE:
            num_occupants = 6
        elif room.room_type == RoomType.MEETING:
            num_occupants = 4
        elif room.room_type in [RoomType.LOUNGE, RoomType.LOBBY]:
            num_occupants = 3
        elif room.room_type == RoomType.RECEPTION:
            num_occupants = 2
        else:
            num_occupants = min(2, room.max_occupancy)
        num_occupants = min(num_occupants, room.max_occupancy)
        room.occupancy = num_occupants
        for i in range(num_occupants):
            name, pref_temp, tolerance = occupant_names[occupant_idx % len(occupant_names)]
            activity_name, met, clo = activities[occupant_idx % len(activities)]
            occupant = Occupant(
                id=f"occ_{room_id}_{i}",
                name=name,
                room_id=room_id,
                activity=activity_name,
                metabolic_rate=met,
                clothing_insulation=clo,
                preferred_temp=pref_temp,
                comfort_tolerance=tolerance,
                current_comfort=0.0,
                active=True,
            )
            state.occupants[occupant.id] = occupant
            room.occupants_list.append(occupant.id)
            occupant_idx += 1

    return state


def load_demo_building_state() -> BuildingState:
    """Load the isolated built-in Demo Building twin.

    The demo twin intentionally lives in a different storage key from AVA's
    active/configured building so demo exploration can never mutate the
    building AVA is controlling.
    """
    payload = get_json("demo_building_state")
    if payload is not None:
        try:
            state = BuildingState.from_dict(payload)
            if any(room.temperature < 17.0 or room.temperature > 32.0 for room in state.rooms.values()):
                raise ValueError("Persisted demo state is outside safe thermal bounds")
            put_json("demo_building_state", state.to_dict())
            return state
        except (TypeError, ValueError, KeyError):
            delete_key("demo_building_state")
    state = create_default_building()
    put_json("demo_building_state", state.to_dict())
    return state

def save_demo_building_state(state: BuildingState) -> None:
    put_json("demo_building_state", state.to_dict())

def reset_demo_building_state() -> BuildingState:
    delete_key("demo_building_state")
    state = create_default_building()
    put_json("demo_building_state", state.to_dict())
    return state

def load_building_state() -> BuildingState:
    payload = get_json("building_state")
    if payload is None and BUILDING_STATE_FILE.exists():
        try:
            with open(BUILDING_STATE_FILE, encoding="utf-8") as f:
                payload = json.load(f)
            if payload.get("simulation_profile_version") != SIMULATION_PROFILE_VERSION:
                payload = None
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            payload = None
    if payload is not None:
        try:
            state = BuildingState.from_dict(payload)
            if any(room.temperature < 17.0 or room.temperature > 32.0 for room in state.rooms.values()):
                raise ValueError("Persisted building state is outside safe thermal bounds")
            put_json("building_state", state.to_dict())
            return state
        except (TypeError, ValueError, KeyError):
            delete_key("building_state")
    state = create_default_building()
    put_json("building_state", state.to_dict())
    return state

def _atomic_json_write(path: Path, payload: Any) -> None:
    """Write JSON atomically so concurrent requests never observe half a file."""
    _ensure_data_dir()
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_building_state(state: BuildingState) -> None:
    put_json("building_state", state.to_dict())

def append_building_history(entry: dict) -> None:
    entry = dict(entry)
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    storage_append_history(entry, limit=1000)

def load_building_history() -> list[dict]:
    return storage_load_history()

def reset_building_state() -> BuildingState:
    delete_key("building_state")
    storage_clear_history()
    state = create_default_building()
    put_json("building_state", state.to_dict())
    return state

