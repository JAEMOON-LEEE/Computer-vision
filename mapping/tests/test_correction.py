"""python -m unittest discover -s mapping/tests"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping import fit_homography, load_export  # noqa: E402
from twinsight_mapping.correction import (  # noqa: E402
    TrackClassVoter,
    TrackHeadings,
    bearing_to_vector,
    column_convergence_point,
    correct_bottom_center,
    fit_effective_dimensions,
    footprint_support,
    load_dimensions_file,
    parse_dimensions,
    required_support,
    touches_border,
)
from twinsight_mapping.evaluate import fit_from_control_points, object_errors, summarize_rows  # noqa: E402
from twinsight_mapping.synthetic import PinholeCamera, SceneConfig, generate  # noqa: E402


def _camera_and_homography(cfg=None):
    cfg = cfg or SceneConfig()
    cam = PinholeCamera(cfg)
    xs, zs = np.meshgrid(np.arange(-6, 7, 3.0), np.arange(5, 90, 5.0))
    ground = np.c_[xs.ravel(), zs.ravel()]
    pixels, _ = cam.project(np.c_[ground[:, 0], np.zeros(len(ground)), ground[:, 1]])
    return cfg, cam, fit_homography(pixels, ground)


def _car_box(cam, center_xz, size=(1.8, 1.5, 4.5)):
    """z 방향으로 놓인 상자의 화면 박스."""
    w, h, l = size
    x, z = center_xz
    corners = np.array([[x + sx * w / 2, sy * h, z + sz * l / 2] for sx in (-1, 1) for sy in (0, 1) for sz in (-1, 1)])
    uv, _ = cam.project(corners)
    return [*uv.min(axis=0), *uv.max(axis=0)]


class GeometryTest(unittest.TestCase):
    def test_columns_meet_behind_the_nadir(self):
        cfg, _, H = _camera_and_homography()
        x, h, z = cfg.camera_position
        yaw, pitch = math.radians(cfg.yaw_deg), math.radians(cfg.pitch_deg)
        forward = np.array([math.sin(yaw), math.cos(yaw)])
        expected = np.array([x, z]) - h * math.tan(pitch) * forward
        np.testing.assert_allclose(column_convergence_point(H), expected, atol=1e-3)

    def test_footprint_support(self):
        along, across = np.array([0.0, 1.0]), np.array([1.0, 0.0])
        self.assertAlmostEqual(footprint_support(4.0, 2.0, along, along), 2.0)
        self.assertAlmostEqual(footprint_support(4.0, 2.0, along, across), 1.0)
        diagonal = np.array([1.0, 1.0]) / math.sqrt(2)
        self.assertAlmostEqual(footprint_support(4.0, 2.0, along, diagonal), 3.0 / math.sqrt(2))

    def test_bearing_vector(self):
        np.testing.assert_allclose(bearing_to_vector(0), [0, 1], atol=1e-12)
        np.testing.assert_allclose(bearing_to_vector(90), [1, 0], atol=1e-12)

    def test_parse_dimensions_overrides_defaults(self):
        dims = parse_dimensions("car=4.5x1.8")
        self.assertEqual(dims["car"], (4.5, 1.8))
        self.assertIn("truck", dims)


class CorrectionTest(unittest.TestCase):
    def test_correction_moves_point_to_vehicle_center(self):
        _, cam, H = _camera_and_homography()
        dims = {"car": (4.5, 1.8)}
        for center in [(1.75, 25.0), (-5.25, 40.0), (5.25, 60.0)]:
            bbox = _car_box(cam, center)
            raw, corrected = correct_bottom_center(H, bbox, "car", bearing_to_vector(0), dims)
            self.assertGreater(np.linalg.norm(raw - center), 1.5)
            self.assertLess(np.linalg.norm(corrected - center), 0.3)

    def test_unknown_class_is_not_moved(self):
        _, cam, H = _camera_and_homography()
        raw, corrected = correct_bottom_center(H, _car_box(cam, (1.75, 25.0)), "pothole")
        np.testing.assert_array_equal(raw, corrected)

    def test_track_heading_needs_motion(self):
        headings = TrackHeadings(min_distance=2.0)
        self.assertIsNone(headings.update(7, [0.0, 0.0]))
        self.assertIsNone(headings.update(7, [0.0, 1.0]))
        np.testing.assert_allclose(headings.update(7, [0.0, 3.0]), [0, 1])
        np.testing.assert_allclose(headings.get(7), [0, 1])
        self.assertIsNone(headings.get(8))

    def test_touches_border(self):
        self.assertTrue(touches_border([0, 10, 50, 60], 100, 100))
        self.assertTrue(touches_border([10, 10, 50, 99], 100, 100))
        self.assertFalse(touches_border([10, 10, 50, 60], 100, 100))


class LearningTest(unittest.TestCase):
    def test_voter_uses_confidence_weighted_majority(self):
        voter = TrackClassVoter()
        self.assertEqual(voter.update(3, "car", 0.9), "car")
        self.assertEqual(voter.update(3, "truck", 0.4), "car")
        self.assertEqual(voter.update(3, "truck", 0.6), "truck")
        self.assertEqual(voter.update(None, "bus", 0.9), "bus")

    def test_effective_length_recovers_box_length(self):
        _, cam, H = _camera_and_homography()
        road = bearing_to_vector(0)
        samples = []
        for x in (-5.25, -1.75, 1.75, 5.25):
            for z in range(15, 75, 5):
                support, direction = required_support(H, _car_box(cam, (x, float(z))), (x, float(z)))
                samples.append(("car", support, direction, road))
        fitted = fit_effective_dimensions(samples, {"car": (4.6, 1.8)}, min_samples=10)
        self.assertAlmostEqual(fitted["car"]["length"], 4.5, delta=0.25)

    def test_load_dimensions_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "correction.json"
            path.write_text(json.dumps({"dimensions": {"car": [2.8, 1.85]}}), encoding="utf-8")
            dims = load_dimensions_file(path)
            self.assertEqual(dims["car"], (2.8, 1.85))
            self.assertIn("bus", dims)


class EndToEndTest(unittest.TestCase):
    def test_correction_removes_most_of_the_bias(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = load_export(generate(SceneConfig(frames=60), Path(tmp) / "export"))
            H, _ = fit_from_control_points(export.control_points, 8)
            dims = parse_dimensions("car=4.5x1.8,truck=8x2.5")
            rows, _ = object_errors(export, H, classes={"car", "truck"}, max_distance=80,
                                    dimensions=dims, road_heading=bearing_to_vector(0))
            summary = summarize_rows(rows)
            raw = summary["bbox_bottom"]["overall"]
            for mode in ("bbox_bottom+view", "bbox_bottom+track", "bbox_bottom+road"):
                corrected = summary[mode]["overall"]
                self.assertLess(corrected["mean"], 0.25 * raw["mean"], mode)
                self.assertLess(abs(corrected["longitudinal_bias"]), 0.3, mode)


class CalibrateScriptTest(unittest.TestCase):
    def test_heldout_calibration_on_box_vehicles(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        with tempfile.TemporaryDirectory() as tmp:
            export = generate(SceneConfig(frames=120), Path(tmp) / "export")
            subprocess.run([sys.executable, str(scripts / "calibrate_correction.py"), str(export), "--source", "gt",
                            "--road-heading-deg", "0"], check=True, capture_output=True)
            data = json.loads((export / "correction.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(data["dimensions"]["car"][0], 4.5, delta=0.3)
            raw = data["heldout"]["보정 없음"]["mean"]
            learned = data["heldout"]["학습 길이 · 다수결 클래스"]["mean"]
            self.assertLess(learned, 0.2 * raw)


if __name__ == "__main__":
    unittest.main()
