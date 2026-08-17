from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, minimize

from app.models import ZoneState
from app.simulation.digital_twin import (
    AIR_DENSITY,
    MAX_AIRFLOW,
    CP_AIR,
    COP,
    FAN_POWER_MAX,
    HEAT_GAIN,
    ZONE_THERMAL_MASS,
)
from pythermalcomfort.models import pmv_ppd_iso
from pythermalcomfort.utilities import v_relative

SUPPLY_TEMP_MIN = 14.0
SUPPLY_TEMP_MAX = 22.0
FAN_SPEED_MIN = 0.1
FAN_SPEED_MAX_OPT = 1.0


@dataclass
class OptimizationResult:
    supply_temp: float
    fan_speed: float
    energy_cost: float
    pmv_after: float
    success: bool
    message: str

    def to_dict(self) -> dict:
        return {
            "supply_temp": self.supply_temp,
            "fan_speed": self.fan_speed,
            "energy_cost": round(self.energy_cost, 4),
            "pmv_after": round(self.pmv_after, 4),
            "success": self.success,
            "message": self.message,
        }


def _compute_pmv(room_temp: float, air_speed: float,
                  humidity: float, met: float, clo: float) -> float:
    v_r = v_relative(v=air_speed, met=met)
    result = pmv_ppd_iso(
        tdb=room_temp,
        tr=room_temp,
        vr=v_r,
        rh=humidity,
        met=met,
        clo=clo,
        model="7730-2005",
        limit_inputs=False,
    )
    pmv_val = float(result.pmv) if result.pmv == result.pmv else 0.0
    return pmv_val


def _evaluate(state: ZoneState, supply_temp: float, fan_speed: float,
              target_pmv: float = 0.0) -> tuple[float, float, float]:
    fan_power = FAN_POWER_MAX * (fan_speed ** 3)
    cooling_delta = max(state.temperature - supply_temp, 0.0)
    compressor_power = (fan_speed * MAX_AIRFLOW * AIR_DENSITY * CP_AIR * cooling_delta) / COP
    energy = fan_power + compressor_power

    air_flow = fan_speed * MAX_AIRFLOW
    cooling_power = air_flow * AIR_DENSITY * CP_AIR * (state.temperature - supply_temp)
    dT = (cooling_power - HEAT_GAIN) / ZONE_THERMAL_MASS * 300.0
    room_temp = max(18.0, min(30.0, state.temperature - dT))
    air_speed = 0.1 + fan_speed * 0.4
    pmv = _compute_pmv(room_temp, air_speed,
                       state.humidity, state.metabolic_rate, state.clothing_insulation)
    return energy, pmv, room_temp


def _is_feasible(pmv: float, target_pmv: float) -> bool:
    return abs(pmv - target_pmv) <= 0.5


def optimize_hvac(state: ZoneState, target_pmv: float = 0.0) -> OptimizationResult:
    def energy_cost(x: np.ndarray) -> float:
        fan_power = FAN_POWER_MAX * (x[1] ** 3)
        cooling_delta = max(state.temperature - x[0], 0.0)
        compressor_power = (x[1] * MAX_AIRFLOW * AIR_DENSITY * CP_AIR * cooling_delta) / COP
        return fan_power + compressor_power

    def pmv_constraint(x: np.ndarray) -> float:
        _, pmv, _ = _evaluate(state, x[0], x[1], target_pmv)
        return 0.5 - abs(pmv - target_pmv)

    x0 = np.array([state.hvac_setpoint, state.fan_speed])
    bounds = Bounds(lb=[SUPPLY_TEMP_MIN, FAN_SPEED_MIN], ub=[SUPPLY_TEMP_MAX, FAN_SPEED_MAX_OPT])
    constraints = [{"type": "ineq", "fun": pmv_constraint}]

    best_energy_init, best_pmv_init, _ = _evaluate(state, x0[0], x0[1], target_pmv)
    best_x = x0.copy()
    best_energy = best_energy_init
    best_pmv = best_pmv_init
    best_feasible = _is_feasible(best_pmv, target_pmv)

    try:
        result = minimize(
            fun=energy_cost,
            x0=x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 200},
        )

        cand_energy, cand_pmv, _ = _evaluate(state, result.x[0], result.x[1], target_pmv)
        cand_feasible = _is_feasible(cand_pmv, target_pmv)

        if cand_feasible and (not best_feasible or cand_energy < best_energy):
            best_x = result.x.copy()
            best_energy = cand_energy
            best_pmv = cand_pmv
            best_feasible = True
    except Exception:
        pass

    grid_best_x = best_x.copy()
    grid_best_energy = best_energy
    grid_best_pmv = best_pmv
    grid_best_feasible = best_feasible

    for st in np.linspace(SUPPLY_TEMP_MIN, SUPPLY_TEMP_MAX, 20):
        for fs in np.linspace(FAN_SPEED_MIN, FAN_SPEED_MAX_OPT, 10):
            e, p, _ = _evaluate(state, st, fs, target_pmv)
            f = _is_feasible(p, target_pmv)
            if f and (not grid_best_feasible or e < grid_best_energy):
                grid_best_x = np.array([st, fs])
                grid_best_energy = e
                grid_best_pmv = p
                grid_best_feasible = True

    if grid_best_feasible and (not best_feasible or grid_best_energy < best_energy):
        best_x = grid_best_x
        best_energy = grid_best_energy
        best_pmv = grid_best_pmv
        best_feasible = True

    if best_feasible:
        return OptimizationResult(
            supply_temp=round(best_x[0], 2),
            fan_speed=round(best_x[1], 4),
            energy_cost=round(best_energy, 4),
            pmv_after=round(best_pmv, 4),
            success=True,
            message="Optimization converged",
        )

    return OptimizationResult(
        supply_temp=state.hvac_setpoint,
        fan_speed=state.fan_speed,
        energy_cost=round(energy_cost(x0), 4),
        pmv_after=round(best_pmv, 4),
        success=False,
        message="No feasible solution found, using current setpoints",
    )
