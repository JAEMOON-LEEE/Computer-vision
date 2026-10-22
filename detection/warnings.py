"""Observation-only warning rules. Never read Unity objects, events or signal ground truth."""

from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path

VEHICLES = {"car", "truck", "bus", "motorcycle", "bicycle"}
HAZARDS = {"pothole", "crack", "debris"}


def inside(point, polygon):
    if not polygon:
        return False
    x, y = point
    result = False
    previous = polygon[-1]
    for current in polygon:
        ax, ay = previous; bx, by = current
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            result = not result
        previous = current
    return result


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0


class WarningEngine:
    def __init__(self, context=None, confidence=0.5, persistence=0.4, cooldown=15.0, stop_model=None):
        self.context = context or {}
        self.confidence, self.persistence, self.cooldown = confidence, persistence, cooldown
        for polygon in [self.context.get("road_polygon", []), *self.context.get("stop_zones", [])]:
            if polygon and (len(polygon) < 3 or any(len(p) != 2 or not all(math.isfinite(v) and 0 <= v <= 1 for v in p) for p in polygon)):
                raise ValueError("Context polygons need at least 3 normalized [x,y] points")
        self.camera = None
        self.last_time = None
        self.history = {}
        self.hazards = {}
        self.contacts = {}
        self.emitted = {}
        self.hazard_alerts = []
        self.structure_memory = {}
        self.collision_latches = {}
        self.index = 0
        if isinstance(stop_model, (str, Path)):
            from .stop_collision import StopCollisionModel
            stop_model = StopCollisionModel(stop_model)
        self.stop_model = stop_model
        self.stop_candidates = []

    def key(self, detection):
        track = detection.get("track_id")
        return f'{detection.get("model_id", "primary")}:{track}' if track is not None else None

    def _emit(self, record, kind, key, detections, message):
        now = float(record["timestamp"])
        cooldown_key = (kind, key)
        if now - self.emitted.get(cooldown_key, -math.inf) < self.cooldown:
            return None
        self.emitted[cooldown_key] = now
        self.index += 1
        return {"alert_id": f'{record["camera_id"]}:{self.index}', "camera_id": record["camera_id"],
                "frame": record["frame"], "timestamp": now, "type": kind, "severity": "warning",
                "status": "unconfirmed", "message": message,
                "evidence": [{"class_name": d["class_name"], "track_id": d.get("track_id"),
                              "model_id": d.get("model_id", "primary"), "bbox_xyxy": d["bbox_xyxy"],
                              "confidence": d["confidence"], "observed_at": d.get("_observed_at", now),
                              "temporarily_occluded": d.get("_temporarily_occluded", False)} for d in detections],
                "basis": "visual_detections_and_motion"}

    def _motion(self, key, now):
        samples = self.history.get(key, [])
        if len(samples) < 4:
            return False
        height = max(4.0, samples[-1][3])
        recent = [sample for sample in samples if now - sample[0] <= 0.5]
        if len(recent) < 3 or recent[-1][0] - recent[0][0] < 0.35:
            return False
        dt = recent[-1][0] - recent[0][0]
        stopped = math.hypot(recent[-1][1] - recent[0][1], recent[-1][2] - recent[0][2]) / height / dt < 0.2
        earlier = [sample for sample in samples if 0.5 < now - sample[0] <= 2.5]
        if not stopped:
            return False
        # Distant approaching vehicles move fewer pixels. Require sustained,
        # directed displacement instead of accepting a single fast box jitter.
        for start in range(len(earlier)):
            path = 0.0
            for end in range(start + 1, len(earlier)):
                a, b = earlier[end - 1], earlier[end]
                path += math.hypot(b[1] - a[1], b[2] - a[2])
                first = earlier[start]
                duration = b[0] - first[0]
                net = math.hypot(b[1] - first[1], b[2] - first[2])
                if (end - start >= 2 and duration >= 0.35 and net >= max(2.0, 0.2 * height)
                        and net / height / duration > 0.35 and net / max(path, 1e-6) >= 0.8):
                    return True
        return False

    def _occluded_motion(self, key, now):
        # A barrier can hide a car's bottom edge. Its visible roof/top can
        # still show sustained approach and then stopping. Used only with
        # the learned stop-zone policy, never as a standalone alert.
        samples=list(self.history.get(key,[]))
        recent=[s for s in samples if now-s[0]<=.5]
        if len(recent)<3 or recent[-1][0]-recent[0][0]<.35:return False
        height=max(4,recent[-1][3])
        top=lambda s:s[2]-s[3]
        if abs(top(recent[-1])-top(recent[0]))/height/(recent[-1][0]-recent[0][0])>=.25:return False
        earlier=[s for s in samples if .5<now-s[0]<=2.5]
        for start in range(len(earlier)):
            path=0
            for end in range(start+1,len(earlier)):
                path+=abs(top(earlier[end])-top(earlier[end-1]))
                dt=earlier[end][0]-earlier[start][0]
                net=abs(top(earlier[end])-top(earlier[start]))
                if end-start>=2 and dt>=.35 and net>=max(2,.1*height) and net/height/dt>.3 and net/max(path,1e-6)>=.8:
                    return True
        return False

    def update(self, record):
        self.stop_candidates = []
        now = float(record["timestamp"])
        width, height = record["width"], record["height"]
        if not math.isfinite(now) or width <= 0 or height <= 0:
            raise ValueError("Warning input needs finite time and positive image dimensions")
        if self.camera != record["camera_id"] or (self.last_time is not None and (now < self.last_time or now - self.last_time > 2)):
            self.history.clear(); self.hazards.clear(); self.contacts.clear(); self.emitted.clear()
            self.hazard_alerts.clear()
            self.structure_memory.clear()
            self.collision_latches.clear()
        self.camera, self.last_time = record["camera_id"], now
        detections = []
        for detection in record.get("detections", []):
            box = detection.get("bbox_xyxy", [])
            minimum=min(.3,self.confidence) if detection.get("class_name") in VEHICLES else self.confidence
            if detection.get("confidence", 0) < minimum or len(box) != 4 or not all(math.isfinite(v) for v in box):
                continue
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            point = ((box[0] + box[2]) / 2 / width, box[3] / height)
            if self.context.get("road_polygon") and not inside(point, self.context["road_polygon"]):
                continue
            key = self.key(detection)
            if key is not None:
                history = self.history.setdefault(key, deque(maxlen=150))
                if history and now - history[-1][0] > 0.6:
                    history.clear()
                if not history or now > history[-1][0]:
                    history.append((now, (box[0] + box[2]) / 2, box[3], box[3] - box[1]))
            if detection.get("confidence",0)>=self.confidence or detection.get("class_name") in VEHICLES:
                detections.append(detection)
        self.history = {key: values for key, values in self.history.items() if values and now - values[-1][0] <= 3}
        alerts, seen = [], set()
        for detection in detections:
            name, box = detection["class_name"], detection["bbox_xyxy"]
            if name not in HAZARDS:
                continue
            # Persistent spatial bins allow replayed detector records even without tracker IDs.
            key = (name, self.key(detection) or (round((box[0] + box[2]) / width * 10), round(box[3] / height * 10)))
            seen.add(key)
            first, last, count = self.hazards.get(key, (now, now, 0))
            if now - last > 0.5:
                first, count = now, 0
            self.hazards[key] = (first, now, count + 1)
            if count + 1 >= 3 and now - first >= self.persistence:
                # A stationary hazard can acquire a new ByteTrack ID after occlusion.
                # Keep its spatial cooldown across ID changes.
                if any(old_name == name and now - time < self.cooldown and iou(box, old_box) >= 0.2
                       for old_name, old_box, time in self.hazard_alerts):
                    continue
                alert = self._emit(record, "road_damage" if name in ("pothole", "crack") else "road_debris",
                                   str(key), [detection], f"Persistent {name} detected on the road")
                if alert:
                    alerts.append(alert)
                    self.hazard_alerts.append((name, list(box), now))
        self.hazard_alerts = [item for item in self.hazard_alerts if now - item[2] < self.cooldown]
        self.hazards = {key: value for key, value in self.hazards.items() if now - value[1] <= 0.5}
        vehicles = [d for d in detections if d["class_name"] in VEHICLES and self.key(d) is not None]
        structures = [d for d in detections if d["class_name"] == "barrier"]
        current_structures = set()
        for structure in structures:
            key = self.key(structure) or str(tuple(round(v / 20) for v in structure["bbox_xyxy"]))
            current_structures.add(key)
            _, last, count = self.structure_memory.get(key, (None, now, 0))
            self.structure_memory[key] = (dict(structure, _observed_at=now), now,
                                          count + 1 if now - last <= 0.5 else 1)
        self.structure_memory = {key: value for key, value in self.structure_memory.items() if now - value[1] <= 1.0}
        for key, (structure, last, count) in self.structure_memory.items():
            # A car can hide the barrier at contact. Retain only a briefly
            # occluded structure with at least two confident observations.
            if key not in current_structures and count >= 2:
                structures.append(dict(structure, _temporarily_occluded=True))
        active_contacts = set()
        for index, vehicle in enumerate(vehicles):
            box = vehicle["bbox_xyxy"]
            point = ((box[0] + box[2]) / width / 2, box[3] / height)
            vehicle_in_stop = any(inside(point, polygon) for polygon in self.context.get("stop_zones", []))
            for other in vehicles[index + 1:] + structures:
                other_box = other["bbox_xyxy"]
                other_point = ((other_box[0] + other_box[2]) / width / 2, other_box[3] / height)
                in_stop = vehicle_in_stop or any(inside(other_point, polygon) for polygon in self.context.get("stop_zones", []))
                strong = min(vehicle["confidence"], other["confidence"]) >= self.confidence
                if not in_stop and not strong:
                    continue
                # Rear-end contact in an oblique view can overlap only a few pixels.
                # Approach, abrupt stopping and persistence remain required below.
                if iou(box, other["bbox_xyxy"]) < 0.02:
                    continue
                other_key = self.key(other) or "barrier:" + str(tuple(round(v / 20) for v in other["bbox_xyxy"]))
                pair = tuple(sorted((self.key(vehicle), other_key)))
                active_contacts.add(pair)
                first, last = self.contacts.get(pair, (now, now))
                if now - last > 0.5:
                    first = now
                self.contacts[pair] = (first, now)
                if pair in self.collision_latches:
                    self.collision_latches[pair] = now
                    continue
                eligible = now-first >= 0.5 and (self._motion(self.key(vehicle),now) or self._motion(self.key(other),now))
                if in_stop and not eligible and now-first>=.5:
                    eligible=self._occluded_motion(self.key(vehicle),now) or self._occluded_motion(self.key(other),now)
                eligible = eligible and strong
                score = None
                if in_stop:
                    from .stop_collision import pair_features
                    features=pair_features(vehicle,other,self.history,self.key,now)
                    self.stop_candidates.append({"frame":record["frame"],"timestamp":now,"pair":pair,
                        "structure":other["class_name"]=="barrier","features":features,"eligible":eligible,
                        "boxes":[list(box),list(other_box)],"classes":[vehicle["class_name"],other["class_name"]]})
                    if self.stop_model is None:
                        continue
                    score=self.stop_model.score(features)
                    if score < self.stop_model.threshold:
                        continue
                if not eligible:
                    continue
                kind = "suspected_vehicle_structure_collision" if other["class_name"] == "barrier" else "suspected_vehicle_collision"
                alert = self._emit(record, kind, str(pair), [vehicle, other], "Contact-like overlap followed by abrupt stopping; review video")
                if alert:
                    if in_stop:
                        alert["stop_zone_decision"]={"score":score,"threshold":self.stop_model.threshold,
                            "basis":"trained_visual_pair_motion"}
                    alerts.append(alert)
                    self.collision_latches[pair] = now
        self.contacts = {key: value for key, value in self.contacts.items() if now - value[1] <= 0.5}
        self.collision_latches = {key: time for key, time in self.collision_latches.items() if now - time <= 1.0}
        return alerts


def replay_warnings(source, output, context=None, stop_model=None):
    engine = WarningEngine(context, stop_model=stop_model)
    count = 0
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with Path(source).open(encoding="utf-8-sig") as reader, Path(output).open("x", encoding="utf-8") as writer:
        for line in reader:
            if line.strip():
                for alert in engine.update(json.loads(line)):
                    writer.write(json.dumps(alert, ensure_ascii=False) + "\n")
                    count += 1
    return count
