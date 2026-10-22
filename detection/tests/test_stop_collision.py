import unittest

import numpy as np

from detection.stop_collision import FEATURE_NAMES, pair_features


class StopCollisionFeatureTests(unittest.TestCase):
    def test_same_motion_at_two_capture_resolutions_has_same_features(self):
        def build(scale):
            a={"class_name":"car","track_id":1,"bbox_xyxy":[20*scale,20*scale,40*scale,40*scale]}
            b={"class_name":"barrier","track_id":2,"bbox_xyxy":[30*scale,20*scale,50*scale,40*scale]}
            h={1:[(t,(10+t*10)*scale,40*scale,20*scale) for t in (0,.2,.4,.6,.8,1,1.2,1.4,1.6)],
               2:[(t,40*scale,40*scale,20*scale) for t in (0,.2,.4,.6,.8,1,1.2,1.4,1.6)]}
            return pair_features(a,b,h,lambda d:d['track_id'],1.6)
        self.assertEqual(len(build(1)),len(FEATURE_NAMES))
        np.testing.assert_allclose(build(1),build(2),atol=1e-6)
