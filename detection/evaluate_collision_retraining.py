"""Fixed before/after object tests; no parameter selection or training."""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
import time
import hashlib
import yaml

from .collision_scenes import read,lines
from .evaluate_detection import evaluate,average_precision
from .runner import write_json
from .warnings import iou


def grouped(result_folder,data):
    source=Path(data).parent
    cases=read('runs/collision-v1/scene-audit.json')['clips']
    domain={hashlib.sha256(str(Path(e['source']).resolve()).encode()).hexdigest()[:10]:e['lighting']
            for e in cases if e['split']=='test'}
    names=['person','car','pothole','debris','barrier'];groups={}
    for record in lines(Path(result_folder)/'detections.jsonl'):
        image=record['image'];parts=Path(image).stem.split('_')
        label='new-'+domain[parts[1]] if parts[0]=='focus' else 'retained'
        from .sources import decode_image
        h,w=decode_image(source/'images/test'/image).shape[:2]
        gt={name:[] for name in names}
        for row in (source/'labels/test'/(Path(image).stem+'.txt')).read_text().splitlines():
            if not row.strip():continue
            cls,cx,cy,bw,bh=map(float,row.split())
            gt[names[int(cls)]].append([(cx-bw/2)*w,(cy-bh/2)*h,(cx+bw/2)*w,(cy+bh/2)*h])
        group=groups.setdefault(label,{'images':0,'positive':Counter(),'tp':Counter(),'fp':Counter(),'samples':{n:[] for n in names}})
        group['images']+=1
        for name in names:
            boxes=gt[name];group['positive'][name]+=len(boxes);used=set()
            for pred in sorted((d for d in record['detections'] if d['class_name']==name),key=lambda d:-d['confidence']):
                overlap,index=max(((iou(pred['bbox_xyxy'],box),i) for i,box in enumerate(boxes) if i not in used),default=(0,-1))
                matched=overlap>=.5
                if matched:used.add(index)
                group['samples'][name].append((pred['confidence'],matched))
                if pred['confidence']>=.25:group['tp' if matched else 'fp'][name]+=1
    output={}
    for name,g in groups.items():
        output[name]={'images':g['images'],'classes':{}}
        for cls in names:
            positives=g['positive'][cls];tp=g['tp'][cls];fp=g['fp'][cls]
            output[name]['classes'][cls]={'ground_truth':positives,'true_positives':tp,'false_positives':fp,
                'precision':tp/(tp+fp) if tp+fp else 0,'recall':tp/positives if positives else None,
                'AP50':average_precision(g['samples'][cls],positives)}
    return output


def main():
    out=Path('runs/collision-v2');out.mkdir(exist_ok=True)
    while not (out/'detector-complete.json').exists():time.sleep(30)
    report={'synthetic_only':True,'test_used_for_selection':False,'fixed_test_previously_benchmarked':True,'models':{}}
    data='datasets/day-night-collision-v2/dataset.yaml'
    for tag,weights in [('before','detection/models/simulation-cctv-day-night.pt'),('after','detection/models/simulation-cctv-collision-v2.pt')]:
        target=out/'object-evaluation'/tag
        if (target/'metrics.json').exists():metrics=read(target/'metrics.json')
        else:metrics=evaluate(data,weights,target,imgsz=640)
        report['models'][tag]={'metrics':metrics,'groups':grouped(target,data),
            'weights_sha256':hashlib.sha256(Path(weights).read_bytes()).hexdigest()}
        write_json(out/'object-comparison.json',report)
    print('OBJECT_COMPARISON_COMPLETE',flush=True)


if __name__=='__main__':main()
