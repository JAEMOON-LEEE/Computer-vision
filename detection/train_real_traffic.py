"""Fine-tune real CCTV vehicles, choose using validation, then freeze test.

No synthetic classes overwrite COCO vehicle support. Baseline weights remain
eligible: a new fine-tune is not automatically a better deployment model.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import csv
import json
from pathlib import Path
import shutil

from .dataset import check_dataset
from .evaluate_detection import evaluate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"runs/real-traffic-v1"
DATA=ROOT/"datasets/real-traffic-mio-v1/dataset.yaml"
DEST=ROOT/"detection/models/real-traffic.pt"


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf8")


def main():
    import torch
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect import DetectionTrainer
    class HeadlessCCTVTrainer(DetectionTrainer):
        # Optional Matplotlib plotting is blocked by Windows on this machine.
        # Validate the actual data with our stricter existing checker instead;
        # optimizer, labels, batches, validation and checkpointing are unchanged.
        def get_dataset(self):
            resolved,_=check_dataset(self.args.data)
            return {**resolved,"nc":len(resolved["names"]),"channels":3,"yaml_file":str(DATA)}
        def final_eval(self):
            # Standalone Ultralytics validation unconditionally checks plot
            # fonts. Equivalent name-based validation is performed below for
            # every baseline and candidate at the same input size.
            from ultralytics.utils.torch_utils import strip_optimizer
            for path in (self.last,self.best):
                if path.exists():strip_optimizer(path)
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/"object-complete.json").exists():
        print("Completed experiment preserved");return
    _,checked=check_dataset(DATA);write(OUT/"dataset-check.json",checked)
    torch.set_num_threads(4)
    candidate=OUT/"detector/weights/best.pt"
    if not candidate.exists():
        if (OUT/"detector").exists():raise ValueError("Incomplete training exists; preserve before explicit resume")
        model=YOLO(str(ROOT/"detection/models/yolo11n.pt"))
        def progress(trainer):
            write(OUT/"progress.json",{"stage":"real_cctv_detector_training","epoch":trainer.epoch+1,
                "epochs":8,"at":datetime.now(timezone.utc).isoformat(),"metrics":{k:float(v) for k,v in trainer.metrics.items()}})
        model.add_callback("on_fit_epoch_end",progress)
        model.train(trainer=HeadlessCCTVTrainer,data=str(DATA),epochs=8,batch=8,imgsz=416,device="cpu",workers=0,
            seed=251025,deterministic=True,freeze=10,patience=8,mosaic=.2,close_mosaic=2,
            degrees=3,translate=.05,scale=.2,hsv_v=.3,project=str(OUT),name="detector",plots=False)
    with (OUT/"detector/results.csv").open() as stream:
        epochs_completed=len(list(csv.DictReader(stream)))
    if epochs_completed!=8:raise ValueError("Training interrupted before8 epochs; preserve and resume explicitly")
    write(OUT/"detector-training-complete.json",{"epochs":epochs_completed,"weights":str(candidate),
        "sha256":hashlib.sha256(candidate.read_bytes()).hexdigest(),"plots":False,
        "standalone_evaluation":"same existing name-based evaluator for all candidates"})
    candidates={"coco_n":ROOT/"detection/models/yolo11n.pt",
                "coco_s":ROOT/"detection/models/yolo11s.pt","mio_n":candidate}
    validation={}
    for name,weights in candidates.items():
        folder=OUT/"objects"/("val_"+name)
        metrics=folder/"metrics.json"
        validation[name]=json.loads(metrics.read_text(encoding="utf8")) if metrics.exists() else evaluate(str(DATA),str(weights),folder,split="val",imgsz=640)
    # Predeclared deployment selection: mean car/truck/bus AP50 on val only.
    scores={name:sum(report["classes"][c]["AP50_101point"] for c in ("car","truck","bus"))/3
            for name,report in validation.items()}
    selected=max(scores,key=scores.get)
    sha=hashlib.sha256(candidates[selected].read_bytes()).hexdigest()
    selection={"selected":selected,"criterion":"val mean AP50(car,truck,bus), no test use", "scores":scores,
        "source":str(candidates[selected]),"sha256":sha,"validation":validation,"test_used_for_selection":False}
    existing=OUT/"object-selection.json"
    if existing.exists() and json.loads(existing.read_text(encoding="utf8"))["sha256"]!=sha:raise ValueError("Selection changed after freeze")
    write(existing,selection)
    if DEST.exists() and hashlib.sha256(DEST.read_bytes()).hexdigest()!=sha:raise ValueError("Preserve existing deployment weights")
    if not DEST.exists():shutil.copy2(candidates[selected],DEST)
    tests={}
    for name,weights in {"previous_synthetic":ROOT/"detection/models/simulation-cctv-collision-v2.pt","selected_real":DEST}.items():
        folder=OUT/"objects"/("test_"+name);metrics=folder/"metrics.json"
        tests[name]=json.loads(metrics.read_text(encoding="utf8")) if metrics.exists() else evaluate(str(DATA),str(weights),folder,split="test",imgsz=640)
    metadata={"status":"complete","completed_at":datetime.now(timezone.utc).isoformat(),"retrained":True,
        "training_epochs":8,"training_images":checked["splits"]["train"]["images"],
        "selected":selected,"selected_sha256":sha,"selection":selection,"test":tests,
        "real_cctv_pilot":True,"camera_disjoint":False,"accident_accuracy_evaluated":False,
        "available_classes":["person","car","truck","bus","motorcycle","bicycle"],
        "unavailable_classes":["pothole","debris","barrier","crack"],
        "production_ready":False}
    write(OUT/"object-complete.json",metadata)
    write(DEST.with_suffix(".json"),{k:v for k,v in metadata.items() if k not in ("selection","test")})
    print("REAL TRAFFIC DETECTOR COMPLETE",selected,sha,flush=True)


if __name__=="__main__":main()
