import asyncio
import struct
import tempfile
import time
import unittest
import wave
from unittest import mock

from ip_commandmic.emulator import (
    DISPLAY_AFTER,
    DISPLAY_BEFORE,
    DISPLAY_SUFFIX,
    RADIO_AUDIO_CLOSE,
    RADIO_AUDIO_OPEN,
    RADIO_AUDIO_STATUS_CLOSED,
    RADIO_AUDIO_STATUS_OPEN,
    RADIO_BOOT_RTP,
    RADIO_RTP_SSRC,
    RADIO_PROBE_HEAD,
    RADIO_PROBE_TAIL,
    RADIO_STARTUP_HELLO,
    RADIO_STARTUP_READY,
    radio_stable_sync,
    RADIO_TX_ACTIVE,
    RADIO_TX_STATUS_ACTIVE,
    MIC_RTP_SSRC,
    MIC_BOOT_RTP,
    MIC_PTT_DOWN,
    MIC_PTT_UP,
    MIC_DISPLAY_ACK,
    MIC_IDENTITY,
    MIC_PROBE_RESPONSE,
    MIC_STARTUP_SYNC,
    SYNTHETIC_MIC_MAC,
    CommandMicEmulator,
    EmulatorConfig,
    VerifiedRadioUdpProtocol,
    VerifiedMicUdpProtocol,
    run_emulator,
)
from ip_commandmic.audio import MicrophoneCaptureStats
from ip_commandmic.models import Direction, MessageKind
from ip_commandmic.protocol import (
    MIC_IDLE_HEARTBEAT,
    RADIO_IDLE_HEARTBEAT,
    build_frame,
    classify_message,
    encode_key_tap,
    parse_stream,
)


class EmulatorTests(unittest.TestCase):
    def test_radio_emulator_defaults_are_neutral_and_passive(self):
        config = EmulatorConfig("radio", "127.0.0.1", "127.0.0.2")
        self.assertEqual("", config.startup_opening_text)
        self.assertEqual("", config.startup_idle_text)
        self.assertFalse(config.startup_status_carousel)
        self.assertFalse(config.automatic_key_responses)
        self.assertFalse(config.automatic_ptt_responses)

    def test_software_mic_tx_requires_all_explicit_gates(self):
        with self.assertRaisesRegex(ValueError, "listening mic role"):
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.2",
                verified_startup=True, enable_tx=True,
            )
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            EmulatorConfig(
                "mic", "127.0.0.2", "127.0.0.1",
                verified_startup=True, listen=True, enable_tx=True,
                mic_key_script=("p1",),
            )
        with self.assertRaisesRegex(ValueError, "require enable_tx"):
            EmulatorConfig(
                "mic", "127.0.0.2", "127.0.0.1",
                verified_startup=True, listen=True,
                exit_after_tx_script=True,
            )
        config = EmulatorConfig(
            "mic", "127.0.0.2", "127.0.0.1",
            verified_startup=True, listen=True, enable_tx=True,
            tx_hold_seconds=0.5, exit_after_tx_script=True,
        )
        self.assertTrue(config.enable_tx)
        self.assertTrue(config.exit_after_tx_script)
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            EmulatorConfig(
                "mic", "127.0.0.2", "127.0.0.1",
                verified_startup=True, listen=True, enable_tx=True,
                tx_wav="unused.wav", tx_live_device="Microphone",
            )

    def test_stable_sync_uses_selected_verified_mic_gain(self):
        for gain in (1, 2, 3, 4, 5):
            sync = radio_stable_sync(gain)
            self.assertEqual(build_frame(0x02, 0x0E, bytes((gain,))), sync[8])
            self.assertEqual(build_frame(0x02, 0x0E, bytes((gain + 1,))), sync[9])

    def test_stable_sync_uses_verified_backlight_state(self):
        off = radio_stable_sync(backlight_state="off")
        dim = radio_stable_sync(backlight_state="dim")
        on = radio_stable_sync(backlight_state="on")
        self.assertEqual(build_frame(0x02, 0x0B, b"\x00"), off[1])
        self.assertEqual(build_frame(0x02, 0x0B, b"\x01"), dim[1])
        self.assertEqual(build_frame(0x02, 0x0B, b"\x02"), on[1])
        self.assertEqual(off[:1], on[:1])
        self.assertEqual(off[2:], on[2:])
        self.assertEqual(dim[:1], on[:1])
        self.assertEqual(dim[2:], on[2:])

    def test_experimental_mic_gain_companion_is_guarded_and_changes_one_frame(self):
        with self.assertRaisesRegex(ValueError, "allow_experimental_gain_pair"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                experimental_mic_gain_companion=5,
            )
        config = EmulatorConfig(
            "radio",
            "127.0.0.1",
            "127.0.0.2",
            verified_startup=True,
            mic_gain=5,
            experimental_mic_gain_companion=5,
            allow_experimental_gain_pair=True,
        )
        normal = radio_stable_sync(5)
        mutated = radio_stable_sync(
            config.mic_gain, config.experimental_mic_gain_companion
        )
        self.assertEqual(normal[:9], mutated[:9])
        self.assertNotEqual(normal[9], mutated[9])
        self.assertEqual(normal[10:], mutated[10:])
        self.assertEqual(build_frame(0x02, 0x0E, b"\x05"), mutated[9])

    def test_mic_role_only_knows_observed_heartbeat(self):
        emulator = CommandMicEmulator(EmulatorConfig("mic", "127.0.0.1", "127.0.0.2"))
        self.assertEqual(Direction.RADIO_TO_MIC, emulator.incoming_direction)
        self.assertEqual(RADIO_IDLE_HEARTBEAT, emulator.expected_heartbeat)
        self.assertEqual(MIC_IDLE_HEARTBEAT, emulator.response_heartbeat)

    def test_tx_is_disabled_by_default(self):
        config = EmulatorConfig("radio", "127.0.0.1", "127.0.0.2")
        self.assertFalse(config.enable_tx)
        self.assertFalse(config.enable_rx_audio)

    def test_receive_audio_requires_verified_radio_profile(self):
        with self.assertRaises(ValueError):
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.2", enable_rx_audio=True
            )

    def test_key_beep_is_bounded_to_verified_radio_profile_and_safe_modes(self):
        with self.assertRaisesRegex(ValueError, "verified_startup"):
            EmulatorConfig("radio", "127.0.0.1", "127.0.0.2", key_beep="normal")
        with self.assertRaisesRegex(ValueError, "unknown key beep"):
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.2",
                verified_startup=True, key_beep="other",
            )

    def test_mic_key_script_requires_verified_listening_mic_and_ordinary_keys(self):
        with self.assertRaisesRegex(ValueError, "mic role"):
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.2",
                verified_startup=True, mic_key_script=("p1",),
            )
        with self.assertRaisesRegex(ValueError, "gated mic key"):
            EmulatorConfig(
                "mic", "127.0.0.1", "127.0.0.2",
                verified_startup=True, listen=True, mic_key_script=("emergency",),
            )
        config = EmulatorConfig(
            "mic", "127.0.0.1", "127.0.0.2",
            verified_startup=True, listen=True,
            mic_key_script=("p1", "up", "keypad_5"),
        )
        self.assertEqual(("p1", "up", "keypad_5"), config.mic_key_script)
        with self.assertRaisesRegex(ValueError, "requires mic_key_script"):
            EmulatorConfig(
                "mic", "127.0.0.1", "127.0.0.2",
                verified_startup=True, listen=True, exit_after_key_script=True,
            )
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.2",
                verified_startup=True, key_beep="low", enable_rx_audio=True,
            )
        config = EmulatorConfig(
            "radio", "127.0.0.1", "127.0.0.2",
            verified_startup=True, key_beep="normal",
        )
        self.assertFalse(config.enable_tx)
        self.assertEqual(3, config.beep_level)
        with self.assertRaisesRegex(ValueError, "beep_level"):
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.2",
                verified_startup=True, key_beep="normal", beep_level=6,
            )

    def test_display_offset56_test_is_bounded_to_observed_values_and_safe_mode(self):
        with self.assertRaisesRegex(ValueError, "verified_startup"):
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.2", display_offset56_test=True
            )
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset56_test=True,
                enable_rx_audio=True,
            )
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset56_test=True,
            )
        )
        for value in (0x00, 0x88, 0x8A, 0xFA):
            tail = emulator._tail_with_offset56(value)
            self.assertEqual(value, tail[48])
            self.assertEqual(DISPLAY_SUFFIX[:48], tail[:48])
            self.assertEqual(DISPLAY_SUFFIX[49:], tail[49:])
        with self.assertRaises(ValueError):
            emulator._tail_with_offset56(0x89)

    def test_display_offset56_low_bit_test_is_bounded_and_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, "only one"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset56_test=True,
                display_offset56_low_bit_test=True,
            )
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset56_low_bit_test=True,
                enable_tx=True,
            )
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset56_low_bit_test=True,
            )
        )
        for value in (0x00, 0x08, 0x80, 0x88):
            tail = emulator._tail_with_offset56_low_candidate(value)
            self.assertEqual(value, tail[48])
            self.assertEqual(DISPLAY_SUFFIX[:48], tail[:48])
            self.assertEqual(DISPLAY_SUFFIX[49:], tail[49:])
        with self.assertRaises(ValueError):
            emulator._tail_with_offset56_low_candidate(0x89)

    def test_display_offset56_rssi_ladder_is_bounded_and_safe(self):
        with self.assertRaisesRegex(ValueError, "only one"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset56_low_bit_test=True,
                display_offset56_rssi_ladder_test=True,
            )
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset56_rssi_ladder_test=True,
            )
        )
        for value in range(0x80, 0x100, 0x10):
            tail = emulator._tail_with_offset56_rssi_candidate(value)
            self.assertEqual(value, tail[48])
            self.assertEqual(DISPLAY_SUFFIX[:48], tail[:48])
            self.assertEqual(DISPLAY_SUFFIX[49:], tail[49:])
        for value in (0x70, 0x88, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset56_rssi_candidate(value)

    def test_display_offset56_remaining_bits_test_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset56_remaining_bits_test=True,
            )
        )
        for value in (0x00, 0x01, 0x04, 0x05):
            tail = emulator._tail_with_offset56_remaining_candidate(value)
            self.assertEqual(value, tail[48])
            self.assertEqual(DISPLAY_SUFFIX[:48], tail[:48])
            self.assertEqual(DISPLAY_SUFFIX[49:], tail[49:])
        for value in (0x02, 0x08, 0x80, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset56_remaining_candidate(value)

    def test_display_offset57_bit_scan_changes_only_target_byte(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset57_bit_scan=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset57_candidate(value)
            self.assertEqual(60, len(tail))
            self.assertEqual(value, tail[49])
            self.assertEqual(bytes(49), tail[:49])
            self.assertEqual(bytes(10), tail[50:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset57_candidate(value)

    def test_display_offset58_bit_scan_changes_only_target_byte(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset58_bit_scan=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset58_candidate(value)
            self.assertEqual(60, len(tail))
            self.assertEqual(value, tail[50])
            self.assertEqual(bytes(50), tail[:50])
            self.assertEqual(bytes(9), tail[51:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset58_candidate(value)

    def test_display_offset59_bit_scan_changes_only_target_byte(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset59_bit_scan=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset59_candidate(value)
            self.assertEqual(60, len(tail))
            self.assertEqual(value, tail[51])
            self.assertEqual(bytes(51), tail[:51])
            self.assertEqual(bytes(8), tail[52:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset59_candidate(value)

    def test_offset59_all_visible_interaction_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset59_low_all_visible_test=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x0F):
            tail = emulator._tail_with_offset59_low_and_all_visible(value)
            self.assertEqual(0xFF, tail[48])
            self.assertEqual(0xFF, tail[49])
            self.assertEqual(0xFF, tail[50])
            self.assertEqual(0xF0 | value, tail[51])
            self.assertEqual(bytes(48), tail[:48])
            self.assertEqual(bytes(8), tail[52:])
        for value in (0x03, 0x10, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset59_low_and_all_visible(value)

    def test_offset60_all_visible_scan_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset60_bit_scan_all_visible=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset60_and_all_visible(value)
            self.assertEqual(bytes((0xFF, 0xFF, 0xFF, 0xF0, value)), tail[48:53])
            self.assertEqual(bytes(48), tail[:48])
            self.assertEqual(bytes(7), tail[53:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset60_and_all_visible(value)

    def test_offset61_all_visible_scan_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset61_bit_scan_all_visible=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset61_and_all_visible(value)
            self.assertEqual(bytes((0xFF, 0xFF, 0xFF, 0xF0, 0x00, value)), tail[48:54])
            self.assertEqual(bytes(48), tail[:48])
            self.assertEqual(bytes(6), tail[54:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset61_and_all_visible(value)

    def test_offset62_all_visible_scan_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset62_bit_scan_all_visible=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset62_and_all_visible(value)
            self.assertEqual(
                bytes((0xFF, 0xFF, 0xFF, 0xF0, 0x00, 0x00, value)),
                tail[48:55],
            )
            self.assertEqual(bytes(48), tail[:48])
            self.assertEqual(bytes(5), tail[55:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset62_and_all_visible(value)

    def test_offset63_all_visible_scan_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset63_bit_scan_all_visible=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset63_and_all_visible(value)
            self.assertEqual(
                bytes((0xFF, 0xFF, 0xFF, 0xF0, 0x00, 0x00, 0x00, value)),
                tail[48:56],
            )
            self.assertEqual(bytes(48), tail[:48])
            self.assertEqual(bytes(4), tail[56:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset63_and_all_visible(value)

    def test_offset64_all_visible_scan_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset64_bit_scan_all_visible=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset64_and_all_visible(value)
            self.assertEqual(
                bytes((0xFF, 0xFF, 0xFF, 0xF0, 0, 0, 0, 0, value)),
                tail[48:57],
            )
            self.assertEqual(bytes(48), tail[:48])
            self.assertEqual(bytes(3), tail[57:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset64_and_all_visible(value)

    def test_offset65_all_visible_scan_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset65_bit_scan_all_visible=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset65_and_all_visible(value)
            self.assertEqual(
                bytes((0xFF, 0xFF, 0xFF, 0xF0, 0, 0, 0, 0, 0, value)),
                tail[48:58],
            )
            self.assertEqual(bytes(48), tail[:48])
            self.assertEqual(bytes(2), tail[58:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset65_and_all_visible(value)

    def test_offset66_all_visible_scan_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset66_bit_scan_all_visible=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset66_and_all_visible(value)
            self.assertEqual(
                bytes((0xFF, 0xFF, 0xFF, 0xF0, 0, 0, 0, 0, 0, 0, value)),
                tail[48:59],
            )
            self.assertEqual(bytes(48), tail[:48])
            self.assertEqual(bytes(1), tail[59:])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset66_and_all_visible(value)

    def test_offset67_all_visible_scan_is_bounded(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset67_bit_scan_all_visible=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_with_offset67_and_all_visible(value)
            self.assertEqual(
                bytes((0xFF, 0xFF, 0xFF, 0xF0, 0, 0, 0, 0, 0, 0, 0, value)),
                tail[48:60],
            )
            self.assertEqual(bytes(48), tail[:48])
        for value in (0x03, 0x05, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_with_offset67_and_all_visible(value)

    def test_offsets8_33_observed_probe_changes_only_observed_fields(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offsets8_33_observed_probe=True,
            )
        )
        plain = emulator._tail_for_offsets8_33_observed_probe("plain")
        base = emulator._tail_for_offsets8_33_observed_probe("keypad_base")
        at32 = emulator._tail_for_offsets8_33_observed_probe("offset32")
        at33 = emulator._tail_for_offsets8_33_observed_probe("offset33")
        self.assertEqual(0x88, plain[48])
        self.assertEqual(bytes(20), plain[:20])
        self.assertEqual(b" " * 20, base[:20])
        self.assertEqual(0x80, at32[24])
        self.assertEqual(0, at32[25])
        self.assertEqual(0, at33[24])
        self.assertEqual(0x80, at33[25])
        self.assertEqual(0x88, base[48])
        self.assertEqual(0x88, at32[48])
        self.assertEqual(0x88, at33[48])
        with self.assertRaises(ValueError):
            emulator._tail_for_offsets8_33_observed_probe("both")

    def test_character_blink_position_scan_is_one_attribute_byte_at_a_time(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_character_blink_position_scan=True,
            )
        )
        for position in range(1, 9):
            tail = emulator._tail_for_character_blink_position(position)
            self.assertEqual(b" " * 20, tail[:20])
            attributes = tail[20:28]
            self.assertEqual(0x80, attributes[position - 1])
            self.assertEqual(1, sum(value != 0 for value in attributes))
            self.assertEqual(0x88, tail[48])
        for position in (0, 9):
            with self.assertRaises(ValueError):
                emulator._tail_for_character_blink_position(position)

    def test_character_attribute_bit_scan_is_bounded_to_position_five(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_character_attribute_bit_scan=True,
            )
        )
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            tail = emulator._tail_for_character_attribute_value(value)
            self.assertEqual(b" " * 20, tail[:20])
            self.assertEqual(value, tail[24])  # Absolute offset 32.
            self.assertEqual(1 if value else 0, sum(v != 0 for v in tail[20:28]))
            self.assertEqual(0x88, tail[48])
        for value in (0x03, 0xFF):
            with self.assertRaises(ValueError):
                emulator._tail_for_character_attribute_value(value)

    def test_status_led_scan_is_guarded_like_other_visual_diagnostics(self):
        config = EmulatorConfig(
            "radio",
            "127.0.0.1",
            "127.0.0.2",
            verified_startup=True,
            status_led_observed_scan=True,
        )
        self.assertTrue(config.status_led_observed_scan)
        with self.assertRaisesRegex(ValueError, "cannot be combined with audio or TX"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                status_led_observed_scan=True,
                enable_rx_audio=True,
            )

    def test_backlight_timeout_test_is_guarded_like_visual_diagnostics(self):
        config = EmulatorConfig(
            "radio",
            "127.0.0.1",
            "127.0.0.2",
            verified_startup=True,
            backlight_timeout_wake_test=True,
        )
        self.assertTrue(config.backlight_timeout_wake_test)
        with self.assertRaisesRegex(ValueError, "cannot be combined with audio or TX"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                backlight_timeout_wake_test=True,
                enable_tx=True,
            )

    def test_display_diagnostic_can_use_blank_primary_text(self):
        with self.assertRaisesRegex(ValueError, "requires a display diagnostic"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_test_blank_text=True,
            )
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                display_offset59_bit_scan=True,
                display_test_blank_text=True,
            )
        )
        self.assertEqual("", emulator._display_test_text)
        frame = emulator._display_frame(
            emulator._display_test_text,
            tail=emulator._tail_with_offset59_candidate(0x80),
        )
        self.assertEqual(bytes(8), frame[7:15])

    def test_mic_recording_requires_verified_radio_and_cannot_overlap_rx(self):
        with self.assertRaisesRegex(ValueError, "verified_startup"):
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.2", record_mic_wav="mic.wav"
            )
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                enable_rx_audio=True,
                record_mic_wav="mic.wav",
            )
        with self.assertRaises(ValueError):
            EmulatorConfig(
                "mic",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                enable_rx_audio=True,
            )

    def test_verified_mic_startup_requires_listener_mode(self):
        with self.assertRaises(ValueError):
            EmulatorConfig(
                "mic", "127.0.0.1", "127.0.0.2", verified_startup=True
            )
        config = EmulatorConfig(
            "mic",
            "127.0.0.1",
            "127.0.0.2",
            verified_startup=True,
            listen=True,
        )
        self.assertTrue(config.verified_startup)

    def test_verified_frames_match_cold_boot_capture(self):
        self.assertEqual("f341710505000101794cfd", RADIO_STARTUP_HELLO.hex())
        self.assertEqual("f341710501000101494dfd", RADIO_STARTUP_READY.hex())
        self.assertEqual("f341710206000401000000a15cfd", RADIO_PROBE_HEAD[0].hex())
        self.assertEqual("f541710503000101ff014cfd", RADIO_PROBE_HEAD[1].hex())
        self.assertEqual("f54171ee0504012895fd", RADIO_PROBE_TAIL[-1].hex())
        self.assertEqual(332, len(RADIO_BOOT_RTP))
        self.assertFalse(any(RADIO_BOOT_RTP[12:]))
        self.assertEqual("807d08f14d5a659c7069c2cc", MIC_BOOT_RTP[:12].hex())
        self.assertFalse(any(MIC_BOOT_RTP[12:]))
        self.assertEqual("f341710502001a", MIC_IDENTITY[:7].hex())
        self.assertEqual(6, len(SYNTHETIC_MIC_MAC))
        self.assertEqual(0x02, SYNTHETIC_MIC_MAC[0] & 0x03)
        self.assertEqual(SYNTHETIC_MIC_MAC, classify_message(MIC_IDENTITY, "mic").body[18:24])
        self.assertEqual("f341710209000101e9ff0afd", MIC_DISPLAY_ACK.hex())

    def test_verified_display_frame_matches_capture(self):
        emulator = CommandMicEmulator(
            EmulatorConfig("radio", "127.0.0.1", "127.0.0.2")
        )
        frame = emulator._display_frame("QTH NODE")
        message = classify_message(frame, "radio")
        self.assertEqual(MessageKind.DISPLAY_UPDATE, message.kind)
        self.assertEqual("QTH NODE", message.metadata["display_text"])

    def test_opening_display_uses_real_radio_zero_tail(self):
        emulator = CommandMicEmulator(
            EmulatorConfig("radio", "127.0.0.1", "127.0.0.2")
        )
        frame = emulator._display_frame("OPENING", tail=bytes(60))
        message = classify_message(frame, Direction.RADIO_TO_MIC)
        self.assertEqual("OPENING", message.metadata["display_text"])
        self.assertEqual(bytes(60).hex(), message.metadata["display_unknown_hex"])


class FakeDatagramTransport:
    def __init__(self):
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.sent_at: list[float] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))
        self.sent_at.append(time.perf_counter())


class FakeStreamWriter:
    def __init__(self):
        self.sent: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.sent.append(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def is_closing(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class UdpSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_microphone_tx_uses_latest_payload_supplier(self):
        class Source:
            def __init__(self):
                self.calls = 0

            def latest_payload(self):
                self.calls += 1
                return struct.pack(">h", self.calls) * 160

            @property
            def stats(self):
                return MicrophoneCaptureStats(
                    captured=self.calls,
                    delivered=self.calls,
                    overwritten=0,
                    underruns=0,
                    buffered=0,
                )

        source = Source()
        audit = _MemoryAudit()
        protocol = VerifiedMicUdpProtocol("192.0.2.1", 50000, audit=audit)
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.send_boot()
        protocol.datagram_received(RADIO_BOOT_RTP, ("192.0.2.1", 50000))
        sent = await protocol.send_live_transmit(source, packet_count=3)  # type: ignore[arg-type]
        self.assertEqual(3, sent)
        self.assertEqual(3, source.calls)
        self.assertEqual(
            [struct.pack(">h", value) * 160 for value in (1, 2, 3)],
            [packet[12:] for packet, _ in transport.sent[1:]],
        )
        stats_events = [
            fields for event, fields in audit.events
            if event == "mic_live_capture_stats"
        ]
        self.assertEqual(1, len(stats_events))
        self.assertEqual(3, stats_events[0]["stats"]["delivered"])

    async def test_software_mic_tx_failure_sends_fail_closed_ptt_release(self):
        protocol = VerifiedMicUdpProtocol("192.0.2.1", 50000, audit=_NullAudit())
        protocol.connection_made(FakeDatagramTransport())  # type: ignore[arg-type]
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "mic", "192.0.2.2", "192.0.2.1",
                verified_startup=True, listen=True, enable_tx=True,
                tx_hold_seconds=0.5, tx_start_delay_seconds=0.0,
                exit_after_tx_script=True,
            ),
            udp_protocol=protocol,
        )
        writer = FakeStreamWriter()
        task = asyncio.create_task(emulator._run_mic_tx_script(writer))  # type: ignore[arg-type]
        for _ in range(100):
            if writer.sent:
                break
            await asyncio.sleep(0.001)
        self.assertEqual([MIC_PTT_DOWN], writer.sent)
        emulator._mic_tx_active.set()
        await asyncio.wait_for(task, 1.0)
        self.assertEqual([MIC_PTT_DOWN, MIC_PTT_UP], writer.sent)
        self.assertIsInstance(emulator._mic_tx_error, RuntimeError)
        self.assertTrue(emulator._mic_tx_complete.is_set())
        self.assertTrue(writer.closed)

    async def test_software_mic_tx_rtp_continues_exact_boot_sequence(self):
        audit = _MemoryAudit()
        protocol = VerifiedMicUdpProtocol("192.0.2.1", 50000, audit=audit)
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        self.assertTrue(protocol.send_boot())
        protocol.datagram_received(RADIO_BOOT_RTP, ("192.0.2.1", 50000))
        payloads = [bytes(320), b"\x00\x01" * 160]
        sent = await protocol.send_transmit_payloads(payloads, source="test")
        self.assertEqual(2, sent)
        self.assertEqual(3, len(transport.sent))
        self.assertEqual(MIC_BOOT_RTP, transport.sent[0][0])
        headers = [
            struct.unpack("!BBHII", packet[:12])
            for packet, _ in transport.sent[1:]
        ]
        _, _, boot_sequence, boot_timestamp, _ = struct.unpack(
            "!BBHII", MIC_BOOT_RTP[:12]
        )
        self.assertEqual((boot_sequence + 1) & 0xFFFF, headers[0][2])
        self.assertEqual((boot_timestamp + 160) & 0xFFFFFFFF, headers[0][3])
        self.assertEqual(MIC_RTP_SSRC, headers[0][4])
        self.assertEqual(1, (headers[1][2] - headers[0][2]) & 0xFFFF)
        self.assertEqual(160, (headers[1][3] - headers[0][3]) & 0xFFFFFFFF)
        self.assertAlmostEqual(
            0.020, transport.sent_at[2] - transport.sent_at[1], delta=0.012
        )

    async def test_software_mic_tx_is_withheld_before_radio_boot(self):
        protocol = VerifiedMicUdpProtocol("192.0.2.1", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.send_boot()
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            await protocol.send_transmit_payloads([bytes(320)], source="test")
        self.assertEqual([(MIC_BOOT_RTP, ("192.0.2.1", 50000))], transport.sent)

    async def test_top_level_emulator_propagates_playback_backend_failure(self):
        class Transport:
            def close(self):
                pass

        sink = mock.Mock()
        sink.close.side_effect = RuntimeError("render failed")
        sink.jitter.stats = mock.Mock(
            received=0,
            played=0,
            concealed=0,
            duplicates=0,
            late=0,
            discontinuities=0,
            buffered=0,
        )
        loop = asyncio.get_running_loop()
        with (
            mock.patch(
                "ip_commandmic.emulator.FfplayRadioAudioSink",
                return_value=sink,
            ),
            mock.patch.object(
                loop,
                "create_datagram_endpoint",
                new=mock.AsyncMock(return_value=(Transport(), None)),
            ),
            mock.patch.object(
                CommandMicEmulator,
                "run",
                new=mock.AsyncMock(return_value=None),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "playback failed"):
                await run_emulator(
                    EmulatorConfig(
                        "mic",
                        "127.0.0.2",
                        "127.0.0.1",
                        listen=True,
                        verified_startup=True,
                        play_radio_audio=True,
                    )
                )

    def test_only_verified_zero_boot_rtp_gets_response(self):
        protocol = VerifiedRadioUdpProtocol("192.0.2.2", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.datagram_received(b"not rtp", ("192.0.2.2", 50000))
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + b"\x01" + bytes(319),
            ("192.0.2.2", 50000),
        )
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("192.0.2.99", 50000),
        )
        self.assertEqual([], transport.sent)
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("192.0.2.2", 50000),
        )
        self.assertEqual([(RADIO_BOOT_RTP, ("192.0.2.2", 50000))], transport.sent)

    async def test_bounded_receive_tone_has_verified_rtp_shape_and_timing(self):
        protocol = VerifiedRadioUdpProtocol("192.0.2.2", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        boot = bytes.fromhex("807d00010000000100000001") + bytes(320)
        protocol.datagram_received(boot, ("192.0.2.2", 50000))
        sent = await protocol.send_tone(
            frequency_hz=1000.0, level_dbfs=-30.0, duration_seconds=0.04
        )
        self.assertEqual(2, sent)
        audio = [packet for packet, _ in transport.sent[1:]]
        self.assertEqual([332, 332], [len(packet) for packet in audio])
        headers = [struct.unpack("!BBHII", packet[:12]) for packet in audio]
        self.assertEqual([0x80, 0x80], [header[0] for header in headers])
        self.assertEqual([0x7D, 0x7D], [header[1] for header in headers])
        self.assertEqual(1, (headers[1][2] - headers[0][2]) & 0xFFFF)
        self.assertEqual(160, (headers[1][3] - headers[0][3]) & 0xFFFFFFFF)
        self.assertEqual(headers[0][4], headers[1][4])
        samples = [sample[0] for sample in struct.iter_unpack(">h", audio[0][12:])]
        self.assertTrue(any(samples))
        self.assertLessEqual(max(abs(sample) for sample in samples), 1037)

    async def test_receive_audio_pacer_preserves_absolute_timeline(self):
        audit = _MemoryAudit()
        protocol = VerifiedRadioUdpProtocol("192.0.2.2", 50000, audit=audit)
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("192.0.2.2", 50000),
        )
        await protocol.send_tone(
            frequency_hz=1000.0, level_dbfs=-30.0, duration_seconds=0.2
        )
        audio_times = transport.sent_at[1:]
        intervals = [current - prior for prior, current in zip(audio_times, audio_times[1:])]
        self.assertEqual(9, len(intervals))
        self.assertAlmostEqual(0.18, audio_times[-1] - audio_times[0], delta=0.02)
        self.assertLess(max(intervals), 0.04)
        completed = [
            fields for event, fields in audit.events if event == "rx_audio_completed"
        ]
        self.assertEqual(1, len(completed))
        self.assertEqual(10, completed[0]["packet_count"])
        self.assertIsNotNone(completed[0]["first_send_monotonic"])
        self.assertGreaterEqual(completed[0]["max_late_ms"], 0.0)
        self.assertGreaterEqual(completed[0]["pacing_resyncs"], 0)

    async def test_receive_tone_is_withheld_until_verified_udp_peer(self):
        protocol = VerifiedRadioUdpProtocol("192.0.2.2", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        sent = await protocol.send_tone(
            frequency_hz=1000.0, level_dbfs=-30.0, duration_seconds=0.02
        )
        self.assertEqual(0, sent)
        self.assertEqual([], transport.sent)

    async def test_key_beep_sender_uses_profile_packet_counts_and_rtp_continuity(self):
        protocol = VerifiedRadioUdpProtocol("192.0.2.2", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("192.0.2.2", 50000),
        )
        normal_count = await protocol.send_key_beep("normal")
        low_count = await protocol.send_key_beep("low", beep_level=5)
        self.assertEqual((4, 7), (normal_count, low_count))
        audio = [packet for packet, _ in transport.sent[1:]]
        self.assertEqual(11, len(audio))
        headers = [struct.unpack("!BBHII", packet[:12]) for packet in audio]
        self.assertTrue(all(header[1] == 0x7D for header in headers))
        self.assertTrue(all(len(packet) == 332 for packet in audio))
        self.assertTrue(all(
            ((current[2] - prior[2]) & 0xFFFF) == 1
            and ((current[3] - prior[3]) & 0xFFFFFFFF) == 160
            for prior, current in zip(headers, headers[1:])
        ))

    async def test_mic_rtp_is_recorded_only_inside_explicit_ptt_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/mic.wav"
            audit = _MemoryAudit()
            protocol = VerifiedRadioUdpProtocol(
                "192.0.2.2",
                50000,
                audit=audit,
                record_mic_wav=path,
                mic_recording_max_seconds=1.0,
            )
            transport = FakeDatagramTransport()
            protocol.connection_made(transport)  # type: ignore[arg-type]
            boot = bytes.fromhex("807d0001000000017069c2cc") + bytes(320)
            protocol.datagram_received(boot, ("192.0.2.2", 50000))

            payload_one = b"".join(struct.pack(">h", value) for value in ([1, -2] * 80))
            before_ptt = struct.pack("!BBHII", 0x80, 0x7D, 9, 840, MIC_RTP_SSRC) + payload_one
            protocol.datagram_received(before_ptt, ("192.0.2.2", 50000))
            protocol.start_mic_recording()
            for sequence, timestamp in ((10, 1000), (11, 1160)):
                packet = (
                    struct.pack("!BBHII", 0x80, 0x7D, sequence, timestamp, MIC_RTP_SSRC)
                    + payload_one
                )
                protocol.datagram_received(packet, ("192.0.2.2", 50000))
            protocol.release_mic_recording(tail_seconds=0.01)
            await asyncio.sleep(0.02)

            with wave.open(path, "rb") as recorded:
                self.assertEqual((1, 2, 8000, 320), (
                    recorded.getnchannels(),
                    recorded.getsampwidth(),
                    recorded.getframerate(),
                    recorded.getnframes(),
                ))
                self.assertEqual(bytes.fromhex("0100feff"), recorded.readframes(2))
            self.assertEqual(1, len(transport.sent))  # boot response only; RTP is never echoed
            completed = [fields for event, fields in audit.events if event == "mic_recording_completed"]
            self.assertEqual(1, len(completed))
            self.assertEqual(2, completed[0]["packets"])
            self.assertEqual(0, completed[0]["sequence_errors"])
            self.assertEqual(0, completed[0]["timestamp_errors"])

    def test_initial_ptt_release_does_not_open_a_capture_session(self):
        protocol = VerifiedRadioUdpProtocol(
            "192.0.2.2", 50000, audit=_NullAudit(), record_mic_wav="unused.wav"
        )
        self.assertFalse(protocol.release_mic_recording())

    def test_radio_audio_recording_requires_verified_listening_mic(self):
        with self.assertRaisesRegex(ValueError, "listening mic role"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                record_radio_wav="radio.wav",
            )
        with self.assertRaisesRegex(ValueError, "between 0.1 and 30"):
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                radio_recording_max_seconds=31.0,
            )
        with self.assertRaisesRegex(ValueError, "listening mic role"):
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                play_radio_audio=True,
            )
        with self.assertRaisesRegex(ValueError, "between 1 and 25"):
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                radio_jitter_packets=0,
            )
        with self.assertRaisesRegex(ValueError, "between 0 and 30"):
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                mic_key_start_delay_seconds=31.0,
            )

    def test_radio_rtp_is_recorded_only_inside_verified_receive_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/radio.wav"
            audit = _MemoryAudit()
            protocol = VerifiedMicUdpProtocol(
                "192.0.2.1",
                50000,
                audit=audit,
                record_radio_wav=path,
                radio_recording_max_seconds=1.0,
            )
            transport = FakeDatagramTransport()
            protocol.connection_made(transport)  # type: ignore[arg-type]
            self.assertTrue(protocol.send_boot())
            protocol.datagram_received(RADIO_BOOT_RTP, ("192.0.2.1", 50000))

            payload = b"".join(struct.pack(">h", value) for value in ([1, -2] * 80))

            def packet(sequence: int, timestamp: int) -> bytes:
                return (
                    struct.pack(
                        "!BBHII", 0x80, 0x7D, sequence, timestamp, RADIO_RTP_SSRC
                    )
                    + payload
                )

            protocol.datagram_received(packet(9, 840), ("192.0.2.1", 50000))
            protocol.set_radio_audio_gate(True)
            protocol.datagram_received(packet(10, 1000), ("192.0.2.1", 50000))
            protocol.datagram_received(packet(11, 1160), ("192.0.2.1", 50000))
            protocol.set_radio_audio_gate(False)
            protocol.datagram_received(packet(12, 1320), ("192.0.2.1", 50000))
            protocol.set_radio_audio_gate(True)
            protocol.datagram_received(packet(20, 2000), ("192.0.2.1", 50000))
            protocol.set_radio_audio_gate(False)
            protocol.close()

            with wave.open(path, "rb") as recorded:
                self.assertEqual((1, 2, 8000, 480), (
                    recorded.getnchannels(),
                    recorded.getsampwidth(),
                    recorded.getframerate(),
                    recorded.getnframes(),
                ))
                self.assertEqual(bytes.fromhex("0100feff"), recorded.readframes(2))
            self.assertEqual(
                [(MIC_BOOT_RTP, ("192.0.2.1", 50000))], transport.sent
            )
            completed = [
                fields for event, fields in audit.events
                if event == "radio_audio_recording_completed"
            ]
            self.assertEqual(1, len(completed))
            self.assertEqual(2, completed[0]["gate_sessions"])
            self.assertEqual(3, completed[0]["packets"])
            self.assertEqual(0, completed[0]["sequence_errors"])
            self.assertEqual(0, completed[0]["timestamp_errors"])

    def test_radio_audio_callbacks_receive_verified_packets_and_gate_boundaries(self):
        audit = _MemoryAudit()
        packets = []
        gates = []
        protocol = VerifiedMicUdpProtocol(
            "192.0.2.1",
            50000,
            audit=audit,
            radio_audio_callback=packets.append,
            radio_audio_gate_callback=gates.append,
        )
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.send_boot()
        protocol.datagram_received(RADIO_BOOT_RTP, ("192.0.2.1", 50000))
        payload = b"".join(struct.pack(">h", value) for value in ([1, -2] * 80))
        packet = (
            struct.pack("!BBHII", 0x80, 0x7D, 10, 1000, RADIO_RTP_SSRC)
            + payload
        )

        protocol.datagram_received(packet, ("192.0.2.1", 50000))
        protocol.set_radio_audio_gate(True)
        protocol.datagram_received(packet, ("192.0.2.1", 50000))
        protocol.set_radio_audio_gate(False)

        self.assertEqual(1, len(packets))
        self.assertEqual((1, 10, 1000, RADIO_RTP_SSRC), (
            packets[0].session,
            packets[0].sequence,
            packets[0].timestamp,
            packets[0].ssrc,
        ))
        self.assertEqual(160, packets[0].sample_count)
        self.assertEqual(bytes.fromhex("0100feff"), packets[0].pcm_s16le[:4])
        self.assertEqual([(1, True, 0), (1, False, 1)], [
            (event.session, event.open, event.packet_count) for event in gates
        ])

    def test_radio_audio_callback_exceptions_are_contained_and_audited(self):
        audit = _MemoryAudit()

        def fail(_packet):
            raise RuntimeError("application failed")

        protocol = VerifiedMicUdpProtocol(
            "192.0.2.1", 50000, audit=audit, radio_audio_callback=fail
        )
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.send_boot()
        protocol.datagram_received(RADIO_BOOT_RTP, ("192.0.2.1", 50000))
        protocol.set_radio_audio_gate(True)
        payload = bytes(320)
        packet = (
            struct.pack("!BBHII", 0x80, 0x7D, 10, 1000, RADIO_RTP_SSRC)
            + payload
        )
        protocol.datagram_received(packet, ("192.0.2.1", 50000))
        self.assertTrue(any(
            event == "radio_audio_callback_error" for event, _ in audit.events
        ))

    def test_verified_mic_udp_sends_one_exact_boot_and_accepts_only_radio_boot(self):
        audit = _MemoryAudit()
        protocol = VerifiedMicUdpProtocol("192.0.2.1", 50000, audit=audit)
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        self.assertTrue(protocol.send_boot())
        self.assertEqual([(MIC_BOOT_RTP, ("192.0.2.1", 50000))], transport.sent)
        protocol.datagram_received(RADIO_BOOT_RTP, ("192.0.2.99", 50000))
        self.assertFalse(protocol._radio_boot_verified)
        protocol.datagram_received(RADIO_BOOT_RTP, ("192.0.2.1", 50000))
        self.assertTrue(protocol._radio_boot_verified)

    async def test_bounded_wav_is_converted_to_s16be_and_padded(self):
        protocol = VerifiedRadioUdpProtocol("192.0.2.2", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("192.0.2.2", 50000),
        )
        samples = [1, -2] + [0] * 159
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/test.wav"
            with wave.open(path, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b"".join(struct.pack("<h", value) for value in samples))
            sent = await protocol.send_wav(path)
        self.assertEqual(2, sent)
        audio = [packet for packet, _ in transport.sent[1:]]
        self.assertEqual(bytes.fromhex("0001fffe"), audio[0][12:16])
        self.assertEqual(bytes(318), audio[1][14:])

    async def test_wav_rejects_unsupported_format(self):
        protocol = VerifiedRadioUdpProtocol("192.0.2.2", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("192.0.2.2", 50000),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/stereo.wav"
            with wave.open(path, "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(bytes(640))
            with self.assertRaisesRegex(ValueError, "mono"):
                await protocol.send_wav(path)


class _NullAudit:
    def write(self, event: str, **fields: object) -> None:
        pass


class _MemoryAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def write(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


class EmulatorLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_mic_emulator_replies_only_with_observed_heartbeat(self):
        emulator = CommandMicEmulator(
            EmulatorConfig("mic", "127.0.0.1", "127.0.0.1", read_timeout=1.0)
        )
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(RADIO_IDLE_HEARTBEAT)
            await writer.drain()
            response = await asyncio.wait_for(reader.readexactly(12), 1.0)
            self.assertEqual(MIC_IDLE_HEARTBEAT, response)
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0)
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_mic_probe_transcript_and_udp_boot(self):
        udp = VerifiedMicUdpProtocol("127.0.0.1", 50000, audit=_NullAudit())
        udp_transport = FakeDatagramTransport()
        udp.connection_made(udp_transport)  # type: ignore[arg-type]
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                read_timeout=1.0,
            ),
            udp_protocol=udp,
        )
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(RADIO_STARTUP_HELLO)
            await writer.drain()
            startup = await asyncio.wait_for(
                reader.readexactly(sum(map(len, MIC_STARTUP_SYNC))), 1.0
            )
            self.assertEqual(b"".join(MIC_STARTUP_SYNC), startup)
            writer.write(RADIO_STARTUP_READY)
            await writer.drain()
            self.assertEqual(
                MIC_IDENTITY,
                await asyncio.wait_for(reader.readexactly(len(MIC_IDENTITY)), 1.0),
            )
            self.assertEqual([(MIC_BOOT_RTP, ("127.0.0.1", 50000))], udp_transport.sent)
            writer.write(b"".join(RADIO_PROBE_HEAD))
            await writer.drain()
            response = await asyncio.wait_for(
                reader.readexactly(sum(map(len, MIC_PROBE_RESPONSE))), 1.0
            )
            self.assertEqual(b"".join(MIC_PROBE_RESPONSE), response)
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_mic_answers_special_probe_on_powered_radio_attach(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                read_timeout=1.0,
            )
        )
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(RADIO_IDLE_HEARTBEAT + RADIO_PROBE_HEAD[1])
            await writer.drain()
            expected = MIC_IDLE_HEARTBEAT + b"".join(MIC_PROBE_RESPONSE)
            self.assertEqual(
                expected,
                await asyncio.wait_for(reader.readexactly(len(expected)), 1.0),
            )
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_mic_answers_power_transition_prompt_on_stable_session(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                read_timeout=1.0,
            )
        )
        emulator._mic_session_count = 1
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            # Real-radio shutdown prompt captured after a successful Power hold.
            writer.write(bytes.fromhex("f541710503000102ff000cfd"))
            await writer.drain()
            self.assertEqual(
                b"".join(MIC_PROBE_RESPONSE),
                await asyncio.wait_for(
                    reader.readexactly(sum(map(len, MIC_PROBE_RESPONSE))), 1.0
                ),
            )
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_mic_stable_display_ack_and_heartbeat(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                read_timeout=1.0,
            )
        )
        emulator._mic_session_count = 1
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(DISPLAY_BEFORE + emulator._display_frame("QTH NODE") + DISPLAY_AFTER)
            await writer.drain()
            self.assertEqual(
                MIC_DISPLAY_ACK,
                await asyncio.wait_for(reader.readexactly(len(MIC_DISPLAY_ACK)), 1.0),
            )
            writer.write(RADIO_IDLE_HEARTBEAT)
            await writer.drain()
            self.assertEqual(
                MIC_IDLE_HEARTBEAT,
                await asyncio.wait_for(reader.readexactly(len(MIC_IDLE_HEARTBEAT)), 1.0),
            )
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_mic_applies_radio_audio_open_and_close_to_udp_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/radio.wav"
            audit = _MemoryAudit()
            protocol = VerifiedMicUdpProtocol(
                "127.0.0.1", 50000, audit=audit, record_radio_wav=path
            )
            emulator = CommandMicEmulator(
                EmulatorConfig(
                    "mic",
                    "127.0.0.2",
                    "127.0.0.1",
                    verified_startup=True,
                    listen=True,
                    read_timeout=1.0,
                    record_radio_wav=path,
                ),
                audit_log=audit,
                udp_protocol=protocol,
            )
            emulator._mic_session_count = 1
            server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
            try:
                port = server.sockets[0].getsockname()[1]
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(RADIO_AUDIO_OPEN)
                await writer.drain()
                await asyncio.sleep(0.05)
                self.assertTrue(protocol._radio_audio_gate_open, audit.events)
                writer.write(RADIO_AUDIO_CLOSE)
                await writer.drain()
                await asyncio.sleep(0.20)
                self.assertFalse(protocol._radio_audio_gate_open, audit.events)
                writer.close()
                await writer.wait_closed()
            finally:
                server.close()
                await server.wait_closed()
            protocol.close()
            self.assertTrue(any(
                event == "radio_audio_recording_completed"
                for event, _ in audit.events
            ))

    async def test_verified_mic_emits_script_only_after_second_stable_display(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                read_timeout=2.0,
                mic_key_script=("p1",),
                mic_key_hold_seconds=0.02,
                mic_key_interval_seconds=0.0,
            )
        )
        emulator._mic_session_count = 1
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(RADIO_STARTUP_HELLO)
            await writer.drain()
            await asyncio.wait_for(
                reader.readexactly(sum(map(len, MIC_STARTUP_SYNC))), 1.0
            )
            writer.write(RADIO_STARTUP_READY)
            await writer.drain()
            await asyncio.wait_for(reader.readexactly(len(MIC_IDENTITY)), 1.0)

            display = DISPLAY_BEFORE + emulator._display_frame("OPENING") + DISPLAY_AFTER
            writer.write(display)
            await writer.drain()
            self.assertEqual(
                MIC_DISPLAY_ACK,
                await asyncio.wait_for(reader.readexactly(len(MIC_DISPLAY_ACK)), 1.0),
            )
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(reader.read(1), 0.05)

            display = DISPLAY_BEFORE + emulator._display_frame("QTH NODE") + DISPLAY_AFTER
            writer.write(display)
            await writer.drain()
            self.assertEqual(
                MIC_DISPLAY_ACK,
                await asyncio.wait_for(reader.readexactly(len(MIC_DISPLAY_ACK)), 1.0),
            )
            wire = await asyncio.wait_for(reader.read(1024), 1.0)
            await asyncio.sleep(0.05)
            while True:
                try:
                    wire += await asyncio.wait_for(reader.read(1024), 0.02)
                except TimeoutError:
                    break
            messages, remainder = parse_stream(wire, Direction.MIC_TO_RADIO)
            self.assertFalse(remainder)
            key_messages = [
                message for message in messages if message.kind is MessageKind.KEY_STATE
            ]
            self.assertEqual(
                [("p1", "press"), ("p1", "release"), (None, "neutral")],
                [
                    (message.metadata["key_button"], message.metadata["key_action"])
                    for message in key_messages
                ],
            )
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_mic_emits_script_after_warm_single_display_grace(self):
        audit = _MemoryAudit()
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "mic",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                listen=True,
                read_timeout=5.0,
                mic_key_script=("p1",),
                mic_key_hold_seconds=0.02,
                mic_key_interval_seconds=0.0,
            ),
            audit_log=audit,
        )
        emulator._mic_session_count = 1
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            display = DISPLAY_BEFORE + emulator._display_frame("QTH NODE") + DISPLAY_AFTER
            writer.write(display)
            await writer.drain()
            self.assertEqual(
                MIC_DISPLAY_ACK,
                await asyncio.wait_for(reader.readexactly(len(MIC_DISPLAY_ACK)), 1.0),
            )
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(reader.read(1), 0.1)

            wire = await asyncio.wait_for(reader.read(1024), 4.0)
            await asyncio.sleep(0.05)
            while True:
                try:
                    wire += await asyncio.wait_for(reader.read(1024), 0.02)
                except TimeoutError:
                    break
            messages, remainder = parse_stream(wire, Direction.MIC_TO_RADIO)
            self.assertFalse(remainder)
            key_messages = [
                message for message in messages if message.kind is MessageKind.KEY_STATE
            ]
            self.assertEqual(
                [("p1", "press"), ("p1", "release"), (None, "neutral")],
                [
                    (message.metadata["key_button"], message.metadata["key_action"])
                    for message in key_messages
                ],
            )
            self.assertTrue(any(
                event == "mic_controls_ready"
                and fields.get("reason") == "single_display_grace_elapsed"
                for event, fields in audit.events
            ))
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_software_radio_and_mic_interoperate_through_probe_and_stable(self):
        radio_audit = _MemoryAudit()
        mic_audit = _MemoryAudit()
        radio = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.2",
                "127.0.0.1",
                verified_startup=True,
                read_timeout=6.0,
                automatic_key_responses=True,
            ),
            audit_log=radio_audit,
        )
        mic = CommandMicEmulator(
            EmulatorConfig(
                "mic",
                "127.0.0.1",
                "127.0.0.2",
                verified_startup=True,
                listen=True,
                read_timeout=6.0,
                mic_key_script=("p1", "up"),
                mic_key_hold_seconds=0.02,
                mic_key_interval_seconds=0.0,
            ),
            audit_log=mic_audit,
        )
        server = await asyncio.start_server(mic._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await asyncio.wait_for(radio._session(reader, writer), 1.0)

            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            stable_task = asyncio.create_task(radio._session(reader, writer))
            # The verified startup carousel plus the warm-display grace timer
            # can overlap on slower Windows event loops. Allow the transcript
            # to complete instead of depending on the previous tight margin.
            await asyncio.sleep(5.0)
            stable_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await stable_task

            mic_sessions = [
                fields["session_kind"]
                for event, fields in mic_audit.events
                if event == "verified_mic_session"
            ]
            self.assertEqual(["probe", "stable"], mic_sessions)
            self.assertTrue(any(
                event == "sent_verified" and fields.get("reason") == "display:"
                for event, fields in radio_audit.events
            ), radio_audit.events)
            self.assertTrue(any(
                event == "sent_verified" and fields.get("reason") == "mic_display_ack"
                for event, fields in mic_audit.events
            ))
            received_raw = {
                fields.get("raw_hex")
                for event, fields in radio_audit.events
                if event == "received"
            }
            for button in ("p1", "up"):
                self.assertTrue(
                    {frame.hex() for frame in encode_key_tap(button)} <= received_raw
                )
            self.assertTrue(any(
                event == "sent_verified" and fields.get("reason") == "mic_heartbeat_response"
                for event, fields in mic_audit.events
            ))
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_probe_transcript(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.1",
                verified_startup=True,
                read_timeout=1.0,
            )
        )
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            self.assertEqual(
                RADIO_STARTUP_HELLO,
                await asyncio.wait_for(reader.readexactly(len(RADIO_STARTUP_HELLO)), 1.0),
            )
            writer.write(build_frame(0x05, 0x06, b"\x00"))
            await writer.drain()
            self.assertEqual(
                RADIO_STARTUP_READY,
                await asyncio.wait_for(reader.readexactly(len(RADIO_STARTUP_READY)), 1.0),
            )
            writer.write(MIC_IDENTITY)
            await writer.drain()
            expected_head = b"".join(RADIO_PROBE_HEAD)
            self.assertEqual(
                expected_head,
                await asyncio.wait_for(reader.readexactly(len(expected_head)), 1.0),
            )
            writer.write(build_frame(0x05, 0x04, b"\x01", start_byte=0xF5))
            await writer.drain()
            expected_tail = b"".join(RADIO_PROBE_TAIL)
            self.assertEqual(
                expected_tail,
                await asyncio.wait_for(reader.readexactly(len(expected_tail)), 1.0),
            )
            self.assertEqual(b"", await asyncio.wait_for(reader.read(), 1.0))
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_channel_key_sends_display_transaction(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.1", automatic_key_responses=True
            )
        )
        up = classify_message(build_frame(0x01, 0x01, b"\x20"), "mic")

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await emulator._handle_verified_key(writer, up)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            wire = await asyncio.wait_for(reader.read(), 1.0)
            messages, remainder = parse_stream(wire, Direction.RADIO_TO_MIC)
            self.assertFalse(remainder)
            self.assertEqual(3, len(messages))
            self.assertEqual(DISPLAY_BEFORE, messages[0].raw)
            self.assertEqual("CHANNEL2", messages[1].metadata["display_text"])
            self.assertEqual(DISPLAY_AFTER, messages[2].raw)
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_volume_down_reaches_and_clamps_mute(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.1", automatic_key_responses=True
            )
        )
        volume_down = classify_message(build_frame(0x01, 0x01, b"\x01"), "mic")

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await emulator._handle_verified_key(writer, volume_down)
            await emulator._handle_verified_key(writer, volume_down)
            if emulator._restore_task:
                emulator._restore_task.cancel()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            wire = await asyncio.wait_for(reader.read(), 1.0)
            messages, remainder = parse_stream(wire, Direction.RADIO_TO_MIC)
            self.assertFalse(remainder)
            displays = [
                message for message in messages
                if message.kind is MessageKind.DISPLAY_UPDATE
            ]
            self.assertEqual(["VOL  0", "VOL  0"], [
                message.metadata["display_text"].strip() for message in displays
            ])
            self.assertEqual([0, 0], [
                message.metadata["volume_level"] for message in displays
            ])
            self.assertEqual(0, emulator._volume_level)
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_volume_up_reaches_and_clamps_real_radio_maximum(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.1", automatic_key_responses=True
            )
        )
        emulator._volume_level = 31
        volume_up = classify_message(build_frame(0x01, 0x01, b"\x10"), "mic")

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await emulator._handle_verified_key(writer, volume_up)
            await emulator._handle_verified_key(writer, volume_up)
            if emulator._restore_task:
                emulator._restore_task.cancel()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            wire = await asyncio.wait_for(reader.read(), 1.0)
            messages, remainder = parse_stream(wire, Direction.RADIO_TO_MIC)
            self.assertFalse(remainder)
            displays = [
                message for message in messages
                if message.kind is MessageKind.DISPLAY_UPDATE
            ]
            self.assertEqual(["VOL 32", "VOL 32"], [
                message.metadata["display_text"].strip() for message in displays
            ])
            self.assertEqual([32, 32], [
                message.metadata["volume_level"] for message in displays
            ])
            captured_maximum = bytes.fromhex(
                "f34171020a004420564f4c20333200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000880000000000000000000000b2ddfd"
            )
            self.assertEqual([captured_maximum, captured_maximum], [
                message.raw for message in displays
            ])
            self.assertEqual(32, emulator._volume_level)
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_receive_audio_wraps_rtp_in_verified_open_close_state(self):
        protocol = VerifiedRadioUdpProtocol("127.0.0.1", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("127.0.0.1", 50000),
        )
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.1",
                verified_startup=True,
                enable_rx_audio=True,
                rx_tone_seconds=0.04,
            ),
            udp_protocol=protocol,
        )

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await emulator._run_receive_audio(writer)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            wire = await asyncio.wait_for(reader.read(), 1.0)
            messages, remainder = parse_stream(wire, Direction.RADIO_TO_MIC)
            self.assertFalse(remainder)
            self.assertEqual(RADIO_AUDIO_OPEN, messages[0].raw)
            self.assertEqual(DISPLAY_BEFORE, messages[1].raw)
            self.assertEqual("", messages[2].metadata["display_text"])
            self.assertEqual(DISPLAY_AFTER, messages[3].raw)
            self.assertEqual(RADIO_AUDIO_STATUS_OPEN, messages[4].raw)
            self.assertEqual(RADIO_AUDIO_CLOSE, messages[5].raw)
            self.assertEqual(RADIO_AUDIO_STATUS_CLOSED, messages[6].raw)
            self.assertEqual(3, len(transport.sent))  # boot response + two tone packets
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_key_beep_uses_audio_gate_without_receive_status_or_display(self):
        protocol = VerifiedRadioUdpProtocol("127.0.0.1", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("127.0.0.1", 50000),
        )
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio", "127.0.0.1", "127.0.0.1",
                verified_startup=True, key_beep="normal",
            ),
            udp_protocol=protocol,
        )

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await emulator._run_key_beep(writer)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            wire = await asyncio.wait_for(reader.read(), 1.0)
            messages, remainder = parse_stream(wire, Direction.RADIO_TO_MIC)
            self.assertFalse(remainder)
            self.assertEqual([RADIO_AUDIO_OPEN, RADIO_AUDIO_CLOSE], [
                message.raw for message in messages
            ])
            self.assertNotIn(RADIO_AUDIO_STATUS_OPEN, wire)
            self.assertNotIn(DISPLAY_BEFORE, wire)
            self.assertEqual(5, len(transport.sent))  # boot response + four tone packets
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_receive_audio_open_only_sends_control_state_without_rtp(self):
        protocol = VerifiedRadioUdpProtocol("127.0.0.1", 50000, audit=_NullAudit())
        transport = FakeDatagramTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        protocol.datagram_received(
            bytes.fromhex("807d00010000000100000001") + bytes(320),
            ("127.0.0.1", 50000),
        )
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.1",
                verified_startup=True,
                enable_rx_audio=True,
                rx_open_only_seconds=0.02,
            ),
            udp_protocol=protocol,
        )

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await emulator._run_receive_audio(writer)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            wire = await asyncio.wait_for(reader.read(), 1.0)
            messages, remainder = parse_stream(wire, Direction.RADIO_TO_MIC)
            self.assertFalse(remainder)
            self.assertEqual(RADIO_AUDIO_OPEN, messages[0].raw)
            self.assertEqual(RADIO_AUDIO_STATUS_OPEN, messages[4].raw)
            self.assertEqual(RADIO_AUDIO_CLOSE, messages[5].raw)
            self.assertEqual(RADIO_AUDIO_STATUS_CLOSED, messages[6].raw)
            self.assertEqual(1, len(transport.sent))  # verified boot response only
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_radio_withholds_ptt_response(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.1",
                verified_startup=True,
                read_timeout=0.05,
            )
        )
        emulator._radio_session_count = 1
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await reader.readexactly(len(RADIO_STARTUP_HELLO))
            writer.write(build_frame(0x01, 0x00, b"\x01"))
            await writer.drain()
            self.assertEqual(b"", await asyncio.wait_for(reader.read(), 0.5))
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_radio_passively_captures_ptt_audio_without_response(self):
        payloads: list[bytes] = []
        protocol = VerifiedRadioUdpProtocol(
            "127.0.0.1", 50000, audit=_NullAudit(), mic_audio_callback=payloads.append
        )
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.1",
                verified_startup=True,
                read_timeout=1.0,
                automatic_ptt_responses=False,
            ),
            udp_protocol=protocol,
        )
        emulator._radio_session_count = 1
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await reader.readexactly(len(RADIO_STARTUP_HELLO))
            writer.write(build_frame(0x01, 0x00, b"\x01"))
            await writer.drain()
            for _ in range(50):
                if protocol._mic_recording:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(protocol._mic_recording)
            audio_payload = bytes.fromhex("0001fffe") + bytes(316)
            packet = struct.pack("!BBHII", 0x80, 0x7D, 1, 160, MIC_RTP_SSRC) + audio_payload
            protocol.datagram_received(packet, ("127.0.0.1", 50000))
            self.assertEqual([audio_payload], payloads)

            writer.write(build_frame(0x01, 0x00, b"\x00"))
            await writer.drain()
            for _ in range(50):
                if not protocol._mic_ptt_session_active:
                    break
                await asyncio.sleep(0.01)
            self.assertFalse(protocol._mic_ptt_session_active)
            self.assertTrue(protocol._mic_recording)  # release-tail capture remains open
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def test_verified_radio_records_ptt_with_exact_active_and_close_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/mic.wav"
            protocol = VerifiedRadioUdpProtocol(
                "127.0.0.1", 50000, audit=_NullAudit(), record_mic_wav=path
            )
            emulator = CommandMicEmulator(
                EmulatorConfig(
                    "radio",
                    "127.0.0.1",
                    "127.0.0.1",
                    verified_startup=True,
                    record_mic_wav=path,
                    read_timeout=1.0,
                    automatic_ptt_responses=True,
                ),
                udp_protocol=protocol,
            )
            emulator._radio_session_count = 1
            server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
            try:
                port = server.sockets[0].getsockname()[1]
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                await reader.readexactly(len(RADIO_STARTUP_HELLO))
                writer.write(build_frame(0x01, 0x00, b"\x01"))
                await writer.drain()
                active = await asyncio.wait_for(
                    reader.readexactly(len(RADIO_TX_ACTIVE) + len(RADIO_TX_STATUS_ACTIVE)),
                    0.5,
                )
                self.assertEqual(RADIO_TX_ACTIVE + RADIO_TX_STATUS_ACTIVE, active)
                writer.write(build_frame(0x01, 0x00, b"\x00"))
                await writer.drain()
                closed = await asyncio.wait_for(
                    reader.readexactly(
                        len(RADIO_AUDIO_STATUS_CLOSED) + len(RADIO_AUDIO_CLOSE)
                    ),
                    0.75,
                )
                self.assertEqual(RADIO_AUDIO_STATUS_CLOSED + RADIO_AUDIO_CLOSE, closed)
                await asyncio.sleep(0.36)
                with wave.open(path, "rb") as recorded:
                    self.assertEqual(0, recorded.getnframes())
                writer.close()
                await writer.wait_closed()
            finally:
                server.close()
                await server.wait_closed()

    async def test_stable_startup_sends_opening_display(self):
        emulator = CommandMicEmulator(
            EmulatorConfig(
                "radio",
                "127.0.0.1",
                "127.0.0.1",
                verified_startup=True,
                read_timeout=1.0,
            )
        )
        emulator._radio_session_count = 1
        server = await asyncio.start_server(emulator._session, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await reader.readexactly(len(RADIO_STARTUP_HELLO))
            writer.write(build_frame(0x05, 0x06, b"\x00"))
            await writer.drain()
            await reader.readexactly(len(RADIO_STARTUP_READY))
            writer.write(MIC_IDENTITY)
            await writer.drain()

            received = b""
            opening_text = None
            for _ in range(20):
                received += await asyncio.wait_for(reader.read(4096), 1.0)
                messages, remainder = parse_stream(received, Direction.RADIO_TO_MIC)
                if remainder:
                    received = b"".join(message.raw for message in messages) + remainder
                for message in messages:
                    if message.kind is MessageKind.DISPLAY_UPDATE:
                        opening_text = message.metadata["display_text"]
                        break
                if opening_text is not None:
                    break
            self.assertEqual("", opening_text)
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0)
        finally:
            server.close()
            await server.wait_closed()

    async def test_probe_and_stable_sessions_use_distinct_source_ports(self):
        accepted = 0
        source_ports: list[int] = []

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            nonlocal accepted
            accepted += 1
            source_ports.append(writer.get_extra_info("peername")[1])
            try:
                await reader.read()
            except ConnectionResetError:
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            emulator = CommandMicEmulator(
                EmulatorConfig("radio", "127.0.0.2", "127.0.0.1", port=port)
            )
            _, writer = await emulator._open_outbound_connection(local_port=0)
            writer.close()
            await writer.wait_closed()
            _, writer = await emulator._open_outbound_connection(local_port=port)
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.05)
            self.assertEqual(2, accepted)
            self.assertNotEqual(source_ports[0], source_ports[1])
            self.assertEqual(port, source_ports[1])
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
