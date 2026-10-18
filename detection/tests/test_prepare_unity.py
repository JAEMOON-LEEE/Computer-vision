import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from detection.prepare_unity import prepare_unity
from detection.dataset import check_dataset


class UnityConversionTests(unittest.TestCase):
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
