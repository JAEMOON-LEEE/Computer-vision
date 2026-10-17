"""python -m unittest discover -s mapping/tests"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

MAPPING_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAPPING_DIR))

from twinsight_mapping import pixels_to_ground  # noqa: E402
from twinsight_mapping.calibration import (  # noqa: E402
    fit_calibration,
    latlon_to_local_xz,
    load_calibration,
    suspicious_points,
)
from twinsight_mapping.synthetic import PinholeCamera, SceneConfig  # noqa: E402

EARTH_RADIUS = 6371008.8


def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS * math.asin(math.sqrt(a))


def _road_points(image_size=(1920, 1080)):
    cam = PinholeCamera(SceneConfig(image_size=image_size))
    xs, zs = np.meshgrid([-6.0, -2.0, 2.0, 6.0], [10.0, 25.0, 45.0, 70.0])
    ground = np.c_[xs.ravel(), zs.ravel()]
    pixels, _ = cam.project(np.c_[ground[:, 0], np.zeros(len(ground)), ground[:, 1]])
    return pixels, ground


class LatLonTest(unittest.TestCase):
    def test_matches_haversine_within_half_percent(self):
        origin = (36.78, 127.0)  # 아산 부근
        for dlat, dlon in [(0.001, 0.0), (0.0, 0.001), (0.0007, -0.0012)]:
            xz = latlon_to_local_xz(origin[0] + dlat, origin[1] + dlon, origin)
            expected = _haversine(origin[0], origin[1], origin[0] + dlat, origin[1] + dlon)
            self.assertAlmostEqual(float(np.linalg.norm(xz)), expected, delta=expected * 0.005)

    def test_axes_point_east_and_north(self):
        x, z = latlon_to_local_xz(36.781, 127.001, (36.78, 127.0))
        self.assertGreater(x, 0)
        self.assertGreater(z, 0)


class FitTest(unittest.TestCase):
    def test_exact_points_have_tiny_errors(self):
        pixels, ground = _road_points()
        result = fit_calibration(pixels, ground)
        self.assertLess(result["fit_rmse_m"], 1e-4)
        self.assertLess(np.nanmax(result["loo_errors_m"]), 1e-3)

    def test_wrong_point_is_flagged(self):
        pixels, ground = _road_points()
        ground = ground.copy()
        ground[5] += [0.0, 3.0]  # 5번 점의 실제 좌표를 3 m 잘못 입력
        result = fit_calibration(pixels, ground)
        self.assertEqual(int(np.nanargmax(result["loo_errors_m"])), 5)
        self.assertIn(5, suspicious_points(result["loo_errors_m"]).tolist())


class ScriptTest(unittest.TestCase):
    def test_points_csv_end_to_end(self):
        pixels, ground = _road_points()
        held_out_pixel, held_out_ground = pixels[-1], ground[-1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            image_path = tmp / "cam-7_20261017_120000.png"
            cv2.imwrite(str(image_path), np.full((1080, 1920, 3), 80, np.uint8))
            points_csv = tmp / "points.csv"
            with open(points_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["id", "u", "v", "x", "z"])
                for i, ((u, v), (x, z)) in enumerate(zip(pixels[:-1], ground[:-1]), start=1):
                    writer.writerow([i, round(u, 2), round(v, 2), x, z])

            out = tmp / "calibration" / "cam-7.json"
            subprocess.run(
                [sys.executable, str(MAPPING_DIR / "scripts" / "calibrate_homography.py"),
                 "--image", str(image_path), "--points", str(points_csv), "--out", str(out), "--no-show"],
                check=True, capture_output=True)

            data = load_calibration(out)
            self.assertEqual(data["camera_id"], "cam-7")
            self.assertEqual(data["image_size"], [1920, 1080])
            self.assertEqual(data["units"], "m")
            estimated = pixels_to_ground(data["H"], held_out_pixel[None])[0]
            self.assertLess(np.linalg.norm(estimated - held_out_ground), 0.05)
            self.assertTrue((tmp / "calibration" / "cam-7_birdseye.png").exists())
            self.assertEqual(len(json.loads(out.read_text(encoding="utf-8"))["points"]), len(pixels) - 1)


if __name__ == "__main__":
    unittest.main()
