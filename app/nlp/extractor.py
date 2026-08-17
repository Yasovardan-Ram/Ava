from __future__ import annotations

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"

COMPLAINT_SCHEMA = {
    "type": "object",
    "properties": {
        "zone": {
            "type": "string",
            "description": "Room or zone identifier from the complaint, e.g. 'Room A', 'Conference Room'. Default: 'Room A'",
        },
        "temperature_offset": {
            "type": "number",
            "description": "Desired temperature change in degrees C. Negative = cooler, positive = warmer. Default: 0",
        },
        "humidity_delta": {
            "type": "number",
            "description": "Desired relative humidity change in percent. Negative = drier, positive = more humid. Default: 0",
        },
        "air_velocity": {
            "type": "number",
            "description": "Desired air speed in m/s. Range 0.0-1.0. Default: 0.15",
        },
        "metabolic_rate": {
            "type": "number",
            "description": "Occupant activity level in met. 1.0=sitting, 1.2=standing, 1.7=walking. Default: 1.2",
        },
        "clothing_insulation": {
            "type": "number",
            "description": "Clothing level in clo. 0.5=summer indoor, 1.0=winter indoor. Default: 0.5",
        },
        "confidence": {
            "type": "number",
            "description": "Extraction confidence from 0.0 to 1.0 based on how clear the complaint is.",
        },
        "raw_text": {
            "type": "string",
            "description": "The original complaint text verbatim.",
        },
    },
    "required": ["zone", "temperature_offset", "confidence", "raw_text"],
}

SYSTEM_PROMPT = (
    "You are an HVAC comfort complaint parser. "
    "Extract structured data from the occupant's natural language complaint. "
    "Use the provided JSON schema. "
    "When the occupant does not specify a value, use sensible defaults: "
    "temperature_offset=0, humidity_delta=0, air_velocity=0.15, "
    "metabolic_rate=1.2 (standing relaxed), clothing_insulation=0.5 (summer indoor). "
    "Confidence should reflect how clearly you can interpret the complaint. "
    "Return ONLY valid JSON matching the schema. No commentary."
)

_cache: dict[str, dict] = {}


@dataclass
class NLPResult:
    zone: str
    temperature_offset: float
    humidity_delta: float
    air_velocity: float
    metabolic_rate: float
    clothing_insulation: float
    confidence: float
    raw_text: str

    def to_dict(self) -> dict:
        return {
            "zone": self.zone,
            "temperature_offset": self.temperature_offset,
            "humidity_delta": self.humidity_delta,
            "air_velocity": self.air_velocity,
            "metabolic_rate": self.metabolic_rate,
            "clothing_insulation": self.clothing_insulation,
            "confidence": self.confidence,
            "raw_text": self.raw_text,
        }


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _validate_and_clamp(raw: dict) -> dict:
    raw.setdefault("zone", "Room A")
    raw.setdefault("temperature_offset", 0.0)
    raw.setdefault("humidity_delta", 0.0)
    raw.setdefault("air_velocity", 0.15)
    raw.setdefault("metabolic_rate", 1.2)
    raw.setdefault("clothing_insulation", 0.5)
    raw.setdefault("confidence", 0.5)
    raw.setdefault("raw_text", "")

    raw["temperature_offset"] = _clamp(float(raw["temperature_offset"]), -5.0, 5.0)
    raw["humidity_delta"] = _clamp(float(raw["humidity_delta"]), -20.0, 20.0)
    raw["air_velocity"] = _clamp(float(raw["air_velocity"]), 0.0, 1.0)
    raw["metabolic_rate"] = _clamp(float(raw["metabolic_rate"]), 0.7, 6.3)
    raw["clothing_insulation"] = _clamp(float(raw["clothing_insulation"]), 0.3, 1.5)
    raw["confidence"] = _clamp(float(raw["confidence"]), 0.0, 1.0)
    raw["zone"] = str(raw["zone"])[:100]

    return raw


def extract_complaint(text: str) -> NLPResult:
    text = text.strip()
    if not text:
        return NLPResult(
            zone="Room A", temperature_offset=0, humidity_delta=0,
            air_velocity=0.15, metabolic_rate=1.2, clothing_insulation=0.5,
            confidence=0.0, raw_text=text,
        )

    if text in _cache:
        d = _cache[text]
        return NLPResult(**d)

    api_key = os.environ.get("NIM_API_KEY", "")
    if not api_key:
        return NLPResult(
            zone="Room A", temperature_offset=0, humidity_delta=0,
            air_velocity=0.15, metabolic_rate=1.2, clothing_insulation=0.5,
            confidence=0.0, raw_text=text,
        )

    client = OpenAI(base_url=NIM_BASE_URL, api_key=api_key)

    response = client.chat.completions.create(
        model=NIM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Parse this HVAC comfort complaint:\n\n{text}"},
        ],
        extra_body={"guided_json": COMPLAINT_SCHEMA, "thinking": {"type": "disabled"}},
        temperature=0,
        max_tokens=512,
        stream=False,
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[: -3].strip()

    raw = json.loads(content)
    validated = _validate_and_clamp(raw)
    _cache[text] = validated

    return NLPResult(**validated)
