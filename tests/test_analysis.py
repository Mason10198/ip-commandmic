import unittest

from ip_commandmic.analysis import byte_differences
from ip_commandmic.checksums import rank_crc16_candidates
from ip_commandmic.protocol import MIC_IDLE_HEARTBEAT, RADIO_IDLE_HEARTBEAT


class AnalysisTests(unittest.TestCase):
    def test_idle_direction_differences(self):
        differences = byte_differences(RADIO_IDLE_HEARTBEAT, MIC_IDLE_HEARTBEAT)
        self.assertEqual([7, 8, 10], [difference.offset for difference in differences])

    def test_checksum_search_finds_verified_commandmic_crc(self):
        candidates = rank_crc16_candidates([RADIO_IDLE_HEARTBEAT, MIC_IDLE_HEARTBEAT])
        self.assertTrue(candidates)
        best = candidates[0]
        self.assertEqual("crc16_modbus", best.algorithm)
        self.assertEqual("after_start_byte", best.covered_slice)
        self.assertEqual("big", best.byte_order)
        self.assertEqual(2, best.matches)


if __name__ == "__main__":
    unittest.main()
