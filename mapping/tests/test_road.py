"""python -m unittest discover -s mapping/tests"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

MAPPING_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAPPING_DIR))

from twinsight_mapping.road import GroundPlane, _clip_unit, analyse_road, build_context  # noqa: E402
from twinsight_mapping.synthetic import PinholeCamera, SceneConfig  # noqa: E402

PPM = 20  # 노면 그림 해상도(px/m)
X_RANGE, Z_RANGE = (-15.0, 15.0), (-20.0, 140.0)


def road_texture() -> np.ndarray:
    """위에서 본 노면(BGR): 노란 중앙선 x=0, 점선 x=±3.5(3 m/8 m), 가장자리선 x=±7, 풀 |x|>8.5,
    z=40~43 횡단보도, z=37.5~38 오른쪽(x>0) 정지선."""
    w, h = int((X_RANGE[1] - X_RANGE[0]) * PPM), int((Z_RANGE[1] - Z_RANGE[0]) * PPM)
    rng = np.random.default_rng(0)
    img = np.clip(rng.normal(118, 6, (h, w, 1)), 0, 255).repeat(3, axis=2).astype(np.uint8)
    col = lambda x: int(round((x - X_RANGE[0]) * PPM))  # noqa: E731
    row = lambda z: int(round((Z_RANGE[1] - z) * PPM))  # noqa: E731
    grass = (60, 110, 70)
    img[:, :col(-8.5)] = grass
    img[:, col(8.5):] = grass
    def band(x0, x1, z0, z1, color):
        img[row(z1):row(z0), col(x0):col(x1)] = color
    band(-0.08, 0.08, Z_RANGE[0], Z_RANGE[1], (40, 200, 235))           # 노란 중앙선
    for x in (-7.0, 7.0):
        band(x - 0.08, x + 0.08, Z_RANGE[0], Z_RANGE[1], (235, 235, 235))  # 가장자리선
    for x in (-3.5, 3.5):
        for z in np.arange(Z_RANGE[0], Z_RANGE[1], 8.0):
            band(x - 0.08, x + 0.08, z, z + 3.0, (235, 235, 235))         # 차선 점선
    img[row(43):row(40), col(-7):col(7)] = (118, 118, 118)
    for x in np.arange(-6.75, 6.8, 1.0):
        band(x, x + 0.5, 40.0, 43.0, (235, 235, 235))                      # 횡단보도
    band(0.1, 7.0, 37.5, 38.0, (235, 235, 235))                              # 정지선(멀어지는 쪽)
    return img


def render(cfg: SceneConfig, texture: np.ndarray):
    cam = PinholeCamera(cfg)
    plane = GroundPlane.from_camera(cam.K, np.c_[cam.R, cam.t], cfg.image_size, 0.0)
    w, h = cfg.image_size
    us, vs = np.meshgrid(np.arange(w, dtype=float), np.arange(h, dtype=float))
    g = plane.to_ground(np.c_[us.ravel(), vs.ravel()])
    _, front = plane.to_pixel(g)
    mx = ((g[:, 0] - X_RANGE[0]) * PPM).reshape(h, w).astype(np.float32)
    my = ((Z_RANGE[1] - g[:, 1]) * PPM).reshape(h, w).astype(np.float32)
    img = cv2.remap(texture, mx, my, cv2.INTER_AREA, borderMode=cv2.BORDER_CONSTANT, borderValue=(200, 170, 120))
    img[~front.reshape(h, w)] = (230, 200, 160)  # 하늘
    return img, plane


class RoadContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = SceneConfig(image_size=(960, 540), camera_position=(-4.0, 9.0, -10.0), pitch_deg=16.0, yaw_deg=4.0,
                          vertical_fov_deg=45.0)
        cls.image, cls.plane = render(cfg, road_texture())
        cls.scene = analyse_road(cls.image, cls.plane, max_distance_m=80)
        cls.ctx = build_context(cls.scene, cls.plane, camera_id="synthetic")

    def ground_x(self, lateral):
        return float(self.scene.frame.to_ground([[30.0, lateral]])[0, 0])

    def test_lines_found_at_true_positions(self):
        yellow = [l for l in self.scene.lines if l.color == "yellow"]
        self.assertTrue(yellow)
        self.assertAlmostEqual(self.ground_x(self.scene.centre_lateral), 0.0, delta=0.25)
        dashed = [l for l in self.scene.lines if l.kind == "dashed"]
        xs = sorted(self.ground_x(l.lateral_m) for l in dashed)
        self.assertEqual(len(xs), 2, xs)
        np.testing.assert_allclose(xs, [-3.5, 3.5], atol=0.3)
        for l in dashed:
            self.assertAlmostEqual(l.dash_period_m, 8.0, delta=1.0)
            self.assertAlmostEqual(l.dash_length_m, 3.0, delta=1.0)

    def test_road_polygon_covers_road_only(self):
        poly = np.array(self.ctx["road_polygon"])
        self.assertGreaterEqual(len(poly), 3)
        self.assertTrue(((poly >= 0) & (poly <= 1)).all())
        w, h = self.plane.image_size
        def inside(x, z):
            uv = self.plane.to_pixel([[x, z]])[0][0] / [w, h]
            return cv2.pointPolygonTest(poly.astype(np.float32), (float(uv[0]), float(uv[1])), False) >= 0
        self.assertTrue(inside(2.0, 30.0) and inside(-5.0, 20.0) and inside(6.0, 38.0))
        self.assertFalse(inside(11.0, 30.0) or inside(-11.0, 25.0))

    def test_crosswalk_and_stop_zone(self):
        self.assertEqual(len(self.ctx["crosswalks"]), 1)
        a0, a1 = self.ctx["crosswalks"][0]["along_m"]
        z0 = float(self.scene.frame.to_ground([[a0, 0.0]])[0, 1])
        z1 = float(self.scene.frame.to_ground([[a1, 0.0]])[0, 1])
        self.assertAlmostEqual(z0, 40.0, delta=1.0)
        self.assertAlmostEqual(z1, 43.0, delta=1.0)
        self.assertEqual([s["side"] for s in self.ctx["stop_lines"]], ["away"])
        self.assertGreaterEqual(len(self.ctx["stop_zones"]), 2)  # 정지선 앞(멀어지는 쪽) + 횡단보도 뒤(다가오는 쪽)
        sides = {b["side"]: b for b in self.ctx["stop_zone_basis"]}
        self.assertEqual(sides["away"]["basis"], "stop_line")
        self.assertEqual(sides["toward"]["basis"], "crosswalk")

    def test_clip_unit(self):
        poly = _clip_unit(np.array([[-0.5, 0.5], [0.5, -0.5], [1.5, 0.5], [0.5, 1.5]]))
        self.assertTrue(((poly >= 0) & (poly <= 1)).all())
        self.assertGreater(cv2.contourArea(poly.astype(np.float32)), 0.7)


if __name__ == "__main__":
    unittest.main()
