"""Evaluate old and fine-tuned YOLO on the same vehicle-free test scenes only."""
import json
from collections import Counter
from pathlib import Path
import cv2,numpy as np
from detection.evaluate_detection import evaluate,average_precision
from detection.warnings import iou
ROOT=Path.cwd(); W=ROOT/'runs/centerline-near-20261118'; DATA=W/'dataset'
NAMES=['pothole','debris','delineator_normal','delineator_broken','delineator_fallen','manhole_normal','manhole_abnormal','guardrail_normal','guardrail_abnormal']
models={'previous':ROOT/'runs/unified-yolo-20261118/training/weights/best.pt','retrained':W/'training/weights/best.pt'}
if not (W/'training-complete.json').is_file(): raise ValueError('Training is not complete')
rows=json.loads((DATA/'manifest.json').read_text(encoding='utf8'))
def subset(name):
    predictions={r['image']:r['detections'] for r in map(json.loads,(W/('test-'+name)/'detections.jsonl').read_text(encoding='utf8').splitlines())}
    samples=[r for r in rows if r['split']=='test' and r['origin']=='centerline_nearest']; counts=Counter(); matches={n:[] for n in NAMES}; threshold={n:[0,0] for n in NAMES}
    for row in samples:
        image=DATA/row['image']; img=cv2.imdecode(np.fromfile(str(image),dtype='uint8'),cv2.IMREAD_COLOR); h,w=img.shape[:2]; truths={n:[] for n in NAMES}
        for line in (DATA/row['label']).read_text().splitlines():
            c,cx,cy,bw,bh=map(float,line.split()); cls=NAMES[int(c)]; truths[cls].append([(cx-bw/2)*w,(cy-bh/2)*h,(cx+bw/2)*w,(cy+bh/2)*h]); counts[cls]+=1
        for cls in NAMES:
            used=set()
            for p in sorted((p for p in predictions[image.name] if p['class_name']==cls),key=lambda p:-p['confidence']):
                overlap,index=max(((iou(p['bbox_xyxy'],b),i) for i,b in enumerate(truths[cls]) if i not in used),default=(0,-1))
                hit=overlap>=.5
                if hit: used.add(index)
                matches[cls].append((p['confidence'],hit))
                if p['confidence']>=.25: threshold[cls][0 if hit else 1]+=1
    result={}
    for cls in NAMES:
        tp,fp=threshold[cls]; gt=counts[cls]
        result[cls]={'ground_truth':gt,'tp':tp,'fp':fp,'recall':tp/gt if gt else None,'AP50':average_precision(matches[cls],gt)}
    return {'images':len(samples),'classes':result}
result={}
for name,weights in models.items():
    report=evaluate(str(DATA/'dataset.yaml'),str(weights),W/('test-'+name),split='test',imgsz=512)
    result[name]={'all':report,'centerline_nearest':subset(name)}
(W/'comparison-test.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print('COMPARISON_COMPLETE',flush=True)
