"""Audit/export varied Unity collision clips, and measure frozen-model warnings.

Physics events are used only for offline labels and evaluation, never inference.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

import cv2
import numpy as np

from .runner import run_predictions, write_json
from .sources import decode_image
from .warnings import iou

FOCUS = (230/720, 130/480, 440/720, 270/480)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def footprint(car):
    # Same planar box collider as RoadScenarioDirector.CreateImpactVehicle.
    angle = math.radians(car["yaw"])
    forward = np.array([math.sin(angle), math.cos(angle)])
    right = np.array([math.cos(angle), -math.sin(angle)])
    center = np.array([car["position"][0], car["position"][2]])
    return np.array([center + f*car["half_length"]*forward + r*.335*right
                     for f, r in ((1, 1), (1, -1), (-1, -1), (-1, 1))], np.float32)


def surface_gap(a, b):
    """Planar convex footprint distance, independent of camera projection."""
    a, b = footprint(a), footprint(b)
    if cv2.intersectConvexConvex(a, b)[0] > 1e-8:
        return 0.0
    def point_segment(p, u, v):
        d = v-u
        t = np.clip(np.dot(p-u, d)/max(1e-12, np.dot(d, d)), 0, 1)
        return float(np.linalg.norm(p-(u+t*d)))
    return min(point_segment(p, q[i], q[(i+1)%4])
               for vertices, q in ((a, b), (b, a)) for p in vertices for i in range(4))


def same_physics_events(first, second):
    # Unity JsonUtility and Newtonsoft serialize the same float32 differently.
    a={e["event_id"]:e for e in first};b={e["event_id"]:e for e in second}
    if len(a)!=len(first) or len(b)!=len(second) or a.keys()!=b.keys():return False
    for key,e in a.items():
        other=b[key]
        if any(e[field]!=other[field] for field in ("event_type","evidence","object_a","object_b")):return False
        if any(abs(e[field]-other[field])>.001 for field in ("timestamp","relative_speed_units_per_second")):return False
    return True


def audit(root, output):
    root, output = Path(root), Path(output)
    entries = read(root/"capture-audit.json")
    report = {"synthetic_only": True, "human_label_review_complete": False, "clips": [], "passed": True}
    poses, sources, seeds = [], set(), set()
    for entry in entries:
        source = Path(entry["source"])
        if source.resolve() in sources or entry["seed"] in seeds:
            raise ValueError("Duplicate scene or seed across splits")
        sources.add(source.resolve()); seeds.add(entry["seed"])
        truth = lines(source/"ground_truth.jsonl")
        motion = read(source/"motion_audit.json")["frames"]
        camera = read(source/"camera.json")
        pose = {k: camera[k] for k in ("position", "rotation_euler_deg", "vertical_fov_deg", "image_width", "image_height")}
        poses.append(pose)
        contacts = entry["physics_events"]
        truth_contacts=[e for e in truth[-1]["scenario"]["events"]
                        if e["evidence"]=="physics_contact" and e["event_type"]=="vehicle_collision"]
        pairs={tuple(sorted((e["object_a"],e["object_b"]))) for e in truth_contacts
               if e["object_a"]!=e["object_b"] and e["relative_speed_units_per_second"]>=.45}
        final = {v["track_id"]: v for v in motion[-1]["vehicles"]}
        gaps = [surface_gap(final[e["object_a"]], final[e["object_b"]]) for e in contacts]
        queue_gap = None
        if not entry["expected_collision"]:
            a, b = final.values()
            queue_gap = abs(a["position"][0]-b["position"][0])-a["half_length"]-b["half_length"]
        dt = [b["timestamp"]-a["timestamp"] for a, b in zip(truth, truth[1:])]
        checks = {
            "complete": len(truth)==entry["frames"]==len(motion),
            "all_images_present": all((source/f["image"]).is_file() for f in truth),
            "clock": bool(dt) and all(abs(d-1/entry["capture_fps"])<.005 for d in dt),
            "lighting": all(f["lighting"]["time_of_day"]==entry["lighting"] for f in truth),
            "physics": (len(pairs)>=entry["required_distinct_contacts"] if entry["expected_collision"]
                        else not truth_contacts) and same_physics_events(contacts,truth_contacts),
            "approach_context": not contacts or entry["first_contact_after_seconds"]>=3,
            "close_after_contact": not gaps or max(gaps)<=.15,
            "normal_clearance": queue_gap is None or queue_gap>=entry["intended_queue_gap"]-.025,
            "settled": all(v["velocity"]<.01 for v in final.values()),
        }
        item = {**entry, "final_contact_surface_gaps": gaps, "final_queue_clearance": queue_gap,
                "checks": checks, "passed": all(checks.values())}
        report["clips"].append(item); report["passed"] &= item["passed"]
    report["fixed_cctv"] = all(p==poses[0] for p in poses)
    report["passed"] &= report["fixed_cctv"]
    report["capture_complete"]=(root/"capture-complete.txt").is_file()
    report["passed"] &= report["capture_complete"]
    report["camera"] = poses[0]
    report["clip_count"] = len(entries)
    report["frames"] = sum(e["frames"] for e in entries)
    report["by_split"] = dict(Counter(e["split"] for e in entries))
    report["by_lighting"] = dict(Counter(e["lighting"] for e in entries))
    output.mkdir(parents=True, exist_ok=True)
    write_json(output/"scene-audit.json", report)
    return report


def prepare(report, output):
    from .prepare_unity import prepare_unity
    if not report["passed"]:
        raise ValueError("Repair scene audit failures before preparing training data")
    splits = {s: [e["source"] for e in report["clips"] if e["split"]==s] for s in ("train", "val", "test")}
    return prepare_unity(splits, output, ["person", "car", "pothole", "debris", "barrier"])


def evaluate(report, output, weights, profiles):
    from .engine import Detector
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    evaluations = {"synthetic_only": True, "retrained": False, "production_ready": False, "profiles": {}}
    for profile in profiles:
        focused = profile=="unity-focus"
        detector = Detector(weights, track=True, focus=FOCUS if focused else None)
        context = read("detection/config/geumchon-city-lab.context.json") if focused else None
        stop = "detection/models/stop-zone-collision-day-night.xml" if focused else None
        rows=[]
        for entry in report["clips"]:
            if entry["split"]!="test": continue
            source=Path(entry["source"]); destination=output/profile/source.name
            detector.reset_tracking()
            summary=run_predictions(detector,str(source),destination,warnings=True,context=context,stop_model=stop)
            truth=lines(source/"ground_truth.jsonl")
            alerts=lines(destination/"alerts.jsonl")
            collision_alerts=[a for a in alerts if a["type"]=="suspected_vehicle_collision"]
            matched=[]
            for alert in collision_alerts:
                objects=truth[alert["frame"]]["objects"]
                ids=[]
                for evidence in alert["evidence"]:
                    overlap, track=max(((iou(evidence["bbox_xyxy"],o["bbox_xyxy"]),o["track_id"])
                                       for o in objects if o["class_name"]=="car"), default=(0,None))
                    ids.append(track if overlap>=.3 else None)
                actual=any(None not in ids and len(set(ids))==2 and set(ids)=={e["object_a"],e["object_b"]}
                           and alert["timestamp"]>=e["timestamp"] for e in entry["physics_events"])
                matched.append(actual)
            rows.append({"source":str(source),"scenario":entry["scenario"],"lighting":entry["lighting"],
                         "expected_collision":entry["expected_collision"],"summary":summary,
                         "collision_alerts":len(collision_alerts),"correct_pair_after_contact":any(matched),
                         "unmatched_or_early_alerts":sum(not m for m in matched)})
            print(profile,entry["lighting"],entry["scenario"],"alerts",len(collision_alerts),"strict",any(matched),flush=True)
            write_json(output/(profile+"-progress.json"),rows)
        positives=[r for r in rows if r["expected_collision"]]
        negatives=[r for r in rows if not r["expected_collision"]]
        evaluations["profiles"][profile]={"cases":rows,"accident_clips":len(positives),
            "correct_pair_after_contact_clips":sum(r["correct_pair_after_contact"] for r in positives),
            "normal_clips":len(negatives),"normal_clips_with_collision_alert":sum(r["collision_alerts"]>0 for r in negatives),
            "detector":detector.metadata()}
        write_json(output/"verification.json",evaluations)
    return evaluations


def previews(report, output, lighting="Day"):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    tiles=[]
    for entry in report["clips"]:
        if entry["lighting"]!=lighting or entry["split"] not in {"test","smoke"}: continue
        source=Path(entry["source"]); records=lines(source/"ground_truth.jsonl")
        # Labelled crop for visual inspection only; source images/camera are preserved.
        x1,y1,x2,y2=FOCUS
        writer=cv2.VideoWriter(str(output/(entry["scenario"]+"-focus.webm")),cv2.VideoWriter_fourcc(*"VP80"),entry["capture_fps"],(960,640))
        if not writer.isOpened(): raise RuntimeError("WebM encoder unavailable")
        for record in records:
            image=decode_image(source/record["image"]);h,w=image.shape[:2]
            image=image[round(y1*h):round(y2*h),round(x1*w):round(x2*w)]
            canvas=cv2.resize(image,(960,640))
            cv2.putText(canvas,lighting+" "+entry["scenario"]+" | CCTV crop",(12,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2)
            cv2.putText(canvas,f'{record["timestamp"]-records[0]["timestamp"]:.2f} s',(12,57),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2)
            writer.write(canvas)
        writer.release()
        tile=cv2.resize(canvas,(480,320));tiles.append(tile)
    if tiles:
        rows=[]
        for start in range(0,len(tiles),2):
            pair=tiles[start:start+2]
            if len(pair)<2:pair.append(np.zeros_like(pair[0]))
            rows.append(np.concatenate(pair,axis=1))
        ok,data=cv2.imencode(".jpg",np.concatenate(rows,axis=0))
        if not ok:raise RuntimeError("Preview encode failed")
        data.tofile(output/"overview.jpg")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports",required=True);parser.add_argument("--out",required=True)
    parser.add_argument("--dataset");parser.add_argument("--previews",action="store_true")
    parser.add_argument("--preview-lighting",choices=("Day","Night"),default="Day")
    parser.add_argument("--evaluate",action="store_true")
    parser.add_argument("--profiles",default="unity-focus,lab-fullframe")
    parser.add_argument("--weights",default="detection/models/simulation-cctv-day-night.pt")
    args=parser.parse_args()
    if not set(args.profiles.split(",")).issubset({"unity-focus","lab-fullframe"}):
        parser.error("Use unity-focus and/or lab-fullframe profiles")
    report=audit(args.exports,args.out)
    print("scene audit",report["passed"],report["clip_count"],"clips",flush=True)
    if args.previews:previews(report,Path(args.out)/"previews",args.preview_lighting)
    if args.dataset:prepare(report,args.dataset)
    if args.evaluate:
        if not report["passed"]:raise ValueError("Scene audit failed")
        evaluate(report,Path(args.out)/"inference",args.weights,args.profiles.split(","))
    return 0 if report["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
