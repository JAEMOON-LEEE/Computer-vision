"""Vehicle-free daytime dataset, with new centerline/near facility scenes."""
import hashlib,json,shutil
from collections import Counter
from pathlib import Path
import yaml
from detection.dataset import check_dataset
from detection.facility_audit import audit_facility_splits
from detection.sources import confined_image

ROOT=Path.cwd(); WORK=ROOT/'runs/centerline-near-20261118'; DATA=WORK/'dataset'
BASE=ROOT/'runs/unified-yolo-20261118/dataset-no-vehicle'
CAPTURE=ROOT/'simulation/TwinSightSim/TwinSightExport/centerline-nearest-day-20261118'
NAMES=['pothole','debris','delineator_normal','delineator_broken','delineator_fallen','manhole_normal','manhole_abnormal','guardrail_normal','guardrail_abnormal']
if DATA.exists(): raise ValueError('Dataset output already exists; preserve it')
if not (CAPTURE/'capture-complete.txt').is_file(): raise ValueError('Capture incomplete')
splits={s:sorted(CAPTURE.glob('facility-'+s+'-*')) for s in ('train','val','test')}
if any(len(x)!=288 for x in splits.values()): raise ValueError('Unexpected capture count')
audit=audit_facility_splits(splits); records=[]; excluded=[]; seen={k:{} for k in ('seed','session','hash')}
def add(split,img,label,meta):
    img=Path(img); digest=hashlib.sha256(img.read_bytes()).hexdigest()
    for field,value in [('seed',meta['seed']),('session',meta['source_session']),('hash',digest)]:
        if value in seen[field] and seen[field][value]!=split: raise ValueError('Cross-split '+field)
        seen[field][value]=split
    stem=hashlib.sha256((meta['source_session']+'|'+str(meta['source_frame'])).encode()).hexdigest()[:24]
    target=DATA/'images'/split/(stem+img.suffix.lower()); lbl=DATA/'labels'/split/(stem+'.txt')
    target.parent.mkdir(parents=True,exist_ok=True); lbl.parent.mkdir(parents=True,exist_ok=True)
    if target.exists(): raise ValueError('Duplicate frame')
    shutil.copyfile(img,target); lbl.write_text(label,encoding='utf8')
    records.append({**meta,'split':split,'image':str(target.relative_to(DATA)),'label':str(lbl.relative_to(DATA)),'sha256':digest})
def vehicles(row): return [o for o in row['objects'] if o['class_name'] in ('car','truck','bus','motorcycle')]

for r in json.loads((BASE/'manifest.json').read_text(encoding='utf8')):
    if not r.get('no_vehicle_requested'): continue
    session=Path(r['source_session']); lines=[json.loads(x) for x in (session/'ground_truth.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
    source=[x for x in lines if x['frame']==r['source_frame']]
    if len(source)!=1 or vehicles(source[0]): raise ValueError('Source contains vehicle or missing frame')
    if source[0]['lighting']['time_of_day']!='Day': raise ValueError('Day-only')
    meta={k:v for k,v in r.items() if k not in ('split','image','label','sha256')}; meta['origin']='prior_explicit_no_vehicle'
    add(r['split'],BASE/r['image'],(BASE/r['label']).read_text(encoding='utf8'),meta)

for split,sessions in splits.items():
    for session in sessions:
        lines=[json.loads(x) for x in (session/'ground_truth.jsonl').read_text(encoding='utf-8-sig').splitlines() if x.strip()]
        if len(lines)!=1: raise ValueError('One frame per scene required')
        row=lines[0]; f=row['scenario']['facility']; variant=f['variant']; pos=f['reference_position_world']
        if row['lighting']['time_of_day']!='Day' or vehicles(row): raise ValueError('Unexpected lighting or tracked vehicle')
        if not -7.001<=pos[0]<=-2.999: raise ValueError('Wrong near position')
        if f['kind'] in ('delineator','guardrail') and abs(pos[2]-(-.41))>1e-4: raise ValueError('Not on centerline')
        if f['kind']=='delineator':
            expected={'DelineatorNormal':'delineator_normal','DelineatorBroken':'delineator_broken','DelineatorFallen':'delineator_fallen','DelineatorMissing':None}[variant]
        else: expected=f['kind']+'_'+f['state']
        objs=[o for o in row['objects'] if o['class_name'] in NAMES]
        if (expected is None and objs) or (expected is not None and (len(objs)!=1 or objs[0]['class_name']!=expected or objs[0]['truncated'])):
            excluded.append({'split':split,'session':str(session),'variant':variant,'reason':'missing_wrong_or_truncated_box'}); continue
        labels=[]; w,h=row['width'],row['height']
        for obj in objs:
            x1,y1,x2,y2=obj['bbox_xyxy']
            if x2-x1<2 or y2-y1<2: raise ValueError('Tiny emitted box')
            labels.append(f"{NAMES.index(obj['class_name'])} {(x1+x2)/(2*w):.9f} {(y1+y2)/(2*h):.9f} {(x2-x1)/w:.9f} {(y2-y1)/h:.9f}\n")
        add(split,confined_image(session,row['image']),''.join(labels),{'origin':'centerline_nearest','source_session':str(session),'source_frame':row['frame'],
            'seed':row['scenario']['seed'],'variant':variant,'state':f['state'],'reference_position_world':pos,'actual_position_world':f['actual_position_world'],
            'no_vehicle_requested':True,'visibility':'not_measured','bbox_source':'Unity projected amodal renderer bounds'})
config={'path':str(DATA.resolve()),'names':dict(enumerate(NAMES)),'train':'images/train','val':'images/val','test':'images/test'}
(DATA/'dataset.yaml').write_text(yaml.safe_dump(config,sort_keys=False),encoding='utf8')
(DATA/'manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
(DATA/'provenance.json').write_text(json.dumps({'synthetic_only':True,'daytime_only':True,'no_tracked_vehicle':True,'human_review_complete':False}),encoding='utf8')
_,check=check_dataset(DATA/'dataset.yaml')
summary={'check':check,'source_audit':audit,'by_origin_split':{s:dict(Counter(r['origin'] for r in records if r['split']==s)) for s in splits},
         'by_case_split':{s:dict(Counter(r['variant'] for r in records if r['split']==s)) for s in splits},'excluded':dict(Counter(r['reason'] for r in excluded)),
         'limitations':'Vehicle check uses Unity tracked objects and hides one known static vehicle mesh; static scene not exhaustively verified. Amodal boxes, human review incomplete, same city and similar views.'}
(WORK/'dataset-report.json').write_text(json.dumps(summary,indent=2),encoding='utf8'); (WORK/'excluded.json').write_text(json.dumps(excluded,indent=2),encoding='utf8')
print(json.dumps(summary,indent=2),flush=True)
