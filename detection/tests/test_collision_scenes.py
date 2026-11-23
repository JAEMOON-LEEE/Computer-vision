"""The physical scene audit must distinguish bumper contact from queue spacing."""
import unittest

from detection.collision_scenes import same_physics_events, surface_gap


def car(x, z=0, yaw=90):
    return {"position":[x,.507,z],"yaw":yaw,"half_length":.8}


class CollisionSceneGeometryTests(unittest.TestCase):
    def test_normal_bumper_gap(self):
        self.assertAlmostEqual(surface_gap(car(0),car(2.35)),.75,places=5)

    def test_touching_and_overlap_are_close(self):
        self.assertAlmostEqual(surface_gap(car(0),car(1.6)),0,places=5)
        self.assertEqual(surface_gap(car(0),car(1.3)),0)

    def test_side_contact_uses_width_and_heading(self):
        self.assertAlmostEqual(surface_gap(car(0,yaw=0),car(1,yaw=0)),.33,places=5)
        self.assertEqual(surface_gap(car(0,yaw=0),car(1,yaw=90)),0)

    def test_direction_and_translation_do_not_change_clearance(self):
        self.assertAlmostEqual(surface_gap(car(0),car(2.35)),surface_gap(car(10,3,270),car(12.35,3,270)),places=5)

    def test_contact_serializers_may_round_same_float_differently(self):
        event=dict(event_id="a",event_type="vehicle_collision",evidence="physics_contact",
                   object_a=1,object_b=2,timestamp=339.719971,relative_speed_units_per_second=6.5)
        self.assertTrue(same_physics_events([event],[dict(event,timestamp=339.71997)]))
        self.assertFalse(same_physics_events([event],[dict(event,object_b=3)]))
        self.assertFalse(same_physics_events([event],[dict(event,timestamp=340)]))
        self.assertFalse(same_physics_events([event,event],[event]))


if __name__=="__main__":
    unittest.main()
