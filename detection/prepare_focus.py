"""Add separately captured far-road crops to a full-frame YOLO dataset, preserving session splits."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import cv2
import yaml

from .dataset import check_dataset
from .sources import decode_image, IMAGE_EXTENSIONS


def prepare(full_data, detail_data, output, focus):
    full, _ = check_dataset(full_data)
    # A supplemental capture may contain only a subset of the final classes.
    # The merged dataset is still checked with all classes required below.
    detail, _ = check_dataset(detail_data, require_all_classes=False)
    if list(full["names"].values()) != list(detail["names"].values()):
        raise ValueError("Dataset class names/order must agree")
    if len(focus) != 4 or not 0 <= focus[0] < focus[2] <= 1 or not 0 <= focus[1] < focus[3] <= 1:
        raise ValueError("Invalid normalized focus region")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    config = {"path": str(output.resolve()), "names": full["names"]}
    counts = {}
    for split in ("train", "val", "test"):
        config[split] = "images/" + split
        images, labels = output / "images" / split, output / "labels" / split
        images.mkdir(parents=True); labels.mkdir(parents=True)
        count = 0
        for source, crop in ((full, False), (detail, True)):
            folder = Path(source[split])
            for image_path in sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS):
                label_path = folder.parent.parent / "labels" / split / (image_path.stem + ".txt")
                stem = ("focus_" if crop else "full_") + image_path.stem
                if not crop:
                    shutil.copy2(image_path, images / (stem + image_path.suffix))
                    shutil.copy2(label_path, labels / (stem + ".txt"))
                else:
                    image = decode_image(image_path); h, w = image.shape[:2]
                    x0, y0, x1, y1 = [round(v * s) for v, s in zip(focus, (w, h, w, h))]
                    rows = []
                    for line in label_path.read_text().splitlines():
                        if not line.strip():
                            continue
                        cls, cx, cy, bw, bh = map(float, line.split())
                        a, b = max(x0, (cx-bw/2)*w), max(y0, (cy-bh/2)*h)
                        c, d = min(x1, (cx+bw/2)*w), min(y1, (cy+bh/2)*h)
                        if c-a < 4 or d-b < 4:
                            continue
                        rows.append(f"{int(cls)} {(a+c-2*x0)/2/(x1-x0):.8f} {(b+d-2*y0)/2/(y1-y0):.8f} {(c-a)/(x1-x0):.8f} {(d-b)/(y1-y0):.8f}")
                    # Encode as PNG to avoid a second JPEG compression of tiny objects.
                    encoded = cv2.imencode(".png", image[y0:y1, x0:x1])[1]
                    encoded.tofile(str(images / (stem + ".png")))
                    (labels / (stem + ".txt")).write_text("\n".join(rows), encoding="utf-8")
                count += 1
        counts[split] = count
    (output / "dataset.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    provenance = {"synthetic_only": True, "human_review_complete": False, "focus": focus,
                  "full_data": str(Path(full_data).resolve()), "detail_data": str(Path(detail_data).resolve()),
                  "frame_counts": counts, "splits": "preserved; no random frame split"}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    check_dataset(output / "dataset.yaml")
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-data", required=True)
    parser.add_argument("--detail-data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--focus", default="0.319444444,0.270833333,0.611111111,0.5625")
    args = parser.parse_args()
    print(prepare(args.full_data, args.detail_data, args.out, tuple(map(float, args.focus.split(",")))))
