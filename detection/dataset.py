"""Strict checks before training: explicit labels, valid boxes, no split leakage."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path

import yaml

from .sources import IMAGE_EXTENSIONS, decode_image
from .taxonomy import CATEGORIES


def check_dataset(config: str | Path, require_all_classes=True):
    config = Path(config).resolve()
    raw = yaml.safe_load(config.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or not all(key in raw for key in ("names", "train", "val")):
        raise ValueError("Dataset YAML requires names, train and val")
    names = raw["names"]
    if not isinstance(names, (list, dict)):
        raise ValueError("Dataset names must be a list or integer-keyed mapping")
    if isinstance(names, dict):
        if set(names) != set(range(len(names))):
            raise ValueError("Dataset class IDs must be contiguous from zero")
        names = [names[index] for index in range(len(names))]
    if not all(isinstance(name, str) for name in names) or not names or len(names) != len(set(names)) or not set(names).issubset(CATEGORIES):
        raise ValueError(f"Use unique project class names: {CATEGORIES}")
    root = (config.parent / raw.get("path", ".")).resolve()
    resolved = {"path": str(root), "names": dict(enumerate(names))}
    report = {"config": str(config), "names": names, "splits": {}}
    hashes = {}
    for split in ("train", "val", "test"):
        if split == "test" and not raw.get(split):
            continue
        folder = (root / raw[split]).resolve()
        if not folder.is_dir() or folder.parent.name != "images":
            raise ValueError(f"Expected {split} directory at <dataset>/images/{split}: {folder}")
        images = sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS)
        if not images:
            raise ValueError(f"No {split} images: {folder}")
        counts = Counter()
        label_paths = set()
        negatives = 0
        for image in images:
            decode_image(image)
            label = folder.parent.parent / "labels" / folder.name / image.relative_to(folder).with_suffix(".txt")
            if label in label_paths:
                raise ValueError(f"Images share one label filename: {label}")
            label_paths.add(label)
            if not label.is_file():
                raise ValueError(f"Missing annotation: {label}. Reviewed negative images need an empty .txt file.")
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            if digest in hashes and hashes[digest] != split:
                raise ValueError(f"Image leakage between {hashes[digest]} and {split}: {image}")
            hashes[digest] = split
            lines = [line for line in label.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            negatives += not lines
            for line in lines:
                values = line.split()
                if len(values) != 5:
                    raise ValueError(f"Expected detection label 'class cx cy w h': {label}")
                cls = int(values[0])
                cx, cy, width, height = map(float, values[1:])
                if not 0 <= cls < len(names):
                    raise ValueError(f"Unknown class ID {cls}: {label}")
                if not all(math.isfinite(v) for v in (cx, cy, width, height)) or not (
                    0 < width <= 1 and 0 < height <= 1 and
                    cx - width / 2 >= -1e-6 and cx + width / 2 <= 1 + 1e-6 and
                    cy - height / 2 >= -1e-6 and cy + height / 2 <= 1 + 1e-6
                ):
                    raise ValueError(f"Invalid normalized box: {label}: {line}")
                counts[names[cls]] += 1
        missing = set(names) - counts.keys()
        if missing and require_all_classes:
            raise ValueError(f"No {split} positive labels for {sorted(missing)}; collect these classes before training")
        resolved[split] = str(folder)
        report["splits"][split] = {"images": len(images), "negative_images": negatives, "objects": dict(counts)}
    return resolved, report
