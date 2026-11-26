import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from detection.facility_audit import audit_facility_splits, CASES


class FacilityAuditTests(unittest.TestCase):
    def test_additional_abnormal_variants_have_explicit_truth(self):
        for name in ("GuardrailBrokenLeft", "GuardrailBrokenRight", "GuardrailBentOpposite"):
            self.assertEqual(CASES[name], ("guardrail", "abnormal", True))
        self.assertEqual(CASES["ManholeOpenShadow"], ("manhole", "abnormal", False))
        for name in ("ManholeDisplacedSmall", "ManholeDisplacedLateral"):
            self.assertEqual(CASES[name], ("manhole", "abnormal", True))
    def test_new_normal_variants_have_explicit_truth(self):
        for name, kind in (("GuardrailNormalCurved", "guardrail"), ("GuardrailNormalJoint", "guardrail"),
                           ("GuardrailNormalLight", "guardrail"), ("ManholeNormalPattern", "manhole"),
                           ("ManholeNormalWorn", "manhole"), ("ManholePassingVehicle", "manhole"),
                           ("GuardrailNormalShadow", "guardrail"), ("ManholeNormalShadow", "manhole")):
            with self.subTest(name=name):
                self.assertEqual(CASES[name], (kind, "normal", True))
    def test_whole_clips_and_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            splits, rows = {}, {}
            for index, split in enumerate(("train", "val", "test")):
                folder = root / split
                folder.mkdir()
                ok, image = cv2.imencode(".png", np.full((20, 30, 3), index * 40, dtype=np.uint8))
                self.assertTrue(ok)
                image.tofile(folder / "0.png")
                scenario = {"seed": index + 10, "episode": 1, "scenario": "Facility", "scenario_variant": "DelineatorMissing",
                            "hazard_state": "abnormal", "facility": {"variant": "DelineatorMissing", "kind": "delineator",
                            "state": "abnormal", "present": False, "reference_position_world": [1, 2, 3]}}
                row = {"frame": 0, "timestamp": 1, "image": "0.png", "width": 30, "height": 20, "scenario": scenario}
                rows[split] = row
                (folder / "ground_truth.jsonl").write_text(json.dumps(row), encoding="utf-8")
                splits[split] = [folder]
            self.assertEqual(audit_facility_splits(splits)["splits"]["test"]["cases"], {"DelineatorMissing": 1})
            rows["val"]["scenario"]["seed"] = 10
            (splits["val"][0] / "ground_truth.jsonl").write_text(json.dumps(rows["val"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Seed leakage"):
                audit_facility_splits(splits)
            rows["val"]["scenario"]["seed"] = 11
            rows["val"]["scenario"]["facility"]["present"] = True
            (splits["val"][0] / "ground_truth.jsonl").write_text(json.dumps(rows["val"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid facility truth"):
                audit_facility_splits(splits)
            rows["val"]["scenario"]["facility"]["present"] = False
            (splits["val"][0] / "ground_truth.jsonl").write_text(json.dumps(rows["val"]), encoding="utf-8")
            (splits["val"][0] / "0.png").write_bytes((splits["train"][0] / "0.png").read_bytes())
            with self.assertRaisesRegex(ValueError, "Image leakage"):
                audit_facility_splits(splits)


if __name__ == "__main__":
    unittest.main()
