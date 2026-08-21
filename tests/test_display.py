import unittest

from ip_commandmic.display import (
    AUXILIARY_REGION_OFFSET,
    AUXILIARY_REGION_SIZE,
    CHARACTER_ATTRIBUTE_OFFSET,
    CHARACTER_ATTRIBUTE_SIZE,
    DisplayBuffer,
    DISPLAY_CONTROL_64_OFFSET,
    DISPLAY_CONTROL_65_OFFSET,
    DISPLAY_CONTROL_66_OFFSET,
    DISPLAY_CONTROL_67_OFFSET,
    DisplayEventKind,
    DisplayPhase,
    DisplayStateModel,
    INDICATOR_STATE_OFFSET,
    KEY_AND_POINT_STATE_OFFSET,
    KEY_AND_POINT_BLINK_MASK_OFFSET,
    PRIMARY_BLINK_MASK_OFFSET,
    SECONDARY_BLINK_MASK_OFFSET,
    SECONDARY_POINT_STATE_OFFSET,
    SECONDARY_POINT_BLINK_MASK_OFFSET,
    SECONDARY_INDICATOR_STATE_OFFSET,
    VERIFIED_BASELINE_DISPLAY_TAIL,
    summarize_display_buffers,
    verified_character_blink_controls,
    verified_display_bit_controls,
    verified_display_blink_bit_controls,
    verified_display_visual_modes,
    verified_display_svg_decimal_point_paths,
)
from ip_commandmic.models import Direction
from ip_commandmic.protocol import build_frame, classify_message


class DisplayBufferTests(unittest.TestCase):
    def test_ui_metadata_covers_all_verified_steady_and_blink_planes(self):
        steady = verified_display_bit_controls()
        blink = verified_display_blink_bit_controls()
        self.assertEqual(28, len(steady))
        self.assertEqual(28, len(blink))
        self.assertEqual(
            {(item["key"], item["offset"] + 4, item["mask"]) for item in steady},
            {(item["key"], item["offset"], item["mask"]) for item in blink},
        )

    def test_ui_metadata_covers_character_blink_and_verified_visual_modes(self):
        self.assertEqual(
            tuple(range(1, 9)),
            tuple(item["position"] for item in verified_character_blink_controls()),
        )
        self.assertTrue(
            all(item["mask"] == 0x80 for item in verified_character_blink_controls())
        )
        modes = {item["value"]: item["key"] for item in verified_display_visual_modes()}
        self.assertEqual("normal_composed_display", modes[0x00])
        self.assertEqual("full_segment_pattern", modes[0x01])
        self.assertEqual("blank_display", modes[0x08])

    def test_lossless_buffer_exposes_only_verified_text_semantics(self):
        raw = b"QTH NODE" + VERIFIED_BASELINE_DISPLAY_TAIL
        display = DisplayBuffer(raw)
        self.assertEqual(raw, display.raw)
        self.assertEqual(8, AUXILIARY_REGION_OFFSET)
        self.assertEqual(20, AUXILIARY_REGION_SIZE)
        self.assertEqual(bytes(20), display.auxiliary_region_raw)
        self.assertEqual(28, CHARACTER_ATTRIBUTE_OFFSET)
        self.assertEqual(8, CHARACTER_ATTRIBUTE_SIZE)
        self.assertEqual(bytes(8), display.character_attribute_raw)
        self.assertEqual((), display.verified_blinking_character_positions)
        self.assertEqual("QTH NODE", display.primary_text)
        self.assertEqual(VERIFIED_BASELINE_DISPLAY_TAIL, display.unknown_tail)
        self.assertEqual(((56, 0x88),), display.unknown_nonzero_offsets)
        self.assertEqual(56, INDICATOR_STATE_OFFSET)
        self.assertEqual(0x88, display.indicator_state_byte)
        self.assertEqual(57, SECONDARY_INDICATOR_STATE_OFFSET)
        self.assertEqual(0, display.secondary_indicator_state_byte)
        self.assertEqual(58, KEY_AND_POINT_STATE_OFFSET)
        self.assertEqual(0, display.key_and_point_state_byte)
        self.assertEqual(59, SECONDARY_POINT_STATE_OFFSET)
        self.assertEqual(0, display.secondary_point_state_byte)
        self.assertEqual(60, PRIMARY_BLINK_MASK_OFFSET)
        self.assertEqual(0, display.primary_blink_mask_byte)
        self.assertEqual(61, SECONDARY_BLINK_MASK_OFFSET)
        self.assertEqual(0, display.secondary_blink_mask_byte)
        self.assertEqual(62, KEY_AND_POINT_BLINK_MASK_OFFSET)
        self.assertEqual(0, display.key_and_point_blink_mask_byte)
        self.assertEqual(63, SECONDARY_POINT_BLINK_MASK_OFFSET)
        self.assertEqual(0, display.secondary_point_blink_mask_byte)
        self.assertEqual(64, DISPLAY_CONTROL_64_OFFSET)
        self.assertEqual(0, display.display_control_64_byte)
        self.assertEqual("normal_composed_display", display.verified_offset64_visual_state)
        self.assertEqual(65, DISPLAY_CONTROL_65_OFFSET)
        self.assertEqual(0, display.display_control_65_byte)
        self.assertEqual(
            "no_visible_change_all_visible", display.verified_offset65_visual_state
        )
        self.assertEqual(66, DISPLAY_CONTROL_66_OFFSET)
        self.assertEqual(0, display.display_control_66_byte)
        self.assertEqual(
            "no_visible_change_all_visible", display.verified_offset66_visual_state
        )
        self.assertEqual(67, DISPLAY_CONTROL_67_OFFSET)
        self.assertEqual(0, display.display_control_67_byte)
        self.assertEqual(
            "no_visible_change_all_visible", display.verified_offset67_visual_state
        )
        self.assertEqual(
            ("low_power", "rssi"), display.verified_indicators
        )
        self.assertEqual((), display.verified_rssi_bars)

    def test_exact_offset56_visual_mappings_and_unknown_value(self):
        expected = {
            0x00: (),
            0x01: ("message",),
            0x04: ("shift",),
            0x05: ("shift", "message"),
            0x08: ("low_power",),
            0x80: ("rssi",),
            0x88: ("low_power", "rssi"),
            0x8A: ("low_power", "audible", "rssi"),
            0x90: ("rssi",),
            0xA0: ("rssi",),
            0xB0: ("rssi",),
            0xC0: ("rssi",),
            0xD0: ("rssi",),
            0xE0: ("rssi",),
            0xF0: ("rssi",),
            0xFA: ("low_power", "audible", "rssi"),
        }
        for value, indicators in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[56] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(indicators, display.verified_indicators)
            self.assertEqual(list(indicators), display.to_dict()["verified_indicators"])

        expected_bars = {
            0x80: (),
            0x90: (3,),
            0xA0: (2,),
            0xB0: (2, 3),
            0xC0: (1,),
            0xD0: (1, 3),
            0xE0: (1, 2),
            0xF0: (1, 2, 3),
            0xFA: (1, 2, 3),
        }
        for value, bars in expected_bars.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[56] = value
            self.assertEqual(bars, DisplayBuffer(bytes(raw)).verified_rssi_bars)

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[56] = 0x10
        unknown = DisplayBuffer(bytes(raw))
        self.assertIsNone(unknown.verified_indicators)
        self.assertIsNone(unknown.verified_rssi_bars)

        raw[56] = 0x8F
        combined = DisplayBuffer(bytes(raw))
        self.assertEqual(
            ("low_power", "shift", "audible", "message", "rssi"),
            combined.verified_indicators,
        )
        self.assertEqual((), combined.verified_rssi_bars)

    def test_offset57_maps_every_remaining_standard_icon_bit(self):
        expected = {
            0x01: "bluetooth",
            0x02: "lone_worker",
            0x04: "talk_around",
            0x08: "gps",
            0x10: "encryption",
            0x20: "scan_target",
            0x40: "scan",
            0x80: "bell",
        }
        for value, indicator in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[56] = 0
            raw[57] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.secondary_indicator_state_byte)
            self.assertEqual((indicator,), display.verified_indicators)
            self.assertEqual((indicator,), display.verified_secondary_indicators)

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[56] = 0x0F
        raw[57] = 0xFF
        display = DisplayBuffer(bytes(raw))
        self.assertEqual(
            (
                "low_power",
                "shift",
                "audible",
                "message",
                "bell",
                "scan",
                "scan_target",
                "encryption",
                "gps",
                "talk_around",
                "lone_worker",
                "bluetooth",
            ),
            display.verified_indicators,
        )

    def test_offset58_maps_dealer_icons_and_first_four_decimal_points(self):
        expected = {
            0x01: ((), (4,)),
            0x02: ((), (3,)),
            0x04: ((), (2,)),
            0x08: ((), (1,)),
            0x10: (("dealer_p4",), ()),
            0x20: (("dealer_p3",), ()),
            0x40: (("dealer_p2",), ()),
            0x80: (("dealer_p1",), ()),
        }
        for value, (keys, points) in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[56] = 0
            raw[58] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(keys, display.verified_dealer_key_icons)
            self.assertEqual(points, display.verified_decimal_points)
            self.assertEqual(keys, display.verified_indicators)

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[56] = 0
        raw[58] = 0xFF
        display = DisplayBuffer(bytes(raw))
        self.assertEqual(
            ("dealer_p1", "dealer_p2", "dealer_p3", "dealer_p4"),
            display.verified_dealer_key_icons,
        )
        self.assertEqual((1, 2, 3, 4), display.verified_decimal_points)

    def test_offset59_high_nibble_maps_last_four_decimal_points(self):
        expected = {
            0x10: (8,),
            0x20: (7,),
            0x40: (6,),
            0x80: (5,),
        }
        for value, points in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[59] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.secondary_point_state_byte)
            self.assertEqual(points, display.verified_decimal_points)
            self.assertEqual(0, display.unresolved_offset59_low_nibble)

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[58] = 0x0F
        raw[59] = 0xFF
        display = DisplayBuffer(bytes(raw))
        self.assertEqual(tuple(range(1, 9)), display.verified_decimal_points)
        self.assertEqual(0x0F, display.unresolved_offset59_low_nibble)

    def test_decimal_point_ui_controls_are_ordered_left_to_right(self):
        steady = [
            item for item in verified_display_bit_controls()
            if str(item["key"]).startswith("decimal_")
        ]
        blinking = [
            item for item in verified_display_blink_bit_controls()
            if str(item["key"]).startswith("decimal_")
        ]
        self.assertEqual([f"decimal_{position}" for position in range(1, 9)], [item["key"] for item in steady])
        self.assertEqual([f"decimal_{position}" for position in range(1, 9)], [item["key"] for item in blinking])
        self.assertEqual(
            (382, 384, 383, 386, 385, 387, 388, 389),
            verified_display_svg_decimal_point_paths(),
        )

    def test_offset60_mirrors_offset56_as_blink_mask(self):
        expected = {
            0x01: (("message",), ()),
            0x02: (("audible",), ()),
            0x04: (("shift",), ()),
            0x08: (("low_power",), ()),
            0x10: ((), (3,)),
            0x20: ((), (2,)),
            0x40: ((), (1,)),
            0x80: (("rssi",), ()),
        }
        for value, (indicators, bars) in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[60] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.primary_blink_mask_byte)
            self.assertEqual(indicators, display.verified_blinking_indicators)
            self.assertEqual(bars, display.verified_blinking_rssi_bars)

    def test_offset61_mirrors_offset57_as_blink_mask(self):
        expected = {
            0x01: "bluetooth",
            0x02: "lone_worker",
            0x04: "talk_around",
            0x08: "gps",
            0x10: "encryption",
            0x20: "scan_target",
            0x40: "scan",
            0x80: "bell",
        }
        for value, indicator in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[61] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.secondary_blink_mask_byte)
            self.assertEqual(
                (indicator,), display.verified_secondary_blinking_indicators
            )

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[61] = 0xFF
        display = DisplayBuffer(bytes(raw))
        self.assertEqual(
            ("bell", "scan", "scan_target", "encryption", "gps",
             "talk_around", "lone_worker", "bluetooth"),
            display.verified_secondary_blinking_indicators,
        )

    def test_offset62_mirrors_offset58_as_blink_mask(self):
        expected = {
            0x01: ((), (4,)),
            0x02: ((), (3,)),
            0x04: ((), (2,)),
            0x08: ((), (1,)),
            0x10: (("dealer_p4",), ()),
            0x20: (("dealer_p3",), ()),
            0x40: (("dealer_p2",), ()),
            0x80: (("dealer_p1",), ()),
        }
        for value, (keys, points) in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[62] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.key_and_point_blink_mask_byte)
            self.assertEqual(keys, display.verified_blinking_dealer_key_icons)
            self.assertEqual(points, display.verified_blinking_decimal_points)

    def test_offset63_high_nibble_mirrors_offset59_point_blink_mask(self):
        expected = {
            0x10: (8,),
            0x20: (7,),
            0x40: (6,),
            0x80: (5,),
        }
        for value, points in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[63] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.secondary_point_blink_mask_byte)
            self.assertEqual(points, display.verified_blinking_decimal_points)
            self.assertEqual(0, display.unresolved_offset63_low_nibble)

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[62] = 0x0F
        raw[63] = 0xFF
        display = DisplayBuffer(bytes(raw))
        self.assertEqual(tuple(range(1, 9)), display.verified_blinking_decimal_points)
        self.assertEqual(0x0F, display.unresolved_offset63_low_nibble)

    def test_offset64_exposes_only_synchronized_verified_visual_states(self):
        expected = {
            0x00: "normal_composed_display",
            0x01: "full_segment_pattern",
            0x02: "lower_segment_pattern",
            0x04: "u_segment_pattern",
            0x08: "blank_display",
            0x10: "blank_display",
            0x20: "blank_display",
            0x40: "blank_display",
            0x80: "blank_display",
        }
        for value, state in expected.items():
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[64] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.display_control_64_byte)
            self.assertEqual(state, display.verified_offset64_visual_state)

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[64] = 0x03
        self.assertIsNone(DisplayBuffer(bytes(raw)).verified_offset64_visual_state)

    def test_offset64_exposes_exact_photographed_segment_patterns(self):
        raw = bytearray(DisplayBuffer.from_primary_text("TEST").raw)
        raw[64] = 0x02
        lower = DisplayBuffer(bytes(raw))
        self.assertEqual(
            tuple(("e", "m", "d") for _ in range(8)),
            lower.verified_offset64_pattern["segments_by_position"],
        )
        self.assertEqual(
            ("rssi", "dealer_p2", "dealer_p3"),
            lower.verified_offset64_pattern["indicators"],
        )
        self.assertEqual(tuple(range(1, 9)), lower.verified_offset64_pattern["decimal_points"])

        raw[64] = 0x04
        upper = DisplayBuffer(bytes(raw))
        self.assertEqual(
            ("b", "e", "m", "c", "d"),
            upper.verified_offset64_pattern["segments_by_position"][0],
        )
        self.assertEqual(
            tuple(("e", "m", "c", "d") for _ in range(7)),
            upper.verified_offset64_pattern["segments_by_position"][1:],
        )
        self.assertEqual(
            ("scan", "encryption", "rssi_bar_3"),
            upper.verified_offset64_pattern["indicators"],
        )
        self.assertEqual((), upper.verified_offset64_pattern["decimal_points"])

        self.assertIn("verified_offset64_pattern", upper.to_dict())

    def test_offset65_records_bounded_negative_visual_results(self):
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[65] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.display_control_65_byte)
            self.assertEqual(
                "no_visible_change_all_visible",
                display.verified_offset65_visual_state,
            )

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[65] = 0x03
        self.assertIsNone(DisplayBuffer(bytes(raw)).verified_offset65_visual_state)

    def test_offset66_records_bounded_negative_visual_results(self):
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[66] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.display_control_66_byte)
            self.assertEqual(
                "no_visible_change_all_visible",
                display.verified_offset66_visual_state,
            )

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[66] = 0x03
        self.assertIsNone(DisplayBuffer(bytes(raw)).verified_offset66_visual_state)

    def test_offset67_records_bounded_negative_visual_results(self):
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
            raw[67] = value
            display = DisplayBuffer(bytes(raw))
            self.assertEqual(value, display.display_control_67_byte)
            self.assertEqual(
                "no_visible_change_all_visible",
                display.verified_offset67_visual_state,
            )

        raw = bytearray(DisplayBuffer.from_primary_text("QTH NODE").raw)
        raw[67] = 0x03
        self.assertIsNone(DisplayBuffer(bytes(raw)).verified_offset67_visual_state)

    def test_character_attributes_blink_all_eight_positions(self):
        for position, offset in enumerate(range(28, 36), 1):
            raw = bytearray(DisplayBuffer.from_primary_text("ABCDEFGH").raw)
            raw[8:28] = b" " * 20
            raw[offset] = 0x80
            display = DisplayBuffer(bytes(raw))
            self.assertEqual((position,), display.verified_blinking_character_positions)

        raw = bytearray(DisplayBuffer.from_primary_text("ABCDEFGH").raw)
        raw[32] = 0x80
        raw[33] = 0x80
        self.assertEqual(
            (5, 6), DisplayBuffer(bytes(raw)).verified_blinking_character_positions
        )

    def test_replacing_primary_text_preserves_every_unknown_byte(self):
        original = DisplayBuffer(b"QTH NODE" + VERIFIED_BASELINE_DISPLAY_TAIL)
        changed = original.with_primary_text("TEST TWO")
        self.assertEqual("TEST TWO", changed.primary_text)
        self.assertEqual(original.unknown_tail, changed.unknown_tail)

    def test_invalid_size_and_text_are_rejected(self):
        with self.assertRaises(ValueError):
            DisplayBuffer(bytes(67))
        with self.assertRaises(ValueError):
            DisplayBuffer.from_primary_text("NINE CHARS")
        with self.assertRaises(UnicodeEncodeError):
            DisplayBuffer.from_primary_text("RADIO \N{BLACK STAR}")


class DisplayStateModelTests(unittest.TestCase):
    @staticmethod
    def _message(command: int, payload: bytes, direction: Direction):
        return classify_message(build_frame(0x02, command, payload), direction)

    def test_complete_transaction_tracks_lossless_state_and_revision(self):
        state = DisplayStateModel()
        raw = b"QTH NODE" + VERIFIED_BASELINE_DISPLAY_TAIL

        before = state.consume(self._message(0x07, b"\x02", Direction.RADIO_TO_MIC))
        updated = state.consume(self._message(0x0A, raw, Direction.RADIO_TO_MIC))
        after = state.consume(self._message(0x08, b"\x00\x44", Direction.RADIO_TO_MIC))
        ack = state.consume(self._message(0x09, b"\x01", Direction.MIC_TO_RADIO))

        self.assertEqual(DisplayEventKind.SYNC_BEFORE, before.kind)
        self.assertEqual(DisplayEventKind.BUFFER_UPDATED, updated.kind)
        self.assertEqual(raw, updated.buffer.raw)
        self.assertEqual(DisplayEventKind.SYNC_AFTER, after.kind)
        self.assertEqual(DisplayEventKind.ACKNOWLEDGED, ack.kind)
        self.assertEqual(DisplayPhase.ACKNOWLEDGED, state.phase)
        self.assertEqual(1, state.revision)
        self.assertIsNone(state.last_warning)

    def test_out_of_sequence_update_is_retained_and_warned(self):
        state = DisplayStateModel()
        raw = b"QTH NODE" + VERIFIED_BASELINE_DISPLAY_TAIL
        event = state.consume(self._message(0x0A, raw, Direction.RADIO_TO_MIC))
        self.assertEqual(DisplayEventKind.BUFFER_UPDATED, event.kind)
        self.assertEqual("display buffer received during idle", event.warning)
        self.assertEqual(raw, state.current.raw)

    def test_classifier_exports_json_safe_lossless_display_fields(self):
        raw = DisplayBuffer.from_primary_text(" VOL  7").raw
        message = self._message(0x0A, raw, Direction.RADIO_TO_MIC)
        self.assertEqual(" VOL  7", message.metadata["display_text"])
        self.assertEqual(7, message.metadata["volume_level"])
        self.assertEqual(raw[8:].hex(), message.metadata["display_unknown_hex"])
        self.assertEqual(
            [{"offset": 56, "value": 0x88}],
            message.metadata["display_unknown_nonzero_offsets"],
        )

    def test_inventory_reports_variation_by_absolute_unknown_offset(self):
        first = DisplayBuffer.from_primary_text("FIRST")
        changed_tail = bytearray(VERIFIED_BASELINE_DISPLAY_TAIL)
        changed_tail[4] = 0x20  # Absolute payload offset 12.
        second = DisplayBuffer.from_primary_text("SECOND", tail=bytes(changed_tail))
        report = summarize_display_buffers(
            [("a.pcapng", first), ("b.pcapng", second)]
        )
        self.assertEqual(2, report["display_count"])
        self.assertEqual(2, report["distinct_unknown_tail_count"])
        self.assertEqual(
            [{"value": 0, "count": 1}, {"value": 0x20, "count": 1}],
            report["variable_unknown_offsets"]["12"],
        )


if __name__ == "__main__":
    unittest.main()
