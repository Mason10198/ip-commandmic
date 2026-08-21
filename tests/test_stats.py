import unittest

from ip_commandmic.analysis import distribution


class StatisticsTests(unittest.TestCase):
    def test_distribution(self):
        result = distribution([1.0, 2.0, 3.0])
        self.assertEqual(3, result["count"])
        self.assertEqual(1.0, result["min"])
        self.assertEqual(2.0, result["mean"])
        self.assertEqual(3.0, result["max"])

    def test_empty_distribution(self):
        self.assertEqual(0, distribution([])["count"])
        self.assertIsNone(distribution([])["mean"])


if __name__ == "__main__":
    unittest.main()
