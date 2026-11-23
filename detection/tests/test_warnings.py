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

    def test_stationary_hazard_id_changes_do_not_repeat_alerts(self):
        engine = WarningEngine(); alerts = []
        for i in range(20):
            alerts.extend(engine.update(frame(i / 10, [detection(track=1 if i < 8 else 2)])))
        self.assertEqual(len(alerts), 1)

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
    def sequence(self, context=None, structure=False, stop=True, track=True, other_x=60):
        engine = WarningEngine(context)
        alerts = []
        for i in range(25):
            # Approach a stopped vehicle/barrier; then remain in contact-like visual overlap.
            x = 10 + min(i, 10) * 3 if stop else 10 + i * 3
            first = detection("car", [x, 40, x + 30, 60], 1 if track else None)
            second = detection("barrier" if structure else "car", [other_x, 40, other_x + 30, 60], 2 if track else None)
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

    def test_small_rear_end_overlap_still_requires_motion_and_excludes_stop_zone(self):
        self.assertEqual(len(self.sequence(other_x=68)), 1)
        context = {"stop_zones": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}
        self.assertFalse(self.sequence(context=context, other_x=68))

    def test_overlap_alone_and_passing_vehicles_do_not_warn(self):
        engine = WarningEngine()
        for i in range(25):
            self.assertFalse(engine.update(frame(i / 10, [detection("car", track=1), detection("car", track=2)])))
        self.assertFalse(self.sequence(stop=False))

    def test_stop_zone_suppresses_red_light_queue(self):
        context = {"stop_zones": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}
        self.assertFalse(self.sequence(context))

    def test_trained_stop_policy_can_warn_inside_zone_without_bypassing_motion(self):
        class Policy:
            threshold=0.8
            def score(self, features):
                return 0.95 if features[1]>.3 else 0.1
        context={"stop_zones":[[[0,0],[1,0],[1,1],[0,1]]]}
        for other_x,expected in [(60,False),(52,True)]:
            engine=WarningEngine(context,stop_model=Policy());alerts=[]
            for i in range(25):
                x=10+min(i,10)*3
                alerts.extend(engine.update(frame(i/10,[detection("car",[x,40,x+30,60],1),
                    detection("car",[other_x,40,other_x+30,60],2)])))
            self.assertEqual(bool(alerts),expected)
            if alerts:self.assertIn("stop_zone_decision",alerts[0])
        engine=WarningEngine(context,stop_model=Policy())
        for i in range(25):
            self.assertFalse(engine.update(frame(i/10,[detection("car",track=1),detection("car",track=2)])))

    def test_untracked_boxes_cannot_claim_collision(self):
        self.assertFalse(self.sequence(track=False))

    def test_weak_history_can_be_retained_but_cannot_emit_stop_collision(self):
        class Policy:
            threshold = .6
            def score(self, features):
                return 1.0
        engine = WarningEngine({"stop_zones": [[[0,0],[1,0],[1,1],[0,1]]]}, stop_model=Policy())
        for i in range(25):
            x = 10 + min(i,10)*3
            weak = detection("car", [x,40,x+30,60], 1)
            weak["confidence"] = .4
            self.assertFalse(engine.update(frame(i/10, [weak, detection("car", [52,40,82,60], 2)])))
        self.assertTrue(engine.history)

    def test_distant_directed_approach_is_distinct_from_box_jitter(self):
        for jitter in (False, True):
            engine = WarningEngine(); alerts = []
            for i in range(25):
                x = 19 + i % 2 * 2 if jitter else 10 + min(i, 10)
                alerts.extend(engine.update(frame(i / 10, [
                    detection("car", [x,40,x+30,60],1),
                    detection("car", [48,40,78,60],2)])))
            self.assertEqual(bool(alerts), not jitter)

    def test_briefly_occluded_barrier_requires_repeated_recent_observations(self):
        for visible_until, single, expected in [(10,False,True),(10,True,False),(3,False,False)]:
            engine = WarningEngine(); alerts = []
            for i in range(25):
                x = 10 + min(i,10) * 3
                detections = [detection("car", [x,40,x+30,60],1)]
                if i < visible_until and (not single or i == visible_until - 1):
                    detections.append(detection("barrier", [60,40,90,60],2))
                alerts.extend(engine.update(frame(i / 10, detections)))
            self.assertEqual(bool(alerts), expected)
            if alerts:
                self.assertTrue(alerts[0]["evidence"][1]["temporarily_occluded"])

    def test_continuing_contact_does_not_realert_when_box_drifts_after_cooldown(self):
        engine = WarningEngine(); alerts = []
        for i in range(250):
            x = 10 + min(i,10)*3 + min(max(i-160,0),10)
            alerts.extend(engine.update(frame(i / 10, [
                detection("car", [x,40,x+30,60],1),
                detection("barrier", [60,40,90,60],2)])))
        self.assertEqual(len(alerts), 1)


if __name__ == "__main__":
    unittest.main()
