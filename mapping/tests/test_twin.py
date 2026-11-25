"""python -m unittest discover -s mapping/tests"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping.calibration import local_xz_to_latlon  # noqa: E402
from twinsight_mapping.synthetic import PinholeCamera, SceneConfig  # noqa: E402
from twinsight_mapping.twin import RoadAxes, detection_to_twin, lanes_to_twin  # noqa: E402


def car_box(cam: PinholeCamera, x: float, z: float, length=4.6, width=1.85, height=1.5):
    corners = np.array([[x + sx * width / 2, sy * height, z + sz * length / 2]
                        for sx in (-1, 1) for sy in (0, 1) for sz in (-1, 1)])
    uv, _ = cam.project(corners)
    return [float(uv[:, 0].min()), float(uv[:, 1].min()), float(uv[:, 0].max()), float(uv[:, 1].max())]


class TwinTest(unittest.TestCase):
    def setUp(self):
        self.cfg = SceneConfig(camera_position=(0.0, 8.0, -10.0), pitch_deg=15.0, yaw_deg=0.0)
        self.cam = PinholeCamera(self.cfg)
        H_ground_to_pixel = self.cam.K @ np.column_stack([self.cam.R[:, 0], self.cam.R[:, 2], self.cam.t])
        self.H = np.linalg.inv(H_ground_to_pixel)
        origin = (37.77, 126.79)
        # 도로 중앙선: x = 0, z = -50에서 +z 방향. 카메라(z = -10)는 첫 점에서 40 m 앞
        road_pose = {"road_line": [list(local_xz_to_latlon(0.0, -50.0, origin)), list(local_xz_to_latlon(0.0, 150.0, origin))]}
        self.axes = RoadAxes.from_road_pose(road_pose, origin)

    def test_vehicle_centre_recovered(self):
        for x, z, side in [(1.8, 40.0, "away"), (-1.8, 25.0, "toward"), (5.3, 60.0, "away")]:
            det = {"class_name": "car", "confidence": 0.9, "bbox_xyxy": car_box(self.cam, x, z)}
            obj = detection_to_twin(det, self.H, self.axes, camera_along=40.0, image_size=self.cfg.image_size)
            self.assertEqual(obj["direction"], side)
            self.assertAlmostEqual(obj["lateral_m"], x, delta=0.3)
            self.assertAlmostEqual(obj["along_m"], z + 10.0, delta=0.6)   # 카메라(z=-10)에서 앞쪽 거리
            self.assertLess(obj["raw_along_m"], obj["along_m"])           # 보정 전은 카메라 쪽으로 치우친다

    def test_non_vehicle_skipped(self):
        det = {"class_name": "person", "confidence": 0.9, "bbox_xyxy": car_box(self.cam, 0.0, 30.0)}
        self.assertIsNone(detection_to_twin(det, self.H, self.axes, 0.0, self.cfg.image_size))

    def test_duplicate_classes_merged(self):
        from twinsight_mapping.twin import merge_duplicates
        objs = [{"bbox_xyxy": [10, 10, 50, 40], "confidence": 0.6, "class_name": "truck"},
                {"bbox_xyxy": [11, 10, 50, 41], "confidence": 0.8, "class_name": "car"},
                {"bbox_xyxy": [80, 10, 120, 40], "confidence": 0.5, "class_name": "car"}]
        kept = merge_duplicates(objs)
        self.assertEqual([o["class_name"] for o in kept], ["car", "car"])
        self.assertEqual(kept[0]["confidence"], 0.8)

    def test_lanes_converted(self):
        context = {"road_frame": {"origin_ground": [3.0, -5.0], "forward_ground": [0.0, 1.0], "meters_per_unit": 1.0},
                   "lanes": [{"color": "white", "kind": "dashed", "lateral_m": 0.5, "along_m": [10.0, 60.0]}]}
        lane = lanes_to_twin(context, self.axes, camera_along=40.0)[0]
        np.testing.assert_allclose(lane["lateral_m"], [3.5, 3.5], atol=1e-6)
        np.testing.assert_allclose(lane["along_m"], [15.0, 65.0], atol=1e-6)


if __name__ == "__main__":
    unittest.main()
