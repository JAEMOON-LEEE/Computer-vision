"""Experimental synthetic collision decisions from boxes and causal history only."""
from __future__ import annotations
import json
import math
from pathlib import Path

from .stop_collision import FEATURE_NAMES as BASE_FEATURES, pair_features

FEATURE_NAMES=BASE_FEATURES+['confidence_min','confidence_max','pair_age',
    'shared_history_age','maximum_closing_4s','height_span_min_4s','height_span_max_4s']


def interaction_features(a,b,histories,key,now,pair_age):
    base=pair_features(a,b,histories,key,now)
    ah=[s for s in histories.get(key(a),[]) if 0<=now-s[0]<=4]
    bh=[s for s in histories.get(key(b),[]) if 0<=now-s[0]<=4]
    scale=max(4,((a['bbox_xyxy'][3]-a['bbox_xyxy'][1])+(b['bbox_xyxy'][3]-b['bbox_xyxy'][1]))/2)
    current=math.hypot((a['bbox_xyxy'][0]+a['bbox_xyxy'][2]-b['bbox_xyxy'][0]-b['bbox_xyxy'][2])/2,
                       a['bbox_xyxy'][3]-b['bbox_xyxy'][3])
    distances=[]
    for row in ah:
        nearest=min(bh,key=lambda other:abs(other[0]-row[0])) if bh else None
        if nearest and abs(nearest[0]-row[0])<=.1:
            distances.append(math.hypot(row[1]-nearest[1],row[2]-nearest[2]))
    shared=min(now-ah[0][0] if ah else 0,now-bh[0][0] if bh else 0)
    span=lambda rows: max((r[3] for r in rows),default=1)/max(1,min((r[3] for r in rows),default=1))
    return base+[min(a['confidence'],b['confidence']),max(a['confidence'],b['confidence']),
                 min(4,pair_age),min(4,shared),max(0,(max(distances,default=current)-current)/scale),*sorted((span(ah),span(bh)))]


def close_pair(a,b):
    a,b=a['bbox_xyxy'],b['bbox_xyxy']
    gap_x=max(0,max(a[0],b[0])-min(a[2],b[2]))
    gap_y=max(0,max(a[1],b[1])-min(a[3],b[3]))
    return math.hypot(gap_x,gap_y)<=.35*max(4,((a[3]-a[1])+(b[3]-b[1]))/2)


class ObservationPolicy:
    """Collect candidates without generating alerts; no truth enters the engine."""
    threshold=2.0
    metadata={'synthetic_only':True}
    def score(self,features):return 0.0


class CollisionPolicy:
    def __init__(self,path):
        import cv2
        path=Path(path);self.metadata=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if self.metadata['features']!=FEATURE_NAMES:raise ValueError('Collision feature schema differs')
        self.threshold=float(self.metadata['threshold'])
        if not .5<=self.threshold<=1.001:raise ValueError('Invalid collision threshold')
        self.model=cv2.ml.RTrees_load(str(path))
        if self.model.getVarCount()!=len(FEATURE_NAMES):raise ValueError('Invalid collision model feature count')

    def score(self,features):
        import numpy as np
        row=np.asarray(features,np.float32).reshape(1,-1)
        if row.shape[1]!=len(FEATURE_NAMES) or not np.isfinite(row).all():return 0.0
        votes=self.model.getVotes(row,0);positive=np.flatnonzero(votes[0]==1)
        return float(votes[1,positive[0]]/max(1,votes[1].sum())) if len(positive) else 0.0
