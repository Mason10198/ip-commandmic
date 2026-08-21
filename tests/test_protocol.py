import unittest
import json
from pathlib import Path

from ip_commandmic.models import Direction, MessageKind
from ip_commandmic.display import DisplayBuffer
from ip_commandmic.protocol import (
    MIC_IDLE_HEARTBEAT,
    RADIO_IDLE_HEARTBEAT,
    build_frame,
    classify_message,
    crc16_commandmic,
    encode_audio_path,
    encode_backlight_state,
    encode_display_transaction,
    encode_message,
    encode_power_state,
    encode_ptt_state,
    encode_status_led,
    parse_stream,
    stuff_bytes,
    unstuff_bytes,
)


class ProtocolTests(unittest.TestCase):
    def test_typed_control_composers_round_trip(self):
        display = DisplayBuffer.from_primary_text("QTH NODE")
        frames = (
            *encode_display_transaction(display),
            encode_status_led("orange"),
            encode_backlight_state("dim"),
            encode_ptt_state("press"),
            encode_power_state("release"),
            encode_audio_path("receive_open"),
        )
        messages, remainder = parse_stream(b"".join(frames), Direction.UNKNOWN)
        self.assertEqual(b"", remainder)
        self.assertEqual(frames, tuple(message.raw for message in messages))
        self.assertTrue(all(message.checksum_valid for message in messages))

    def test_typed_control_composers_reject_unknown_values(self):
        for composer, value in (
            (encode_status_led, "blue"),
            (encode_backlight_state, "auto"),
            (encode_ptt_state, "tap"),
            (encode_power_state, "toggle"),
            (encode_audio_path, "open"),
        ):
            with self.subTest(composer=composer.__name__):
                with self.assertRaises(ValueError):
                    composer(value)

    def test_known_heartbeats(self):
        messages, remainder = parse_stream(
            RADIO_IDLE_HEARTBEAT + MIC_IDLE_HEARTBEAT, Direction.UNKNOWN
        )
        self.assertEqual(b"", remainder)
        self.assertEqual([MessageKind.HEARTBEAT, MessageKind.HEARTBEAT], [m.kind for m in messages])
        self.assertEqual(Direction.RADIO_TO_MIC, messages[0].direction)
        self.assertEqual(Direction.MIC_TO_RADIO, messages[1].direction)
        self.assertTrue(all(message.checksum_valid for message in messages))

    def test_arbitrary_fragmentation(self):
        data = RADIO_IDLE_HEARTBEAT
        buffered = b""
        emitted = []
        for byte in data:
            messages, buffered = parse_stream(buffered + bytes([byte]), "radio")
            emitted.extend(messages)
        self.assertEqual(b"", buffered)
        self.assertEqual([data], [message.raw for message in emitted])

    def test_coalesced_frames_round_trip(self):
        data = RADIO_IDLE_HEARTBEAT * 3
        messages, remainder = parse_stream(data, "radio")
        self.assertEqual(b"", remainder)
        self.assertEqual(data, b"".join(encode_message(message) for message in messages))

    def test_unframed_bytes_are_not_silently_lost(self):
        data = b"noise" + RADIO_IDLE_HEARTBEAT
        messages, remainder = parse_stream(data, "unknown")
        self.assertEqual(b"", remainder)
        self.assertEqual(MessageKind.UNFRAMED, messages[0].kind)
        self.assertEqual(b"noise", messages[0].raw)
        self.assertEqual(data, b"".join(message.raw for message in messages))

    def test_half_magic_is_retained(self):
        messages, remainder = parse_stream(b"abc\xf3", "unknown")
        self.assertEqual(b"\xf3", remainder)
        self.assertEqual(b"abc", messages[0].raw)

    def test_resynchronizes_at_new_magic(self):
        corrupt = b"\xf3\x41\x01\x02" + RADIO_IDLE_HEARTBEAT
        messages, remainder = parse_stream(corrupt, "radio")
        self.assertFalse(remainder)
        self.assertEqual(MessageKind.UNFRAMED, messages[0].kind)
        self.assertEqual(MessageKind.HEARTBEAT, messages[1].kind)

    def test_sanitized_idle_fixture(self):
        fixture_path = Path(__file__).parent / "fixtures" / "idle_heartbeat_pairs.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for item in fixture["messages"]:
            raw = bytes.fromhex(item["raw_hex"])
            messages, remainder = parse_stream(raw, item["direction"])
            self.assertFalse(remainder)
            self.assertEqual(MessageKind.HEARTBEAT, messages[0].kind)

    def test_sanitized_startup_fixture(self):
        fixture_path = Path(__file__).parent / "fixtures" / "startup_frames.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for item in fixture["messages"]:
            raw = bytes.fromhex(item["raw_hex"])
            messages, remainder = parse_stream(raw, item["direction"])
            self.assertFalse(remainder)
            self.assertEqual(raw, messages[0].raw)
            self.assertTrue(messages[0].framing_valid)
            self.assertTrue(messages[0].checksum_valid)

    def test_verified_stuffing_and_crc(self):
        wire = bytes.fromhex(
            "f341710502001a010101ff0fff0fff0fff0f60cc49636f6d20496e63010090c71243595a680c50fd"
        )
        message = classify_message(wire, "mic")
        self.assertTrue(message.framing_valid)
        self.assertTrue(message.checksum_valid)
        self.assertTrue(message.metadata["wire_stuffed"])
        self.assertEqual(26, message.metadata["declared_payload_length"])
        self.assertEqual(wire, build_frame(0x05, 0x02, message.body))

    def test_f5_frame_with_stuffed_checksum(self):
        wire = bytes.fromhex("f541710503000101ff014cfd")
        message = classify_message(wire, "radio")
        self.assertTrue(message.checksum_valid)
        self.assertEqual(b"\x01", message.body)
        self.assertEqual(wire, build_frame(0x05, 0x03, b"\x01", start_byte=0xF5))

    def test_f5_special_frame_is_preserved_and_crc_valid(self):
        wire = bytes.fromhex("f54171ee0503011897fd")
        messages, remainder = parse_stream(wire, "mic")
        self.assertFalse(remainder)
        self.assertEqual(wire, messages[0].raw)
        self.assertTrue(messages[0].checksum_valid)
        self.assertEqual("special_or_unknown", messages[0].metadata["frame_format"])

    def test_stuffing_round_trip(self):
        logical = bytes(range(0xEF, 0x100))
        self.assertEqual(logical, unstuff_bytes(stuff_bytes(logical)))

    def test_verified_heartbeat_crc_value(self):
        decoded = RADIO_IDLE_HEARTBEAT
        self.assertEqual(0x3570, crc16_commandmic(decoded[1:-3]))

    def test_verified_volume_key_states(self):
        expected = {
            0x01: ("volume_down", "press"),
            0x81: ("volume_down", "release"),
            0x10: ("volume_up", "press"),
            0x90: ("volume_up", "release"),
            0x7F: (None, "neutral"),
        }
        for wire_value, (button, action) in expected.items():
            message = classify_message(build_frame(0x01, 0x01, bytes([wire_value])), "mic")
            self.assertEqual(MessageKind.KEY_STATE, message.kind)
            self.assertEqual(button, message.metadata["key_button"])
            self.assertEqual(action, message.metadata["key_action"])

    def test_verified_mic_gain_startup_values(self):
        for programmed_gain in (1, 2, 3, 4, 5):
            first = classify_message(
                build_frame(0x02, 0x0E, bytes((programmed_gain,))), "radio"
            )
            second = classify_message(
                build_frame(0x02, 0x0E, bytes((programmed_gain + 1,))), "radio"
            )
            self.assertEqual(MessageKind.MIC_GAIN, first.kind)
            self.assertEqual(programmed_gain, first.metadata["mic_gain_value"])
            self.assertEqual(MessageKind.MIC_GAIN, second.kind)
            self.assertEqual(programmed_gain + 1, second.metadata["mic_gain_value"])

    def test_verified_backlight_startup_values(self):
        off = classify_message(build_frame(0x02, 0x0B, b"\x00"), "radio")
        dim = classify_message(build_frame(0x02, 0x0B, b"\x01"), "radio")
        on = classify_message(build_frame(0x02, 0x0B, b"\x02"), "radio")
        self.assertEqual(MessageKind.BACKLIGHT_STATE, off.kind)
        self.assertEqual("off", off.metadata["backlight_state"])
        self.assertFalse(off.metadata["backlight_active"])
        self.assertFalse(off.metadata["backlight_dimmed"])
        self.assertEqual(MessageKind.BACKLIGHT_STATE, dim.kind)
        self.assertEqual("dim", dim.metadata["backlight_state"])
        self.assertTrue(dim.metadata["backlight_active"])
        self.assertTrue(dim.metadata["backlight_dimmed"])
        self.assertEqual(MessageKind.BACKLIGHT_STATE, on.kind)
        self.assertEqual("on", on.metadata["backlight_state"])
        self.assertTrue(on.metadata["backlight_active"])
        self.assertFalse(on.metadata["backlight_dimmed"])

    def test_verified_wizard_key_states(self):
        expected = {
            0x00: ("f1", "press"), 0x80: ("f1", "release"),
            0x34: ("keypad_0", "press"), 0xB4: ("keypad_0", "release"),
            0x03: ("keypad_1", "press"), 0x83: ("keypad_1", "release"),
            0x04: ("keypad_2", "press"), 0x84: ("keypad_2", "release"),
            0x05: ("keypad_3", "press"), 0x85: ("keypad_3", "release"),
            0x13: ("keypad_4", "press"), 0x93: ("keypad_4", "release"),
            0x14: ("keypad_5", "press"), 0x94: ("keypad_5", "release"),
            0x15: ("keypad_6", "press"), 0x95: ("keypad_6", "release"),
            0x23: ("keypad_7", "press"), 0xA3: ("keypad_7", "release"),
            0x24: ("keypad_8", "press"), 0xA4: ("keypad_8", "release"),
            0x25: ("keypad_9", "press"), 0xA5: ("keypad_9", "release"),
            0x33: ("keypad_star", "press"), 0xB3: ("keypad_star", "release"),
            0x35: ("keypad_hash", "press"), 0xB5: ("keypad_hash", "release"),
            0x02: ("p1", "press"), 0x82: ("p1", "release"),
            0x12: ("p2", "press"), 0x92: ("p2", "release"),
            0x22: ("p3", "press"), 0xA2: ("p3", "release"),
            0x32: ("p4", "press"), 0xB2: ("p4", "release"),
            0x20: ("up", "press"), 0xA0: ("up", "release"),
            0x21: ("down", "press"), 0xA1: ("down", "release"),
            0x31: ("left", "press"), 0xB1: ("left", "release"),
            0x30: ("right", "press"), 0xB0: ("right", "release"),
            0x40: ("emergency", "press"), 0xC0: ("emergency", "release"),
        }
        for wire_value, (button, action) in expected.items():
            message = classify_message(build_frame(0x01, 0x01, bytes([wire_value])), "mic")
            self.assertEqual(MessageKind.KEY_STATE, message.kind)
            self.assertEqual(button, message.metadata["key_button"])
            self.assertEqual(action, message.metadata["key_action"])

    def test_display_update_is_projected_without_changing_original_bytes(self):
        payload = b" VOL  1" + bytes(61)
        wire = build_frame(0x02, 0x0A, payload)
        message = classify_message(wire, "radio")
        self.assertEqual(MessageKind.DISPLAY_UPDATE, message.kind)
        self.assertTrue(message.metadata["display_ascii_projection"].startswith(" VOL  1"))
        self.assertEqual(" VOL  1", message.metadata["display_text"])
        self.assertEqual(1, message.metadata["volume_level"])
        self.assertEqual(wire, encode_message(message))

    def test_verified_channel_display_transaction(self):
        before = classify_message(build_frame(0x02, 0x07, b"\x02"), "radio")
        display = classify_message(
            build_frame(0x02, 0x0A, b"TEST TWO" + bytes(60)), "radio"
        )
        after = classify_message(build_frame(0x02, 0x08, b"\x00\x44"), "radio")
        ack = classify_message(build_frame(0x02, 0x09, b"\x01"), "mic")
        self.assertEqual(MessageKind.DISPLAY_SYNC, before.kind)
        self.assertEqual("before_buffer", before.metadata["display_sync_phase"])
        self.assertEqual(MessageKind.DISPLAY_UPDATE, display.kind)
        self.assertEqual("TEST TWO", display.metadata["display_text"])
        self.assertEqual(MessageKind.DISPLAY_SYNC, after.kind)
        self.assertEqual("after_buffer", after.metadata["display_sync_phase"])
        self.assertEqual(MessageKind.DISPLAY_ACK, ack.kind)

    def test_verified_ptt_state(self):
        pressed = classify_message(build_frame(0x01, 0x00, b"\x01"), "mic")
        released = classify_message(build_frame(0x01, 0x00, b"\x00"), "mic")
        self.assertEqual(MessageKind.PTT_STATE, pressed.kind)
        self.assertEqual("press", pressed.metadata["ptt_action"])
        self.assertTrue(pressed.metadata["ptt_active"])
        self.assertEqual(MessageKind.PTT_STATE, released.kind)
        self.assertEqual("release", released.metadata["ptt_action"])
        self.assertFalse(released.metadata["ptt_active"])

    def test_verified_audio_states_and_statuses(self):
        receive_open = classify_message(
            build_frame(0x01, 0x04, b"\x01\x00\x00\x00"), "radio"
        )
        transmit_active = classify_message(
            build_frame(0x01, 0x04, b"\x08\x00\x00\x00"), "radio"
        )
        closed = classify_message(build_frame(0x01, 0x04, bytes(4)), "radio")
        tx_status = classify_message(build_frame(0x02, 0x02, b"\x02"), "radio")
        rx_status = classify_message(build_frame(0x02, 0x02, b"\x04"), "radio")
        combined_status = classify_message(build_frame(0x02, 0x02, b"\x06"), "radio")
        idle_status = classify_message(build_frame(0x02, 0x02, b"\x00"), "radio")
        self.assertEqual(MessageKind.AUDIO_STATE, receive_open.kind)
        self.assertEqual("receive_open", receive_open.metadata["audio_state"])
        self.assertEqual("transmit_active", transmit_active.metadata["audio_state"])
        self.assertEqual("closed", closed.metadata["audio_state"])
        self.assertEqual(MessageKind.AUDIO_STATUS, tx_status.kind)
        self.assertEqual("transmit_active", tx_status.metadata["audio_status"])
        self.assertEqual("red", tx_status.metadata["status_led_color"])
        self.assertTrue(tx_status.metadata["status_led_red"])
        self.assertFalse(tx_status.metadata["status_led_green"])
        self.assertEqual("green", rx_status.metadata["status_led_color"])
        self.assertEqual("combined_active", combined_status.metadata["audio_status"])
        self.assertEqual("orange", combined_status.metadata["status_led_color"])
        self.assertTrue(combined_status.metadata["status_led_red"])
        self.assertTrue(combined_status.metadata["status_led_green"])
        self.assertEqual("off", idle_status.metadata["status_led_color"])

    def test_verified_power_state(self):
        activated = classify_message(build_frame(0x01, 0x09, b"\x01"), "mic")
        released = classify_message(build_frame(0x01, 0x09, b"\x00"), "mic")
        self.assertEqual(MessageKind.POWER_STATE, activated.kind)
        self.assertEqual("press", activated.metadata["power_action"])
        self.assertTrue(activated.metadata["power_active"])
        self.assertEqual(MessageKind.POWER_STATE, released.kind)
        self.assertEqual("release", released.metadata["power_action"])
        self.assertFalse(released.metadata["power_active"])


if __name__ == "__main__":
    unittest.main()
