"""python -m unittest discover -s mapping/tests"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

MAPPING_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAPPING_DIR))

from twinsight_mapping.calibration import latlon_to_local_xz, local_xz_to_latlon  # noqa: E402
from twinsight_mapping.pose import (  # noqa: E402
    describe_pose,
    estimate_camera_pose,
    focal_from_homography,
    pose_report,
)
from twinsight_mapping.synthetic import PinholeCamera, SceneConfig  # noqa: E402

CAMERAS = [
    SceneConfig(),
    SceneConfig(image_size=(720, 480), camera_position=(-12.0, 11.0, 5.0), pitch_deg=25.0, yaw_deg=35.0,
                vertical_fov_deg=38.0),
    SceneConfig(image_size=(1280, 720), camera_position=(3.0, 6.0, -25.0), pitch_deg=10.0, yaw_deg=-60.0,
                vertical_fov_deg=55.0),
]


def _points(cfg):
    cam = PinholeCamera(cfg)
    xs, zs = np.meshgrid(np.arange(-30, 31, 5.0), np.arange(-40, 91, 5.0))
    ground = np.c_[xs.ravel(), zs.ravel()]
    uv, depth = cam.project(np.c_[ground[:, 0], np.zeros(len(ground)), ground[:, 1]])
    ok = (depth > 0) & cam.in_frame(uv)
    return uv[ok], ground[ok], cam


class PoseTest(unittest.TestCase):
    def test_recovers_known_cameras(self):
        for cfg in CAMERAS:
            pixels, ground, _ = _points(cfg)
            d = describe_pose(estimate_camera_pose(pixels, ground, cfg.image_size), cfg.image_size)
            x, h, z = cfg.camera_position
            np.testing.assert_allclose(d["unity"]["position"], [x, h, z], atol=1e-3)
            self.assertAlmostEqual(d["pitch_deg"], cfg.pitch_deg, delta=1e-3)
            self.assertAlmostEqual(d["heading_deg"], cfg.yaw_deg % 360.0, delta=1e-3)
            self.assertAlmostEqual(d["vertical_fov_deg"], cfg.vertical_fov_deg, delta=1e-3)
            self.assertAlmostEqual(abs(d["roll_deg"]) % 360.0, 0.0, delta=1e-3)

    def test_focal_from_homography(self):
        cfg = CAMERAS[1]
        pixels, ground, cam = _points(cfg)
        H, _ = cv2.findHomography(ground, pixels)
        self.assertAlmostEqual(focal_from_homography(H, cfg.image_size), cam.K[0, 0], delta=1e-3 * cam.K[0, 0])

    def test_fixed_focal(self):
        cfg = CAMERAS[0]
        pixels, ground, cam = _points(cfg)
        pose = estimate_camera_pose(pixels[:8], ground[:8], cfg.image_size, focal=cam.K[0, 0])
        self.assertTrue(pose["focal_fixed"])
        self.assertAlmostEqual(pose["center"][2], cfg.camera_position[1], delta=1e-3)

    def test_report_scales_unity_values_and_adds_latlon(self):
        cfg = CAMERAS[0]
        pixels, ground, _ = _points(cfg)
        origin = (36.78, 127.0)
        report = pose_report(pixels, ground, cfg.image_size, origin_latlon=origin, meters_per_unit=2.0)
        np.testing.assert_allclose(report["unity"]["position"], np.array(cfg.camera_position) / 2.0, atol=1e-3)
        lat, lon = report["position_latlon"]
        np.testing.assert_allclose(latlon_to_local_xz(lat, lon, origin),
                                   [cfg.camera_position[0], cfg.camera_position[2]], atol=1e-3)


class LatLonRoundTripTest(unittest.TestCase):
    def test_round_trip(self):
        origin = (36.78, 127.0)
        for x, z in [(0.0, 0.0), (120.5, -80.25), (-300.0, 450.0)]:
            lat, lon = local_xz_to_latlon(x, z, origin)
            np.testing.assert_allclose(latlon_to_local_xz(lat, lon, origin), [x, z], atol=1e-6)


class CalibrateToolPoseTest(unittest.TestCase):
    def test_calibration_writes_pose(self):
        cfg = CAMERAS[1]
        pixels, ground, _ = _points(cfg)
        origin = (36.78, 127.0)
        pick = np.linspace(0, len(pixels) - 1, 12).astype(int)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            image = tmp / "cam_20261019_120000.png"
            cv2.imwrite(str(image), np.full((cfg.image_size[1], cfg.image_size[0], 3), 90, np.uint8))
            points = tmp / "points.csv"
            with open(points, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["id", "u", "v", "lat", "lon"])
                for i, k in enumerate(pick, 1):
                    lat, lon = local_xz_to_latlon(ground[k, 0], ground[k, 1], origin)
                    writer.writerow([i, pixels[k, 0], pixels[k, 1], f"{lat:.10f}", f"{lon:.10f}"])
            out = tmp / "calibration" / "cam.json"
            subprocess.run([sys.executable, str(MAPPING_DIR / "scripts" / "calibrate_homography.py"),
                            "--image", str(image), "--points", str(points), "--origin", f"{origin[0]},{origin[1]}",
                            "--out", str(out), "--no-show"], check=True, capture_output=True)
            pose = json.loads(out.with_suffix(".pose.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(pose["position_m"]["height"], cfg.camera_position[1], delta=0.01)
            self.assertAlmostEqual(pose["pitch_deg"], cfg.pitch_deg, delta=0.05)
            self.assertAlmostEqual(pose["heading_deg"], cfg.yaw_deg % 360.0, delta=0.05)
            self.assertAlmostEqual(pose["vertical_fov_deg"], cfg.vertical_fov_deg, delta=0.05)


if __name__ == "__main__":
    unittest.main()
