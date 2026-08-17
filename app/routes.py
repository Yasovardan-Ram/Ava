from flask import Blueprint, jsonify, render_template, request

from app.models import (
    append_history,
    load_history,
    load_state,
    reset_state,
    save_state,
)
from app.nlp.extractor import extract_complaint
from app.optimizer.hvac_optimizer import optimize_hvac
from app.simulation.digital_twin import DigitalTwin, assess_comfort

main = Blueprint("main", __name__)

MAX_COMPLAINT_LENGTH = 1000


@main.route("/")
def index():
    return render_template("index.html")


@main.route("/api/complaint", methods=["POST"])
def handle_complaint():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    text = data.get("complaint", "").strip()
    if not text:
        return jsonify({"error": "No complaint text provided"}), 400
    if len(text) > MAX_COMPLAINT_LENGTH:
        return jsonify({"error": f"Complaint too long (max {MAX_COMPLAINT_LENGTH} characters)"}), 400

    nlp_result = extract_complaint(text)

    if nlp_result.confidence < 0.3:
        return jsonify({
            "error": "Could not parse the complaint. Please try rephrasing.",
            "nlp": nlp_result.to_dict(),
        }), 422

    state = load_state()

    pmv_before = assess_comfort(state)

    if nlp_result.zone and nlp_result.zone.lower() not in ("unknown", "room a", ""):
        state.zone_name = nlp_result.zone
    state.metabolic_rate = nlp_result.metabolic_rate
    state.clothing_insulation = nlp_result.clothing_insulation

    opt_result = optimize_hvac(state)

    twin = DigitalTwin(state)
    new_state, energy = twin.simulate(opt_result.supply_temp, opt_result.fan_speed)
    pmv_after = assess_comfort(new_state)

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
    comfort = assess_comfort(state)
    return jsonify({
        "state": state.to_dict(),
        "comfort": {"pmv": comfort.pmv, "ppd": comfort.ppd, "tsv": comfort.tsv},
    })


@main.route("/api/history")
def get_history():
    return jsonify(load_history())


@main.route("/api/reset", methods=["POST"])
def api_reset():
    state = reset_state()
    comfort = assess_comfort(state)
    return jsonify({
        "message": "Zone reset to defaults",
        "state": state.to_dict(),
        "comfort": {"pmv": comfort.pmv, "ppd": comfort.ppd, "tsv": comfort.tsv},
    })
