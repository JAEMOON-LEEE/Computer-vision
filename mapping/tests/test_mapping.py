"""python -m unittest discover -s mapping/tests"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping import fit_homography, load_detections, load_export, pixels_to_ground  # noqa: E402
from twinsight_mapping.evaluate import (  # noqa: E402
    check_camera_consistency,
    control_point_errors,
    fit_from_control_points,
    greedy_match,
    iou_matrix,
    object_errors,
    summarize_rows,
)
from twinsight_mapping.homography import select_spread_points  # noqa: E402
from twinsight_mapping.synthetic import PinholeCamera, SceneConfig, generate  # noqa: E402


class HomographyTest(unittest.TestCase):
    def setUp(self):
        self.cam = PinholeCamera(SceneConfig())
        xs, zs = np.meshgrid(np.arange(-6, 7, 3.0), np.arange(5, 80, 5.0))
        self.ground = np.c_[xs.ravel(), zs.ravel()]
        world = np.c_[self.ground[:, 0], np.zeros(len(self.ground)), self.ground[:, 1]]
        self.pixels, _ = self.cam.project(world)

    def test_flat_road_is_recovered_exactly(self):
        idx = select_spread_points(self.pixels, 6)
        H = fit_homography(self.pixels[idx], self.ground[idx])
        np.testing.assert_allclose(pixels_to_ground(H, self.pixels), self.ground, atol=1e-4)  # 0.1 mm

    def test_pixels_above_horizon_are_nan(self):
        H = fit_homography(self.pixels, self.ground)
        sky = np.array([[960.0, 5.0]])  # 화면 맨 위는 지평선 위
        self.assertTrue(np.isnan(pixels_to_ground(H, sky)).all())

    def test_needs_four_points(self):
        with self.assertRaises(ValueError):
            fit_homography(self.pixels[:3], self.ground[:3])

    def test_spread_points_are_unique_and_cover_the_image(self):
        idx = select_spread_points(self.pixels, 6)
        self.assertEqual(len(set(idx.tolist())), 6)
        chosen_span = np.ptp(self.pixels[idx], axis=0)
        self.assertTrue((chosen_span >= 0.9 * np.ptp(self.pixels, axis=0)).all())


class MatchingTest(unittest.TestCase):
    def test_iou(self):
        iou = iou_matrix([[0, 0, 10, 10]], [[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]])
        np.testing.assert_allclose(iou, [[1.0, 1 / 3, 0.0]])

    def test_greedy_match_prefers_best_pair(self):
        gt = [[0, 0, 10, 10], [100, 100, 110, 110]]
        det = [[1, 0, 11, 10], [100, 100, 110, 111], [0, 0, 10, 10]]
        pairs = {(g, d) for g, d, _ in greedy_match(gt, det, 0.5)}
        self.assertEqual(pairs, {(0, 2), (1, 1)})


class EndToEndTest(unittest.TestCase):
    def _export(self, tmp, **kwargs):
        cfg = SceneConfig(frames=40, fake_detections=True, **kwargs)
        return load_export(generate(cfg, Path(tmp) / "export"))

    def test_flat_road(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = self._export(tmp)
            self.assertLess(check_camera_consistency(export), 1e-3)

            H, fit_idx = fit_from_control_points(export.control_points, 6)
            self.assertLess(control_point_errors(export.control_points, H, fit_idx).max(), 1e-4)

            detections = load_detections(export.root / "detections.jsonl")
            rows, stats = object_errors(export, H, detections, classes={"car", "truck"})
            summary = summarize_rows(rows)
            self.assertLess(summary["ground_pixel"]["overall"]["max"], 1e-3)
            # 박스 아래 중앙은 차체 앞뒤 끝이라 실제보다 카메라 쪽으로 추정된다
            self.assertLess(summary["bbox_bottom"]["overall"]["longitudinal_bias"], -1.0)
            self.assertGreater(stats["recall"], 0.8)

    def test_curved_road_breaks_plane_assumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = self._export(tmp, sag=0.0002)
            H, fit_idx = fit_from_control_points(export.control_points, 6)
            self.assertGreater(control_point_errors(export.control_points, H, fit_idx).mean(), 0.5)


if __name__ == "__main__":
    unittest.main()
