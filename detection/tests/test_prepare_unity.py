import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from detection.prepare_unity import prepare_unity, audit_hazard_splits
from detection.dataset import check_dataset


class UnityConversionTests(unittest.TestCase):
    def test_hazard_audit_rejects_leaks_and_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            splits = {}
            rows = {}
            for index, split in enumerate(("train", "val", "test")):
                session = root / split
                session.mkdir()
                (session / "frame.png").write_bytes(bytes([index]))
                rows[split] = {"image": "frame.png", "scenario": {"seed": index, "episode": 1, "scenario": "Pothole"}}
                (session / "ground_truth.jsonl").write_text(json.dumps(rows[split]), encoding="utf-8")
                splits[split] = [session]
            self.assertEqual(audit_hazard_splits(splits)["unique_seeds"], 3)
            rows["val"]["scenario"]["seed"] = 0
            (splits["val"][0] / "ground_truth.jsonl").write_text(json.dumps(rows["val"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "seed leakage"):
                audit_hazard_splits(splits)
            rows["val"]["scenario"]["seed"] = 1
            rows["val"]["scenario"]["scenario"] = "VehicleCollision"
            (splits["val"][0] / "ground_truth.jsonl").write_text(json.dumps(rows["val"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "collision"):
                audit_hazard_splits(splits)
            rows["val"]["scenario"]["scenario"] = "Normal"
            (splits["val"][0] / "ground_truth.jsonl").write_text(json.dumps(rows["val"]), encoding="utf-8")
            (splits["val"][0] / "frame.png").write_bytes(b"\x00")
            with self.assertRaisesRegex(ValueError, "Image leakage"):
                audit_hazard_splits(splits)

    def test_sessions_are_split_and_boxes_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            splits = {}
            for index, split in enumerate(("train", "val", "test")):
                session = root / split
                session.mkdir()
                ok, pixels = cv2.imencode(".png", np.full((100, 200, 3), 20 + index * 10, dtype=np.uint8))
                self.assertTrue(ok)
                pixels.tofile(session / "frame.png")
                row = {"frame": 0, "image": "frame.png", "width": 200, "height": 100,
                       "objects": [{"class_name": "pothole", "bbox_xyxy": [20, 10, 60, 30]},
                                   {"class_name": "car", "bbox_xyxy": [80, 10, 120, 50]}]}
                (session / "ground_truth.jsonl").write_text(json.dumps(row), encoding="utf-8")
                splits[split] = [session]
            output = root / "converted"
            report = prepare_unity(splits, output, ["pothole"])
            self.assertEqual(report["frame_counts"], {"train": 1, "val": 1, "test": 1})
            _, checked = check_dataset(output / "dataset.yaml")
            self.assertEqual(checked["splits"]["train"]["objects"], {"pothole": 1})
            text = next((output / "labels/train").glob("*.txt")).read_text()
            self.assertEqual(text, "0 0.20000000 0.20000000 0.20000000 0.20000000")
            with self.assertRaisesRegex(ValueError, "multiple splits"):
                prepare_unity({"train": splits["train"], "val": splits["train"]}, root / "bad", ["pothole"])


if __name__ == "__main__":
    unittest.main()
