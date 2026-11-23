"""Fine-tune day/night vehicle poses while preserving prior hazard classes and splits."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import yaml
from .dataset import check_dataset
from .runner import write_json

KEYFRAMES={0,16,23,24,26,28,30,32,34,36,40,44,48,56,64,79}


def prepare(source, output):
    source,output=Path(source),Path(output)
    if output.exists() and any(output.iterdir()):raise ValueError("Preserve existing dataset")
    config=yaml.safe_load((source/'dataset.yaml').read_text(encoding='utf-8-sig'))
    target={'path':str(output.resolve()),'names':config['names']}
    counts={}
    for split in ('train','val','test'):
        images,labels=output/'images'/split,output/'labels'/split
        images.mkdir(parents=True);labels.mkdir(parents=True)
        count={'retained':0,'new_collision_keyframes':0}
        for image in sorted((source/'images'/split).iterdir()):
            supplemental=image.stem.startswith('focus_')
            if supplemental and int(image.stem.rsplit('_',1)[1]) not in KEYFRAMES:continue
            shutil.copy2(image,images/image.name)
            shutil.copy2(source/'labels'/split/(image.stem+'.txt'),labels/(image.stem+'.txt'))
            count['new_collision_keyframes' if supplemental else 'retained']+=1
        target[split]='images/'+split;counts[split]=count
    (output/'dataset.yaml').write_text(yaml.safe_dump(target,sort_keys=False),encoding='utf-8')
    _,checked=check_dataset(output/'dataset.yaml')
    write_json(output/'dataset-check.json',checked)
    write_json(output/'provenance.json',{'synthetic_only':True,'human_review_complete':False,
        'source':str(source.resolve()),'keyframes_per_new_clip':sorted(KEYFRAMES),'counts':counts,
        'splits':'preserved; no random frame splitting','lighting':'new clips include Day and Night equally'})
    return output/'dataset.yaml'


def train(epochs,batch):
    import torch
    from ultralytics import YOLO
    root=Path.cwd();output=root/'runs/collision-v2';output.mkdir(exist_ok=True)
    destination=root/'detection/models/simulation-cctv-collision-v2.pt'
    if destination.exists() or (output/'detector').exists():raise ValueError('Preserve prior training run')
    data=root/'datasets/day-night-collision-v2/dataset.yaml'
    if not data.exists():prepare(root/'datasets/day-night-collision-v1',data.parent)
    resolved,checked=check_dataset(data);write_json(output/'dataset-check.json',checked)
    initial=root/'detection/models/simulation-cctv-day-night.pt'
    initial_sha=hashlib.sha256(initial.read_bytes()).hexdigest()
    model=YOLO(str(initial));torch.set_num_threads(4)
    def progress(trainer):
        write_json(output/'progress.json',{'updated_at':datetime.now(timezone.utc).isoformat(),
            'stage':'detector_training','epoch_completed':trainer.epoch+1,'epochs':epochs,
            'metrics':{k:float(v) for k,v in trainer.metrics.items()}})
    model.add_callback('on_fit_epoch_end',progress)
    model.train(data=str(data),epochs=epochs,batch=batch,imgsz=640,device='cpu',workers=0,
        seed=251025,deterministic=True,freeze=10,patience=5,mosaic=0,
        degrees=8,translate=.04,scale=.15,hsv_v=.25,lr0=.0005,
        project=str(output),name='detector',exist_ok=False,plots=True)
    best=output/'detector/weights/best.pt';shutil.copy2(best,destination)
    assert hashlib.sha256(initial.read_bytes()).hexdigest()==initial_sha
    write_json(output/'detector-complete.json',{'completed_at':datetime.now(timezone.utc).isoformat(),
        'weights':str(destination),'sha256':hashlib.sha256(best.read_bytes()).hexdigest(),
        'initial_sha256':initial_sha,'best_selected_on':'validation only','test_used_for_training':False,
        'synthetic_only':True,'epochs_limit':epochs,'batch':batch,'night_collisions_included':True})
    print('DETECTOR_TRAINING_COMPLETE',str(destination),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--epochs',type=int,default=12)
    p.add_argument('--batch',type=int,default=4);a=p.parse_args();train(a.epochs,a.batch)
