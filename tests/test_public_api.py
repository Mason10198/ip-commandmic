from __future__ import annotations

import ip_commandmic as icom


def test_public_api_exports_both_endpoint_roles_and_wire_primitives() -> None:
    assert icom.__version__ == "1.0.0rc2"
    assert callable(icom.encode_mic_gain_transaction)
    assert icom.SoftwareCommandMicEndpoint
    assert icom.SoftwareRadioEndpoint
    assert icom.SoftwareRadioConfig
    assert icom.DisplayBuffer
    assert icom.parse_stream
    assert icom.build_frame
    assert icom.encode_key_state
    assert icom.VerifiedRadioUdpProtocol
    assert icom.VerifiedMicUdpProtocol
    assert icom.verified_display_blink_bit_controls
    assert icom.verified_character_blink_controls
    assert icom.verified_display_visual_modes
    assert icom.DISPLAY_BUFFER_SIZE == 68
    assert icom.PRIMARY_TEXT_SIZE == 8
    assert icom.STATUS_LED_COLORS == ("off", "red", "green", "orange")
    assert icom.load_s16be_audio_file_payloads
    assert icom.MicrophoneAudioSource
    assert icom.BufferedMicrophoneSource
    assert icom.verified_display_svg_decimal_point_paths() == (
        382, 384, 383, 386, 385, 387, 388, 389
    )


def test_public_wire_round_trip_preserves_unknown_payload() -> None:
    raw = icom.build_frame(0x7E, 0xA5, b"\x00\xf0\xff\x42")
    messages, remainder = icom.parse_stream(raw, icom.Direction.RADIO_TO_MIC)
    assert remainder == b""
    assert len(messages) == 1
    assert messages[0].body == b"\x00\xf0\xff\x42"
    assert icom.encode_message(messages[0]) == raw
