"""OpenCV media input and the team's Unity GroundTruthExporter reader."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass
class Frame:
    image: np.ndarray
    number: int
    timestamp: float
    camera_id: str
    timestamp_kind: str
    image_path: str | None = None


def decode_image(path: Path):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot decode image: {path}")
    return image


def confined_image(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing image or path outside Unity export: {relative}")
    return path


def unity_frames(root: Path, camera_id=None, follow=False, idle_timeout=10):
    seen = set()
    with (root / "ground_truth.jsonl").open(encoding="utf-8-sig") as source:
        last_data = time.monotonic()
        while True:
            position = source.tell()
            line = source.readline()
            if not line or not line.endswith("\n"):
                if not follow:
                    if not line:
                        break
                else:
                    source.seek(position)
                    if time.monotonic() - last_data >= idle_timeout:
                        break
                    time.sleep(0.05)
                    continue
            last_data = time.monotonic()
            if not line.strip():
                continue
            record = json.loads(line)
            number = int(record["frame"])
            if number in seen:
                raise ValueError(f"Duplicate Unity frame number: {number}")
            seen.add(number)
            timestamp = float(record["timestamp"])
            if not math.isfinite(timestamp):
                raise ValueError("Non-finite Unity timestamp")
            image = decode_image(confined_image(root, record["image"]))
            if image.shape[:2] != (record["height"], record["width"]):
                raise ValueError(f"Unity image/metadata dimensions differ at frame {number}")
            yield Frame(image, number, timestamp, camera_id or record["camera_id"],
                        "simulation_seconds", record["image"])


def read_frames(source: str, camera_id=None, stride=1, max_frames=None, follow=False):
    if stride < 1 or (max_frames is not None and max_frames < 1):
        raise ValueError("stride and max-frames must be positive")
    path = Path(source)
    if path.is_dir() and (path / "ground_truth.jsonl").exists():
        frames = unity_frames(path, camera_id, follow)
    elif follow:
        raise ValueError("--follow requires an existing Unity export folder with ground_truth.jsonl")
    elif path.is_dir() or path.suffix.lower() in IMAGE_EXTENSIONS:
        paths = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS) if path.is_dir() else [path]
        frames = (Frame(decode_image(p), i, 0.0, camera_id or "image", "unspecified", str(p.resolve()))
                  for i, p in enumerate(paths))
    else:
        frames = video_frames(source, camera_id)
    count = 0
    try:
        for index, frame in enumerate(frames):
            if index % stride:
                continue
            yield frame
            count += 1
            if max_frames is not None and count >= max_frames:
                break
    finally:
        frames.close()


def video_frames(source: str, camera_id=None):
    live = source.isdecimal() or source.lower().startswith(("rtsp://", "http://", "https://", "rtmp://"))
    if not live and not Path(source).is_file():
        raise FileNotFoundError(f"Source not found: {source}")
    capture = cv2.VideoCapture(int(source) if source.isdecimal() else source)
    try:
        if not capture.isOpened():
            raise ValueError("OpenCV could not open the video/camera source")
        if live:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not live and (not math.isfinite(fps) or fps <= 0):
            raise ValueError("Video has no valid FPS; convert it to a fixed-FPS video first")
        index = 0
        while True:
            ok, image = capture.read()
            if not ok:
                if live or index == 0:
                    raise RuntimeError("Video/camera frame read failed")
                break
            yield Frame(image, index, time.time() if live else index / fps,
                        camera_id or ("camera" if live else Path(source).stem),
                        "unix_seconds" if live else "video_seconds")
            index += 1
    finally:
        capture.release()
