import csv
import tempfile
import unittest
from pathlib import Path

from ip_commandmic.experiments import append_event


class ExperimentTests(unittest.TestCase):
    def test_append_event_creates_header_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.csv"
            append_event(path, experiment_id="test", event="start")
            append_event(path, experiment_id="test", event="stop")
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(["start", "stop"], [row["event"] for row in rows])


if __name__ == "__main__":
    unittest.main()
