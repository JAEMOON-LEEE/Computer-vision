"""Experimental real CCTV accident-scene classifier; not physical contact detection.

The frozen public COCO backbone supplies image features. TAD folder labels are
weak scene labels; no participant pair, accident onset or cause is inferred.
"""
from __future__ import annotations
from collections import deque
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
EMBED_WEIGHTS=ROOT/"detection/models/yolo11n.pt"
MODEL_PATH=ROOT/"detection/models/real-incident-scene-v1.xml"
EMBED_LAYER=10
IMGSZ=416


class SceneFeatures:
    def __init__(self):
        from ultralytics import YOLO
        self.model=YOLO(str(EMBED_WEIGHTS))

    def extract(self,image):
        values=self.model.predict(image,imgsz=IMGSZ,device="cpu",verbose=False,embed=[EMBED_LAYER])[0]
        row=values.detach().float().cpu().numpy().ravel()
        row=row/max(1e-9,float(np.linalg.norm(row)))
        if row.shape!=(256,) or not np.isfinite(row).all():raise ValueError("Scene embedding schema changed")
        return row


def vote_scores(model,features):
    rows=np.asarray(features,np.float32).reshape(-1,256)
    if not len(rows):return np.zeros(0)
    votes=model.getVotes(rows,0);indices=np.flatnonzero(votes[0]==1)
    return votes[1:,indices[0]]/np.maximum(1,votes[1:].sum(axis=1)) if len(indices) else np.zeros(len(rows))


def scene_hit(scores,times,threshold):
    consecutive=[]
    for score,t in zip(scores,times):
        if score<threshold:
            consecutive=[];continue
        if consecutive and t-consecutive[-1]>.8:consecutive=[]
        consecutive.append(float(t))
        if len(consecutive)>=3 and t-consecutive[0]>=.9:return True
    return False


class RealIncidentScorer:
    def __init__(self,path=MODEL_PATH):
        path=Path(path);self.metadata=json.loads(path.with_suffix(".json").read_text(encoding="utf8"))
        if not self.metadata.get("alerts_enabled"):raise ValueError("Real incident scene validation gate failed")
        if hashlib.sha256(EMBED_WEIGHTS.read_bytes()).hexdigest()!=self.metadata["embedding_sha256"]:raise ValueError("Scene backbone weights differ")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=self.metadata["model_sha256"]:raise ValueError("Scene classifier weights differ")
        self.model=cv2.ml.RTrees_load(str(path))
        if self.model.getVarCount()!=256:raise ValueError("Scene model schema differs")
        self.features=SceneFeatures();self.reset()

    def reset(self):
        self.last_sample=None;self.last_warning=None;self.votes=deque(maxlen=3)

    def update(self,image,record):
        t=record["timestamp"]
        if self.last_sample is not None and t-self.last_sample<.49:return [],None
        if self.last_sample is not None and (t<self.last_sample or t-self.last_sample>.8):self.votes.clear()
        score=float(vote_scores(self.model,[self.features.extract(image)])[0]);self.last_sample=t
        if score<self.metadata["threshold"]:self.votes.clear()
        else:self.votes.append(t)
        alerts=[]
        if len(self.votes)>=3 and t-self.votes[0]>=.9 and (self.last_warning is None or t-self.last_warning>=15):
            self.last_warning=t
            alerts=[{"alert_id":record["camera_id"]+":real-scene:"+str(record["frame"]),
                "camera_id":record["camera_id"],"frame":record["frame"],"timestamp":t,
                "type":"suspected_traffic_incident_scene","severity":"warning","status":"unconfirmed",
                "message":"Real-data scene classifier suggests an accident scene; review source video",
                "basis":"weakly_supervised_real_scene_appearance","evidence":[],
                "scene_decision":{"vote_ratio":score,"threshold":self.metadata["threshold"],
                    "not_calibrated_probability":True,"contact_or_participants_identified":False}}]
        return alerts,score
