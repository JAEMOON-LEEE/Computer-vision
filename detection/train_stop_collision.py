"""Train a visual stop-zone collision classifier with session-level train/val/test separation."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from .engine import Detector
from .runner import run_predictions, write_json
from .stop_collision import FEATURE_NAMES, StopCollisionModel
from .warnings import WarningEngine, inside, iou

FOCUS=(230/720,130/480,440/720,270/480)
POSITIVE={"RearEnd","StructureImpact"}


def minimum_control_clearance(objects):
    """Evaluate all same-lane pairs; background cars must not change the case schema.

    CityLab's controlled SUV/Mini pair has half-length sum 1.45, and the
    SUV/barrier pair has sum 1.05. Other lanes are 1.3 units away.
    This is ground-truth audit only, never an input to the warning engine.
    """
    cars=[o for o in objects if o['class_name']=='car']
    barriers=[o for o in objects if o['class_name']=='barrier']
    gaps=[]
    for index,car in enumerate(cars):
        for other in cars[index+1:]+barriers:
            a,b=car['ground_point_world'],other['ground_point_world']
            if abs(a[2]-b[2])>.4:continue
            gaps.append(abs(a[0]-b[0])-(1.45 if other['class_name']=='car' else 1.05))
    if not gaps:raise ValueError('No visible same-lane control pair to audit')
    return min(gaps)


def collect(exports, output, weights, context, prefix="queue-v2-"):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    sources={}
    for source in sorted(Path(exports).glob(prefix+"*_20*")):
        truth=[json.loads(x) for x in (source/"ground_truth.jsonl").read_text(encoding="utf-8-sig").splitlines() if x.strip()]
        if len(truth)!=40: continue  # Unfinished captures are never used as training sessions.
        camera=json.loads((source/"camera.json").read_text(encoding="utf-8"))
        sources[camera["camera_id"]]=(source,truth)
    counts=Counter(name.split("-")[2] for name in sources)
    if dict(counts)!={"train":20,"val":10,"test":10}:
        raise ValueError(f"Need 20/10/10 complete independent sessions, found {counts}")
    model=Detector(weights,track=True,focus=FOCUS)
    detector_sha=hashlib.sha256(Path(weights).read_bytes()).hexdigest()
    road=json.loads(Path(context).read_text(encoding="utf-8"))
    candidates=[]; manifest=[]
    for name,(source,truth) in sorted(sources.items()):
        split,case=name.split("-")[2:4]
        impacts=[e for e in truth[-1]["scenario"]["events"] if e["evidence"]=="physics_contact"
                 and e["event_type"] in {"vehicle_collision","vehicle_structure_collision"}]
        if bool(impacts)!=(case in POSITIVE):
            raise ValueError(f"Actual physics contact does not match intended case: {source}")
        first_impact=min((e["timestamp"] for e in impacts),default=float("inf"))
        prediction=output/name
        if (prediction/"summary.json").exists():
            session=json.loads((prediction/"session.json").read_text(encoding="utf-8"))
            if session["source"]!=str(source.resolve()) or session["detector"]["models"][0]["sha256"]!=detector_sha:
                raise ValueError("Cached detector run uses a different capture or model; use a new --out directory")
        if not (prediction/"summary.json").exists():
            model.reset_tracking()
            run_predictions(model,str(source),prediction)
        engine=WarningEngine(road)
        records=[json.loads(x) for x in (prediction/"detections.jsonl").read_text(encoding="utf-8").splitlines()]
        eligible=0; unmatched=0
        for record in records:
            engine.update(record)
            for candidate in engine.stop_candidates:
                if not candidate["eligible"]: continue
                if case in POSITIVE:
                    objects=truth[record["frame"]]["objects"]
                    matched=[]
                    for box,cls in zip(candidate["boxes"],candidate["classes"]):
                        options=[(iou(box,o["bbox_xyxy"]),o["track_id"]) for o in objects if o["class_name"]==cls]
                        overlap,track=max(options,default=(0,None))
                        matched.append(track if overlap>=.3 else None)
                    if None in matched or len(set(matched))!=2:
                        unmatched+=1
                        continue
                    actual_pair=any(set(matched)=={e["object_a"],e["object_b"]} and record["timestamp"]>=e["timestamp"] for e in impacts)
                else: actual_pair=False
                candidate.update(clip=name,split=split,case=case,
                                 target=int(actual_pair))
                candidates.append(candidate);eligible+=1
        entry={"clip":name,"split":split,"case":case,"source":str(source.resolve()),
               "first_impact":None if not impacts else first_impact,"eligible_candidates":eligible,
               "frames":len(truth),"physics_events":impacts,"unmatched_ambiguous_candidates":unmatched}
        if case not in POSITIVE:
            objects=truth[-1]["objects"]
            clearance=minimum_control_clearance(objects)
            entry["final_clearance_units"]=clearance
            entry["visible_control_objects"]=dict(Counter(o['class_name'] for o in objects))
            if clearance < .03: raise ValueError(f"Negative control is interpenetrating: {source}")
        manifest.append(entry)
        print(name,"candidates",eligible,flush=True)
    write_json(output/"manifest.json",manifest)
    (output/"candidates.jsonl").write_text("".join(json.dumps(c)+"\n" for c in candidates),encoding="utf-8")
    return candidates,manifest


def train(output, destination, weights):
    output,destination=Path(output),Path(destination)
    rows=[json.loads(x) for x in (output/"candidates.jsonl").read_text().splitlines()]
    manifest=json.loads((output/"manifest.json").read_text())
    train_rows=[]
    for entry in manifest:
        if entry["split"]!="train": continue
        group=[r for r in rows if r["clip"]==entry["clip"]]
        for label in (0,1):
            samples=[r for r in group if r["target"]==label]
            train_rows.extend(samples[i] for i in np.linspace(0,len(samples)-1,min(10,len(samples))).round().astype(int))
    x=np.asarray([r["features"] for r in train_rows],np.float32)
    y=np.asarray([r["target"] for r in train_rows],np.int32)
    if set(y.tolist())!={0,1} or len(train_rows)<20:
        raise ValueError("Not enough actual positive and negative visual candidates")
    cv2.setRNGSeed(42)
    model=cv2.ml.RTrees_create();model.setMaxDepth(6);model.setMinSampleCount(2)
    model.setMaxCategories(2);model.setCalculateVarImportance(True)
    model.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER,128,0));model.train(x,cv2.ml.ROW_SAMPLE,y)
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists(): raise ValueError("Preserve previous models: choose a new destination")
    model.save(str(destination))
    metadata={"features":FEATURE_NAMES,"threshold":.51,"synthetic_only":True,
              "detector_weights_sha256":hashlib.sha256(Path(weights).read_bytes()).hexdigest(),
              "focus":FOCUS,"training_samples":len(train_rows),"training_classes":dict(Counter(y.tolist())),
              "training_clips":sum(e["split"]=="train" for e in manifest),
              "validation_clips":sum(e["split"]=="val" for e in manifest),
              "test_clips":sum(e["split"]=="test" for e in manifest),
              "labels":"Training-only Unity physics contact; runtime uses detections and causal history only"}
    write_json(destination.with_suffix(".json"),metadata)
    scorer=StopCollisionModel(destination)
    # Threshold selection uses val clips only. Test clips remain untouched here.
    val=[]
    for entry in manifest:
        if entry["split"]!="val": continue
        scores=[scorer.score(r["features"]) for r in rows if r["clip"]==entry["clip"]]
        val.append((entry,max(scores,default=0)))
    # Require a strict majority of trees; tune the operating point on val
    # clips rather than imposing an unvalidated 60% vote floor.
    thresholds=sorted({.51,.55,.6,.65,.7,.75,.8,.85,.9,.95,1.0,*[min(1.0,s+.001) for e,s in val if e["case"] not in POSITIVE]})
    choices=[]
    for threshold in thresholds:
        if threshold < .51: continue
        fp=sum(s>=threshold for e,s in val if e["case"] not in POSITIVE)
        tp=sum(s>=threshold for e,s in val if e["case"] in POSITIVE)
        choices.append((fp,-tp,threshold))
    fp,minus_tp,threshold=min(choices)
    metadata.update(threshold=threshold,validation_false_alert_clips=fp,validation_detected_collision_clips=-minus_tp,
                    feature_importance=dict(zip(FEATURE_NAMES,model.getVarImportance().ravel().tolist())))
    write_json(destination.with_suffix(".json"),metadata)
    write_json(output/"training-report.json",metadata)
    print("Trained",metadata,flush=True)


def verify(output, destination, context):
    output=Path(output); road=json.loads(Path(context).read_text(encoding="utf-8"))
    manifest=json.loads((output/"manifest.json").read_text())
    report={"synthetic_only":True,"model":str(destination),"clips":[],"passed":True}
    for entry in manifest:
        engine=WarningEngine(road,stop_model=destination);alerts=[]
        for line in (output/entry["clip"]/"detections.jsonl").read_text().splitlines():
            alerts.extend(engine.update(json.loads(line)))
        kind="suspected_vehicle_collision" if entry["case"]=="RearEnd" else "suspected_vehicle_structure_collision"
        collision_alerts=[a for a in alerts if a["type"].startswith("suspected_")]
        passed=(len(collision_alerts)==1 and collision_alerts[0]["type"]==kind
                and "stop_zone_decision" in collision_alerts[0]
                and collision_alerts[0]["timestamp"]>=entry["first_impact"]-1e-4) if entry["case"] in POSITIVE else not alerts
        item={**entry,"alerts":dict(Counter(a["type"] for a in alerts)),"passed":passed}
        if entry["case"] in POSITIVE:
            # Evaluation only: independently confirm the physical collision was
            # inside a controlled waiting zone. Never pass these rows to engine.
            truth=[json.loads(line) for line in (Path(entry["source"])/"ground_truth.jsonl").read_text(encoding="utf-8-sig").splitlines()]
            event=entry["physics_events"][0]
            contact=next(row for row in truth if row["timestamp"]>=event["timestamp"])
            participants=[obj for obj in contact["objects"] if obj["track_id"] in (event["object_a"],event["object_b"])]
            item["both_participants_inside_stop_zone"]=(len(participants)==2 and all(
                any(inside((obj["ground_point_pixel"][0]/contact["width"],obj["ground_point_pixel"][1]/contact["height"]),zone)
                    for zone in road.get("stop_zones",[])) for obj in participants))
            passed &= item["both_participants_inside_stop_zone"]
            item["passed"]=passed
            item["alert_latency_seconds"]=(collision_alerts[0]["timestamp"]-entry["first_impact"]) if collision_alerts else None
        report["clips"].append(item)
        if entry["split"] in {"val","test"}: report["passed"] &= passed
        (output/entry["clip"]/"final-alerts.jsonl").write_text("".join(json.dumps(a)+"\n" for a in alerts),encoding="utf-8")
        print(entry["clip"],item["alerts"],"PASS" if passed else "FAIL",flush=True)
    write_json(output/"verification.json",report)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("collect","train","verify"))
    parser.add_argument("--exports",default="simulation/TwinSightSim/TwinSightExport")
    parser.add_argument("--out",default="runs/queue-v3")
    parser.add_argument("--prefix",default="queue-v2-")
    parser.add_argument("--weights",default="detection/models/simulation-cctv-queue.pt")
    parser.add_argument("--model",default="detection/models/stop-zone-collision-final.xml")
    parser.add_argument("--context",default="detection/config/geumchon-city-lab.context.json")
    args=parser.parse_args()
    if args.mode=="collect": collect(args.exports,args.out,args.weights,args.context,args.prefix)
    elif args.mode=="train": train(args.out,args.model,args.weights)
    else: raise SystemExit(0 if verify(args.out,args.model,args.context)["passed"] else 1)
