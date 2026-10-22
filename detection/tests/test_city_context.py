import json
import unittest
from pathlib import Path

from detection.warnings import inside


class CityContextRegressionTests(unittest.TestCase):
    def test_controlled_signal_queues_are_excluded_but_downstream_incidents_are_not(self):
        context = json.loads((Path(__file__).parents[1] / "config/geumchon-city-lab.context.json").read_text(encoding="utf-8"))
        # Measured box bottom-centres in held-out fixed-view clips, normalized 720x480.
        queues = [(339.8 / 720, 201.4 / 480), (346.3 / 720, 211.9 / 480)]
        incidents = [(319.2 / 720, 169.5 / 480), (322.2 / 720, 174.5 / 480), (339.9 / 720, 174.2 / 480)]
        for point in queues:
            self.assertTrue(any(inside(point, z) for z in context["stop_zones"]))
        for point in incidents:
            self.assertTrue(inside(point, context["road_polygon"]))
            self.assertFalse(any(inside(point, z) for z in context["stop_zones"]))


if __name__ == "__main__":
    unittest.main()
