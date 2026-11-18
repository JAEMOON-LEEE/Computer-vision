import unittest
import numpy as np
from detection.facility_state import FacilityEvidenceGate, roi_features


class FacilityStateTests(unittest.TestCase):
    def test_visibility_and_signal_transitions_reset_evidence(self):
        g = FacilityEvidenceGate('traffic_signal', .5, min_duration_seconds=2, min_observations=3)
        self.assertEqual(g.update(0, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(g.update(1, .9, visible=False, camera_stable=True), 'unknown')
        self.assertEqual(g.update(2, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(g.update(3, .9, visible=True, camera_stable=True, transition_or_flashing=True), 'unknown')
        self.assertEqual(g.update(4, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(g.update(5, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(g.update(6, .9, visible=True, camera_stable=True), 'suspected_dark')
        self.assertEqual(g.update(8, .9, visible=True, camera_stable=True), 'unknown')

    def test_roi_must_be_visible_in_frame(self):
        image = np.zeros((100, 120, 3), dtype=np.uint8)
        self.assertGreater(len(roi_features(image, (5, 5, 80, 80))), 0)
        with self.assertRaises(ValueError): roi_features(image, (-1, 0, 20, 20))

    def test_manhole_occlusion_does_not_trigger_change(self):
        g = FacilityEvidenceGate('manhole', .5, min_duration_seconds=2, min_observations=3)
        self.assertEqual(g.update(0, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(g.update(1, None, visible=False, camera_stable=True), 'unknown')
        self.assertEqual(g.update(2, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(g.update(3, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(g.update(4, .9, visible=True, camera_stable=True), 'suspected_change')

if __name__ == '__main__': unittest.main()
