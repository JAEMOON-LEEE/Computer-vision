"""Study paired synthetic references, visibility proxy, and temporal evidence.

Ground-truth boxes and camera stability are oracle simulation inputs, not an
evaluation of a deployed vehicle detector or real CCTV visibility.
"""
import json, math, re, runpy
from pathlib import Path
from detection.facility_reference import ReferenceBank, assess_visibility
from detection.facility_state import FacilityEvidenceGate
from detection.sources import confined_image, decode_image

ROOT=Path.cwd()
DATA=ROOT/'simulation/TwinSightSim/TwinSightExport/facility-paired-day-20261117'
OUT=ROOT/'runs/facility-improvement-20261117/paired-study.json'
ref=runpy.run_path(str(ROOT/'runs/manhole-facility-20261117/train_facilities.py'))
make_roi=ref['make_roi']
pat=re.compile(r'^facility-(train|val|test)-Day-(.+)-(reference|target)-s(\d+)_')


def load(session):
    return json.loads((session/'camera.json').read_text(encoding='utf-8-sig')), [json.loads(s) for s in (session/'ground_truth.jsonl').read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def boxes(row):
    return [o['bbox_xyxy'] for o in row.get('objects',[]) if o.get('class_name') in ('car','truck','bus')]


def decide(series, kind, threshold):
    gate=FacilityEvidenceGate(kind, threshold, min_duration_seconds=.5,min_observations=3,max_gap_seconds=.25)
    alerted=False; valid_start=None; sufficient=False; reasons={}
    for point in series:
        visible=point['visible']; timestamp=point['time']
        reasons[point['reason']]=reasons.get(point['reason'],0)+1
        if visible:
            if valid_start is None: valid_start=timestamp
            if timestamp-valid_start>=.5: sufficient=True
        else: valid_start=None
        state=gate.update(timestamp,point['distance'] if visible else None,visible=visible,camera_stable=True)
        alerted |= state=='suspected_change'
    return {'alert':alerted,'evaluable':sufficient,'reasons':reasons}


def summarize(clips, kind, threshold):
    rows=[(c,decide(c['series'],kind,threshold)) for c in clips if c['kind']==kind and c['reference_ready']]
    eligible=[(c,d) for c,d in rows if d['evaluable']]
    return {'eligible':len(eligible),'unknown_or_too_short':len([c for c in clips if c['kind']==kind])-len(eligible),
      'tp':sum(c['label']==1 and d['alert'] for c,d in eligible),
      'fn':sum(c['label']==1 and not d['alert'] for c,d in eligible),
      'fp':sum(c['label']==0 and d['alert'] for c,d in eligible),
      'tn':sum(c['label']==0 and not d['alert'] for c,d in eligible)}


def main():
    if OUT.exists(): raise ValueError('Preserve existing results')
    if not (DATA/'capture-complete.txt').is_file(): raise ValueError('Capture incomplete')
    groups={}
    for path in DATA.glob('facility-*'):
        if not path.is_dir(): continue
        m=pat.match(path.name)
        if not m: raise ValueError('Unrecognized path: '+str(path))
        split,variant,role,seed=m.groups()
        key=(split,variant,int(seed))
        if role in groups.setdefault(key,{}): raise ValueError('Duplicate pair role')
        groups[key][role]=path
    if len(groups)!=54 or any(set(v)!={'reference','target'} for v in groups.values()): raise ValueError('Missing reference-target pair')
    clips=[]
    for (split,variant,seed),pair in sorted(groups.items()):
        rc,rr=load(pair['reference']); tc,tr=load(pair['target'])
        if len(rr)!=24 or len(tr)!=24: raise ValueError('Incomplete paired clip')
        rtruth=rr[0]['scenario']['facility']; ttruth=tr[0]['scenario']['facility']
        if rr[0]['scenario']['seed']!=seed or tr[0]['scenario']['seed']!=seed or rtruth['state']!='normal': raise ValueError('Invalid pair truth')
        if rtruth['kind']!=ttruth['kind'] or rtruth['reference_position_world']!=ttruth['reference_position_world'] or abs(rtruth['scale']-ttruth['scale'])>1e-6:
            raise ValueError('Pair has different seeded reference geometry')
        roi=make_roi(rc,rtruth)
        if roi!=make_roi(tc,ttruth): raise ValueError('Reference and target ROI differ')
        bank=ReferenceBank(); key=f'{split}-{seed}'; ready=0
        for row in rr[:6]:
            image=decode_image(confined_image(pair['reference'],row['image']))
            quality=assess_visibility(image,roi,vehicle_boxes=boxes(row),detector_healthy=True,camera_stable=True,min_focus=5)
            if quality['visible']:
                bank.register(split,key,image,roi,confirmed_normal=True); ready+=1
                if ready==3: break
        series=[]
        if ready:
            for row in tr:
                image=decode_image(confined_image(pair['target'],row['image']))
                quality=assess_visibility(image,roi,vehicle_boxes=boxes(row),detector_healthy=True,camera_stable=True,min_focus=5)
                d=bank.distance(split,key,image,roi) if quality['visible'] else None
                series.append({'time':row['timestamp'],'visible':quality['visible'],'reason':quality['reason'],'distance':d})
        clips.append({'split':split,'kind':ttruth['kind'],'variant':variant,'seed':seed,'label':int(ttruth['state']=='abnormal'),
          'reference':str(pair['reference']),'target':str(pair['target']),'roi':roi,'reference_count':ready,'reference_ready':ready>0,'series':series})
    print('PAIRED_FEATURES_READY',flush=True)
    report={'synthetic_only':True,'production_ready':False,'reference':'up to 3 visible frames from same-seed normal reference session',
       'visibility':'simulated truth vehicle boxes and assumed stable camera, Laplacian variance >=5; NOT an actual detector or visibility proof',
       'gate':'0.5 seconds, at least 3 observations, gaps <=0.25 seconds; trial values, not deployment settings',
       'selection':'minimum validation false positives with at least 90% validation recall, threshold 0.005..0.5; illustrative, small sample',
       'models':{},'clips':clips}
    for kind in ('guardrail','manhole'):
        val=[c for c in clips if c['split']=='val']; test=[c for c in clips if c['split']=='test']
        candidates=[]
        for n in range(1,101):
            t=n/200; m=summarize(val,kind,t); positives=m['tp']+m['fn']
            if positives and m['tp']>=math.ceil(.9*positives): candidates.append((m['fp'],-m['tp'],-t,t))
        if not candidates:
            report['models'][kind]={'status':'no_validation_threshold_meets_constraint'}; continue
        t=min(candidates)[-1]
        report['models'][kind]={'threshold':t,'validation':summarize(val,kind,t),'test':summarize(test,kind,t)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps(report['models'],ensure_ascii=False),flush=True)


if __name__=='__main__': main()
