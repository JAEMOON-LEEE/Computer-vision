"""Compare temporal gate and any single valid frame at the same score threshold."""
import json
from pathlib import Path
from detection.facility_paired_study import decide

root=Path.cwd()/'runs/facility-improvement-20261117'
clips=json.loads((root/'paired-study.json').read_text(encoding='utf8'))['clips']
models=json.loads((root/'paired-calibration.json').read_text(encoding='utf8'))['models']
out=root/'temporal-comparison.json'
if out.exists(): raise ValueError('Preserve previous result')
report={'note':'Threshold chosen for the temporal rule on validation, then also applied to any-frame check; small synthetic paired clips, no deployment claim.','models':{}}
for kind in ('guardrail','manhole'):
    threshold=models[kind]['threshold']; rows=[]
    for clip in clips:
        if clip['split']!='test' or clip['kind']!=kind or not clip['reference_ready']: continue
        gated=decide(clip['series'],kind,threshold)
        if not gated['evaluable']: continue
        single=any(p['visible'] and p['distance']>=threshold for p in clip['series'])
        rows.append({'variant':clip['variant'],'seed':clip['seed'],'label':clip['label'],'any_frame':single,'temporal':gated['alert']})
    def counts(key):
        return {name:sum((r['label']==label and r[key]==alert) for r in rows) for name,label,alert in [('tp',1,True),('fn',1,False),('fp',0,True),('tn',0,False)]}
    report['models'][kind]={'threshold':threshold,'eligible':len(rows),'any_frame':counts('any_frame'),'temporal':counts('temporal'),'sessions':rows}
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:{a:b for a,b in v.items() if a!='sessions'} for k,v in report['models'].items()},ensure_ascii=False))
