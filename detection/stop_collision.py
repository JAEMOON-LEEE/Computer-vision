"""Learned stop-zone decision from visual boxes and causal track history only."""
from __future__ import annotations

import json
import math
from pathlib import Path

FEATURE_NAMES = ["structure", "iou", "intersection_fraction", "horizontal_overlap", "vertical_overlap",
                 "dx", "dy", "distance", "width_ratio", "height_ratio", "past_vx", "past_vy",
                 "recent_vx", "recent_vy", "other_past_vx", "other_past_vy", "other_recent_vx",
                 "other_recent_vy", "closing", "height_change", "other_height_change",
                 "past_top_vy","recent_top_vy","other_past_top_vy","other_recent_top_vy"]


def pair_features(vehicle, other, histories, key, now):
    def displacement(detection):
        rows=[s for s in histories.get(key(detection),[]) if 0<=now-s[0]<=2.5]
        return math.hypot(rows[-1][1]-rows[0][1],rows[-1][2]-rows[0][2]) if len(rows)>1 else 0
    if other["class_name"] != "barrier" and displacement(other)>displacement(vehicle):
        vehicle,other=other,vehicle
    a, b = vehicle["bbox_xyxy"], other["bbox_xyxy"]
    wa, ha, wb, hb = max(1,a[2]-a[0]), max(1,a[3]-a[1]), max(1,b[2]-b[0]), max(1,b[3]-b[1])
    scale = max(4,(ha+hb)/2)
    ax, ay, bx, by = (a[0]+a[2])/2, a[3], (b[0]+b[2])/2, b[3]
    ix, iy = max(0,min(a[2],b[2])-max(a[0],b[0])), max(0,min(a[3],b[3])-max(a[1],b[1]))
    inter=ix*iy; union=wa*ha+wb*hb-inter
    ah, bh = list(histories.get(key(vehicle), [])), list(histories.get(key(other), []))
    def velocity(history, low, high):
        rows=[s for s in history if low <= now-s[0] <= high]
        if len(rows)<2 or rows[-1][0]-rows[0][0]<0.15: return (0,0)
        dt=rows[-1][0]-rows[0][0]
        return ((rows[-1][1]-rows[0][1])/scale/dt,(rows[-1][2]-rows[0][2])/scale/dt)
    def top_velocity(history,low,high):
        rows=[s for s in history if low<=now-s[0]<=high]
        if len(rows)<2 or rows[-1][0]-rows[0][0]<.15:return 0
        return ((rows[-1][2]-rows[-1][3])-(rows[0][2]-rows[0][3]))/scale/(rows[-1][0]-rows[0][0])
    olda=next((s for s in reversed(ah) if now-s[0]>=1.0),None)
    oldb=next((s for s in reversed(bh) if now-s[0]>=1.0),None)
    distance=math.hypot(ax-bx,ay-by)/scale
    closing=(math.hypot(olda[1]-oldb[1],olda[2]-oldb[2])/scale-distance) if olda and oldb else 0
    values=[float(other["class_name"]=="barrier"), inter/union if union>0 else 0, inter/min(wa*ha,wb*hb),
            ix/min(wa,wb),iy/min(ha,hb),(ax-bx)/scale,(ay-by)/scale,distance,wa/wb,ha/hb,
            *velocity(ah,.5,2.5),*velocity(ah,0,.5),*velocity(bh,.5,2.5),*velocity(bh,0,.5),closing,
            ha/olda[3] if olda else 1,hb/oldb[3] if oldb else 1,
            top_velocity(ah,.5,2.5),top_velocity(ah,0,.5),top_velocity(bh,.5,2.5),top_velocity(bh,0,.5)]
    return values


class StopCollisionModel:
    def __init__(self, path):
        import cv2
        path=Path(path)
        self.metadata=json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if self.metadata["features"] != FEATURE_NAMES:
            raise ValueError("Stop-zone model feature schema differs from runtime")
        self.threshold=float(self.metadata["threshold"])
        self.model=cv2.ml.RTrees_load(str(path))
        if self.model.getVarCount()!=len(FEATURE_NAMES):
            raise ValueError("Stop-zone model has an incompatible feature count")

    def score(self, features):
        import numpy as np
        row=np.asarray(features,dtype=np.float32).reshape(1,-1)
        if not np.isfinite(row).all(): return 0.0
        votes=self.model.getVotes(row,0)
        indices=np.flatnonzero(votes[0]==1)
        return float(votes[1,indices[0]]/max(1,votes[1].sum())) if len(indices) else 0.0
