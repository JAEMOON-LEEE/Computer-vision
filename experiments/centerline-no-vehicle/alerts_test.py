"""Frame-level state alert comparison from existing test predictions; no inference."""
import json
from collections import defaultdict,Counter
from pathlib import Path
W=Path.cwd()/'runs/centerline-near-20261118'; rows=json.loads((W/'dataset/manifest.json').read_text(encoding='utf8'))
kind_names={'Delineator':({'delineator_normal'},{'delineator_broken','delineator_fallen'}),
            'Guardrail':({'guardrail_normal'},{'guardrail_abnormal'}), 'Manhole':({'manhole_normal'},{'manhole_abnormal'})}
result={}
for model in ('previous','retrained'):
    pred={p['image']:p['detections'] for p in map(json.loads,(W/('test-'+model)/'detections.jsonl').read_text(encoding='utf8').splitlines())}
    groups={}
    for group in ('all','centerline_nearest'):
        totals=defaultdict(Counter)
        for row in (r for r in rows if r['split']=='test' and (group=='all' or r['origin']=='centerline_nearest')):
            k=next((k for k in kind_names if row['variant'].startswith(k)),None)
            if not k: continue
            if row['variant']=='DelineatorMissing': totals[k]['missing_excluded']+=1; continue
            normal,abnormal=kind_names[k]; boxes=[x for x in pred[Path(row['image']).name] if x['confidence']>=.25 and x['class_name'] in normal|abnormal]
            alert=any(x['class_name'] in abnormal for x in boxes); unknown=not boxes; state=row['state']
            totals[k][state]+=1; totals[k][state+'_alerts']+=int(alert); totals[k][state+'_unknown']+=int(unknown)
        groups[group]={k:dict(v) for k,v in totals.items()}
    result[model]=groups
(W/'alerts-test.json').write_text(json.dumps({'confidence':.25,'method':'any corresponding abnormal-class detection anywhere in image, without IoU; no detection is unknown and counts as no alert; missing excluded','models':result},indent=2),encoding='utf8')
print(json.dumps(result,indent=2))
