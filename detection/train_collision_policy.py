"""Train/validate visual collision decisions; physics truth is offline only."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np
from .collision_policy import FEATURE_NAMES,ObservationPolicy,CollisionPolicy
from .collision_scenes import read,lines,FOCUS
from .engine import Detector
from .runner import run_predictions,write_json
from .warnings import WarningEngine,iou

ROOT=Path.cwd();OUT=ROOT/'runs/collision-v2';WEIGHTS=ROOT/'detection/models/simulation-cctv-collision-v2.pt'
POLICY=ROOT/'detection/models/collision-policy-v2.xml'
ROAD=ROOT/'detection/config/geumchon-city-lab.context.json'


def entries():
    result=[]
    for item in read(ROOT/'runs/collision-v1/scene-audit.json')['clips']:
        source=Path(item['source'])
        result.append({**item,'clip':source.name,'case':item['scenario'],'domain':'varied',
                       'legacy_cache':None,'positive':item['expected_collision']})
    for item in read(ROOT/'runs/night-v1/temporal-combined/manifest.json'):
        result.append({**item,'domain':'legacy','lighting':'Night' if item['clip'].startswith('night') else 'Day',
                       'legacy_cache':str(ROOT/'runs/night-v1/temporal-combined'/item['clip']),
                       'positive':bool(item['physics_events'])})
    return result


def label(evidence,truth,events,now):
    identities=[];matches=[]
    for box,kind in zip(evidence['boxes'],evidence['classes']):
        overlap,identity=max(((iou(box,o['bbox_xyxy']),o['track_id'])
                             for o in truth['objects'] if o['class_name']==kind),default=(0,None))
        identities.append(identity if overlap>=.3 else None);matches.append(overlap)
    actual=[e for e in events if None not in identities and len(set(identities))==2
            and set(identities)=={e['object_a'],e['object_b']} and now>=e['timestamp']]
    return int(bool(actual)),identities


def predictions(entry,detector,cache_training=True):
    # Old training features are augmentation only. Validation/test use current weights.
    if entry['domain']=='legacy' and entry['split']=='train' and cache_training:
        folder=Path(entry['legacy_cache'])
    else:
        folder=OUT/'temporal'/entry['clip']
        if folder.exists() and (not (folder/'summary.json').exists() or read(folder/'summary.json').get('status')!='completed'):
            # Preserve an interrupted write (e.g. a disconnected external drive).
            base=(OUT/'temporal').resolve();source=folder.resolve()
            renamed=folder.with_name(folder.name+'.interrupted-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')).resolve()
            if not source.is_relative_to(base) or not renamed.is_relative_to(base):
                raise ValueError('Interrupted capture path outside experiment')
            source.rename(renamed)
        if not (folder/'summary.json').exists():
            detector.reset_tracking();run_predictions(detector,entry['source'],folder)
        metadata=read(folder/'session.json')
        if metadata['detector']['models'][0]['sha256']!=hashlib.sha256(WEIGHTS.read_bytes()).hexdigest():
            raise ValueError('Cached predictions use different weights')
    records=lines(folder/'detections.jsonl')
    if len(records)!=entry['frames'] or [r['frame'] for r in records]!=list(range(entry['frames'])):
        raise ValueError('Incomplete or duplicated prediction frames')
    return records


def collect(entry,records):
    truth=lines(Path(entry['source'])/'ground_truth.jsonl')
    engine=WarningEngine(read(ROAD),collision_model=ObservationPolicy());rows=[]
    for record in records:
        engine.update(record)
        for candidate in engine.collision_candidates:
            target,matched=label(candidate,truth[record['frame']],entry['physics_events'],record['timestamp'])
            rows.append({**candidate,'target':target,'matched_truth_ids':matched,
                'clip':entry['clip'],'split':entry['split'],'lighting':entry['lighting'],
                'domain':entry['domain'],'feature_source':'legacy_detector' if entry['domain']=='legacy' and entry['split']=='train' else 'current_detector'})
    return rows


def emissions(rows,scores,threshold):
    votes={};emitted=set();output=[]
    for row,score in zip(rows,scores):
        pair=tuple(row['pair']);now=row['timestamp']
        if pair in emitted:continue
        if not row['eligible'] or score<threshold:votes.pop(pair,None);continue
        start,last,count=votes.get(pair,(now,now,0))
        if now-last>.5:start,count=now,0
        count+=1;votes[pair]=(start,now,count)
        if count>=3 and now-start>=.25:
            emitted.add(pair);output.append(row)
    return output


def scores(model,rows):
    if not rows:return []
    votes=model.getVotes(np.asarray([r['features'] for r in rows],np.float32),0)
    column=int(np.flatnonzero(votes[0]==1)[0])
    return (votes[1:,column]/np.maximum(1,votes[1:].sum(axis=1))).tolist()


def fit(all_entries,rows):
    if POLICY.exists():raise ValueError('Preserve existing collision policy')
    selected=[]
    for entry in all_entries:
        if entry['split']!='train':continue
        part=[r for r in rows if r['clip']==entry['clip'] and r['eligible']]
        for target in (0,1):
            group=[r for r in part if r['target']==target]
            if group:selected.extend(group[i] for i in np.linspace(0,len(group)-1,min(20,len(group))).round().astype(int))
    x=np.asarray([r['features'] for r in selected],np.float32);y=np.asarray([r['target'] for r in selected],np.int32)
    if set(y.tolist())!={0,1}:raise ValueError('Need actual positive and negative training pairs')
    val_entries=[e for e in all_entries if e['split']=='val'];best=None;trials=[]
    for depth in (4,6,8):
      for minimum in (1,3):
       for balanced in (False,True):
        cv2.setRNGSeed(251025);model=cv2.ml.RTrees_create();model.setMaxDepth(depth);model.setMinSampleCount(minimum)
        model.setMaxCategories(2);model.setCalculateVarImportance(True)
        model.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER,128,0))
        if balanced:model.setPriors(np.asarray([1,sum(y==0)/sum(y==1)],np.float32))
        model.train(x,cv2.ml.ROW_SAMPLE,y)
        val={e['clip']:[r for r in rows if r['clip']==e['clip']] for e in val_entries}
        predicted={name:scores(model,part) for name,part in val.items()}
        thresholds=sorted({.55,.65,.75,.85,.95,1.001,*[min(1.001,s+.0001)
            for name,part in val.items() for r,s in zip(part,predicted[name]) if r['target']==0]})
        for threshold in thresholds:
            fp=tp=0;lighting=Counter()
            for e in val_entries:
                emitted=emissions(val[e['clip']],predicted[e['clip']],threshold)
                wrong=any(not r['target'] for r in emitted)
                hit=any(r['target'] for r in emitted)
                fp+=wrong;tp+=hit
                if hit and e['domain']=='varied':lighting[e['lighting']]+=1
            choice=(fp,-min(lighting['Day'],lighting['Night']),-tp,depth,minimum,int(balanced),threshold)
            if best is None or choice<best[0]:
                best=(choice,model,{'depth':depth,'minimum_samples':minimum,'balanced':balanced,
                    'threshold':threshold,'validation_false_alert_clips':int(fp),
                    'validation_true_collision_clips':int(tp),'validation_varied_by_lighting':dict(lighting)})
        trials.append({'depth':depth,'minimum_samples':minimum,'balanced':balanced})
    _,model,parameters=best;model.save(str(POLICY))
    metadata={'features':FEATURE_NAMES,**parameters,'synthetic_only':True,'production_ready':False,
        'detector_weights_sha256':hashlib.sha256(WEIGHTS.read_bytes()).hexdigest(),
        'focus':FOCUS,'training_samples':len(selected),'training_classes':dict(Counter(y.tolist())),
        'training_feature_sources':dict(Counter(r['feature_source'] for r in selected)),
        'test_used_for_selection':False,'fixed_test_previously_benchmarked':True,
        'fixed_candidate_gate':{'min_history_seconds':.5,'min_contact_seconds':.25,'min_observed_closing_normalized':.1,'consecutive_frames':3},
        'validation_selection':'min false clips; balance day/night varied hits; max total hits',
        'labels':'Offline physical contact participant matching after contact; runtime never reads truth',
        'training_clips':[e['clip'] for e in all_entries if e['split']=='train'],
        'validation_clips':[e['clip'] for e in val_entries]}
    write_json(POLICY.with_suffix('.json'),metadata)
    write_json(OUT/'policy-selection.json',{'selected':metadata,'trials':trials})
    print('POLICY_SELECTED',parameters,flush=True)


def verify(entry,records):
    truth=lines(Path(entry['source'])/'ground_truth.jsonl');engine=WarningEngine(read(ROAD),collision_model=POLICY)
    alerts=[];matched=[]
    for record in records:
        for alert in engine.update(record):
            alerts.append(alert)
            if not alert['type'].startswith('suspected_'):continue
            evidence={'boxes':[a['bbox_xyxy'] for a in alert['evidence']],
                      'classes':[a['class_name'] for a in alert['evidence']]}
            target,identities=label(evidence,truth[record['frame']],entry['physics_events'],alert['timestamp'])
            matched.append({'alert':alert,'correct_pair_after_contact':bool(target),'matched_truth_ids':identities})
    folder=OUT/'verification'/entry['clip'];folder.mkdir(parents=True,exist_ok=True)
    (folder/'alerts.jsonl').write_text(''.join(json.dumps(a)+'\n' for a in alerts),encoding='utf-8')
    return {'clip':entry['clip'],'case':entry['case'],'split':entry['split'],'domain':entry['domain'],
        'lighting':entry['lighting'],'positive':entry['positive'],'source':entry['source'],
        'collision_alerts':len(matched),'correct_pair_after_contact':any(a['correct_pair_after_contact'] for a in matched),
        'wrong_or_early_alerts':sum(not a['correct_pair_after_contact'] for a in matched),'alert_audit':matched}


def main(wait,verify_only=False):
    OUT.mkdir(exist_ok=True)
    if wait:
        while not (OUT/'detector-complete.json').exists():
            print('waiting_for_detector_training',flush=True);time.sleep(30)
    all_entries=entries();model=Detector(str(WEIGHTS),track=True,focus=FOCUS)
    if not verify_only:
        training=[]
        for entry in all_entries:
            if entry['split']=='test':continue
            destination=OUT/'features'/(entry['clip']+'.json')
            if destination.exists():part=read(destination)
            else:
                part=collect(entry,predictions(entry,model));destination.parent.mkdir(exist_ok=True)
                write_json(destination,part)
            training+=part
            print('COLLECTED',entry['split'],entry['lighting'],entry['case'],len(part),flush=True)
        fit(all_entries,training)
    else:
        metadata=read(POLICY.with_suffix('.json'))
        assert metadata==read(OUT/'policy-selection.json')['selected']
        assert metadata['detector_weights_sha256']==read(OUT/'detector-complete.json')['sha256']==hashlib.sha256(WEIGHTS.read_bytes()).hexdigest()
        CollisionPolicy(POLICY)
        progress=OUT/'policy-test-progress.json';backup=OUT/'policy-test-progress-before-resume.json'
        if progress.exists() and not backup.exists():write_json(backup,read(progress))
    results=[]
    for entry in all_entries:
        if entry['split']!='test':continue
        result=verify(entry,predictions(entry,model));results.append(result)
        write_json(OUT/'policy-test-progress.json',results)
        print('TEST',entry['domain'],entry['lighting'],entry['case'],'hit',result['correct_pair_after_contact'],'wrong',result['wrong_or_early_alerts'],flush=True)
    summary={'completed_at':datetime.now(timezone.utc).isoformat(),'synthetic_only':True,
        'test_used_for_selection':False,'fixed_test_previously_benchmarked':True,'clips':results,'groups':{}}
    for domain in ('varied','legacy'):
      for lighting in ('Day','Night'):
        group=[r for r in results if r['domain']==domain and r['lighting']==lighting]
        summary['groups'][domain+'-'+lighting]={'positive_clips':sum(r['positive'] for r in group),
            'correct_collision_clips':sum(r['correct_pair_after_contact'] for r in group if r['positive']),
            'negative_clips':sum(not r['positive'] for r in group),
            'negative_clips_with_alert':sum(r['collision_alerts']>0 for r in group if not r['positive']),
            'clips_with_wrong_or_early_alert':sum(r['wrong_or_early_alerts']>0 for r in group)}
    if verify_only and (OUT/'policy-test-progress-before-resume.json').exists():
        previous={e['clip']:e for e in read(OUT/'policy-test-progress-before-resume.json')}
        current={e['clip']:e for e in results}
        keys=('collision_alerts','correct_pair_after_contact','wrong_or_early_alerts')
        summary['resume_audit']={'previous_clips':len(previous),
            'previous_results_unchanged':all(all(p[k]==current[name][k] for k in keys) for name,p in previous.items()),
            'policy_refitted':False}
        assert summary['resume_audit']['previous_results_unchanged']
    write_json(OUT/'policy-verification.json',summary);print('POLICY_TRAINING_AND_TEST_COMPLETE',summary['groups'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--wait-for-detector',action='store_true')
    p.add_argument('--verify-only',action='store_true')
    args=p.parse_args();main(args.wait_for_detector,args.verify_only)
