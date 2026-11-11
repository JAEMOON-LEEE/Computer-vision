"""Train a weakly supervised real CCTV scene candidate and report limitations.

Source folder labels supervise scene presence, never invented contact frames.
Selection uses official train-derived validation only. The official test is
held out until weights/threshold/gate have been frozen.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .real_incident import SceneFeatures,EMBED_WEIGHTS,MODEL_PATH,scene_hit,vote_scores

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"runs/real-traffic-v1/incidents"
SOURCE=ROOT/"datasets/public-sources/real-traffic-v1/tad/manifest.json"


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf8")


def extract(entry,extractor):
    path=Path(entry["path"]);capture=cv2.VideoCapture(str(path))
    frames=int(capture.get(cv2.CAP_PROP_FRAME_COUNT));fps=capture.get(cv2.CAP_PROP_FPS)
    if not capture.isOpened() or frames<3 or not 0<fps<=240:raise ValueError("Invalid source video: "+str(path))
    duration=frames/fps
    # A weak scene pilot, centered 20-second segment (source labels are clip-level).
    start=max(0,(duration-20)/2);indices=sorted(set(min(frames-1,round(t*fps)) for t in np.arange(start,min(duration,start+20),.5)))
    rows=[];times=[]
    for index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=capture.read()
        if not ok:raise ValueError("Source decode failed at "+str(index))
        rows.append(extractor.extract(image));times.append(index/fps)
    capture.release()
    return np.asarray(rows,np.float32),times,{"duration":duration,"fps":fps,"frames":frames,"sampled_frames":indices,"sample_start":start,"sampling_fps":2}


def outcomes(entries,features,times,model,threshold):
    results=[]
    for entry in entries:
        key=entry["sha256"];scores=vote_scores(model,features[key]);hit=scene_hit(scores,times[key],threshold)
        results.append({"video":Path(entry["path"]).name,"source":entry["name"],"split":entry["split"],
            "target":entry["target"],"warning":hit,"maximum_vote_ratio":float(scores.max(initial=0)),"sample_count":len(scores)})
    tp=sum(r["target"]==1 and r["warning"] for r in results);fp=sum(r["target"]==0 and r["warning"] for r in results)
    positives=sum(r["target"]==1 for r in results);negatives=len(results)-positives
    return {"tp":tp,"fp":fp,"positive_clips":positives,"negative_clips":negatives,
        "recall":tp/positives if positives else 0,"false_positive_rate":fp/negatives if negatives else 0,"clips":results}


def main():
    import torch
    torch.set_num_threads(2);cv2.setNumThreads(2)
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/"completion.json").exists():print("Completed scene candidate preserved");return
    manifest=json.loads(SOURCE.read_text(encoding="utf8"));entries=manifest["clips"]
    # Exact duplicates must never cross train/val/test. Conflict => exclude all copies.
    partitions={}
    for e in entries:partitions.setdefault(e["sha256"],set()).add(e["split"])
    conflicts={key for key,splits in partitions.items() if len(splits)>1}
    entries=[e for e in entries if e["sha256"] not in conflicts]
    features={};times={};sampling={};extractor=SceneFeatures()
    # No test feature is used to fit or choose any parameter.
    for split in ("train","val","test"):
        if split=="test":continue
        for entry in [e for e in entries if e["split"]==split]:
            key=entry["sha256"];cache=OUT/"features"/(key+".npz");cache.parent.mkdir(exist_ok=True)
            if cache.exists():
                saved=np.load(cache);x=saved["features"];ts=saved["times"].tolist();meta=json.loads(str(saved["metadata"]))
            else:
                x,ts,meta=extract(entry,extractor);np.savez_compressed(cache,features=x,times=ts,metadata=json.dumps(meta))
            features[key]=x;times[key]=ts;sampling[key]=meta
            print("real scene features",split,len(features),Path(entry["path"]).name,len(x),flush=True)
            write(OUT/"progress.json",{"stage":"feature_extraction","clips_complete":len(features),"total_clips":len(entries)})
    training=[e for e in entries if e["split"]=="train"]
    x=np.concatenate([features[e["sha256"]] for e in training]);y=np.concatenate([np.full(len(features[e["sha256"]]),e["target"],np.int32) for e in training])
    validation=[e for e in entries if e["split"]=="val"];trials=[];best=None
    for depth in (3,5,8):
        cv2.setRNGSeed(251025);model=cv2.ml.RTrees_create();model.setMaxDepth(depth);model.setMinSampleCount(8)
        model.setMaxCategories(2);model.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER,128,0))
        model.train(x,cv2.ml.ROW_SAMPLE,y)
        for threshold in (.55,.65,.75,.85,.9,.95,1.001):
            result=outcomes(validation,features,times,model,threshold)
            # Require <=1/12 val false-positive clips, then maximize recall.
            acceptable=result["false_positive_rate"]<=.1
            rank=(acceptable,result["tp"] if acceptable else -result["fp"],-result["fp"],-depth,threshold)
            trial={"depth":depth,"threshold":threshold,**{k:v for k,v in result.items() if k!="clips"}};trials.append(trial)
            if best is None or rank>best[0]:best=(rank,model,trial,result)
    _,model,selected,val_result=best
    if MODEL_PATH.exists():raise ValueError("Preserve existing real scene classifier")
    model.save(str(MODEL_PATH))
    # Production warning promotion requires >=50% val recall and <=10% val FPR.
    enabled=selected["recall"]>=.5 and selected["false_positive_rate"]<=.1
    metadata={"status":"complete","task":"weakly_supervised_accident_scene_presence", "synthetic_only":False,
        "source":manifest["source"],"labels":manifest["labels"],"license":manifest["license"],
        "embedding_weights":str(EMBED_WEIGHTS),"embedding_sha256":hashlib.sha256(EMBED_WEIGHTS.read_bytes()).hexdigest(),
        "embedding_layer":10,"embedding_dimensions":256,"imgsz":416,"model_sha256":hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
        "threshold":selected["threshold"],"depth":selected["depth"],"trees":128,"alerts_enabled":enabled,
        "gate":"val recall>=0.5 and val FPR<=0.1; no test-based promotion", "training_rows":len(x),
        "split_counts":dict(Counter(e["split"] for e in entries)),"cross_split_exact_duplicates_excluded":len(conflicts),
        "selection":selected,"validation":val_result,"trials":trials,"test_used_for_selection":False,
        "camera_disjoint":False,"contact_or_participants_supervised":False,"production_ready":False,
        "limitations":["weak clip-level source labels", "center20 seconds may miss contact", "static aftermath can be positive", "camera identities unknown", "near duplicate videos not exhaustively audited", "vote ratio is not accident probability", "small selected size-biased pilot"],
        "completed_at":datetime.now(timezone.utc).isoformat()}
    write(MODEL_PATH.with_suffix(".json"),metadata)
    write(OUT/"selection.json",metadata)
    for entry in [e for e in entries if e["split"]=="test"]:
        key=entry["sha256"];x,ts,meta=extract(entry,extractor);features[key]=x;times[key]=ts;sampling[key]=meta
        print("real scene held-out test",len([k for k in sampling if k==key]),Path(entry["path"]).name,flush=True)
    test=outcomes([e for e in entries if e["split"]=="test"],features,times,model,selected["threshold"])
    write(OUT/"test.json",test);write(OUT/"sampling.json",sampling)
    write(OUT/"completion.json",{**metadata,"test":test,"completed_at":datetime.now(timezone.utc).isoformat()})
    print("REAL SCENE TRAINING COMPLETE",json.dumps({"validation":selected,"test":{k:v for k,v in test.items() if k!="clips"},"alerts_enabled":enabled}),flush=True)


if __name__=="__main__":main()
