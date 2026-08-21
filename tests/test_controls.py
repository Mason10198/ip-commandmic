import unittest

from ip_commandmic.controls import (
    KEY_NEUTRAL_VALUE,
    KEY_PRESS_VALUES,
    ORDINARY_KEY_BUTTONS,
    control_display_name,
    key_tap_values,
    key_wire_value,
    normalize_button_name,
)
from ip_commandmic.models import Direction, MessageKind
from ip_commandmic.protocol import encode_key_state, encode_key_tap, parse_stream


class ControlEncodingTests(unittest.TestCase):
    def test_every_ordinary_key_round_trips_press_release_neutral(self):
        self.assertNotIn("emergency", ORDINARY_KEY_BUTTONS)
        for button in ORDINARY_KEY_BUTTONS:
            values = key_tap_values(button)
            self.assertEqual(KEY_PRESS_VALUES[button], values[0])
            self.assertEqual(KEY_PRESS_VALUES[button] | 0x80, values[1])
            self.assertEqual(KEY_NEUTRAL_VALUE, values[2])
            wire = b"".join(encode_key_tap(button))
            messages, remainder = parse_stream(wire, Direction.MIC_TO_RADIO)
            self.assertFalse(remainder)
            self.assertEqual(3, len(messages))
            self.assertTrue(all(message.kind is MessageKind.KEY_STATE for message in messages))
            self.assertEqual(
                [(button, "press"), (button, "release"), (None, "neutral")],
                [
                    (message.metadata["key_button"], message.metadata["key_action"])
                    for message in messages
                ],
            )

    def test_emergency_requires_explicit_gate(self):
        with self.assertRaisesRegex(ValueError, "explicit safety gate"):
            key_tap_values("emergency")
        values = key_tap_values("emergency", allow_emergency=True)
        self.assertEqual((0x40, 0xC0, 0x7F), values)

    def test_human_readable_and_physical_aliases_normalize(self):
        self.assertEqual("f1", normalize_button_name("Monitor"))
        self.assertEqual("volume_up", normalize_button_name("F2"))
        self.assertEqual("volume_down", normalize_button_name("Volume Down"))
        self.assertEqual(0x10, key_wire_value("F2", "press"))
        self.assertEqual("Volume Up (F2 side key)", control_display_name("f2"))

    def test_neutral_and_invalid_states_are_guarded(self):
        self.assertEqual(0x7F, key_wire_value(None, "neutral"))
        neutral = encode_key_state(None, "neutral")
        messages, remainder = parse_stream(neutral, Direction.MIC_TO_RADIO)
        self.assertFalse(remainder)
        self.assertEqual("neutral", messages[0].metadata["key_action"])
        with self.assertRaisesRegex(ValueError, "must not name"):
            key_wire_value("p1", "neutral")
        with self.assertRaisesRegex(ValueError, "unknown key"):
            key_wire_value("center", "press")


if __name__ == "__main__":
    unittest.main()
