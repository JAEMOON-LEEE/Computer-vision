import unittest

from detection.evaluate_detection import average_precision


class AveragePrecisionTests(unittest.TestCase):
    def test_perfect_and_missed_objects(self):
        self.assertAlmostEqual(average_precision([(0.8, True), (0.9, True)], 2), 1.0)
        self.assertEqual(average_precision([], 2), 0)

    def test_false_positive_before_match_lowers_ap(self):
        self.assertAlmostEqual(average_precision([(0.9, False), (0.8, True)], 1), 0.5)

    def test_missing_classes_are_not_scored_as_perfect(self):
        self.assertIsNone(average_precision([], 0))
        self.assertLess(average_precision([(0.8, True)], 2), 0.51)


if __name__ == "__main__":
    unittest.main()
