import json
import os
from datetime import datetime, timezone
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, current_app

from app.models import (
    load_state,
    save_state,
    reset_state,
    append_history,
    load_history,
    ZoneState,
)
from app.simulation.digital_twin import assess_comfort as assess_zone_comfort
from app.models_building import (
    load_building_state,
    save_building_state,
    reset_building_state,
    append_building_history,
    load_building_history,
    BuildingState,
    Room,
    Occupant,
    Weather,
    HVACSystem,
    WeatherCondition,
    HVACMode,
    EventType,
    BuildingEvent,
    SimulationClock,
    RoomType, Orientation,
    create_default_building,
    load_demo_building_state, save_demo_building_state, reset_demo_building_state,
)
from app.nlp.extractor import extract_complaint
from app.nlp.occupant_feedback import extract_occupant_feedback
from app.optimizer.hvac_optimizer import optimize_hvac
from app.optimizer.multi_zone_optimizer import optimize_hvac_multi_zone, optimize_zone_dampers
from app.ai.ava_brain import analyze_feedback, decision_trace, build_room_conflict_context
from app.hvac import HVACAdapterError, get_hvac_adapter
from app.ai.autonomous_agent import run_autonomous_cycle
from app.simulation.building_simulation import (
    step_simulation, calculate_building_metrics, run_baseline_simulation, inject_disturbance, assess_comfort, maintain_normal_comfort,
    add_occupants_to_room, remove_occupants_from_room
)
from app.simulation.digital_twin import DigitalTwin
from app.storage import get_json as storage_get_json, put_json as storage_put_json, delete_key as storage_delete_key, session_id
from app.jobs import submit as submit_job, get as get_job

main = Blueprint("main", __name__)

MAX_FEEDBACK_LENGTH = 1000

def _atomic_json_write(path: Path, payload) -> None:
    """Atomically persist small configuration/state documents."""
    SIM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    import os, tempfile
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

def _request_building_state() -> BuildingState:
    """Return the active AVA building, or the isolated Demo Building when requested by the Demo Twin UI."""
    if request.args.get("scope") == "demo":
        return load_demo_building_state()
    return load_building_state()

def _save_request_building_state(state: BuildingState) -> None:
    if request.args.get("scope") == "demo":
        save_demo_building_state(state)
    else:
        save_building_state(state)

def infer_room_from_feedback(state: BuildingState, text: str):
    """Resolve room references locally so room identification does not depend on the LLM."""
    t = text.lower()
    # Exact room IDs are the most reliable form: "room 203", "203", etc.
    import re
    for room_id, room in state.rooms.items():
        if re.search(rf"(?<!\d){re.escape(str(room_id))}(?!\d)", t):
            return room
    # Then match full/partial room names and common spoken aliases.
    for room in state.rooms.values():
        name = room.name.lower()
        aliases = {
            name,
            name.replace(" room", ""),
            name.replace(" ", ""),
            f"room {room.id}",
            f"room{room.id}",
        }
        if any(alias and alias in t for alias in aliases):
            return room

    # Match occupant names locally. This makes "Arun is cold" sufficient even
    # if the NLP model does not return the occupant/room fields.
    for occupant in state.occupants.values():
        if occupant.name.lower() in t:
            return state.rooms.get(occupant.room_id)

    # Natural-language floor/zone hints.
    floor_match = re.search(r"\bfloor\s*(\d+)\b", t)
    if floor_match:
        floor = int(floor_match.group(1))
        candidates = [room for room in state.rooms.values()
                      if room.floor == floor and room.occupancy > 0]
        if candidates:
            # For an aggregate floor request, target the room with the greatest
            # current comfort problem. The building-wide optimizer then protects
            # the rest of the occupied building.
            return max(candidates, key=lambda r: abs(float(r.pmv or 0.0)))

    # Building-wide comfort requests target the worst occupied room rather than
    # failing just because a building contains multiple rooms.
    building_wide = any(token in t for token in ("building", "everywhere", "whole building", "all floors"))
    occupied = [room for room in state.rooms.values() if room.occupancy > 0]
    if building_wide and occupied:
        return max(occupied, key=lambda r: abs(float(r.pmv or 0.0)))
    if len(occupied) == 1:
        return occupied[0]
    return None


def _quick_feedback_type(text: str) -> str:
    """Recognize unambiguous common HVAC complaints without a remote NLP round-trip."""
    t = text.lower()
    if any(k in t for k in ("too hot", "feeling hot", "feel hot", "very hot", "really hot", "burning")):
        return "too_hot"
    if any(k in t for k in ("too cold", "feeling cold", "feel cold", "very cold", "really cold", "freezing", "chilly")):
        return "too_cold"
    if any(k in t for k in ("too humid", "humidity is high", "muggy")):
        return "too_humid"
    if any(k in t for k in ("too dry", "dry air")):
        return "too_dry"
    if any(k in t for k in ("stuffy", "stale air", "no air", "poor airflow")):
        return "stuffy"
    if any(k in t for k in ("drafty", "draft", "too much airflow")):
        return "drafty"
    return ""


def run_control_response_simulation(state: BuildingState, minutes: int = 10) -> None:
    """Evaluate an HVAC action for a fixed amount of simulated time.

    This is intentionally independent of the UI's 1×/5×/10×/20× playback speed.
    AVA needs a stable evaluation window, otherwise a fast playback setting can
    make one feedback action jump through hours before the dashboard can observe it.
    """
    clock = state.clock
    if not clock:
        return
    old_running = clock.is_running
    old_speed = clock.speed_multiplier
    clock.is_running = True
    clock.speed_multiplier = 1.0
    for _ in range(max(1, int(minutes))):
        step_simulation(state, 60.0)
    clock.speed_multiplier = old_speed
    clock.is_running = old_running


SIM_DATA_DIR = Path(os.environ.get("AVA_RUNTIME_DIR", "/tmp/ava_runtime" if os.environ.get("VERCEL") else str(Path(__file__).resolve().parent.parent.parent / "data")))
SIM_STATE_FILE = SIM_DATA_DIR / "simulation_state.json"
BUILDING_PROFILE_FILE = SIM_DATA_DIR / "building_profile.json"


def get_default_building_profile():
    return {
        "name": "AVA Demo Building",
        "building_type": "Office",
        "floors": 3,
        "hvac_type": "Central AHU + VAV",
        "integration": "Digital Twin / Simulator",
        "sensors": ["temperature", "humidity", "occupancy"],
        "controls": ["setpoint", "fan_speed", "zone_damper"],
        "zones": [
            {"id": "101", "name": "Reception", "floor": 1},
            {"id": "102", "name": "Lobby", "floor": 1},
            {"id": "103", "name": "Conference Room", "floor": 1},
            {"id": "201", "name": "Office 201", "floor": 2},
            {"id": "203", "name": "Meeting Room", "floor": 2},
            {"id": "204", "name": "Open Workspace", "floor": 2},
            {"id": "301", "name": "Office 301", "floor": 3},
            {"id": "303", "name": "Server Room", "floor": 3},
        ],
    }


PROFILE_SENSORS = {"temperature", "humidity", "occupancy", "air_quality", "co2", "energy"}
PROFILE_CONTROLS = {"setpoint", "fan_speed", "zone_damper", "mode", "power"}


def normalize_building_profile(profile):
    base = get_default_building_profile()
    if isinstance(profile, dict):
        base.update(profile)
    base["floors"] = max(1, int(base.get("floors", 1) or 1))
    try:
        base["occupancy_target"] = max(0, int(base.get("occupancy_target", 30) or 0))
    except (TypeError, ValueError):
        base["occupancy_target"] = 30
    base["sensors"] = [str(x).strip().lower() for x in base.get("sensors", []) if str(x).strip()]
    base["controls"] = [str(x).strip().lower() for x in base.get("controls", []) if str(x).strip()]
    zones = []
    for z in base.get("zones", []):
        if not isinstance(z, dict):
            continue
        zid = str(z.get("id", "")).strip()
        name = str(z.get("name", "")).strip()
        try:
            floor = max(1, int(z.get("floor", 1)))
        except (TypeError, ValueError):
            floor = 1
        if zid and name:
            zones.append({"id": zid, "name": name, "floor": floor})
    base["zones"] = zones
    return base


def load_building_profile():
    payload = storage_get_json("building_profile")
    if payload is not None:
        try:
            return normalize_building_profile(payload)
        except (TypeError, ValueError):
            storage_delete_key("building_profile")
    profile = get_default_building_profile()
    save_building_profile(profile)
    return profile

def save_building_profile(profile):
    storage_put_json("building_profile", normalize_building_profile(profile))


CUSTOM_STATE_FILE = SIM_DATA_DIR / "custom_building_state.json"
CUSTOM_STATE_KEY = "custom_building_state"

def _active_state_from_profile(profile):
    """Build the canonical AVA-controlled Digital Twin from the saved profile.

    The existing simulation engine is reused unchanged; only the building
    topology, room metadata and starting population are generated here.
    """
    profile = normalize_building_profile(profile)
    template = create_default_building()
    floors = list(range(1, profile.get("floors", 1) + 1))
    zones = profile.get("zones", []) or [{"id": f"{f}01", "name": f"Floor {f} Zone", "floor": f} for f in floors]

    type_map = {
        "reception": RoomType.RECEPTION, "lobby": RoomType.LOBBY,
        "conference": RoomType.CONFERENCE, "meeting": RoomType.MEETING,
        "office": RoomType.OFFICE, "server": RoomType.SERVER,
        "workspace": RoomType.OPEN_WORKSPACE, "open": RoomType.OPEN_WORKSPACE,
        "training": RoomType.TRAINING, "lounge": RoomType.LOUNGE,
    }
    orientation_cycle = [Orientation.NORTH, Orientation.EAST, Orientation.SOUTH, Orientation.WEST]

    def room_type(name):
        text = str(name).lower()
        for key, value in type_map.items():
            if key in text:
                return value
        return RoomType.OFFICE

    def capacity(name):
        text = str(name).lower()
        if any(k in text for k in ("server", "it room", "electrical")): return 2
        if any(k in text for k in ("conference", "training")): return 12
        if any(k in text for k in ("meeting", "board")): return 8
        if any(k in text for k in ("lobby", "reception")): return 10
        if any(k in text for k in ("open", "workspace", "work space")): return 16
        if any(k in text for k in ("office", "cabin")): return 3
        return 6

    # Start from the stable simulation defaults, then replace only topology.
    state = BuildingState()
    state.floors = floors
    state.weather = template.weather
    state.hvac = template.hvac
    state.clock = template.clock
    state.simulation_profile_version = template.simulation_profile_version
    # The configurable twin gets a gentle autonomous weather stream. The fixed
    # Demo Building remains unchanged because its flag stays False.
    state.dynamic_weather = True
    state.rooms = {}
    state.occupants = {}
    state.events = []
    state.metrics_history = []
    state.baseline_metrics = {}
    state.ava_metrics = {}

    for idx, z in enumerate(zones):
        try: floor = max(1, int(z.get("floor", 1)))
        except (TypeError, ValueError): floor = 1
        if floor > profile["floors"]: continue
        rid = str(z.get("id", "")).strip()
        name = str(z.get("name", rid)).strip()
        if not rid or not name or rid in state.rooms: continue
        rtype = room_type(name)
        cap = capacity(name)
        temp = round(23.5 + ((idx % 3) - 1) * 0.4, 1)
        state.rooms[rid] = Room(
            id=rid, floor=floor, name=name, room_type=rtype, area=30.0, volume=90.0,
            temperature=temp, humidity=50.0, air_velocity=0.12, mean_radiant_temp=temp,
            orientation=orientation_cycle[idx % len(orientation_cycle)], window_area=6.0,
            occupancy=0, max_occupancy=cap, hvac_state={"damper": 0.5, "valve": 0.5},
            supply_temp=22.0, airflow=0.5, fan_speed=0.5, thermal_load=0.0,
            pmv=0.0, ppd=5.0, comfort_status="neutral", energy_consumption=0.0,
        )

    state.hvac.floor_capacities = {f: 5000.0 for f in floors}
    state.hvac.total_capacity = max(10000.0, 5000.0 * len(floors))
    state.hvac.zone_dampers = {rid: 0.5 for rid in state.rooms}
    state.hvac.mode = HVACMode.AUTO
    state.hvac.supply_temp = 22.0
    state.hvac.main_fan_speed = 0.5

    requested = max(0, int(profile.get("occupancy_target", 30)))
    rooms = list(state.rooms.values())
    total_capacity = sum(r.max_occupancy for r in rooms)
    remaining = min(requested, total_capacity)
    names = [("Arun",22.5),("Priya",23.0),("Rahul",22.0),("Sneha",23.5),("Vikram",22.5),("Meera",23.0),("Karan",22.0),("Anita",23.5)]
    for idx, room in enumerate(rooms):
        count = min(room.max_occupancy, round(requested * room.max_occupancy / total_capacity)) if total_capacity else 0
        if idx == len(rooms)-1: count = remaining
        count = min(count, remaining)
        room.occupancy = count
        for i in range(count):
            name_i, pref = names[(idx + i) % len(names)]
            oid = f"occ_{room.id}_{i}"
            occ = Occupant(id=oid, name=name_i, room_id=room.id, activity="Focus Work",
                           metabolic_rate=1.1, clothing_insulation=0.5, preferred_temp=pref,
                           comfort_tolerance=0.5, current_comfort=0.0, active=True)
            state.occupants[oid] = occ
            room.occupants_list.append(oid)
        remaining -= count

    return state

def _custom_state_from_profile(profile):
    """Create a lightweight profile-driven twin. The 3-floor demo stays untouched."""
    profile = normalize_building_profile(profile)
    zones = profile.get("zones", [])
    floors = list(range(1, profile.get("floors", 1) + 1))
    if not zones:
        zones = [{"id": f"{floor}01", "name": f"Floor {floor} Zone", "floor": floor} for floor in floors]
    # Keep only configured floors and make sure each floor has a visible zone.
    normalized = []
    seen = set()
    for z in zones:
        try:
            floor = max(1, int(z.get("floor", 1)))
        except (TypeError, ValueError):
            floor = 1
        if floor > profile["floors"]:
            continue
        zid = str(z.get("id", "")).strip()
        if not zid or zid in seen:
            continue
        seen.add(zid)
        normalized.append({"id": zid, "name": str(z.get("name", zid)).strip() or zid, "floor": floor})
    for floor in floors:
        if not any(z["floor"] == floor for z in normalized):
            zid = f"{floor}01"
            while zid in seen:
                zid = f"{floor}{len(seen)+1:02d}"
            normalized.append({"id": zid, "name": f"Floor {floor} Zone", "floor": floor})
            seen.add(zid)
    def estimate_capacity(name):
        text = str(name).lower()
        if any(k in text for k in ("server", "it room", "electrical")):
            return 2
        if any(k in text for k in ("conference", "training")):
            return 12
        if any(k in text for k in ("meeting", "board")):
            return 8
        if any(k in text for k in ("lobby", "reception")):
            return 10
        if any(k in text for k in ("open", "workspace", "work space")):
            return 16
        if any(k in text for k in ("office", "cabin")):
            return 3
        return 6

    rooms = []
    capacities = [estimate_capacity(z["name"]) for z in normalized]
    requested_people = int(profile.get("occupancy_target", 30))
    total_capacity = sum(capacities)
    remaining = min(requested_people, total_capacity)
    # Distribute the user-selected building population across configured rooms
    # proportionally to room capacity. This is a starting allocation, not a
    # claim that these people were measured by a sensor.
    allocated = []
    for i, capacity in enumerate(capacities):
        if i == len(capacities) - 1:
            count = remaining
        else:
            count = min(capacity, round(requested_people * capacity / total_capacity)) if total_capacity else 0
            count = min(count, remaining)
        allocated.append(count)
        remaining -= count
    # If rounding left people unallocated, fill rooms with remaining capacity.
    for i, capacity in enumerate(capacities):
        if remaining <= 0: break
        extra = min(capacity - allocated[i], remaining)
        allocated[i] += extra
        remaining -= extra
    for idx, (z, capacity, occupancy) in enumerate(zip(normalized, capacities, allocated)):
        rooms.append({
            "id": z["id"], "name": z["name"], "floor": z["floor"],
            "temperature": 23.0 + ((idx % 3) - 1) * 0.4,
            "humidity": 50.0, "occupancy": occupancy, "max_occupancy": capacity,
            "occupancy_source": "initial allocation from building population",
            "setpoint": 23.0, "fan_speed": 0.5, "comfort": "Comfortable"
        })
    return {
        "profile": profile, "floors": floors, "rooms": rooms,
        "weather": {"outdoor_temp": 35.0, "condition": "sunny"},
        "last_action": "Custom twin initialized from Building Setup"
    }

def load_custom_building_state():
    profile = load_building_profile()
    expected = _custom_state_from_profile(profile)
    saved = storage_get_json(CUSTOM_STATE_KEY)
    if saved is not None:
        try:
            if saved.get("profile", {}).get("floors") == profile.get("floors") and saved.get("profile", {}).get("zones") == profile.get("zones"):
                return saved
        except AttributeError:
            pass
    save_custom_building_state(expected)
    return expected

def save_custom_building_state(state):
    storage_put_json(CUSTOM_STATE_KEY, state)

def reset_custom_building_state():
    state = _custom_state_from_profile(load_building_profile())
    save_custom_building_state(state)
    return state


def check_building_capabilities(profile, request_kind, requested_sensors=None):
    """Return a user-friendly capability check before AVA reads or controls anything."""
    sensors = set(profile.get("sensors", []))
    controls = set(profile.get("controls", []))
    integration = str(profile.get("integration", "")).lower()
    issues = []
    if requested_sensors:
        missing = sorted(set(requested_sensors) - sensors)
        if missing:
            issues.append(f"Unavailable building data: {', '.join(missing)}")
    if request_kind == "control":
        if integration in {"manual / read-only", "read-only"}:
            issues.append("This building is configured as read-only")
        if not controls.intersection({"setpoint", "fan_speed", "zone_damper", "mode", "power"}):
            issues.append("No controllable HVAC actions are configured")
    return {"allowed": not issues, "issues": issues, "sensors": sorted(sensors), "controls": sorted(controls), "integration": profile.get("integration")}


def load_sim_state():
    SIM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SIM_STATE_FILE.exists():
        with open(SIM_STATE_FILE) as f:
            return json.load(f)
    return get_default_sim_state()


def save_sim_state(state):
    SIM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(SIM_STATE_FILE, state)


def get_default_sim_state():
    return {
        "outdoor_temp": 35,
        "zones": {
            "A": {"name": "Zone A (Open Plan)", "temperature": 24.0, "setpoint": 22.0, "fan_speed": 0.5, "occupants": 12, "humidity": 50.0, "mean_radiant_temp": 24.0, "air_velocity": 0.3},
            "B": {"name": "Zone B (Meeting Rooms)", "temperature": 22.0, "setpoint": 21.0, "fan_speed": 0.6, "occupants": 8, "humidity": 50.0, "mean_radiant_temp": 22.0, "air_velocity": 0.34},
            "C": {"name": "Zone C (Private Offices)", "temperature": 23.0, "setpoint": 22.0, "fan_speed": 0.4, "occupants": 6, "humidity": 50.0, "mean_radiant_temp": 23.0, "air_velocity": 0.26}
        }
    }


@main.route("/")
def index():
    """Public AVA homepage; keeps the product entry points together."""
    return render_template("landing.html")


@main.route("/assistant")
def assistant():
    """Natural-language AVA building assistant dashboard."""
    return render_template("index.html")


@main.route("/api/dashboard")
def dashboard_state():
    state = _request_building_state()
    metrics = calculate_building_metrics(state)
    profile = load_building_profile()
    recent = load_building_history()[-8:]
    return jsonify({
        "profile": profile,
        "building": state.to_dict(),
        "metrics": metrics,
        "recent": recent,
        "simulation": {"available": True, "route": url_for("main.building")},
    })


@main.route("/custom-building")
def custom_building():
    return render_template("custom_building.html", profile=load_building_profile())


@main.route("/api/custom-building")
def custom_building_state():
    state = load_building_state()
    return jsonify({"profile": load_building_profile(), "state": state.to_dict(), "metrics": calculate_building_metrics(state)})


@main.route("/api/custom-building/reset", methods=["POST"])
def custom_building_reset():
    state = _active_state_from_profile(load_building_profile())
    save_building_state(state)
    return jsonify({"profile": load_building_profile(), "state": state.to_dict(), "metrics": calculate_building_metrics(state)})


@main.route("/api/custom-building/tick", methods=["POST"])
def custom_building_tick():
    state = load_building_state()
    old_weather = state.weather.condition if state.weather else None
    old_target = state.weather.dynamic_target if state.weather else None
    step_simulation(state, 60.0)
    new_weather = state.weather.condition if state.weather else None
    new_target = state.weather.dynamic_target if state.weather else None
    if old_target is None and new_target is not None and old_weather is not None:
        # Record the moment the autonomous environment selects a new scenario,
        # so the Assistant activity feed visibly explains why the building may
        # begin drifting before the transition completes.
        target_name = new_target.value.replace('_', ' ').title()
        state.events.append(BuildingEvent(
            id=str(uuid.uuid4())[:8], timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=EventType.WEATHER_CHANGE, description=f"Weather shifting: {old_weather.value.replace('_', ' ').title()} → {target_name}",
            affected_rooms=[], severity="info",
            data={"from": old_weather.value, "to": new_target.value, "source": "autonomous weather simulation"},
        ))
        append_building_history({"type":"weather_change", "description":f"Weather shifting from {old_weather.value} to {new_target.value}", "weather_before":old_weather.value, "weather_after":new_target.value})
    elif old_weather is not None and new_weather is not None and old_weather != new_weather and old_target is not None:
        # Completion marker for the actual condition switch.
        state.events.append(BuildingEvent(
            id=str(uuid.uuid4())[:8], timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=EventType.WEATHER_CHANGE, description=f"Weather changed: {old_weather.value.replace('_', ' ').title()} → {new_weather.value.replace('_', ' ').title()}",
            affected_rooms=[], severity="info",
            data={"old_weather": old_weather.value, "new_weather": new_weather.value, "source": "autonomous weather simulation"},
        ))
    save_building_state(state)
    return jsonify({"profile": load_building_profile(), "state": state.to_dict(), "metrics": calculate_building_metrics(state)})


@main.route("/api/building-profile", methods=["GET", "POST"])
def building_profile():
    if request.method == "GET":
        return jsonify(load_building_profile())
    data = request.get_json() or {}
    profile = load_building_profile()
    for key in ("name", "building_type", "hvac_type", "integration"):
        if key in data and str(data[key]).strip():
            profile[key] = str(data[key]).strip()
    if "floors" in data:
        try:
            profile["floors"] = max(1, int(data["floors"]))
        except (TypeError, ValueError):
            return jsonify({"error": "Floors must be a positive integer"}), 400
    if "occupancy_target" in data:
        try:
            profile["occupancy_target"] = max(0, int(data["occupancy_target"]))
        except (TypeError, ValueError):
            return jsonify({"error": "People in building must be a non-negative integer"}), 400
    for key in ("sensors", "controls"):
        if key in data and isinstance(data[key], list):
            profile[key] = [str(x).strip().lower() for x in data[key] if str(x).strip()]
    if "zones" in data:
        if not isinstance(data["zones"], list):
            return jsonify({"error": "Zones must be a list"}), 400
        profile["zones"] = data["zones"]
    profile = normalize_building_profile(profile)
    unknown_sensors = sorted(set(profile["sensors"]) - PROFILE_SENSORS)
    unknown_controls = sorted(set(profile["controls"]) - PROFILE_CONTROLS)
    if unknown_sensors or unknown_controls:
        return jsonify({"error": "Unsupported capability", "unknown_sensors": unknown_sensors, "unknown_controls": unknown_controls}), 400
    save_building_profile(profile)
    # Regenerate AVA's canonical active twin from the profile. The isolated
    # Demo Building is stored separately and is never touched here.
    active_state = _active_state_from_profile(profile)
    save_building_state(active_state)
    return jsonify({"profile": profile, "capabilities": check_building_capabilities(profile, "control"), "custom_twin": active_state.to_dict()})


@main.route("/api/building-capabilities")
def building_capabilities():
    profile = load_building_profile()
    return jsonify({
        "profile": profile,
        "capabilities": check_building_capabilities(profile, "control"),
        "available_sensors": sorted(PROFILE_SENSORS),
        "available_controls": sorted(PROFILE_CONTROLS),
    })


@main.route("/api/dashboard/message", methods=["POST"])
def dashboard_message():
    data = request.get_json() or {}
    text = str(data.get("message", "")).strip()
    if not text:
        return jsonify({"error": "Please enter a message."}), 400
    if len(text) > MAX_FEEDBACK_LENGTH:
        return jsonify({"error": f"Message too long (max {MAX_FEEDBACK_LENGTH} characters)"}), 400

    state = _request_building_state()
    metrics = calculate_building_metrics(state)
    lower = text.lower()

    # Informational requests are answered directly from live building data;
    # control requests continue through the existing AVA/Nemotron pipeline.
    informational = any(k in lower for k in (
        "what is", "what's", "whats", "how is", "status", "temperature",
        "humidity", "occupancy", "comfortable", "comfort level", "hvac status",
        "how many people", "energy"
    )) and not any(k in lower for k in ("too hot", "too cold", "feeling hot", "feeling cold", "adjust", "change", "make ", "increase", "decrease", "lower", "raise", "cool ", "warm "))

    profile = load_building_profile()
    if informational:
        room = infer_room_from_feedback(state, text)
        requested_sensors = []
        if "humidity" in lower: requested_sensors.append("humidity")
        if "occupancy" in lower or "people" in lower: requested_sensors.append("occupancy")
        if "energy" in lower: requested_sensors.append("energy")
        capability = check_building_capabilities(profile, "information", requested_sensors)
        if not capability["allowed"]:
            return jsonify({"type": "information", "reply": "I can’t provide that detail because this building does not report " + ", ".join(sorted(set(requested_sensors) - set(profile.get("sensors", [])))) + ".", "capability_check": capability, "profile": profile}), 200
        sensors = set(profile.get("sensors", []))
        if room:
            parts = [f"{room.name} is {room.temperature:.1f}°C"] if "temperature" in sensors else []
            if "humidity" in sensors:
                parts.append(f"humidity is {room.humidity:.0f}%")
            if "occupancy" in sensors:
                parts.append(f"there are {room.occupancy} occupants")
            if "air_quality" in sensors:
                parts.append("air quality data is available")
            if "co2" in sensors:
                parts.append("CO₂ data is available")
            if "energy" in sensors:
                parts.append(f"energy use is {room.energy_consumption:.0f} W")
            reply = ". ".join(parts) + "." if parts else "This building does not report the requested room data."
        else:
            parts = []
            if "temperature" in sensors:
                parts.append(f"average temperature is {metrics.get('avg_temperature', 0):.1f}°C")
            if "occupancy" in sensors:
                parts.append(f"there are {metrics.get('total_occupants', 0)} occupants")
            if "energy" in sensors:
                parts.append(f"HVAC load is {metrics.get('hvac_load', 0):.0f} W")
            if "temperature" in sensors and "occupancy" in sensors:
                parts.insert(0, f"building comfort is {metrics.get('comfort_percentage', 0):.0f}%")
            reply = "The building " + ", ".join(parts) + "." if parts else "This building does not report the requested live data."
        return jsonify({"type": "information", "reply": reply, "metrics": metrics, "profile": profile, "capability_check": capability})

    # Never let AVA assume a control exists just because the simulator supports it.
    capability = check_building_capabilities(profile, "control")
    if not capability["allowed"]:
        return jsonify({
            "type": "information",
            "reply": "I understand the request, but I can’t change the HVAC because " + "; ".join(capability["issues"]) + ".",
            "capability_check": capability,
            "profile": profile,
        }), 200

    quick_type = _quick_feedback_type(text)
    response = _handle_occupant_feedback({"feedback": text, "feedback_type": quick_type})
    return response


@main.route("/simulation")
def simulation():
    sim_state = load_sim_state()
    return render_template("simulation.html", state=sim_state)


@main.route("/building")
def building():
    return render_template("building.html")


@main.route("/api/building")
def get_building():
    state = _request_building_state()
    return jsonify(state.to_dict())


@main.route("/api/floors")
def get_floors():
    state = _request_building_state()
    floors = {}
    for floor_num in state.floors:
        floor_rooms = {rid: room.to_dict() for rid, room in state.rooms.items() if room.floor == floor_num}
        floors[floor_num] = floor_rooms
    return jsonify(floors)


@main.route("/api/rooms/<room_id>")
def get_room(room_id: str):
    state = _request_building_state()
    room = state.rooms.get(room_id)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    occupants = [state.occupants[oid].to_dict() for oid in room.occupants_list if oid in state.occupants]
    return jsonify({
        "room": room.to_dict(),
        "occupants": occupants,
    })


@main.route("/api/occupants/<occupant_id>")
def get_occupant(occupant_id: str):
    state = _request_building_state()
    occupant = state.occupants.get(occupant_id)
    if not occupant:
        return jsonify({"error": "Occupant not found"}), 404

    room = state.rooms.get(occupant.room_id)
    comfort = None
    if room:
        comfort = assess_comfort(room, occupant).to_dict()

    return jsonify({
        "occupant": occupant.to_dict(),
        "room": room.to_dict() if room else None,
        "comfort": comfort,
    })


@main.route("/api/ava/analyze", methods=["POST"])
def analyze_ava():
    """Run AVA's Phase 3 reasoning without mutating building state."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    text = data.get("feedback", "").strip()
    occupant_id = data.get("occupant_id", "").strip()
    feedback_type = str(data.get("feedback_type", "")).strip().lower()
    if not text:
        return jsonify({"error": "No feedback text provided"}), 400
    if len(text) > MAX_FEEDBACK_LENGTH:
        return jsonify({"error": f"Feedback too long (max {MAX_FEEDBACK_LENGTH} characters)"}), 400

    state = _request_building_state()
    clock_before_running = bool(state.clock and state.clock.is_running)
    nlp_result = extract_occupant_feedback(text)
    target_occupant = state.occupants.get(occupant_id) if occupant_id else None

    # Resolve an occupant named in natural language before resolving the room.
    if not target_occupant:
        lower_text = text.lower()
        target_occupant = next(
            (o for o in state.occupants.values()
             if o.active and o.name.lower() in lower_text),
            None,
        )

    target_room = state.rooms.get(target_occupant.room_id) if target_occupant else None
    if not target_room and nlp_result.room_id:
        target_room = state.rooms.get(nlp_result.room_id)
    if not target_room and nlp_result.room_name:
        target_room = next((r for r in state.rooms.values() if nlp_result.room_name.lower() in r.name.lower()), None)
    if not target_room:
        target_room = infer_room_from_feedback(state, text)
    if not target_room:
        return jsonify({"error": "Could not identify the room from feedback", "nlp": nlp_result.to_dict()}), 422
    if not target_occupant and target_room.occupants_list:
        target_occupant = state.occupants.get(target_room.occupants_list[0])

    feedback_payload = nlp_result.to_dict()
    decision = analyze_feedback(state, target_room, target_occupant, feedback_payload)
    comfort = assess_comfort(target_room, target_occupant).to_dict() if target_occupant else None
    trace = decision_trace(state, target_room, target_occupant, feedback_payload, decision)
    return jsonify({
        "nlp": feedback_payload,
        "decision": decision.to_dict(),
        "comfort": comfort,
        "conflict": build_room_conflict_context(state, target_room, target_occupant),
        "trace": trace,
        "room": target_room.to_dict(),
        "occupant": target_occupant.to_dict() if target_occupant else None,
        "mutated": False,
    })


@main.route("/api/occupant-feedback", methods=["POST"])
def handle_occupant_feedback():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    # Vercel functions do not provide a durable process for in-memory background jobs.
    # Execute this operation in the request when hosted on Vercel so the result is reliable.
    if os.environ.get("VERCEL"):
        return _handle_occupant_feedback(data)
    job_id = submit_job(lambda: _handle_occupant_feedback(data), session_id=session_id(), app=current_app._get_current_object())
    return jsonify({"status": "queued", "job_id": job_id, "poll": f"/api/jobs/{job_id}"}), 202

@main.route("/api/jobs/<job_id>")
def job_status(job_id):
    job = get_job(job_id, session_id=session_id())
    if not job:
        return jsonify({"error": "Job not found or expired"}), 404
    if job.get("status") in {"queued", "running"}:
        return jsonify({"status": job["status"], "job_id": job_id}), 202
    if job.get("status") == "error":
        return jsonify({"status": "error", "job_id": job_id, "error": job.get("error", "Background job failed")}), 500
    return jsonify({"status": "complete", "job_id": job_id, "result": job.get("result")}), 200


def _handle_occupant_feedback(data):
    text = data.get("feedback", "").strip()
    occupant_id = data.get("occupant_id", "").strip()
    feedback_type = str(data.get("feedback_type", "")).strip().lower()
    if not text:
        return jsonify({"error": "No feedback text provided"}), 400
    if len(text) > MAX_FEEDBACK_LENGTH:
        return jsonify({"error": f"Feedback too long (max {MAX_FEEDBACK_LENGTH} characters)"}), 400

    state = _request_building_state()
    profile = load_building_profile()
    capability = check_building_capabilities(profile, "control")
    if not capability["allowed"]:
        return jsonify({
            "type": "information",
            "reply": "I understand the request, but I can’t change the HVAC because " + "; ".join(capability["issues"]) + ".",
            "capability_check": capability,
            "profile": profile,
        }), 200
    clock_before_running = bool(state.clock and state.clock.is_running)
    nlp_result = extract_occupant_feedback(text)

    # Quick-feedback buttons already provide an unambiguous intent. Do not
    # make a successful button click depend on a remote NLP confidence score.
    # Natural-language text still goes through Nemotron/local parsing.
    quick_types = {
        "too_hot", "too_cold", "too_humid", "too_dry",
        "stuffy", "drafty", "comfortable",
    }
    if feedback_type in quick_types:
        from app.nlp.occupant_feedback import OccupantFeedbackResult
        nlp_result = OccupantFeedbackResult(
            occupant_name=nlp_result.occupant_name,
            room_id=nlp_result.room_id,
            room_name=nlp_result.room_name,
            discomfort_type=feedback_type,
            severity=nlp_result.severity if nlp_result.confidence >= 0.3 else "medium",
            desired_temperature=nlp_result.desired_temperature,
            humidity_concern=feedback_type in {"too_humid", "too_dry"},
            airflow_concern=feedback_type in {"stuffy", "drafty"},
            urgency=nlp_result.urgency if nlp_result.confidence >= 0.3 else "normal",
            confidence=max(nlp_result.confidence, 0.95),
            raw_text=text,
        )
    elif nlp_result.confidence < 0.3:
        return jsonify({
            "error": "Could not parse the feedback. Try a phrase like 'I feel cold', 'I feel hot', or use a quick-feedback button.",
            "nlp": nlp_result.to_dict(),
        }), 422

    target_occupant = state.occupants.get(occupant_id) if occupant_id else None

    # Resolve an occupant named in natural language before resolving the room.
    if not target_occupant:
        lower_text = text.lower()
        target_occupant = next(
            (o for o in state.occupants.values()
             if o.active and o.name.lower() in lower_text),
            None,
        )

    target_room = state.rooms.get(target_occupant.room_id) if target_occupant else None
    if not target_room and nlp_result.room_id:
        target_room = state.rooms.get(nlp_result.room_id)
    if not target_room and nlp_result.room_name:
        target_room = next((r for r in state.rooms.values() if nlp_result.room_name.lower() in r.name.lower()), None)
    if not target_room:
        target_room = infer_room_from_feedback(state, text)
    if not target_room:
        return jsonify({"error": "Could not identify the room from feedback", "nlp": nlp_result.to_dict()}), 422
    if not target_occupant and target_room.occupants_list:
        target_occupant = state.occupants.get(target_room.occupants_list[0])

    comfort_before = assess_comfort(target_room, target_occupant).to_dict() if target_occupant else assess_comfort(target_room, None).to_dict()
    building_comfort_before = calculate_building_metrics(state).get("comfort_percentage", 0)
    room_temperature_before = target_room.temperature
    controls_before = {
        "supply_temp": state.hvac.supply_temp,
        "fan_speed": state.hvac.main_fan_speed,
        "damper": float(state.hvac.zone_dampers.get(target_room.id, target_room.hvac_state.get("damper", 0.5))),
    }
    decision = analyze_feedback(state, target_room, target_occupant, nlp_result.to_dict())
    try:
        adapter = get_hvac_adapter(state, profile)
        control = adapter.apply_decision(target_room, decision)
    except HVACAdapterError as exc:
        return jsonify({
            "type": "information",
            "reply": f"I understood the request, but I did not change the HVAC: {exc}.",
            "decision": decision.to_dict(),
            "capability_check": capability,
            "profile": profile,
            "adapter_error": str(exc),
        }), 200

    # Interactive AVA requests use the AI decision directly. A full building-wide
    # optimizer is still available for the Digital Twin, but running a global
    # candidate search on every chat message makes the public assistant feel slow.
    # The AI decision is already bounded and applied through the HVAC adapter; the
    # verification loop below measures the real simulated response and performs
    # one small local correction only if needed.
    controls = set(profile.get("controls", []))
    if "setpoint" in controls:
        state.hvac.supply_temp = max(19.0, min(23.5, state.hvac.supply_temp))
    if "fan_speed" in controls:
        state.hvac.main_fan_speed = max(0.25, min(1.0, state.hvac.main_fan_speed))
    target_room.supply_temp = state.hvac.supply_temp
    target_room.fan_speed = state.hvac.main_fan_speed
    if "zone_damper" in controls:
        damper = float(state.hvac.zone_dampers.get(target_room.id, target_room.hvac_state.get("damper", 0.5)))
        state.hvac.zone_dampers[target_room.id] = max(0.25, min(1.0, damper))
        target_room.hvac_state["damper"] = state.hvac.zone_dampers[target_room.id]
    target_room.airflow = target_room.fan_speed * state.hvac.zone_dampers.get(target_room.id, 0.5)

    # Closed-loop verification is intentionally bounded. The expensive optimizer
    # runs once; physical response is then simulated for a short deterministic
    # window. If the reporting occupant is still outside the comfort band, AVA
    # applies one small targeted correction instead of launching more full
    # building-wide optimizations. This keeps the assistant responsive while still
    # verifying that its action had a real effect in the Digital Twin.
    clock = state.clock
    if clock:
        old_running, old_speed = clock.is_running, clock.speed_multiplier
        clock.is_running, clock.speed_multiplier = True, 1.0
        # Let the existing normal controller participate immediately without
        # changing the stable Phase 17 simulation engine itself.
        maintain_normal_comfort(state)
        for _ in range(4):
            step_simulation(state, 60.0)
        live = assess_comfort(target_room, target_occupant).pmv if target_occupant else target_room.pmv
        if abs(live) > 0.50:
            # One bounded local correction, based on the measured post-action PMV.
            # Positive PMV => cool; negative PMV => warm.
            direction = -1.0 if live > 0 else 1.0
            if "setpoint" in controls:
                state.hvac.supply_temp = max(19.0, min(23.5, state.hvac.supply_temp + 0.5 * direction))
            if "fan_speed" in controls:
                fan_delta = 0.05 if live > 0 else -0.05
                state.hvac.main_fan_speed = max(0.25, min(1.0, state.hvac.main_fan_speed + fan_delta))
            if "zone_damper" in controls:
                current_damper = float(state.hvac.zone_dampers.get(target_room.id, target_room.hvac_state.get("damper", 0.5)))
                damper_delta = 0.08 if live > 0 else -0.08
                new_damper = max(0.25, min(1.0, current_damper + damper_delta))
                state.hvac.zone_dampers[target_room.id] = new_damper
                target_room.hvac_state["damper"] = new_damper
            target_room.supply_temp = state.hvac.supply_temp
            target_room.fan_speed = state.hvac.main_fan_speed
            target_room.airflow = target_room.fan_speed * state.hvac.zone_dampers.get(target_room.id, 0.5)
            for _ in range(3):
                step_simulation(state, 60.0)
        clock.speed_multiplier = old_speed
        clock.is_running = old_running

    comfort_after = assess_comfort(target_room, target_occupant).to_dict() if target_occupant else assess_comfort(target_room, None).to_dict()

    if target_occupant:
        target_occupant.feedback = text
        target_occupant.current_comfort = comfort_after.get("pmv", target_occupant.current_comfort)

    event = BuildingEvent(
        id=str(hash(f"{text}:{datetime.now(timezone.utc).isoformat()}"))[:8],
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=EventType.HVAC_FAULT if state.hvac.mode == HVACMode.FAILURE else EventType.OCCUPANCY_SURGE,
        description=f"AVA: {decision.intent.replace('_', ' ')} — {text[:70]}",
        affected_rooms=[target_room.id],
        severity=decision.priority,
        data={"feedback": text, "nlp": nlp_result.to_dict(), "decision": decision.to_dict(), "control": control, "integration": profile.get("integration")},
    )
    state.events.append(event)
    _save_request_building_state(state)

    audit = {
        "type": "ava_decision",
        "feedback": text,
        "nlp": nlp_result.to_dict(),
        "decision": decision.to_dict(),
        "control": control,
        "comfort_before": comfort_before,
        "comfort_after": comfort_after,
        "building_comfort_before": building_comfort_before,
        "room_temperature_before": room_temperature_before,
        "controls_before": controls_before,
        "room_id": target_room.id,
        "occupant_id": target_occupant.id if target_occupant else None,
        "trace": decision_trace(state, target_room, target_occupant, nlp_result.to_dict(), decision),
    }
    append_building_history(audit)

    metrics_after = calculate_building_metrics(state)
    optimization = {
        "supply_temp": state.hvac.supply_temp,
        "fan_speed": state.hvac.main_fan_speed,
        "zone_results": [{
            "room_id": target_room.id,
            "supply_temp": target_room.supply_temp,
            "fan_speed": target_room.fan_speed,
            "damper": state.hvac.zone_dampers.get(target_room.id, 0.5),
            "pmv_after": comfort_after.get("pmv", target_room.pmv),
            "energy_cost": target_room.energy_consumption,
            "comfort_improvement": abs(comfort_before.get("pmv", 0)) - abs(comfort_after.get("pmv", 0)),
        }],
        "total_energy": state.hvac.energy_consumption,
        "adapter": control.get("adapter", profile.get("integration")),
        "avg_pmv_after": comfort_after.get("pmv", target_room.pmv),
        "comfort_percentage_after": metrics_after["comfort_percentage"],
        "comfortable_occupants_after": metrics_after["comfortable_occupants"],
        "success": True,
        "message": "AVA decision applied and evaluated by the building simulation",
        "explanation": f"{decision.reason} Tradeoff: {decision.tradeoff}",
    }

    return jsonify({
        "nlp": nlp_result.to_dict(),
        "clock_before_running": clock_before_running,
        "decision": decision.to_dict(),
        "control": control,
        "comfort_before": comfort_before,
        "comfort_after": comfort_after,
        "building_comfort_before": building_comfort_before,
        "room_temperature_before": room_temperature_before,
        "controls_before": controls_before,
        "optimization": optimization,
        "room": target_room.to_dict(),
        "occupant": target_occupant.to_dict() if target_occupant else None,
        "audit": audit,
        "trace": audit["trace"],
        "conflict": build_room_conflict_context(state, target_room, target_occupant),
    })


@main.route("/api/hvac/integration")
def hvac_integration():
    """Report the selected HVAC adapter and fail-closed connection status."""
    profile = load_building_profile()
    state = _request_building_state()
    try:
        adapter = get_hvac_adapter(state, profile)
        caps = adapter.capabilities()
        return jsonify({"connected": True, "adapter": type(adapter).__name__,
                        "integration": caps.integration, "read_only": caps.read_only,
                        "controls": list(caps.controls), "sensors": list(caps.sensors)})
    except HVACAdapterError as exc:
        return jsonify({"connected": False, "adapter": None,
                        "integration": profile.get("integration"), "error": str(exc),
                        "controls": profile.get("controls", []), "sensors": profile.get("sensors", [])})


@main.route("/api/ava/status")
def ava_status():
    """Expose the Phase 3 reasoning engine status for the UI/demo."""
    import os
    return jsonify({
        "engine": "AVA Brain",
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "provider": "NVIDIA NIM",
        "configured": bool(os.environ.get("NIM_API_KEY", "").strip()),
        "fallback_available": True,
        "capabilities": [
            "occupant feedback interpretation",
            "comfort and PMV/PPD reasoning",
            "multi-occupant conflict detection",
            "comfort-vs-energy tradeoff",
            "bounded HVAC recommendations",
            "decision trace / audit record",
        ],
    })


@main.route("/api/environment", methods=["POST"])
def update_environment():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    state = _request_building_state()

    if "outdoor_temp" in data:
        state.weather.outdoor_temp = float(data["outdoor_temp"])
    if "humidity" in data:
        state.weather.humidity = float(data["humidity"])
    if "wind_speed" in data:
        state.weather.wind_speed = float(data["wind_speed"])
    if "condition" in data:
        try:
            state.weather.condition = WeatherCondition(data["condition"])
        except ValueError:
            pass
    if "time_of_day" in data:
        state.clock.current_time = float(data["time_of_day"]) * 3600
        state.weather.time_of_day = float(data["time_of_day"])

    _save_request_building_state(state)
    return jsonify(state.to_dict())


@main.route("/api/simulation/control", methods=["POST"])
def control_simulation():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    state = _request_building_state()

    if "speed" in data:
        state.clock.speed_multiplier = float(data["speed"])
        state.clock.is_running = state.clock.speed_multiplier > 0
    if "action" in data:
        action = data["action"]
        if action == "pause":
            state.clock.is_running = False
            state.clock.speed_multiplier = 0
        elif action == "resume":
            state.clock.is_running = True
            # Preserve the user's selected speed. Only fall back to 1× if the
            # persisted value is invalid or was explicitly paused at zero.
            current_speed = float(state.clock.speed_multiplier or 1.0)
            state.clock.speed_multiplier = current_speed if current_speed > 0 else 1.0

    _save_request_building_state(state)
    return jsonify({"clock": state.clock.to_dict()})


@main.route("/api/simulation/tick", methods=["POST"])
def tick_simulation():
    """Advance the authoritative physics simulation without blocking the UI on LLM calls."""
    state = _request_building_state()
    step_simulation(state, 60.0)
    # Keep the simulation endpoint fast and deterministic. The heavier AVA
    # reasoning cycle is intentionally exposed through /api/autonomy/run so
    # high-speed simulation cannot queue repeated Nemotron requests.
    _save_request_building_state(state)
    return jsonify({
        "state": state.to_dict(),
        "metrics": calculate_building_metrics(state),
        "autonomy": None,
    })


@main.route("/api/events")
def get_events():
    state = _request_building_state()
    return jsonify([e.to_dict() for e in state.events])


@main.route("/api/events", methods=["POST"])
def trigger_event():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    state = _request_building_state()
    event_type_str = data.get("event_type", "")
    room_ids = data.get("room_ids", [])

    try:
        event_type = EventType(event_type_str)
    except ValueError:
        return jsonify({"error": "Invalid event type"}), 400

    if event_type == EventType.HVAC_FAULT:
        severity = data.get("severity", 0.3)
        for room_id in room_ids:
            if room_id in state.rooms:
                state.hvac.failure_zones.append(room_id)
                state.hvac.failure_severity[room_id] = severity
                state.hvac.mode = HVACMode.FAILURE
        description = f"HVAC fault in zones: {', '.join(room_ids)} (severity: {severity:.0%})"
    elif event_type == EventType.HEAT_WAVE:
        state.weather.condition = WeatherCondition.HEAT_WAVE
        description = "Heat wave condition activated"
    elif event_type == EventType.RAIN_START:
        state.weather.condition = WeatherCondition.RAIN
        description = "Rain started"
    elif event_type == EventType.OCCUPANCY_SURGE:
        for room_id in room_ids:
            if room_id in state.rooms:
                room = state.rooms[room_id]
                add_count = min(room.max_occupancy - room.occupancy, 5)
                if add_count > 0:
                    from app.simulation.building_simulation import add_occupants_to_room
                    add_occupants_to_room(state, room, add_count)
        description = f"Occupancy surge in: {', '.join(room_ids)}"
    else:
        description = f"Event triggered: {event_type.value}"

    event = BuildingEvent(
        id=str(uuid.uuid4())[:8],
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        description=description,
        affected_rooms=room_ids,
        severity="warning" if event_type in [EventType.HVAC_FAULT, EventType.HEAT_WAVE] else "info",
        data=data,
    )
    state.events.append(event)

    _save_request_building_state(state)
    return jsonify(event.to_dict())


@main.route("/api/hvac/control", methods=["POST"])
def control_hvac():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    state = _request_building_state()

    if "mode" in data:
        try:
            state.hvac.mode = HVACMode(data["mode"])
        except ValueError:
            pass

    if "supply_temp" in data:
        state.hvac.supply_temp = float(data["supply_temp"])
    if "fan_speed" in data:
        state.hvac.main_fan_speed = float(data["fan_speed"])
    if "zone_dampers" in data:
        for room_id, damper in data["zone_dampers"].items():
            if room_id in state.hvac.zone_dampers:
                state.hvac.zone_dampers[room_id] = float(damper)

    _save_request_building_state(state)
    return jsonify({"hvac": state.hvac.to_dict()})


@main.route("/api/metrics")
def get_metrics():
    state = _request_building_state()
    metrics = calculate_building_metrics(state)
    return jsonify(metrics)


@main.route("/api/history")
def get_history():
    return jsonify(load_building_history())


@main.route("/api/baseline-comparison")
def get_baseline_comparison():
    if os.environ.get("VERCEL"):
        return _baseline_comparison_sync()
    job_id = submit_job(_baseline_comparison_sync, session_id=session_id(), app=current_app._get_current_object())
    return jsonify({"status": "queued", "job_id": job_id, "poll": f"/api/jobs/{job_id}"}), 202

def _baseline_comparison_sync():
    state = _request_building_state()
    baseline = run_baseline_simulation(state)
    current = calculate_building_metrics(state)

    ava_energy = sum(m["total_energy"] for m in state.metrics_history[-288:]) if state.metrics_history else 0
    baseline_energy = baseline["total_energy"]

    energy_savings = 0
    if baseline_energy > 0:
        energy_savings = ((baseline_energy - ava_energy) / baseline_energy) * 100

    return jsonify({
        "baseline": baseline,
        "ava": {
            "total_energy": round(ava_energy, 1),
            "avg_pmv": current["avg_pmv"],
            "comfort_percentage": current["comfort_percentage"],
            "comfort_violations": current["comfort_violations"],
        },
        "energy_savings_pct": round(energy_savings, 1),
    })


@main.route("/api/what-if", methods=["POST"])
def what_if():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    if os.environ.get("VERCEL"):
        return _what_if_sync(data)
    job_id = submit_job(lambda: _what_if_sync(data), session_id=session_id(), app=current_app._get_current_object())
    return jsonify({"status": "queued", "job_id": job_id, "poll": f"/api/jobs/{job_id}"}), 202

def _what_if_sync(data):
    state = _request_building_state()
    test_state = BuildingState.from_dict(state.to_dict())

    if "outdoor_temp" in data:
        test_state.weather.outdoor_temp = float(data["outdoor_temp"])
    if "humidity" in data:
        test_state.weather.humidity = float(data["humidity"])
    if "condition" in data:
        try:
            test_state.weather.condition = WeatherCondition(data["condition"])
        except ValueError:
            return jsonify({"error": "Invalid weather condition"}), 400
    if "occupancy_multiplier" in data:
        multiplier = float(data["occupancy_multiplier"])
        for room in test_state.rooms.values():
            target = min(room.max_occupancy, int(room.occupancy * multiplier))
            if target > room.occupancy:
                add_occupants_to_room(test_state, room, target - room.occupancy)
            elif target < room.occupancy:
                remove_occupants_from_room(test_state, room, room.occupancy - target)
            room.occupancy = target
    if "hvac_capacity_reduction" in data:
        reduction = float(data["hvac_capacity_reduction"])
        test_state.hvac.total_capacity *= (1 - reduction)
        test_state.hvac.mode = HVACMode.FAILURE
        for room_id in test_state.rooms:
            test_state.hvac.failure_zones.append(room_id)
            test_state.hvac.failure_severity[room_id] = reduction
    if "time_of_day" in data:
        test_state.clock.current_time = float(data["time_of_day"]) * 3600
        test_state.weather.time_of_day = float(data["time_of_day"])
    if "window_open" in data:
        room_id = data.get("room_id")
        if room_id and room_id in test_state.rooms:
            test_state.rooms[room_id].windows_open = bool(data["window_open"])
    if "door_open" in data:
        room_id = data.get("room_id")
        if room_id and room_id in test_state.rooms:
            test_state.rooms[room_id].doors_open = bool(data["door_open"])

    run_control_response_simulation(test_state, minutes=10)

    metrics = calculate_building_metrics(test_state)
    opt_result = optimize_hvac_multi_zone(test_state)

    return jsonify({
        "metrics": metrics,
        "optimization": opt_result.to_dict(),
        "hvac": test_state.hvac.to_dict(),
    })


@main.route("/api/autonomy/status")
def get_autonomy_status():
    state = _request_building_state()
    return jsonify({
        "enabled": state.hvac.mode == HVACMode.AUTO,
        "mode": state.hvac.mode.value,
        "loop": "observe→analyze→decide→act→observe",
        "last_event": next((e.to_dict() for e in reversed(state.events) if e.data.get("cycle")), None),
    })


@main.route("/api/autonomy/run", methods=["POST"])
def run_autonomy():
    state = _request_building_state()
    result = run_autonomous_cycle(state, mutate=True)
    if result.get("acted"):
        _save_request_building_state(state)
    return jsonify(result)


@main.route("/api/autonomy/control", methods=["POST"])
def control_autonomy():
    data = request.get_json() or {}
    state = _request_building_state()
    enabled = bool(data.get("enabled", True))
    state.hvac.mode = HVACMode.AUTO if enabled else HVACMode.MANUAL
    _save_request_building_state(state)
    return jsonify({"enabled": enabled, "mode": state.hvac.mode.value})


@main.route("/api/disturbance", methods=["POST"])
def apply_disturbance():
    data = request.get_json() or {}
    kind = str(data.get("kind", "")).strip()
    allowed = {"hvac_degradation", "sensor_drift", "occupancy_surge", "stuck_damper", "window_open"}
    if kind not in allowed:
        return jsonify({"error": "Invalid disturbance type"}), 400

    state = _request_building_state()
    try:
        result = inject_disturbance(
            state,
            kind,
            data.get("room_ids"),
            float(data.get("severity", 0.3)),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    _save_request_building_state(state)
    return jsonify({
        "message": f"Applied disturbance: {kind}",
        "result": result,
        "state": state.to_dict(),
        "metrics": calculate_building_metrics(state),
    })


@main.route("/api/scenarios")
def get_scenarios():
    return jsonify({
        "hot_afternoon": {
            "name": "Hot Afternoon",
            "description": "High outdoor temperature and solar load",
            "params": {"outdoor_temp": 42, "condition": "heat_wave", "time_of_day": 14},
        },
        "rainstorm": {
            "name": "Rainstorm",
            "description": "High humidity and rain",
            "params": {"outdoor_temp": 26, "condition": "rain", "humidity": 85},
        },
        "office_overcrowding": {
            "name": "Office Overcrowding",
            "description": "Large occupancy increase",
            "params": {"occupancy_multiplier": 2.0},
        },
        "hvac_failure": {
            "name": "HVAC Failure",
            "description": "Reduced HVAC capacity on Floor 2",
            "params": {"hvac_capacity_reduction": 0.3, "room_ids": ["201", "202", "203", "204", "205"]},
        },
        "normal_day": {
            "name": "Normal Day",
            "description": "Normal operation",
            "params": {"outdoor_temp": 28, "condition": "sunny", "time_of_day": 10},
        },
        "night": {
            "name": "Night",
            "description": "Low occupancy, reduced HVAC",
            "params": {"outdoor_temp": 22, "condition": "sunny", "time_of_day": 23, "occupancy_multiplier": 0.1},
        },
    })


@main.route("/api/scenarios/<scenario_id>", methods=["POST"])
def apply_scenario(scenario_id: str):
    if os.environ.get("VERCEL"):
        return _apply_scenario_sync(scenario_id)
    job_id = submit_job(lambda: _apply_scenario_sync(scenario_id), session_id=session_id(), app=current_app._get_current_object())
    return jsonify({"status": "queued", "job_id": job_id, "poll": f"/api/jobs/{job_id}"}), 202

def _apply_scenario_sync(scenario_id: str):
    scenarios_resp = get_scenarios().get_json()
    scenario = scenarios_resp.get(scenario_id)
    if not scenario:
        return jsonify({"error": "Scenario not found"}), 404

    # "Normal Day" is a recovery/demo baseline. Starting it from a prior fault
    # should not carry damaged equipment or stale occupancy into the scenario.
    if scenario_id == "normal_day":
        state = reset_demo_building_state() if request.args.get("scope") == "demo" else reset_building_state()
    else:
        state = _request_building_state()
    params = scenario["params"]

    if "outdoor_temp" in params:
        state.weather.outdoor_temp = params["outdoor_temp"]
    if "condition" in params:
        try:
            state.weather.condition = WeatherCondition(params["condition"])
        except ValueError:
            pass
    if "humidity" in params:
        state.weather.humidity = params["humidity"]
    if "time_of_day" in params:
        state.clock.current_time = params["time_of_day"] * 3600
        state.weather.time_of_day = params["time_of_day"]
    if "occupancy_multiplier" in params:
        multiplier = params["occupancy_multiplier"]
        for room in state.rooms.values():
            target = min(room.max_occupancy, int(room.occupancy * multiplier))
            if target > room.occupancy:
                add_occupants_to_room(state, room, target - room.occupancy)
            elif target < room.occupancy:
                remove_occupants_from_room(state, room, room.occupancy - target)
            room.occupancy = target
    if "hvac_capacity_reduction" in params:
        reduction = params["hvac_capacity_reduction"]
        state.hvac.total_capacity *= (1 - reduction)
        state.hvac.mode = HVACMode.FAILURE
        for room_id in params.get("room_ids", []):
            if room_id in state.rooms:
                state.hvac.failure_zones.append(room_id)
                state.hvac.failure_severity[room_id] = reduction

    run_control_response_simulation(state, minutes=10)

    _save_request_building_state(state)
    return jsonify({
        "message": f"Applied scenario: {scenario['name']}",
        "state": state.to_dict(),
        "metrics": calculate_building_metrics(state),
    })


@main.route("/api/reset", methods=["POST"])
def api_reset():
    state = reset_demo_building_state() if request.args.get("scope") == "demo" else reset_building_state()
    # Persist the freshly-created state immediately. Without this, the next
    # request could reload the stale pre-reset state from disk.
    _save_request_building_state(state)
    return jsonify({
        "message": "Building reset to defaults",
        "state": state.to_dict(),
        "metrics": calculate_building_metrics(state),
    })


@main.route("/api/simulation/state")
def get_sim_state():
    return jsonify(load_sim_state())


@main.route("/api/simulation/state", methods=["POST"])
def update_sim_state():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    current_state = load_sim_state()

    if "outdoor_temp" in data:
        current_state["outdoor_temp"] = data["outdoor_temp"]
    if "zones" in data:
        for zone_id, zone_data in data["zones"].items():
            if zone_id in current_state["zones"]:
                current_state["zones"][zone_id].update(zone_data)

    save_sim_state(current_state)
    return jsonify(current_state)


@main.route("/api/simulation/reset", methods=["POST"])
def reset_sim_state():
    default_state = get_default_sim_state()
    save_sim_state(default_state)
    return jsonify(default_state)


# Original API routes for backward compatibility
@main.route("/api/complaint", methods=["POST"])
def handle_complaint():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    text = data.get("complaint", "").strip()
    if not text:
        return jsonify({"error": "No complaint text provided"}), 400
    if len(text) > 1000:
        return jsonify({"error": "Complaint too long (max 1000 characters)"}), 400

    nlp_result = extract_complaint(text)

    if nlp_result.confidence < 0.3:
        return jsonify({
            "error": "Could not parse the complaint. Please try rephrasing.",
            "nlp": nlp_result.to_dict(),
        }), 422

    state = load_state()

    pmv_before = assess_zone_comfort(state)

    if nlp_result.zone and nlp_result.zone.lower() not in ("unknown", "room a", ""):
        state.zone_name = nlp_result.zone
    state.metabolic_rate = nlp_result.metabolic_rate
    state.clothing_insulation = nlp_result.clothing_insulation

    opt_result = optimize_hvac(state)

    twin = DigitalTwin(state)
    new_state, energy = twin.simulate(opt_result.supply_temp, opt_result.fan_speed)
    pmv_after = assess_zone_comfort(new_state)

    save_state(new_state)

    entry = {
        "complaint": text,
        "nlp_result": nlp_result.to_dict(),
        "pmv_before": {"pmv": pmv_before.pmv, "ppd": pmv_before.ppd, "tsv": pmv_before.tsv},
        "pmv_after": {"pmv": pmv_after.pmv, "ppd": pmv_after.ppd, "tsv": pmv_after.tsv},
        "optimization": opt_result.to_dict(),
        "energy_cost": round(energy, 4),
        "state_after": new_state.to_dict(),
    }
    append_history(entry)

    return jsonify({
        "nlp": nlp_result.to_dict(),
        "comfort_before": {"pmv": pmv_before.pmv, "ppd": pmv_before.ppd, "tsv": pmv_before.tsv},
        "optimization": opt_result.to_dict(),
        "comfort_after": {"pmv": pmv_after.pmv, "ppd": pmv_after.ppd, "tsv": pmv_after.tsv},
        "energy_cost": round(energy, 4),
        "state": new_state.to_dict(),
    })


@main.route("/api/zone-state")
def get_zone_state():
    state = load_state()
    comfort = assess_zone_comfort(state)
    return jsonify({
        "state": state.to_dict(),
        "comfort": {"pmv": comfort.pmv, "ppd": comfort.ppd, "tsv": comfort.tsv},
    })


@main.route("/api/zone-reset", methods=["POST"])
def api_reset_zone():
    state = reset_state()
    comfort = assess_zone_comfort(state)
    return jsonify({
        "message": "Zone reset to defaults",
        "state": state.to_dict(),
        "comfort": {"pmv": comfort.pmv, "ppd": comfort.ppd, "tsv": comfort.tsv},
    })


from datetime import datetime, timezone
import uuid