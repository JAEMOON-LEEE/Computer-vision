import unittest

from detection.train_stop_collision import minimum_control_clearance


def obj(kind,x,z):
    return {'class_name':kind,'ground_point_world':[x,0.507,z]}


class StopCaptureValidationTests(unittest.TestCase):
    def test_background_car_does_not_break_queue_audit(self):
        objects=[obj('car',-11.21,.24),obj('car',5.92,-1.06),obj('car',4.22,-1.06)]
        self.assertAlmostEqual(minimum_control_clearance(objects),.25)

    def test_background_car_does_not_hide_barrier_overlap(self):
        objects=[obj('car',-11,.24),obj('barrier',5.76,-1.06),obj('car',5,-1.06)]
        self.assertLess(minimum_control_clearance(objects),0)

    def test_opposite_lanes_are_not_a_longitudinal_pair(self):
        with self.assertRaises(ValueError):
            minimum_control_clearance([obj('car',5,.24),obj('car',5,-1.06)])
