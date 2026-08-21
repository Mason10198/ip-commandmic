import unittest

from ip_commandmic.models import Direction
from ip_commandmic.pcap import (
    TcpSegment,
    UdpDatagram,
    _reassemble_direction,
    _timestamp_at_offset,
    parse_rtp,
)
from ip_commandmic.protocol import RADIO_IDLE_HEARTBEAT


class PcapTests(unittest.TestCase):
    def segment(self, sequence, payload, timestamp):
        return TcpSegment(
            stream=0,
            timestamp=timestamp,
            source_ip="192.168.0.1",
            destination_ip="192.168.0.2",
            source_port=52001,
            destination_port=52001,
            sequence=sequence,
            payload=payload,
        )

    def test_reassembly_deduplicates_overlap_and_tracks_time(self):
        segments = [
            self.segment(100, RADIO_IDLE_HEARTBEAT[:6], 1.0),
            self.segment(103, RADIO_IDLE_HEARTBEAT[3:], 2.0),
            self.segment(100, RADIO_IDLE_HEARTBEAT[:6], 3.0),
        ]
        data, markers, warnings = _reassemble_direction(segments)
        self.assertEqual(RADIO_IDLE_HEARTBEAT, data)
        self.assertFalse(warnings)
        self.assertEqual(1.0, _timestamp_at_offset(markers, 0))
        self.assertEqual(2.0, _timestamp_at_offset(markers, 6))

    def test_udp_boot_packet_is_zero_payload_rtp(self):
        datagram = UdpDatagram(
            timestamp=1.0,
            source_ip="192.168.0.2",
            destination_ip="192.168.0.1",
            source_port=50000,
            destination_port=50000,
            payload=b"\x80\x7d" + bytes.fromhex("08f14d5a659c7069c2cc") + bytes(320),
        )
        record = datagram.to_dict("192.168.0.1", "192.168.0.2")
        self.assertEqual(Direction.MIC_TO_RADIO.value, record["direction"])
        self.assertEqual("rtp", record["kind"])
        self.assertEqual(125, record["rtp_payload_type"])
        self.assertEqual(320, record["rtp_payload_length"])
        self.assertTrue(record["rtp_payload_all_zero"])

    def test_parse_observed_rtp_header(self):
        data = bytes.fromhex("807dca2a462ea214b1947ef9") + bytes(320)
        packet = parse_rtp(data)
        self.assertIsNotNone(packet)
        self.assertEqual(0xCA2A, packet.sequence)
        self.assertEqual(0x462EA214, packet.timestamp)
        self.assertEqual(0xB1947EF9, packet.ssrc)
        self.assertEqual(125, packet.payload_type)
        self.assertEqual(320, len(packet.payload))


if __name__ == "__main__":
    unittest.main()
