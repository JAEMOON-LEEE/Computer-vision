import unittest
import numpy as np
from detection.facility_reference import ReferenceBank, ReferenceChangeMonitor, assess_visibility
from detection.facility_state import FacilityEvidenceGate


class FacilityReferenceTests(unittest.TestCase):
    def setUp(self):
        self.im = np.zeros((96, 96, 3), dtype=np.uint8)
        self.im[24:72, 24:72] = 180
        self.roi = (8, 8, 88, 88)

    def test_reference_requires_approval_and_same_camera_facility(self):
        bank = ReferenceBank()
        with self.assertRaises(ValueError):
            bank.register('c', 'f', self.im, self.roi, confirmed_normal=False)
        bank.register('c', 'f', self.im, self.roi, confirmed_normal=True)
        self.assertAlmostEqual(bank.distance('c', 'f', self.im, self.roi), 0)
        with self.assertRaises(ValueError): bank.distance('other', 'f', self.im, self.roi)
        with self.assertRaises(ValueError): bank.distance('c', 'f', self.im, (8, 8, 87, 88))
        modified = self.im.copy(); modified[24:72, 24:72] = 0
        self.assertGreater(bank.distance('c', 'f', modified, self.roi), 0)

    def test_missing_inputs_occlusion_blur_and_gate_reset(self):
        check = lambda image, boxes, healthy=True: assess_visibility(image, self.roi, vehicle_boxes=boxes,
            detector_healthy=healthy, camera_stable=True, min_focus=1)
        self.assertFalse(check(self.im, None)['visible'])
        self.assertFalse(check(self.im, [], False)['visible'])
        self.assertFalse(check(self.im, [(10,10,70,70)])['visible'])
        self.assertFalse(check(np.zeros_like(self.im), [])['visible'])
        self.assertTrue(check(self.im, [])['visible'])
        gate = FacilityEvidenceGate('manhole', .2, min_duration_seconds=1, min_observations=3, max_gap_seconds=.6)
        self.assertEqual(gate.update(0, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(gate.update(.5, None, visible=False, camera_stable=True), 'unknown')
        self.assertEqual(gate.update(1, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(gate.update(1.5, .9, visible=True, camera_stable=True), 'observing')
        self.assertEqual(gate.update(2, .9, visible=True, camera_stable=True), 'suspected_change')

    def test_integrated_monitor_requires_reference_and_safe_observation(self):
        bank=ReferenceBank()
        monitor=ReferenceChangeMonitor(bank, 'camera', 'facility', self.roi, 'manhole', .01,
                                       min_duration_seconds=1, min_observations=3, max_gap_seconds=.6)
        args={'vehicle_boxes': [], 'detector_healthy':True, 'camera_stable':True, 'min_focus':1}
        self.assertEqual(monitor.observe(self.im, 0, **args)['state'], 'unknown')
        bank.register('camera', 'facility', self.im, self.roi, confirmed_normal=True)
        self.assertEqual(monitor.observe(self.im, .5, **args)['state'], 'normal_observation')
        args['vehicle_boxes']=[(10,10,70,70)]
        result=monitor.observe(self.im, 1, **args)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['quality']['reason'], 'possible_vehicle_occlusion')


if __name__ == '__main__': unittest.main()
