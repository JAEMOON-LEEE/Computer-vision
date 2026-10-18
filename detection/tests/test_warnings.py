import unittest

from detection.warnings import WarningEngine


def detection(name="pothole", box=None, track=None, confidence=0.9):
    return {"class_name": name, "bbox_xyxy": box or [30, 30, 55, 55], "confidence": confidence,
            "track_id": track, "model_id": "primary"}


def frame(time, detections, **extra):
    return {"camera_id": "test", "frame": round(time * 10), "timestamp": time,
            "width": 200, "height": 120, "detections": detections, **extra}


class HazardWarningTests(unittest.TestCase):
    def test_persistent_hazard_warns_once_and_low_confidence_does_not(self):
        engine = WarningEngine()
        alerts = []
        for i in range(12):
            alerts.extend(engine.update(frame(i / 10, [detection()])))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "road_damage")
        self.assertEqual(alerts[0]["basis"], "visual_detections_and_motion")
        self.assertEqual(alerts[0]["status"], "unconfirmed")
        engine = WarningEngine()
        self.assertFalse(any(engine.update(frame(i / 10, [detection(confidence=0.3)])) for i in range(12)))

    def test_brief_hazard_and_missing_frames_do_not_accumulate(self):
        engine = WarningEngine()
        for i in range(3):
            self.assertFalse(engine.update(frame(i / 10, [detection()])))
        engine.update(frame(0.9, []))
        for i in range(3):
            self.assertFalse(engine.update(frame(1.0 + i / 10, [detection()])))

    def test_does_not_read_unity_accident_ground_truth(self):
        engine = WarningEngine()
        for i in range(10):
            self.assertFalse(engine.update(frame(i / 10, [],
                scenario={"scenario": "VehicleCollision", "events": [{"event_type": "vehicle_collision"}]},
                objects=[{"class_name": "debris"}], signals={"vehicle": "red"})))

    def test_context_excludes_nonroad_detections(self):
        engine = WarningEngine({"road_polygon": [[0, 0.6], [1, 0.6], [1, 1], [0, 1]]})
        for i in range(10):
            self.assertFalse(engine.update(frame(i / 10, [detection()])))

    def test_camera_switch_and_time_reset_do_not_share_history(self):
        engine = WarningEngine()
        engine.update(frame(1, [detection()]))
        engine.update(frame(1.2, [detection()]))
        self.assertFalse(engine.update(frame(1.4, [detection()], camera_id="other")))
        self.assertFalse(engine.update(frame(0, [detection()], camera_id="other")))


class CollisionWarningTests(unittest.TestCase):
    def sequence(self, context=None, structure=False, stop=True, track=True):
        engine = WarningEngine(context)
        alerts = []
        for i in range(25):
            # Approach a stopped vehicle/barrier; then remain in contact-like visual overlap.
            x = 10 + min(i, 10) * 3 if stop else 10 + i * 3
            first = detection("car", [x, 40, x + 30, 60], 1 if track else None)
            second = detection("barrier" if structure else "car", [60, 40, 90, 60], 2 if track else None)
            alerts.extend(engine.update(frame(i / 10, [first, second])))
        return alerts

    def test_approach_contact_and_stop_yields_suspected_collision(self):
        alerts = self.sequence()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "suspected_vehicle_collision")

    def test_structure_collision_has_separate_type(self):
        alerts = self.sequence(structure=True)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "suspected_vehicle_structure_collision")

    def test_overlap_alone_and_passing_vehicles_do_not_warn(self):
        engine = WarningEngine()
        for i in range(25):
            self.assertFalse(engine.update(frame(i / 10, [detection("car", track=1), detection("car", track=2)])))
        self.assertFalse(self.sequence(stop=False))

    def test_stop_zone_suppresses_red_light_queue(self):
        context = {"stop_zones": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}
        self.assertFalse(self.sequence(context))

    def test_untracked_boxes_cannot_claim_collision(self):
        self.assertFalse(self.sequence(track=False))


if __name__ == "__main__":
    unittest.main()
