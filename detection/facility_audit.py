"""Audit facility clip provenance; this does not turn simulation truth into predictions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .sources import confined_image, decode_image


CASES = {
    "DelineatorNormal": ("delineator", "normal", True),
    "DelineatorBroken": ("delineator", "abnormal", True),
    "DelineatorFallen": ("delineator", "abnormal", True),
    "DelineatorMissing": ("delineator", "abnormal", False),
    "DelineatorPassingVehicle": ("delineator", "normal", True),
    "GuardrailNormal": ("guardrail", "normal", True),
    "GuardrailBent": ("guardrail", "abnormal", True),
    "GuardrailDisplaced": ("guardrail", "abnormal", True),
    "GuardrailBroken": ("guardrail", "abnormal", True),
    "GuardrailPassingVehicle": ("guardrail", "normal", True),
    "SignalNormal": ("traffic_signal", "normal", True),
    "SignalTransition": ("traffic_signal", "normal", True),
    "SignalFlashing": ("traffic_signal", "normal", True),
    "SignalDark": ("traffic_signal", "abnormal", True),
    "ManholeNormal": ("manhole", "normal", True),
    "ManholeOpen": ("manhole", "abnormal", False),
    "ManholeDisplaced": ("manhole", "abnormal", True),
    "GuardrailNormalCurved": ("guardrail", "normal", True),
    "GuardrailNormalJoint": ("guardrail", "normal", True),
    "GuardrailNormalLight": ("guardrail", "normal", True),
    "ManholeNormalPattern": ("manhole", "normal", True),
    "ManholeNormalWorn": ("manhole", "normal", True),
    "ManholePassingVehicle": ("manhole", "normal", True),
    "GuardrailNormalShadow": ("guardrail", "normal", True),
    "ManholeNormalShadow": ("manhole", "normal", True),
    "GuardrailBrokenLeft": ("guardrail", "abnormal", True),
    "GuardrailBrokenRight": ("guardrail", "abnormal", True),
    "GuardrailBentOpposite": ("guardrail", "abnormal", True),
    "ManholeOpenShadow": ("manhole", "abnormal", False),
    "ManholeDisplacedSmall": ("manhole", "abnormal", True),
    "ManholeDisplacedLateral": ("manhole", "abnormal", True),
}


def audit_facility_splits(splits):
    seeds, images, roots = {}, {}, set()
    result = {"splits": {}, "synthetic_only": True,
              "limitations": "Exact image SHA256 and declared seed/session only; near duplicates and shared cameras/assets remain possible."}
    for split in ("train", "val", "test"):
        sessions = splits.get(split, [])
        if not sessions:
            raise ValueError(f"No sessions for {split}")
        counts = {}
        frame_count = 0
        for session in sessions:
            root = Path(session).resolve()
            if root in roots:
                raise ValueError(f"Session reused: {root}")
            roots.add(root)
            previous_frame, previous_time, identity = -1, None, None
            with (root / "ground_truth.jsonl").open(encoding="utf-8-sig") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    scenario = row.get("scenario") or {}
                    facility = scenario.get("facility") or {}
                    seed, episode = scenario.get("seed"), scenario.get("episode")
                    variant = facility.get("variant")
                    expected = CASES.get(variant)
                    if (type(seed) is not int or type(episode) is not int or scenario.get("scenario") != "Facility"
                            or expected is None or (facility.get("kind"), facility.get("state"), facility.get("present")) != expected
                            or scenario.get("scenario_variant") != variant or scenario.get("hazard_state") != expected[1]
                            or len(facility.get("reference_position_world", [])) != 3):
                        raise ValueError(f"Invalid facility truth in {root}")
                    this_identity = (seed, episode, variant)
                    if identity is None:
                        identity = this_identity
                        if seed in seeds and seeds[seed] != split:
                            raise ValueError(f"Seed leakage between {seeds[seed]} and {split}: {seed}")
                        seeds[seed] = split
                        counts[variant] = counts.get(variant, 0) + 1
                    elif identity != this_identity:
                        raise ValueError(f"Mixed episodes in {root}")
                    frame, timestamp = row.get("frame"), row.get("timestamp")
                    if type(frame) is not int or frame != previous_frame + 1 or not isinstance(timestamp, (int, float)) or (previous_time is not None and timestamp <= previous_time):
                        raise ValueError(f"Nonconsecutive frames or timestamps in {root}")
                    previous_frame, previous_time = frame, timestamp
                    image = confined_image(root, row["image"])
                    height, width = decode_image(image).shape[:2]
                    if (width, height) != (row.get("width"), row.get("height")):
                        raise ValueError(f"Image dimensions differ in {root}")
                    digest = hashlib.sha256(image.read_bytes()).hexdigest()
                    if digest in images and images[digest] != split:
                        raise ValueError(f"Image leakage between {images[digest]} and {split}: {image}")
                    images[digest] = split
                    frame_count += 1
            if identity is None:
                raise ValueError(f"Empty session: {root}")
        result["splits"][split] = {"sessions": len(sessions), "frames": frame_count, "cases": counts}
    return result
