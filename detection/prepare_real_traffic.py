"""Acquire a reproducible, annotated MIO-TCD pilot on the project's D drive.

MIO annotations are human source labels, not predictions. Unknown vehicle types
are excluded with their entire image so they do not become false negatives.
Camera identities are unavailable: perceptual groups reduce near duplicates but
do not establish camera-disjoint evaluation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import io
from collections import Counter, defaultdict
from pathlib import Path
import tarfile

import cv2
import numpy as np
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "datasets/public-sources/real-traffic-v1"
OUT = ROOT / "datasets/real-traffic-mio-v1"
NAMES = ["person", "car", "truck", "bus", "motorcycle", "bicycle"]
MAPPING = {"pedestrian": "person", "car": "car", "work_van": "car",
           "pickup_truck": "truck", "single_unit_truck": "truck",
           "articulated_truck": "truck", "bus": "bus", "motorcycle": "motorcycle",
           "bicycle": "bicycle"}
URL = "https://tcd.miovision.com/static/dataset/MIO-TCD-Localization.tar"


def prepare_assets():
    SOURCE.mkdir(parents=True,exist_ok=True)
    model=ROOT/"detection/models/yolo11s.pt"
    expected="85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5"
    if not model.exists():
        url="https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt"
        response=requests.get(url,timeout=(15,120));response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest()!=expected:raise ValueError("Official model hash differs")
        model.write_bytes(response.content)
    if hashlib.sha256(model.read_bytes()).hexdigest()!=expected:raise ValueError("Preserve unexpected model weights for review")
    target=SOURCE/"mio-code/MIO-TCD-Localization-Code/gt_train.csv"
    if not target.exists():
        response=requests.get("https://tcd.miovision.com/static/dataset/MIO-TCD-Localization-Code.tar",timeout=(15,90));response.raise_for_status()
        (SOURCE/"MIO-TCD-Localization-Code.tar").write_bytes(response.content)
        with tarfile.open(fileobj=io.BytesIO(response.content)) as archive:
            member=archive.getmember("MIO-TCD-Localization-Code/gt_train.csv")
            if not member.isfile() or member.size>20*1024*1024:raise ValueError("Unexpected annotation archive")
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.extractfile(member).read())


def phash(image):
    small = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (32, 32)).astype(np.float32)
    block = cv2.dct(small)[:8, :8].ravel()[1:]
    return sum(int(v > np.median(block)) << i for i, v in enumerate(block))


def grouped_splits(rows):
    """Connected perceptual groups must remain in one split; no label peeking."""
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i, a in enumerate(rows):
        for j in range(i):
            if (a["phash"] ^ rows[j]["phash"]).bit_count() <= 8:
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, row in enumerate(rows): groups[find(i)].append(row)
    for members in groups.values():
        group = min(m["source_id"] for m in members)
        bucket = int(hashlib.sha256(("mio-pilot-20261025:"+group).encode()).hexdigest()[:8], 16) % 10
        split = "train" if bucket < 6 else "val" if bucket < 8 else "test"
        for row in members: row.update(group_id=group, split=split)
    return rows


def main():
    prepare_assets()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = OUT / "provenance.json"
    if manifest.exists():
        print("Existing prepared dataset preserved:", manifest); return
    gt = defaultdict(list)
    with (SOURCE/"mio-code/MIO-TCD-Localization-Code/gt_train.csv").open() as stream:
        for row in csv.reader(stream): gt[row[0]].append(row[1:])
    raw_dir = SOURCE / "mio-pilot-images"; raw_dir.mkdir(exist_ok=True)
    rows=[]; seen=set(); scanned=0
    # The archive is randomly ordered. A bounded prefix is explicitly a pilot,
    # not a representative random sample of the full benchmark.
    with requests.get(URL,stream=True,timeout=(15,90)) as response:
        response.raise_for_status()
        with tarfile.open(fileobj=response.raw,mode="r|") as archive:
            for member in archive:
                if not member.isfile() or "/train/" not in member.name or not member.name.endswith(".jpg"): continue
                identifier=Path(member.name).stem; labels=gt.get(identifier,[])
                if not labels or any(label[0] not in MAPPING for label in labels):continue
                scanned+=1
                payload=archive.extractfile(member).read();digest=hashlib.sha256(payload).hexdigest()
                if digest in seen:continue
                image=cv2.imdecode(np.frombuffer(payload,np.uint8),cv2.IMREAD_COLOR)
                if image is None:raise ValueError("Unreadable source image")
                height,width=image.shape[:2];normalized=[]
                for name,x1,y1,x2,y2 in labels:
                    x1,y1,x2,y2=map(float,(x1,y1,x2,y2))
                    x1,x2=np.clip([x1,x2],0,width);y1,y2=np.clip([y1,y2],0,height)
                    if x2<=x1 or y2<=y1:raise ValueError("Invalid source box")
                    normalized.append([NAMES.index(MAPPING[name]),(x1+x2)/2/width,(y1+y2)/2/height,(x2-x1)/width,(y2-y1)/height])
                (raw_dir/(identifier+".jpg")).write_bytes(payload);seen.add(digest)
                rows.append({"source_id":identifier,"sha256":digest,"phash":phash(image),"width":width,"height":height,"labels":normalized})
                if len(rows)%100==0:print("mio images",len(rows),flush=True)
                if len(rows)>=800:break
    rows=grouped_splits(rows)
    totals={}
    for split in ("train","val","test"):
        images=OUT/"images"/split;labels=OUT/"labels"/split
        images.mkdir(parents=True,exist_ok=True);labels.mkdir(parents=True,exist_ok=True);counts=Counter()
        for row in rows:
            if row["split"]!=split:continue
            identifier=row["source_id"]
            (images/(identifier+".jpg")).write_bytes((raw_dir/(identifier+".jpg")).read_bytes())
            (labels/(identifier+".txt")).write_text("\n".join(str(int(b[0]))+" "+" ".join(f"{v:.8f}" for v in b[1:]) for b in row["labels"])+"\n",encoding="utf8")
            counts.update(NAMES[int(b[0])] for b in row["labels"])
        totals[split]={"images":sum(r["split"]==split for r in rows),"objects":dict(counts)}
    config={"path":str(OUT.resolve()),"train":"images/train","val":"images/val","test":"images/test","names":dict(enumerate(NAMES))}
    (OUT/"dataset.yaml").write_text(yaml.safe_dump(config,sort_keys=False),encoding="utf8")
    provenance={"source_url":"https://tcd.miovision.com/challenge/dataset.html","archive_url":URL,
        "license":"CC-BY-NC-SA-4.0","labels":"source human bounding boxes", "mapping":MAPPING,
        "excluded_images":"Any unmapped class (motorized_vehicle/non-motorized_vehicle)",
        "sampling":"First 800 eligible unique training images in archive order",
        "split_method":"pHash Hamming<=8 connected groups, deterministic group SHA256 60/20/20",
        "camera_disjoint":False,"limitations":["camera identities unavailable", "bounded archive prefix", "pickup mapped to truck; work van mapped to car", "no accident supervision"],
        "totals":totals,"images":rows}
    manifest.write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps(totals,ensure_ascii=False,indent=2),flush=True)


if __name__ == "__main__":main()
