"""Reproducible night-v1 preparation and fine-tuning; independent clips stay held out."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

import torch
import yaml
from ultralytics import YOLO

from .dataset import check_dataset
from .prepare_unity import prepare_unity
from .prepare_focus import prepare
from .prepare_day_night import merge
from .runner import write_json


def main(epochs, batch=4, reuse_prepared=False):
    root = Path.cwd()
    exports = root/'simulation/TwinSightSim/TwinSightExport'
    output = root/'runs/night-v1'
    output.mkdir(parents=True,exist_ok=True)
    if (output/'training-complete.json').exists():
        raise ValueError('Preserve completed training; select a new experiment version')
    sessions = {}
    deadline = time.monotonic()+3600
    while len(sessions)!=3:
        for split,n in [('train',160),('val',40),('test',40)]:
            for folder in sorted(exports.glob('night-v1-'+split+'-*')):
                gt=folder/'ground_truth.jsonl'
                if gt.is_file() and len(gt.read_text(encoding='utf-8-sig').splitlines())==n:
                    rows=[json.loads(s) for s in gt.read_text(encoding='utf-8-sig').splitlines()]
                    if any(r['lighting']['time_of_day']!='Night' or r['lighting']['sun_intensity']>0.101 for r in rows):
                        raise ValueError('Night lighting was overridden: reject this capture')
                    sessions[split]=[folder]
        if len(sessions)==3: break
        if time.monotonic()>deadline: raise TimeoutError('Night capture incomplete')
        print('waiting_for_capture',list(sessions),flush=True);time.sleep(30)
    time.sleep(2)
    classes=['person','car','pothole','debris','barrier']
    full=root/'datasets/night-v1-full'
    focused=root/'datasets/night-v1-focus'
    mixed=root/'datasets/day-night-v1'
    if reuse_prepared:
        previous=json.loads((full/'provenance.json').read_text())
        if previous['sessions']!={s:[str(p.resolve()) for p in folders] for s,folders in sessions.items()}:
            raise ValueError('Prepared data uses different capture sessions')
        check_dataset(full/'dataset.yaml');check_dataset(focused/'dataset.yaml');check_dataset(mixed/'dataset.yaml')
    else:
        prepare_unity(sessions,full,classes)
    focus=(230/720,130/480,440/720,270/480)
    if not reuse_prepared:
        prepare(full/'dataset.yaml',full/'dataset.yaml',focused,focus)
        merge(root/'datasets/queue-objects-focus/dataset.yaml',focused/'dataset.yaml',mixed)
    resolved,report=check_dataset(mixed/'dataset.yaml')
    write_json(output/'dataset-check.json',report)
    data=output/'dataset.resolved.yaml'
    data.write_text(yaml.safe_dump(resolved,sort_keys=False),encoding='utf-8')
    weights=root/'detection/models/simulation-cctv-queue.pt'
    torch.set_num_threads(4)
    model=YOLO(str(weights))
    model.train(data=str(data),epochs=epochs,imgsz=640,batch=batch,device='cpu',workers=0,
                seed=22042,deterministic=True,patience=20,freeze=10,mosaic=0.1,
                hsv_v=0.25,project=str(output),name='detector',plots=True,exist_ok=False)
    best=output/'detector/weights/best.pt'
    destination=root/'detection/models/simulation-cctv-day-night.pt'
    if destination.exists(): raise ValueError('Preserve previous model destination')
    shutil.copy2(best,destination)
    write_json(output/'training-complete.json',{'epochs':epochs,'batch':batch,'weights':str(destination),
        'sha256':hashlib.sha256(best.read_bytes()).hexdigest(),
        'initial_weights':str(weights),'initial_sha256':hashlib.sha256(weights.read_bytes()).hexdigest(),
        'synthetic_only':True,'real_cctv_used_for_training':False,'focus':focus,
        'train_split_only_used_for_gradients':True,'best_selected_on':'val',
        'sessions':{s:[str(p) for p in folders] for s,folders in sessions.items()}})
    print('TRAINING_COMPLETE',str(destination),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--epochs',type=int,default=12)
    p.add_argument('--batch',type=int,default=4);p.add_argument('--reuse-prepared',action='store_true')
    a=p.parse_args();main(a.epochs,a.batch,a.reuse_prepared)
