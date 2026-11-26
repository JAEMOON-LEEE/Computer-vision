"""Calibrate paired reference distances on validation only, then evaluate test."""
import json, math
from pathlib import Path
from detection.facility_paired_study import summarize

root=Path.cwd()/'runs/facility-improvement-20261117'
data=json.loads((root/'paired-study.json').read_text(encoding='utf8'))
out=root/'paired-calibration.json'
if out.exists(): raise ValueError('Preserve previous calibration')
clips=data['clips']; models={}
for kind in ('guardrail','manhole'):
    val=[c for c in clips if c['split']=='val']; test=[c for c in clips if c['split']=='test']
    choices=[]
    for n in range(1001):
        threshold=n/2000
        m=summarize(val,kind,threshold); positives=m['tp']+m['fn']
        if positives and m['tp']>=math.ceil(.9*positives): choices.append((m['fp'],-m['tp'],-threshold,threshold))
    if not choices: models[kind]={'status':'no_validation_threshold_meets_constraint'}; continue
    threshold=min(choices)[-1]
    models[kind]={'threshold':threshold,'validation':summarize(val,kind,threshold),'test':summarize(test,kind,threshold)}
result={'threshold_grid':'0..0.5 step 0.0005; expanded after coarse 0.005 grid failed validation',
        'constraint':'at least 90% validation recall, then minimize validation FP; example only',
        'notice':'Small paired synthetic data; simulated vehicle boxes; not actual CCTV visibility or deployment', 'models':models}
out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(models,ensure_ascii=False))
