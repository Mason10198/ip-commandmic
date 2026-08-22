"""Public API for the Icom F5330D/F6330D CommandMic IP toolkit.

Public symbols are resolved lazily. Importing the package itself must remain a
cheap operation for small tools and desktop application startup.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_MODULE_EXPORTS = {
    "conformance": (
        "ConformanceCheck", "ConformanceReport", "run_loopback_conformance",
    ),
    "audio": (
        "KEY_BEEP_PROFILES", "KEY_BEEP_LEVEL_RMS_DBFS", "KeyBeepProfile",
        "BufferedMicrophoneSource", "MicrophoneAudioSource",
        "FfplayRadioAudioSink", "FfmpegMicrophoneSource", "MicrophoneCaptureStats",
        "RadioAudioGateEvent", "RadioAudioJitterBuffer", "RadioAudioJitterStats",
        "RadioAudioPacket", "RadioAudioPlayoutFrame", "RadioAudioSink",
        "generate_s16be_tone_payloads",
        "generate_s16be_polyphonic_payloads",
        "get_key_beep_profile", "load_s16be_audio_file_payloads", "load_s16be_wav_payloads",
    ),
    "controls": (
        "KEY_PRESS_VALUES", "ORDINARY_KEY_BUTTONS", "key_tap_values", "key_wire_value",
    ),
    "display": (
        "AUXILIARY_REGION_OFFSET", "AUXILIARY_REGION_SIZE", "DISPLAY_BUFFER_SIZE",
        "PRIMARY_TEXT_SIZE", "VERIFIED_DISPLAY_SVG_DECIMAL_POINT_PATHS",
        "CHARACTER_ATTRIBUTE_OFFSET", "CHARACTER_ATTRIBUTE_SIZE", "INDICATOR_STATE_OFFSET",
        "DISPLAY_CONTROL_64_OFFSET", "DISPLAY_CONTROL_65_OFFSET",
        "DISPLAY_CONTROL_66_OFFSET", "DISPLAY_CONTROL_67_OFFSET",
        "KEY_AND_POINT_STATE_OFFSET", "KEY_AND_POINT_BLINK_MASK_OFFSET",
        "PRIMARY_BLINK_MASK_OFFSET", "SECONDARY_BLINK_MASK_OFFSET",
        "SECONDARY_POINT_STATE_OFFSET", "SECONDARY_POINT_BLINK_MASK_OFFSET",
        "SECONDARY_INDICATOR_STATE_OFFSET", "VERIFIED_OFFSET56_INDICATORS",
        "VERIFIED_OFFSET57_INDICATORS", "VERIFIED_OFFSET58_DECIMAL_POINTS",
        "VERIFIED_OFFSET58_KEY_ICONS", "VERIFIED_OFFSET59_DECIMAL_POINTS",
        "VERIFIED_OFFSET60_BLINK_INDICATORS", "VERIFIED_OFFSET64_PATTERNS",
        "VERIFIED_OFFSET64_VISUAL_STATES",
        "VERIFIED_OFFSET65_VISUAL_STATES", "VERIFIED_OFFSET66_VISUAL_STATES",
        "VERIFIED_OFFSET67_VISUAL_STATES", "VERIFIED_CHARACTER_BLINK_ATTRIBUTE_OFFSETS",
        "DisplayBuffer", "DisplayEvent", "DisplayPhase", "DisplayStateModel",
        "verified_character_blink_controls", "verified_display_bit_controls",
        "verified_display_blink_bit_controls", "verified_display_visual_modes",
        "verified_display_svg_decimal_point_paths",
    ),
    "emulator": (
        "AuditLog", "CommandMicEmulator", "EmulatorConfig",
        "VerifiedMicUdpProtocol", "VerifiedRadioUdpProtocol",
    ),
    "gui_server": ("GuiState", "SoftwareCommandMicEndpoint"),
    "models": ("Direction", "Message", "MessageKind"),
    "protocol": (
        "MIC_IDLE_HEARTBEAT", "RADIO_IDLE_HEARTBEAT", "STATUS_LED_COLORS", "build_frame",
        "encode_audio_path", "encode_backlight_state", "encode_display_transaction",
        "encode_key_state", "encode_key_tap", "encode_message", "encode_mic_gain_transaction", "encode_power_state",
        "encode_ptt_state", "encode_status_led", "parse_stream", "stuff_bytes",
        "unstuff_bytes",
    ),
    "test_app": ("EndpointState", "SoftwareRadioConfig", "SoftwareRadioEndpoint"),
}

_SYMBOL_MODULE = {
    symbol: module
    for module, symbols in _MODULE_EXPORTS.items()
    for symbol in symbols
}

V1_ADVANCED_EXPORTS = (
    "AuditLog",
    "CommandMicEmulator",
    "EmulatorConfig",
    "VerifiedMicUdpProtocol",
    "VerifiedRadioUdpProtocol",
)
V1_STABLE_EXPORTS = tuple(
    symbol for symbol in _SYMBOL_MODULE if symbol not in V1_ADVANCED_EXPORTS
)

__all__ = (*tuple(_SYMBOL_MODULE), "V1_STABLE_EXPORTS", "V1_ADVANCED_EXPORTS")
__version__ = "1.0.0"


def __getattr__(name: str) -> Any:
    module_name = _SYMBOL_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
