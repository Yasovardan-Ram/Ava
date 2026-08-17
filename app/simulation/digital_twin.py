from __future__ import annotations

from dataclasses import dataclass

from pythermalcomfort.models import pmv_ppd_iso
from pythermalcomfort.utilities import v_relative

from app.models import ZoneState

CP_AIR = 1005.0
MAX_AIRFLOW = 1.0
ZONE_THERMAL_MASS = 40000.0
HEAT_GAIN = 200.0
COP = 3.5
FAN_POWER_MAX = 200.0
DT = 300.0


@dataclass
class ComfortResult:
    pmv: float
    ppd: float
    tsv: str


def assess_comfort(state: ZoneState) -> ComfortResult:
    v_r = v_relative(v=state.air_velocity, met=state.metabolic_rate)
    result = pmv_ppd_iso(
        tdb=state.temperature,
        tr=state.mean_radiant_temp,
        vr=v_r,
        rh=state.humidity,
        met=state.metabolic_rate,
        clo=state.clothing_insulation,
        model="7730-2005",
        limit_inputs=False,
    )
    pmv_val = float(result.pmv) if not (result.pmv != result.pmv) else 0.0
    ppd_val = float(result.ppd) if not (result.ppd != result.ppd) else 50.0
    return ComfortResult(pmv=pmv_val, ppd=ppd_val, tsv=result.tsv)


def calculate_energy_cost(supply_temp: float, fan_speed: float, room_temp: float) -> float:
    fan_power = FAN_POWER_MAX * (fan_speed ** 3)
    cooling_delta = max(room_temp - supply_temp, 0.1)
    compressor_power = (fan_speed * MAX_AIRFLOW * CP_AIR * cooling_delta) / COP
    return fan_power + compressor_power


def apply_hvac_action(
    state: ZoneState,
    supply_temp: float,
    fan_speed: float,
) -> tuple[ZoneState, float]:
    air_flow = fan_speed * MAX_AIRFLOW
    cooling_power = air_flow * CP_AIR * (state.temperature - supply_temp)
    dT = (cooling_power - HEAT_GAIN) / ZONE_THERMAL_MASS * DT
    new_temp = state.temperature - dT
    new_temp = max(18.0, min(30.0, new_temp))

    new_state = ZoneState(
        temperature=round(new_temp, 2),
        humidity=state.humidity,
        air_velocity=state.air_velocity,
        mean_radiant_temp=round(new_temp, 2),
        metabolic_rate=state.metabolic_rate,
        clothing_insulation=state.clothing_insulation,
        hvac_setpoint=supply_temp,
        fan_speed=fan_speed,
        outdoor_temp=state.outdoor_temp,
        zone_name=state.zone_name,
    )
    energy = calculate_energy_cost(supply_temp, fan_speed, state.temperature)
    return new_state, energy


class DigitalTwin:
    def __init__(self, state: ZoneState | None = None):
        self.state = state or ZoneState()

    def simulate(self, supply_temp: float, fan_speed: float) -> tuple[ZoneState, float]:
        new_state, energy = apply_hvac_action(self.state, supply_temp, fan_speed)
        self.state = new_state
        return new_state, energy
