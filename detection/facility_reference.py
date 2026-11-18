"""Experimental calibrated baseline and conservative observation checks.

Caller must verify the reference is normal and identify camera/facility/ROI.
Bounding boxes and camera stability come from external systems, not ground truth.
"""
from __future__ import annotations

import cv2
import math
import numpy as np
from .facility_state import FacilityEvidenceGate


def _crop(image, roi):
    if image is None or image.ndim != 3 or len(roi) != 4:
        raise ValueError('A BGR image and a four-coordinate ROI are required')
    x1, y1, x2, y2 = map(int, roi)
    h, w = image.shape[:2]
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise ValueError('Invalid reference ROI')
    return image[y1:y2, x1:x2]


def descriptor(image, roi):
    patch = _crop(image, roi)
    gray = cv2.cvtColor(cv2.resize(patch, (32, 32), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
    # Suppress simple global brightness changes; not invariant to shadows or camera drift.
    standardized = (gray - gray.mean()) / max(float(gray.std()), 10.0)
    return np.clip(standardized, -3.0, 3.0).reshape(-1) / 6.0


class ReferenceBank:
    """Explicit user-approved normal reference images keyed by camera and facility."""
    def __init__(self):
        self._references = {}

    def register(self, camera_id, facility_id, image, roi, *, confirmed_normal):
        if not camera_id or not facility_id or confirmed_normal is not True:
            raise ValueError('A camera, facility and explicitly confirmed normal reference are required')
        key = (camera_id, facility_id)
        features = descriptor(image, roi)
        geometry = (tuple(map(int, roi)), tuple(image.shape[:2]))
        entry = self._references.setdefault(key, {'geometry': geometry, 'features': []})
        if entry['geometry'] != geometry:
            raise ValueError('Reference ROI or image size differs for this facility')
        entry['features'].append(features)

    def distance(self, camera_id, facility_id, image, roi):
        entry = self._references.get((camera_id, facility_id))
        if not entry:
            raise ValueError('No normal reference for this camera and facility')
        if entry['geometry'] != (tuple(map(int, roi)), tuple(image.shape[:2])):
            raise ValueError('Reference ROI or image size differs for this facility')
        current = descriptor(image, roi)
        return min(float(np.sqrt(np.mean((current - reference) ** 2))) for reference in entry['features'])


def assess_visibility(image, roi, *, vehicle_boxes, detector_healthy, camera_stable, min_focus, max_overlap=0.03):
    """Conservative heuristics, not a visibility guarantee.

    Vehicle boxes and detector health must be supplied by a detector. Missing
    inputs return unknown, as do visibly blurry crops or ROI overlap. Depth and
    non-vehicle occluders are not inferred.
    """
    patch = _crop(image, roi)
    if detector_healthy is not True or camera_stable is not True or vehicle_boxes is None or min_focus is None:
        return {'visible': False, 'reason': 'missing_or_unstable_inputs'}
    if not math.isfinite(min_focus) or min_focus < 0 or not math.isfinite(max_overlap) or not 0 <= max_overlap <= 1:
        raise ValueError('Invalid quality thresholds')
    x1, y1, x2, y2 = map(float, roi)
    area = (x2-x1)*(y2-y1)
    ratio = 0.0
    for box in vehicle_boxes:
        if len(box) != 4 or not all(math.isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]:
            return {'visible': False, 'reason': 'invalid_vehicle_box'}
        a,b,c,d = map(float, box)
        ratio = max(ratio, max(0, min(x2,c)-max(x1,a))*max(0, min(y2,d)-max(y1,b))/area)
    focus = float(cv2.Laplacian(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
    if ratio > max_overlap:
        return {'visible': False, 'reason': 'possible_vehicle_occlusion', 'overlap': ratio, 'focus': focus}
    if focus < min_focus:
        return {'visible': False, 'reason': 'blur_or_low_texture', 'overlap': ratio, 'focus': focus}
    return {'visible': True, 'reason': 'checks_passed_not_visibility_proof', 'overlap': ratio, 'focus': focus}


class ReferenceChangeMonitor:
    """Combine a caller-registered baseline, input quality checks, and time gate.

    Does not supply the vehicle detector, camera-stability detector, ROI, or
    calibration; these must come from independently validated caller inputs.
    """
    def __init__(self, bank, camera_id, facility_id, roi, kind, threshold, **gate_settings):
        if not camera_id or not facility_id:
            raise ValueError('Camera and facility identifiers are required')
        self.bank, self.camera_id, self.facility_id, self.roi = bank, camera_id, facility_id, roi
        self.gate = FacilityEvidenceGate(kind, threshold, **gate_settings)

    def observe(self, image, timestamp, *, vehicle_boxes, detector_healthy, camera_stable, min_focus, max_overlap=.03):
        try:
            quality = assess_visibility(image, self.roi, vehicle_boxes=vehicle_boxes, detector_healthy=detector_healthy,
                                        camera_stable=camera_stable, min_focus=min_focus, max_overlap=max_overlap)
        except ValueError:
            quality = {'visible': False, 'reason': 'invalid_roi_or_quality_settings'}
        score = None
        if quality['visible']:
            try:
                score = self.bank.distance(self.camera_id, self.facility_id, image, self.roi)
            except ValueError:
                quality = {'visible': False, 'reason': 'reference_missing_or_mismatched'}
        state = self.gate.update(timestamp, score, visible=quality['visible'], camera_stable=camera_stable is True)
        return {'state': state, 'score': score, 'quality': quality, 'experimental': True, 'production_ready': False}
