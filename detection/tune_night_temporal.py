"""Choose RTrees capacity and threshold using training/validation clips only."""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import cv2
import numpy as np

from .runner import write_json
from .stop_collision import FEATURE_NAMES
from .train_stop_collision import POSITIVE, verify


def main(augment_legacy=False):
    root=Path.cwd();base=root/'runs/night-v1';data=base/'temporal-combined'
    output=base/('temporal-tuning-augmented' if augment_legacy else 'temporal-tuning');output.mkdir(exist_ok=True)
    all_rows=[json.loads(s) for s in (data/'candidates.jsonl').read_text().splitlines()]
    # Test rows are never scored or used to choose a configuration here.
    rows=[r for r in all_rows if r['split']=='train'];val_rows=[r for r in all_rows if r['split']=='val']
    for r in rows:r['feature_source']='current_detector'
    if augment_legacy:
        legacy=[json.loads(s) for s in (root/'runs/queue-v3/candidates.jsonl').read_text().splitlines()]
        for r in legacy:
            if r['split']=='train':rows.append({**r,'feature_source':'legacy_detector'})
    manifest=json.loads((data/'manifest.json').read_text())
    val_entries=[e for e in manifest if e['split']=='val']
    train_rows=[]
    for source,clip in sorted({(r['feature_source'],r['clip']) for r in rows}):
        group=[r for r in rows if r['clip']==clip and r['feature_source']==source]
        for label in [0,1]:
            part=[r for r in group if r['target']==label]
            if part:train_rows.extend(part[i] for i in np.linspace(0,len(part)-1,min(10,len(part))).round().astype(int))
    x=np.asarray([r['features'] for r in train_rows],np.float32)
    y=np.asarray([r['target'] for r in train_rows],np.int32)
    trials=[];best=None
    for depth in [4,6,8,10,14]:
        for minimum in [1,2,4]:
            for balanced in [False,True]:
                cv2.setRNGSeed(42)
                model=cv2.ml.RTrees_create();model.setMaxDepth(depth);model.setMinSampleCount(minimum)
                model.setMaxCategories(2);model.setCalculateVarImportance(True)
                model.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER,128,0))
                if balanced:model.setPriors(np.asarray([1.,sum(y==0)/sum(y==1)],np.float32))
                model.train(x,cv2.ml.ROW_SAMPLE,y)
                scores={}
                for entry in val_entries:
                    clip_rows=[r for r in val_rows if r['clip']==entry['clip']]
                    predictions=[]
                    for r in clip_rows:
                        votes=model.getVotes(np.asarray(r['features'],np.float32).reshape(1,-1),0)
                        index=int(np.flatnonzero(votes[0]==1)[0])
                        score=float(votes[1,index]/votes[1].sum())
                        predictions.append((r,score))
                    scores[entry['clip']]=predictions
                thresholds=sorted({.51,.55,.6,.65,.7,.75,.8,.85,.9,.95,1.,
                    *[min(1.,s+.0001) for predictions in scores.values() for r,s in predictions if r['target']==0]})
                for threshold in thresholds:
                    if threshold<.51:continue
                    fp=tp=0
                    for entry in val_entries:
                        positive=[r for r,s in scores[entry['clip']] if s>=threshold]
                        first=min(positive,key=lambda r:r['timestamp']) if positive else None
                        if entry['case'] in POSITIVE:
                            if first is not None and first['target']==1:tp+=1
                            elif first is not None:fp+=1
                        elif first is not None:fp+=1
                    choice=(fp,-tp,depth,minimum,int(balanced),threshold)
                    if best is None or choice<best[0]:
                        best=(choice,model,{'depth':depth,'min_samples':minimum,'balanced_priors':balanced,
                                           'threshold':threshold,'validation_false_alert_clips':fp,
                                           'validation_detected_collision_clips':tp})
                trials.append({'depth':depth,'min_samples':minimum,'balanced_priors':balanced})
    _,model,parameters=best
    destination=root/'detection/models/stop-zone-collision-day-night.xml'
    if (output/'selection.json').exists():raise ValueError('Preserve existing tuning run')
    if augment_legacy and destination.exists():
        existing=json.loads(destination.with_suffix('.json').read_text())
        old_score=(existing['validation_false_alert_clips'],-existing['validation_detected_collision_clips'])
        new_score=(parameters['validation_false_alert_clips'],-parameters['validation_detected_collision_clips'])
        if new_score>=old_score:
            write_json(output/'selection.json',{'selected':parameters,'promoted':False,
                'reason':'No improvement on validation; retain prior candidate','test_used_for_selection':False})
            print('RETAINED_PREVIOUS',parameters,flush=True);return
    for p in [destination,destination.with_suffix('.json')]:
        if p.exists():shutil.copy2(p,output/('initial-'+p.name))
    if (data/'verification.json').exists():shutil.copy2(data/'verification.json',output/'initial-verification.json')
    model.save(str(destination))
    metadata={'features':FEATURE_NAMES,**parameters,'synthetic_only':True,
              'detector_weights_sha256':hashlib.sha256((root/'detection/models/simulation-cctv-day-night.pt').read_bytes()).hexdigest(),
              'focus':[230/720,130/480,440/720,270/480],
              'training_samples':len(train_rows),'training_classes':dict(Counter(y.tolist())),
              'training_clips':40,'validation_clips':20,'test_clips':20,
              'legacy_training_feature_augmentation':augment_legacy,
              'training_feature_sources':['current_detector','legacy_detector'] if augment_legacy else ['current_detector'],
              'selection':'30 training-only RF configurations; select on validation false alerts, then detected collisions',
              'test_used_for_selection':False,
              'labels':'Training physics contact participants; runtime uses visual detections and causal history only'}
    write_json(destination.with_suffix('.json'),metadata)
    write_json(data/'training-report.json',metadata)
    write_json(output/'selection.json',{'selected':parameters,'configurations_evaluated':len(trials),
                                      'test_used_for_selection':False})
    print('SELECTED',parameters,flush=True)
    # Only after selection is final, replay validation and held-out test scenes.
    verify(data,destination,root/'detection/config/geumchon-city-lab.context.json')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--augment-legacy',action='store_true')
    main(p.parse_args().augment_legacy)
