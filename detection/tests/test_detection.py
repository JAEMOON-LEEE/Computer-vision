from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import yaml

from detection.dataset import check_dataset
from detection.engine import Detector, convert_result, resolve_weights
from detection.runner import run_predictions
from detection.sources import read_frames


def image_file(path, color=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(".png", np.full((40, 60, 3), color, dtype=np.uint8))
    assert ok
    data.tofile(path)


class OutputTests(unittest.TestCase):
    def test_model_id_and_project_id_are_separate_and_boxes_are_clipped(self):
        result = SimpleNamespace(boxes=SimpleNamespace(
            xyxy=np.array([[-5, 10, 70, 50], [1, 1, 2, 2], [3, 3, 2, 2], [0, 0, np.nan, 5]]),
            conf=np.array([0.9, 0.8, 0.7, 0.9]), cls=np.array([2, 16, 2, 2])))
        rows = convert_result(result, {2: "car"}, "primary", 60, 40)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bbox_xyxy"], [0, 10, 60, 40])
        self.assertEqual(rows[0]["class_id"], 2)
        self.assertEqual(rows[0]["category_id"], 1)
        self.assertIsNone(rows[0]["track_id"])
        self.assertEqual(rows[0]["ground_point_px"], [30, 40])

    def test_unknown_weight_does_not_silently_download(self):
        with self.assertRaises(FileNotFoundError):
            resolve_weights("misspelled-road-model.pt")

    def test_focus_restores_original_pixels_and_does_not_duplicate_overview(self):
        with tempfile.TemporaryDirectory() as tmp:
            weight = Path(tmp) / "test.pt"; weight.touch()
            calls = []
            class FakeModel:
                task = "detect"
                names = {0: "car"}
                def __init__(self, path):
                    pass
                def predict(self, image, **kwargs):
                    calls.append(image.shape)
                    # Same object: global box [30,20,40,30], crop-relative [10,10,20,20].
                    boxes = [[30,20,40,30],[1,1,9,9]] if image.shape[1] == 80 else [[10,10,20,20]]
                    return [SimpleNamespace(boxes=SimpleNamespace(xyxy=np.array(boxes), conf=np.full(len(boxes),0.9), cls=np.zeros(len(boxes))))]
            with patch.dict("sys.modules", {"torch": SimpleNamespace(set_num_threads=lambda n: None),
                                            "ultralytics": SimpleNamespace(YOLO=FakeModel)}):
                detector = Detector(str(weight), focus=(0.25,0.25,0.75,0.75))
                rows, _ = detector.predict(np.zeros((40,80,3), dtype=np.uint8))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["bbox_xyxy"], [1,1,9,9])
            self.assertEqual(rows[0]["model_id"], "primary")
            self.assertEqual(rows[1]["bbox_xyxy"], [30,20,40,30])
            self.assertEqual(rows[1]["ground_point_px"], [35,30])
            self.assertEqual(rows[1]["model_id"], "focus")
            self.assertEqual(calls, [(40,80,3),(20,40,3)])

    def test_invalid_focus_cannot_silently_select_another_region(self):
        for region in [(0.8,0,0.2,1), (0,0,float("nan"),1), (-0.1,0,1,1)]:
            with self.assertRaises(ValueError):
                Detector("unused.pt", focus=region)

    def test_two_models_use_their_own_class_ids_and_disjoint_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary, road = Path(tmp) / "primary.pt", Path(tmp) / "road.pt"
            primary.touch()
            road.touch()
            calls = []

            class FakeModel:
                task = "detect"

                def __init__(self, path):
                    self.road = Path(path).stem == "road"
                    self.names = {0: "pothole", 1: "crack", 2: "debris"} if self.road else {0: "person", 2: "car", 6: "pothole"}

                def predict(self, image, **kwargs):
                    calls.append(kwargs)
                    cls = 0 if self.road else 2
                    return [SimpleNamespace(boxes=SimpleNamespace(xyxy=np.array([[1, 2, 10, 20]]),
                            conf=np.array([0.9]), cls=np.array([cls])))]

            with patch.dict("sys.modules", {"torch": SimpleNamespace(set_num_threads=lambda n: None),
                                            "ultralytics": SimpleNamespace(YOLO=FakeModel)}):
                detector = Detector(str(primary), str(road))
                rows, _ = detector.predict(np.zeros((40, 60, 3), dtype=np.uint8))
            self.assertEqual([row["class_name"] for row in rows], ["car", "pothole"])
            self.assertEqual([row["category_id"] for row in rows], [1, 6])
            self.assertEqual(calls[0]["classes"], [0, 2])
            self.assertEqual(calls[1]["classes"], [0, 1, 2])
            self.assertEqual(calls[1]["conf"], 0.35)


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        image_file(self.root / "frames" / "000042.png")
        self.record = {"frame": 42, "timestamp": 12.3, "camera_id": "unity-test", "width": 60,
                       "height": 40, "image": "frames/000042.png", "objects": []}

    def write(self, records):
        (self.root / "ground_truth.jsonl").write_text(
            "\n".join(json.dumps(row) for row in records), encoding="utf-8")

    def test_unity_preserves_frame_camera_and_simulation_time(self):
        self.write([self.record])
        frame = list(read_frames(str(self.root)))[0]
        self.assertEqual((frame.number, frame.timestamp, frame.camera_id), (42, 12.3, "unity-test"))
        self.assertEqual(frame.timestamp_kind, "simulation_seconds")

    def test_duplicate_frame_is_rejected(self):
        self.write([self.record, self.record])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            list(read_frames(str(self.root)))

    def test_outside_export_image_is_rejected(self):
        self.record["image"] = "../outside.png"
        self.write([self.record])
        with self.assertRaisesRegex(ValueError, "outside Unity"):
            list(read_frames(str(self.root)))

    def test_wrong_image_dimensions_are_rejected(self):
        self.record["width"] = 100
        self.write([self.record])
        with self.assertRaisesRegex(ValueError, "dimensions"):
            list(read_frames(str(self.root)))

    def test_follow_waits_for_complete_new_unity_record(self):
        path = self.root / "ground_truth.jsonl"
        path.write_text("", encoding="utf-8")
        row = json.dumps(self.record)

        def append():
            time.sleep(0.03)
            with path.open("a", encoding="utf-8") as writer:
                writer.write(row[:20]); writer.flush()
                time.sleep(0.06)
                writer.write(row[20:] + "\n"); writer.flush()

        thread = threading.Thread(target=append)
        thread.start()
        frames = list(read_frames(str(self.root), follow=True, max_frames=1))
        thread.join()
        self.assertEqual(frames[0].number, 42)

    def test_stride_and_limit_do_not_renumber_frames(self):
        self.write([dict(self.record, frame=i) for i in range(6)])
        frames = list(read_frames(str(self.root), stride=2, max_frames=2))
        self.assertEqual([f.number for f in frames], [0, 2])

    def test_jsonl_includes_frames_with_no_detections_and_refuses_overwrite(self):
        class EmptyDetector:
            capabilities = {"available": ["car"], "unavailable": ["pothole", "crack", "debris"]}

            def metadata(self):
                return {"fake_for_test": True}

            def predict(self, image):
                return [], 1.0

        self.write([self.record])
        output = self.root / "result"
        summary = run_predictions(EmptyDetector(), str(self.root), output, save_images=True)
        row = json.loads((output / "detections.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["frame"], 42)
        self.assertEqual(row["detections"], [])
        self.assertEqual(summary["frames"], 1)
        self.assertTrue((output / "annotated" / "000042.jpg").exists())
        with self.assertRaisesRegex(ValueError, "empty"):
            run_predictions(EmptyDetector(), str(self.root), output)


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for split, color in (("train", 0), ("val", 40), ("test", 80)):
            image_file(self.root / "images" / split / "sample.png", color)
            label = self.root / "labels" / split / "sample.txt"
            label.parent.mkdir(parents=True)
            label.write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
        self.config = self.root / "data.yaml"
        self.config.write_text(yaml.safe_dump({"path": ".", "train": "images/train", "val": "images/val",
                                              "test": "images/test", "names": {0: "pothole"}}), encoding="utf-8")

    def test_valid_yolo_dataset_has_absolute_paths(self):
        resolved, report = check_dataset(self.config)
        self.assertEqual(report["splits"]["train"]["objects"], {"pothole": 1})
        self.assertTrue(Path(resolved["train"]).is_absolute())

    def test_exact_image_leakage_is_rejected(self):
        (self.root / "images/val/sample.png").write_bytes((self.root / "images/train/sample.png").read_bytes())
        with self.assertRaisesRegex(ValueError, "leakage"):
            check_dataset(self.config)

    def test_missing_label_is_not_treated_as_negative(self):
        (self.root / "labels/train/sample.txt").unlink()
        with self.assertRaisesRegex(ValueError, "Missing annotation"):
            check_dataset(self.config)

    def test_nan_and_out_of_bounds_labels_are_rejected(self):
        for line in ("0 nan 0.5 0.1 0.1", "0 0.95 0.5 0.5 0.2"):
            (self.root / "labels/train/sample.txt").write_text(line, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid normalized"):
                check_dataset(self.config)

    def test_unlearnable_missing_class_is_rejected(self):
        raw = yaml.safe_load(self.config.read_text(encoding="utf-8"))
        raw["names"][1] = "debris"
        self.config.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "No train positive labels"):
            check_dataset(self.config)
        # Supplemental files may omit classes before merging; the final train check remains strict.
        _, report = check_dataset(self.config, require_all_classes=False)
        self.assertNotIn("debris", report["splits"]["train"]["objects"])


if __name__ == "__main__":
    unittest.main()
