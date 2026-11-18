"""Experimental reference-ROI visual features and conservative temporal gating.

The ROI and visibility must be supplied by the caller, never by simulation truth.
These rules do not establish real-world performance or diagnose an actual fault.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import cv2
import numpy as np

KINDS = ('delineator', 'guardrail', 'traffic_signal')
SUPPORTED_KINDS = KINDS + ('manhole',)


def roi_features(image, roi):
    """Extract visual features from user/calibration-supplied x1,y1,x2,y2 pixels."""
    if image is None or image.ndim != 3 or len(roi) != 4:
        raise ValueError('A BGR image and four pixel ROI coordinates are required')
    h, w = image.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in roi]
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise ValueError('Reference ROI is outside the image')
    patch = cv2.resize(image[y1:y2, x1:x2], (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    hog = cv2.HOGDescriptor((64,64), (16,16), (8,8), (8,8), 9).compute(gray).reshape(-1)
    colors = cv2.resize(patch, (16,16), interpolation=cv2.INTER_AREA).reshape(-1).astype(np.float32) / 255
    return np.concatenate((hog, colors)).astype(np.float32)


def predict_probability(model, features):
    votes = model.getVotes(np.asarray(features, dtype=np.float32).reshape(1, -1), 0)
    if votes is None or votes.shape[0] != 2:
        raise ValueError('Unexpected OpenCV model votes')
    columns = {int(label): i for i, label in enumerate(votes[0])}
    total = float(np.sum(votes[1]))
    return float(votes[1, columns[1]] / total) if total and 1 in columns else 0.0


@dataclass
class FacilityEvidenceGate:
    """Require continuous valid observations; caller supplies the visibility decision."""
    kind: str
    threshold: float
    min_duration_seconds: float = 3.0
    min_observations: int = 3
    max_gap_seconds: float = 1.0
    _start: float | None = None
    _last: float | None = None
    _count: int = 0

    def __post_init__(self):
        if self.kind not in SUPPORTED_KINDS or not 0 <= self.threshold <= 1 or self.min_duration_seconds <= 0 or self.min_observations < 2 or self.max_gap_seconds <= 0:
            raise ValueError('Invalid facility evidence gate settings')

    def update(self, timestamp, score, *, visible, camera_stable, transition_or_flashing=False):
        if not math.isfinite(timestamp) or (self._last is not None and timestamp <= self._last):
            raise ValueError('Observations must have increasing finite timestamps')
        if score is not None and (not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError('Score must be in [0,1]')
        gap = self._last is not None and timestamp - self._last > self.max_gap_seconds
        self._last = timestamp
        if gap or not visible or not camera_stable or transition_or_flashing or score is None:
            self._start = None; self._count = 0
            return 'unknown'
        if score < self.threshold:
            self._start = None; self._count = 0
            return 'normal_observation'
        if self._start is None: self._start = timestamp
        self._count += 1
        if self._count < self.min_observations or timestamp - self._start < self.min_duration_seconds:
            return 'observing'
        return 'suspected_dark' if self.kind == 'traffic_signal' else 'suspected_change'


class FacilityStatePredictor:
    """Evaluate a caller-supplied reference ROI; this is not a facility detector."""
    def __init__(self, kind, model_path, threshold, **gate_settings):
        path = Path(model_path)
        if not path.is_file(): raise FileNotFoundError(path)
        self.model = cv2.ml.RTrees_load(str(path))
        if self.model is None or not self.model.isTrained(): raise ValueError('Invalid facility model')
        self.gate = FacilityEvidenceGate(kind, threshold, **gate_settings)

    def observe(self, image, roi, timestamp, *, visible, camera_stable, transition_or_flashing=False):
        # Do not infer from a hidden/unstable reference; a caller must establish visibility.
        valid = visible and camera_stable and not transition_or_flashing
        score = predict_probability(self.model, roi_features(image, roi)) if valid else None
        state = self.gate.update(timestamp, score, visible=visible, camera_stable=camera_stable,
                                 transition_or_flashing=transition_or_flashing)
        return {'kind': self.gate.kind, 'state': state, 'score': score,
                'experimental': True, 'production_ready': False}
