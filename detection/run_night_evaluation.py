"""Compare held-out day/night detection, retrain motion decisions, and replay real night footage."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import shutil
import time
import cv2
import numpy as np

from .evaluate_detection import evaluate
from .engine import Detector
from .runner import annotate, write_json
from .sources import decode_image
from .train_stop_collision import collect, train, verify
from .verify_simulation import verify as verify_warnings
from .warnings import WarningEngine


def main():
    root=Path.cwd();out=root/'runs/night-v1';ev=out/'evaluation';ev.mkdir(parents=True,exist_ok=True)
    deadline=time.monotonic()+7200
    while not (out/'training-complete.json').exists():
        if time.monotonic()>deadline:raise TimeoutError('Training incomplete')
        print('waiting_for_training',flush=True);time.sleep(30)
    focus=(230/720,130/480,440/720,270/480)
    old=root/'detection/models/simulation-cctv-queue.pt'
    new=root/'detection/models/simulation-cctv-day-night.pt'
    context=root/'detection/config/geumchon-city-lab.context.json'
    reports={}
    for domain,data in [('night','night-v1-full'),('day','geumchon-detail-full')]:
        reports[domain]={}
        for tag,weights in [('before',old),('after',new)]:
            target=ev/(domain+'-'+tag)
            if (target/'metrics.json').exists():r=json.loads((target/'metrics.json').read_text())
            else:r=evaluate(root/'datasets'/data/'dataset.yaml',str(weights),target,imgsz=640,focus=focus)
            reports[domain][tag]=r
    write_json(ev/'comparison.json',reports)
    exports=root/'simulation/TwinSightSim/TwinSightExport'
    while not (root/'simulation/TwinSightSim/Logs/night-v1-capture-complete.txt').exists():
        if time.monotonic()>deadline:raise TimeoutError('Temporal capture incomplete')
        print('waiting_for_temporal_capture',flush=True);time.sleep(30)
    for domain,prefix in [('night','nightqueue-v1-'),('day','queue-v2-')]:
        target=out/('temporal-'+domain)
        if not (target/'manifest.json').exists():collect(exports,target,new,context,prefix)
    combined=out/'temporal-combined';combined.mkdir(exist_ok=True)
    entries=[];candidates=[]
    for domain in ['day','night']:
        target=out/('temporal-'+domain)
        entries+=json.loads((target/'manifest.json').read_text())
        candidates+=(target/'candidates.jsonl').read_text().splitlines()
        for e in json.loads((target/'manifest.json').read_text()):
            shutil.copytree(target/e['clip'],combined/e['clip'],dirs_exist_ok=True)
    write_json(combined/'manifest.json',entries)
    (combined/'candidates.jsonl').write_text('\n'.join(candidates)+'\n',encoding='utf-8')
    classifier=root/'detection/models/stop-zone-collision-day-night.xml'
    if not classifier.exists():train(combined,classifier,new)
    from .tune_night_temporal import main as tune_temporal
    if not (out/'temporal-tuning/selection.json').exists():tune_temporal(False)
    if not (out/'temporal-tuning-augmented/selection.json').exists():tune_temporal(True)
    temporal=verify(combined,classifier,context)
    for domain,prefix in [('night','night-v1-clip-'),('day','geumchon-detail-clip-')]:
        target=out/'warning-checks'/domain
        if not (target/'verification.json').exists():
            verify_warnings(exports,prefix,str(new),target,str(context),640,focus,str(classifier),save_images=False)
    capture=root/'runs/real-cctv-20261022/hls-geumchon-v2'
    real=ev/'real-night-after'
    if not (real/'summary.json').exists():
        real.mkdir(exist_ok=True);(real/'annotated').mkdir(exist_ok=True)
        meta=json.loads((capture/'capture.json').read_text())
        frames=[json.loads(s) for s in (capture/'frames.jsonl').read_text().splitlines()]
        road=json.loads((root/'runs/real-cctv-20261022/real-road-context.json').read_text())
        model=Detector(str(new),track=True,focus=focus);engine=WarningEngine(road,stop_model=classifier)
        counts=Counter();alerts=[];times=[]
        write_json(real/'session.json',{'source':'preserved 120-second real ITS night footage; source PTS',
            'detector':model.metadata(),'training_use':False,'ground_truth_available':False})
        with (real/'detections.jsonl').open('w',encoding='utf-8') as stream:
            for row in frames:
                image=decode_image(capture/row['image']);boxes,ms=model.predict(image)
                record={**row,'detections':boxes,'inference_ms':ms}
                warning=engine.update(record);alerts+=warning;times.append(ms)
                counts.update(d['class_name'] for d in boxes)
                stream.write(json.dumps(record)+'\n')
                if row['frame']%25==0 or warning:
                    cv2.imencode('.jpg',annotate(image,boxes,warning))[1].tofile(str(real/'annotated'/f"{row['frame']:06d}.jpg"))
        (real/'alerts.jsonl').write_text(''.join(json.dumps(a)+'\n' for a in alerts),encoding='utf-8')
        write_json(real/'summary.json',{'frames':len(frames),'media_seconds':meta['media_seconds'],
            'detections_by_class':dict(counts),'alerts_by_type':dict(Counter(a['type'] for a in alerts)),
            'warm_mean_inference_ms':float(np.mean(times[1:])),'ground_truth_available':False,
            'accuracy_evaluated':False,'training_use':False,'timestamp_basis':'original source PTS'})
    write_json(out/'evaluation-complete.json',{'synthetic_only_training':True,
        'day_night_detection_comparison':'evaluation/comparison.json',
        'temporal_validation_test_passed':temporal['passed'],
        'real_ground_truth_available':False})
    print('EVALUATION_COMPLETE',flush=True)


if __name__=='__main__':main()
