from __future__ import annotations

import asyncio
import contextlib
import ctypes
import errno
import json
import logging
import math
import socket
import struct
import sys
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, TextIO

from .audio import (
    FfmpegMicrophoneSource,
    FfplayRadioAudioSink,
    RadioAudioGateEvent,
    RadioAudioPacket,
    MicrophoneAudioSource,
    generate_s16be_tone_payloads,
    generate_s16be_polyphonic_payloads,
    get_key_beep_profile,
    load_s16be_wav_payloads,
    write_wav,
)
from .controls import ORDINARY_KEY_BUTTONS
from .display import DISPLAY_BUFFER_SIZE, DisplayBuffer, DisplayStateModel
from .models import Direction, MessageKind
from .protocol import (
    MIC_IDLE_HEARTBEAT,
    RADIO_IDLE_HEARTBEAT,
    build_frame,
    encode_audio_path,
    encode_backlight_state,
    encode_display_transaction,
    encode_key_state,
    encode_key_tap,
    encode_mic_gain_transaction,
    encode_power_state,
    encode_ptt_state,
    encode_status_led,
    parse_stream,
)

LOGGER = logging.getLogger("ip_commandmic.emulator")


async def _sleep_with_1ms_timer(seconds: float) -> None:
    """Use the supported Windows timer-resolution request for short protocol delays."""

    timer_resolution_active = False
    winmm = None
    if sys.platform == "win32":
        winmm = ctypes.WinDLL("winmm")
        timer_resolution_active = winmm.timeBeginPeriod(1) == 0
    try:
        await asyncio.sleep(seconds)
    finally:
        if timer_resolution_active and winmm is not None:
            winmm.timeEndPeriod(1)

RADIO_STARTUP_HELLO = build_frame(0x05, 0x05, b"\x01")
RADIO_STARTUP_READY = build_frame(0x05, 0x01, b"\x01")
RADIO_PROBE_HEAD = (
    build_frame(0x02, 0x06, b"\x01\x00\x00\x00"),
    build_frame(0x05, 0x03, b"\x01", start_byte=0xF5),
    build_frame(0x02, 0x0B, b"\x02"),
    build_frame(0x01, 0x04, bytes(4)),
)
RADIO_PROBE_TAIL = (
    build_frame(0x01, 0x08, b"\x01"),
    build_frame(0x02, 0x07, b"\x02"),
    bytes.fromhex("f54171ee0504012895fd"),
)
RADIO_STABLE_SYNC = (
    build_frame(0x02, 0x06, b"\x01\x00\x00\x00"),
    build_frame(0x02, 0x0B, b"\x02"),
    build_frame(0x01, 0x04, bytes(4)),
    build_frame(0x01, 0x08, b"\x01"),
    build_frame(0x02, 0x02, b"\x00"),
    build_frame(0x06, 0x09, bytes(32)),
    build_frame(0x06, 0x0A, bytes.fromhex("7c706050423b342d2620")),
    build_frame(0x02, 0x0D, b"\x00\x04\x01"),
    build_frame(0x02, 0x0E, b"\x03"),
    build_frame(0x02, 0x0E, b"\x04"),
    build_frame(0x02, 0x01, b"\xff"),
)


def radio_stable_sync(
    mic_gain: int = 3,
    companion_value: int | None = None,
    backlight_state: str = "on",
) -> tuple[bytes, ...]:
    """Return verified startup sync with observed gain and backlight values."""

    if mic_gain not in (1, 2, 3, 4, 5):
        raise ValueError("mic_gain must be one of the observed values: 1 through 5")
    if companion_value is None:
        companion_value = mic_gain + 1
    if companion_value not in (1, 2, 3, 4, 5, 6):
        raise ValueError("mic_gain companion value must be between 1 and 6")
    if backlight_state not in {"off", "dim", "on"}:
        raise ValueError("backlight_state must be one of the observed values: off, dim, or on")
    return (
        RADIO_STABLE_SYNC[0],
        encode_backlight_state(backlight_state),
        *RADIO_STABLE_SYNC[2:8],
        build_frame(0x02, 0x0E, bytes((mic_gain,))),
        build_frame(0x02, 0x0E, bytes((companion_value,))),
        *RADIO_STABLE_SYNC[10:],
    )


RADIO_STATUS_CAROUSEL = tuple(
    build_frame(0x02, 0x02, bytes((value,)))
    for value in (0x02, 0x06, 0x04, 0x00, 0x02, 0x06, 0x04, 0x00)
)
DISPLAY_BEFORE = encode_display_transaction(DisplayBuffer.from_primary_text(""))[0]
DISPLAY_AFTER = encode_display_transaction(DisplayBuffer.from_primary_text(""))[2]
DISPLAY_SUFFIX = bytes(48) + b"\x88" + bytes(11)
RADIO_BOOT_RTP = bytes.fromhex("807dc9e6462e7794b1947ef9") + bytes(320)
RADIO_RTP_SEQUENCE = 0xC9E7
RADIO_RTP_TIMESTAMP = 0x462E7834
RADIO_RTP_SSRC = 0xB1947EF9
RADIO_AUDIO_OPEN = encode_audio_path("receive_open")
RADIO_AUDIO_CLOSE = encode_audio_path("closed")
RADIO_AUDIO_STATUS_OPEN = build_frame(0x02, 0x02, b"\x04")
RADIO_AUDIO_STATUS_CLOSED = build_frame(0x02, 0x02, b"\x00")
# E-031 observed the real radio closing the control gate roughly 8 ms after
# its final RTP packet. Preserve a slightly conservative bounded tail so UDP
# delivery cannot be overtaken by the TCP close on a busy host.
RADIO_AUDIO_CLOSE_DELAY_SECONDS = 0.010
RADIO_TX_ACTIVE = encode_audio_path("transmit_active")
RADIO_TX_STATUS_ACTIVE = build_frame(0x02, 0x02, b"\x02")
MIC_RTP_SSRC = 0x7069C2CC
MIC_BOOT_RTP = bytes.fromhex("807d08f14d5a659c7069c2cc") + bytes(320)
MIC_PTT_DOWN = encode_ptt_state("press")
MIC_PTT_UP = encode_ptt_state("release")
MIC_STARTUP_SYNC = (
    build_frame(0x01, 0x0A, b"\x00"),
    build_frame(0x01, 0x00, b"\x00"),
    build_frame(0x01, 0x01, b"\x7f"),
    build_frame(0x01, 0x01, b"\x1f"),
    build_frame(0x05, 0x06, b"\x00"),
)
# Never publish or replay a captured device address. The locally administered
# unicast address below preserves the observed identity-frame shape while
# remaining explicitly synthetic. Acceptance by a physical radio is a v1
# release-candidate gate, not a claim made by the hardware-free test suite.
SYNTHETIC_MIC_MAC = bytes.fromhex("020000000001")
MIC_IDENTITY = build_frame(
    0x05,
    0x02,
    bytes.fromhex("010101ffffffff60cc49636f6d20496e6301")
    + SYNTHETIC_MIC_MAC
    + bytes.fromhex("5a68"),
)
MIC_PROBE_RESPONSE = (
    bytes.fromhex("f54171ee0503011897fd"),
    build_frame(0x05, 0x04, b"\x01", start_byte=0xF5),
)
MIC_DISPLAY_ACK = build_frame(0x02, 0x09, b"\x01")


@dataclass(slots=True)
class EmulatorConfig:
    role: str
    local_ip: str
    peer_ip: str
    port: int = 52001
    listen: bool = False
    reconnect_delay: float = 2.0
    read_timeout: float = 6.0
    enable_tx: bool = False
    interactive_tx: bool = False
    verified_startup: bool = False
    voice_port: int = 50000
    probe_source_port: int = 52002
    enable_rx_audio: bool = False
    rx_tone_hz: float = 1000.0
    rx_level_dbfs: float = -30.0
    rx_tone_seconds: float = 3.0
    rx_wav: str | None = None
    rx_open_only_seconds: float | None = None
    key_beep: str | None = None
    beep_level: int = 3
    record_mic_wav: str | None = None
    mic_recording_max_seconds: float = 30.0
    record_radio_wav: str | None = None
    radio_recording_max_seconds: float = 30.0
    play_radio_audio: bool = False
    radio_jitter_packets: int = 2
    tx_tone_hz: float = 1000.0
    tx_level_dbfs: float = -30.0
    tx_hold_seconds: float = 3.0
    tx_wav: str | None = None
    tx_live_device: str | None = None
    tx_device_buffer_ms: int = 20
    tx_capture_queue_packets: int = 1
    tx_start_delay_seconds: float = 2.0
    exit_after_tx_script: bool = False
    mic_gain: int = 3
    backlight_state: str = "on"
    startup_opening_text: str = ""
    startup_idle_text: str | None = ""
    startup_status_carousel: bool = False
    automatic_key_responses: bool = False
    automatic_ptt_responses: bool = False
    experimental_mic_gain_companion: int | None = None
    allow_experimental_gain_pair: bool = False
    display_offset56_test: bool = False
    display_offset56_low_bit_test: bool = False
    display_offset56_rssi_ladder_test: bool = False
    display_offset56_remaining_bits_test: bool = False
    display_offset57_bit_scan: bool = False
    display_offset58_bit_scan: bool = False
    display_offset59_bit_scan: bool = False
    display_offset59_low_all_visible_test: bool = False
    display_offset60_bit_scan_all_visible: bool = False
    display_offset61_bit_scan_all_visible: bool = False
    display_offset62_bit_scan_all_visible: bool = False
    display_offset63_bit_scan_all_visible: bool = False
    display_offset64_bit_scan_all_visible: bool = False
    display_offset65_bit_scan_all_visible: bool = False
    display_offset66_bit_scan_all_visible: bool = False
    display_offset67_bit_scan_all_visible: bool = False
    display_offsets8_33_observed_probe: bool = False
    display_character_blink_position_scan: bool = False
    display_character_attribute_bit_scan: bool = False
    status_led_observed_scan: bool = False
    backlight_timeout_wake_test: bool = False
    display_test_blank_text: bool = False
    display_test_hold_seconds: float = 4.0
    mic_key_script: tuple[str, ...] = ()
    mic_key_hold_seconds: float = 0.15
    mic_key_interval_seconds: float = 0.25
    mic_key_start_delay_seconds: float = 0.0
    exit_after_key_script: bool = False

    def __post_init__(self) -> None:
        if self.role not in {"mic", "radio"}:
            raise ValueError("role must be 'mic' or 'radio'")
        if self.mic_gain not in (1, 2, 3, 4, 5):
            raise ValueError("mic_gain must be one of the observed values: 1 through 5")
        if self.backlight_state not in {"off", "dim", "on"}:
            raise ValueError(
                "backlight_state must be one of the observed values: off, dim, or on"
            )
        if self.beep_level not in (1, 2, 3, 4, 5):
            raise ValueError("beep_level must be one of the observed values: 1 through 5")
        if self.experimental_mic_gain_companion is not None:
            if not self.allow_experimental_gain_pair:
                raise ValueError(
                    "experimental_mic_gain_companion requires "
                    "allow_experimental_gain_pair"
                )
            if self.role != "radio" or not self.verified_startup:
                raise ValueError(
                    "experimental Mic Gain pairs require radio role with verified_startup"
                )
            if self.experimental_mic_gain_companion not in (1, 2, 3, 4, 5, 6):
                raise ValueError("experimental Mic Gain companion must be between 1 and 6")
        if self.role == "mic" and self.verified_startup and not self.listen:
            raise ValueError("verified mic role requires listen mode")
        if self.enable_rx_audio and (self.role != "radio" or not self.verified_startup):
            raise ValueError("receive audio requires radio role with verified_startup")
        if not 20.0 <= self.rx_tone_hz <= 3500.0:
            raise ValueError("rx_tone_hz must be between 20 and 3500 Hz")
        if not -60.0 <= self.rx_level_dbfs <= -6.0:
            raise ValueError("rx_level_dbfs must be between -60 and -6 dBFS")
        if not 0.02 <= self.rx_tone_seconds <= 30.0:
            raise ValueError("rx_tone_seconds must be between 0.02 and 30 seconds")
        if self.rx_wav and not self.enable_rx_audio:
            raise ValueError("rx_wav requires enable_rx_audio")
        if self.rx_open_only_seconds is not None:
            if not self.enable_rx_audio:
                raise ValueError("rx_open_only_seconds requires enable_rx_audio")
            if self.rx_wav:
                raise ValueError("rx_open_only_seconds cannot be combined with rx_wav")
            if not 0.02 <= self.rx_open_only_seconds <= 30.0:
                raise ValueError(
                    "rx_open_only_seconds must be between 0.02 and 30 seconds"
                )
        if self.key_beep is not None:
            get_key_beep_profile(self.key_beep, self.beep_level)
            if self.role != "radio" or not self.verified_startup:
                raise ValueError("key_beep requires radio role with verified_startup")
            if self.enable_rx_audio:
                raise ValueError("key_beep cannot be combined with receive audio")
            if self.record_mic_wav or self.enable_tx:
                raise ValueError("key_beep cannot be combined with mic recording or TX")
        if self.record_mic_wav:
            if self.role != "radio" or not self.verified_startup:
                raise ValueError(
                    "record_mic_wav requires radio role with verified_startup"
                )
            if self.enable_rx_audio:
                raise ValueError(
                    "record_mic_wav cannot be combined with receive audio"
                )
            if Path(self.record_mic_wav).exists():
                raise ValueError("record_mic_wav output already exists")
        if not 0.1 <= self.mic_recording_max_seconds <= 30.0:
            raise ValueError(
                "mic_recording_max_seconds must be between 0.1 and 30 seconds"
            )
        if self.record_radio_wav:
            if self.role != "mic" or not self.verified_startup or not self.listen:
                raise ValueError(
                    "record_radio_wav requires listening mic role with verified_startup"
                )
            if Path(self.record_radio_wav).exists():
                raise ValueError("record_radio_wav output already exists")
        if not 0.1 <= self.radio_recording_max_seconds <= 30.0:
            raise ValueError(
                "radio_recording_max_seconds must be between 0.1 and 30 seconds"
            )
        if self.play_radio_audio:
            if self.role != "mic" or not self.verified_startup or not self.listen:
                raise ValueError(
                    "play_radio_audio requires listening mic role with verified_startup"
                )
        if not 1 <= self.radio_jitter_packets <= 25:
            raise ValueError("radio_jitter_packets must be between 1 and 25")
        display_test_count = sum(
            (
                self.display_offset56_test,
                self.display_offset56_low_bit_test,
                self.display_offset56_rssi_ladder_test,
                self.display_offset56_remaining_bits_test,
                self.display_offset57_bit_scan,
                self.display_offset58_bit_scan,
                self.display_offset59_bit_scan,
                self.display_offset59_low_all_visible_test,
                self.display_offset60_bit_scan_all_visible,
                self.display_offset61_bit_scan_all_visible,
                self.display_offset62_bit_scan_all_visible,
                self.display_offset63_bit_scan_all_visible,
                self.display_offset64_bit_scan_all_visible,
                self.display_offset65_bit_scan_all_visible,
                self.display_offset66_bit_scan_all_visible,
                self.display_offset67_bit_scan_all_visible,
                self.display_offsets8_33_observed_probe,
                self.display_character_blink_position_scan,
                self.display_character_attribute_bit_scan,
                self.status_led_observed_scan,
                self.backlight_timeout_wake_test,
            )
        )
        if display_test_count > 1:
            raise ValueError("select only one display offset 56 test")
        if display_test_count:
            if self.role != "radio" or not self.verified_startup:
                raise ValueError(
                    "display offset 56 tests require radio role with verified_startup"
                )
            if self.enable_rx_audio or self.key_beep or self.record_mic_wav or self.enable_tx:
                raise ValueError(
                    "display offset 56 tests cannot be combined with audio or TX modes"
                )
        elif self.display_test_blank_text:
            raise ValueError("display_test_blank_text requires a display diagnostic")
        if not 2.0 <= self.display_test_hold_seconds <= 10.0:
            raise ValueError("display_test_hold_seconds must be between 2 and 10 seconds")
        if self.mic_key_script:
            if self.role != "mic" or not self.verified_startup or not self.listen:
                raise ValueError(
                    "mic_key_script requires mic role with verified_startup and listen"
                )
            invalid = [
                button for button in self.mic_key_script
                if button not in ORDINARY_KEY_BUTTONS
            ]
            if invalid:
                raise ValueError(f"unverified or gated mic key: {invalid[0]}")
        if not 0.02 <= self.mic_key_hold_seconds <= 10.0:
            raise ValueError("mic_key_hold_seconds must be between 0.02 and 10 seconds")
        if not 0.0 <= self.mic_key_interval_seconds <= 10.0:
            raise ValueError("mic_key_interval_seconds must be between 0 and 10 seconds")
        if not 0.0 <= self.mic_key_start_delay_seconds <= 30.0:
            raise ValueError(
                "mic_key_start_delay_seconds must be between 0 and 30 seconds"
            )
        if self.exit_after_key_script and not self.mic_key_script:
            raise ValueError("exit_after_key_script requires mic_key_script")
        tx_capable = self.enable_tx or self.interactive_tx
        if self.enable_tx and self.interactive_tx:
            raise ValueError("enable_tx and interactive_tx are mutually exclusive")
        if tx_capable:
            if self.role != "mic" or not self.verified_startup or not self.listen:
                raise ValueError(
                    "TX requires listening mic role with verified_startup"
                )
            if self.enable_tx and self.mic_key_script:
                raise ValueError("TX cannot be combined with a mic key script")
            if not 20.0 <= self.tx_tone_hz <= 3500.0:
                raise ValueError("tx_tone_hz must be between 20 and 3500 Hz")
            if not -60.0 <= self.tx_level_dbfs <= -6.0:
                raise ValueError("tx_level_dbfs must be between -60 and -6 dBFS")
            if not 0.5 <= self.tx_hold_seconds <= 30.0:
                raise ValueError("tx_hold_seconds must be between 0.5 and 30 seconds")
            if not 0.0 <= self.tx_start_delay_seconds <= 30.0:
                raise ValueError(
                    "tx_start_delay_seconds must be between 0 and 30 seconds"
                )
            if self.tx_wav and self.tx_live_device:
                raise ValueError("tx_wav and tx_live_device are mutually exclusive")
            if self.tx_wav:
                load_s16be_wav_payloads(self.tx_wav, max_seconds=30.0)
            if not 5 <= self.tx_device_buffer_ms <= 100:
                raise ValueError("tx_device_buffer_ms must be between 5 and 100")
            if not 1 <= self.tx_capture_queue_packets <= 3:
                raise ValueError(
                    "tx_capture_queue_packets must be between 1 and 3"
                )
        elif self.tx_wav or self.tx_live_device or self.exit_after_tx_script:
            raise ValueError(
                "tx_wav, tx_live_device, and exit_after_tx_script require enable_tx"
            )

        if self.interactive_tx:
            if not self.tx_live_device:
                raise ValueError("interactive_tx requires tx_live_device")
            if self.tx_wav or self.exit_after_tx_script:
                raise ValueError(
                    "interactive_tx supports only a live microphone source"
                )


class AuditLog:
    def __init__(
        self,
        path: str | Path | None = None,
        event_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._handle: TextIO | None = None
        self._event_callback = event_callback
        if path:
            output = Path(path)
            output.parent.mkdir(parents=True, exist_ok=True)
            self._handle = output.open("a", encoding="utf-8")

    def write(self, event: str, **fields: object) -> None:
        record = {"event": event, **fields}
        LOGGER.info("%s", json.dumps(record, sort_keys=True))
        if self._handle and not self._handle.closed:
            self._handle.write(json.dumps(record, sort_keys=True) + "\n")
            self._handle.flush()
        if self._event_callback is not None:
            try:
                self._event_callback(record)
            except Exception:
                LOGGER.exception("audit event callback failed")

    def close(self) -> None:
        if self._handle:
            self._handle.close()


class CommandMicEmulator:
    """Fail-closed endpoint for staged protocol research.

    The default profile responds only to an observed idle heartbeat. The
    explicitly selected verified radio profile also replays the evidenced boot,
    display, channel, zone, and volume exchanges. The verified mic profile can
    emit mapped ordinary controls and, only behind explicit safety gates, PTT
    with paced transmit audio. Emergency and configuration traffic remain
    excluded.
    """

    def __init__(
        self,
        config: EmulatorConfig,
        audit_log: AuditLog | None = None,
        udp_protocol: VerifiedRadioUdpProtocol | VerifiedMicUdpProtocol | None = None,
        mic_audio_source: MicrophoneAudioSource | None = None,
    ) -> None:
        self.config = config
        self.audit = audit_log or AuditLog()
        self._server: asyncio.Server | None = None
        self._server_session_tasks: set[asyncio.Task[None]] = set()
        self._radio_session_count = 0
        self._mic_session_count = 0
        self._send_lock = asyncio.Lock()
        self._restore_task: asyncio.Task[None] | None = None
        self._channel_index = 0
        self._zone_index = 0
        self._volume_level = 1
        self._udp_protocol = udp_protocol
        self._mic_audio_source = mic_audio_source
        self.display_state = DisplayStateModel()
        self._display_test_complete = False
        self._mic_control_queue: asyncio.Queue[tuple[str, float, bool]] = asyncio.Queue()
        self._mic_control_task: asyncio.Task[None] | None = None
        self._mic_script_task: asyncio.Task[None] | None = None
        self._mic_ready_task: asyncio.Task[None] | None = None
        self._mic_probe_response_task: asyncio.Task[None] | None = None
        self._mic_script_complete = asyncio.Event()
        self._mic_tx_task: asyncio.Task[None] | None = None
        self._mic_tx_complete = asyncio.Event()
        self._mic_tx_active = asyncio.Event()
        self._mic_tx_closed = asyncio.Event()
        self._mic_ptt_asserted = False
        self._mic_tx_error: BaseException | None = None
        self._mic_writer: asyncio.StreamWriter | None = None
        self._interactive_tx_task: asyncio.Task[int] | None = None
        self._interactive_tx_stop = asyncio.Event()
        self._interactive_ptt_lock = asyncio.Lock()
        self._interactive_key_lock = asyncio.Lock()
        self._interactive_key: str | None = None
        self._radio_writer: asyncio.StreamWriter | None = None

    @property
    def incoming_direction(self) -> Direction:
        return (
            Direction.RADIO_TO_MIC
            if self.config.role == "mic"
            else Direction.MIC_TO_RADIO
        )

    @property
    def expected_heartbeat(self) -> bytes:
        return RADIO_IDLE_HEARTBEAT if self.config.role == "mic" else MIC_IDLE_HEARTBEAT

    @property
    def response_heartbeat(self) -> bytes:
        return MIC_IDLE_HEARTBEAT if self.config.role == "mic" else RADIO_IDLE_HEARTBEAT

    async def _send_frames(
        self,
        writer: asyncio.StreamWriter,
        frames: tuple[bytes, ...] | list[bytes],
        *,
        reason: str,
        interval: float = 0.0,
    ) -> None:
        async with self._send_lock:
            for frame in frames:
                writer.write(frame)
                await writer.drain()
                self.audit.write("sent_verified", reason=reason, raw_hex=frame.hex())
                if interval:
                    await asyncio.sleep(interval)

    def queue_key_tap(
        self,
        button: str,
        *,
        hold_seconds: float | None = None,
        allow_emergency: bool = False,
    ) -> None:
        """Queue one verified physical-key tap for the stable mic session."""

        encode_key_tap(button, allow_emergency=allow_emergency)
        hold = self.config.mic_key_hold_seconds if hold_seconds is None else hold_seconds
        if not 0.02 <= hold <= 10.0:
            raise ValueError("key hold_seconds must be between 0.02 and 10 seconds")
        self._mic_control_queue.put_nowait((button, hold, allow_emergency))
        self.audit.write(
            "mic_key_queued",
            button=button,
            hold_seconds=hold,
            emergency_gate=allow_emergency,
        )

    def queue_power_tap(self, *, hold_seconds: float = 0.15) -> None:
        """Queue the verified class 01/09 Power press/release transaction."""

        if not 0.02 <= hold_seconds <= 0.45:
            raise ValueError("interactive Power tap must be between 0.02 and 0.45 seconds")
        self._mic_control_queue.put_nowait(("power", hold_seconds, False))
        self.audit.write("mic_power_queued", hold_seconds=hold_seconds)

    @property
    def controls_ready(self) -> bool:
        return self._mic_writer is not None and not self._mic_writer.is_closing()

    @property
    def ptt_active(self) -> bool:
        return self._mic_ptt_asserted

    @property
    def radio_controls_ready(self) -> bool:
        return self._radio_writer is not None and not self._radio_writer.is_closing()

    async def send_interactive_display(self, display: DisplayBuffer) -> None:
        writer = self._radio_writer
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        await self._send_frames(
            writer,
            encode_display_transaction(display),
            reason="interactive_display",
        )

    async def send_interactive_status_led(self, color: str) -> None:
        writer = self._radio_writer
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        await self._send_frames(
            writer,
            (encode_status_led(color),),
            reason=f"interactive_status_led:{color}",
        )

    async def send_interactive_backlight(self, state: str) -> None:
        """Send one explicitly requested immediate backlight state."""

        writer = self._radio_writer
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        await self._send_frames(
            writer,
            (encode_backlight_state(state),),
            reason=f"interactive_backlight:{state}",
        )

    async def send_interactive_mic_gain(self, level: int) -> None:
        """Send an operator-requested observed microphone-gain frame pair."""

        writer = self._radio_writer
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        await self._send_frames(
            writer,
            encode_mic_gain_transaction(level),
            reason=f"interactive_mic_gain:{int(level)}",
            interval=0.001,
        )

    async def send_interactive_raw_frame(self, frame: bytes) -> None:
        writer = self._radio_writer
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        messages, remainder = parse_stream(frame, Direction.RADIO_TO_MIC)
        if remainder or len(messages) != 1 or messages[0].raw != frame:
            raise ValueError("raw input must contain exactly one complete framed message")
        await self._send_frames(writer, (frame,), reason="interactive_raw_frame")

    async def send_interactive_audio_tone(
        self, *, frequency_hz: float, level_dbfs: float, duration_seconds: float
    ) -> int:
        writer = self._radio_writer
        protocol = self._udp_protocol
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        if not isinstance(protocol, VerifiedRadioUdpProtocol):
            raise RuntimeError("CommandMic audio transport is not ready")
        await self._send_frames(writer, (RADIO_AUDIO_OPEN,), reason="interactive_audio_open")
        await _sleep_with_1ms_timer(0.01)
        await self._send_frames(
            writer, (RADIO_AUDIO_STATUS_OPEN,), reason="interactive_audio_status_open"
        )
        try:
            return await protocol.send_tone(
                frequency_hz=frequency_hz,
                level_dbfs=level_dbfs,
                duration_seconds=duration_seconds,
            )
        finally:
            await _sleep_with_1ms_timer(RADIO_AUDIO_CLOSE_DELAY_SECONDS)
            await self._send_frames(
                writer,
                (RADIO_AUDIO_CLOSE, RADIO_AUDIO_STATUS_CLOSED),
                reason="interactive_audio_close",
            )

    async def send_interactive_audio_wav(self, path: str | Path) -> int:
        writer = self._radio_writer
        protocol = self._udp_protocol
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        if not isinstance(protocol, VerifiedRadioUdpProtocol):
            raise RuntimeError("CommandMic audio transport is not ready")
        await self._send_frames(writer, (RADIO_AUDIO_OPEN,), reason="interactive_audio_open")
        await _sleep_with_1ms_timer(0.01)
        await self._send_frames(
            writer, (RADIO_AUDIO_STATUS_OPEN,), reason="interactive_audio_status_open"
        )
        try:
            return await protocol.send_wav(path)
        finally:
            await _sleep_with_1ms_timer(RADIO_AUDIO_CLOSE_DELAY_SECONDS)
            await self._send_frames(
                writer,
                (RADIO_AUDIO_CLOSE, RADIO_AUDIO_STATUS_CLOSED),
                reason="interactive_audio_close",
            )

    async def send_interactive_audio_payloads(
        self, payloads: list[bytes], *, source: str
    ) -> int:
        """Play bounded application PCM through the verified speaker transaction."""

        writer = self._radio_writer
        protocol = self._udp_protocol
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        if not isinstance(protocol, VerifiedRadioUdpProtocol):
            raise RuntimeError("CommandMic audio transport is not ready")
        if not payloads:
            return 0
        await self._send_frames(writer, (RADIO_AUDIO_OPEN,), reason="interactive_audio_open")
        await _sleep_with_1ms_timer(0.01)
        await self._send_frames(
            writer, (RADIO_AUDIO_STATUS_OPEN,), reason="interactive_audio_status_open"
        )
        try:
            return await protocol.send_payloads(payloads, source=source)
        finally:
            await _sleep_with_1ms_timer(RADIO_AUDIO_CLOSE_DELAY_SECONDS)
            await self._send_frames(
                writer,
                (RADIO_AUDIO_CLOSE, RADIO_AUDIO_STATUS_CLOSED),
                reason="interactive_audio_close",
            )

    async def send_interactive_polyphonic(
        self,
        steps: tuple[tuple[int, int, tuple[float, ...]], ...],
        *,
        level_dbfs: float = -18.0,
    ) -> int:
        """Play caller-defined delayed polyphonic PCM using the verified audio path."""

        writer = self._radio_writer
        protocol = self._udp_protocol
        if writer is None or writer.is_closing():
            raise RuntimeError("CommandMic session is not ready")
        if not isinstance(protocol, VerifiedRadioUdpProtocol):
            raise RuntimeError("CommandMic audio transport is not ready")
        payloads = generate_s16be_polyphonic_payloads(steps, level_dbfs=level_dbfs)
        await self._send_frames(writer, (RADIO_AUDIO_OPEN,), reason="interactive_polyphonic_open")
        await _sleep_with_1ms_timer(0.01)
        try:
            return await protocol.send_payloads(payloads, source="polyphonic")
        finally:
            await _sleep_with_1ms_timer(RADIO_AUDIO_CLOSE_DELAY_SECONDS)
            await self._send_frames(writer, (RADIO_AUDIO_CLOSE,), reason="interactive_polyphonic_close")

    async def press_interactive_key(
        self, button: str, *, allow_emergency: bool = False
    ) -> None:
        """Send a physical key-down immediately and keep it asserted until release."""

        async with self._interactive_key_lock:
            writer = self._mic_writer
            if writer is None or writer.is_closing():
                raise RuntimeError("CommandMic controls are not ready")
            if self._interactive_key == button:
                return
            if self._interactive_key is not None:
                raise RuntimeError(f"key {self._interactive_key!r} is already held")
            frame = encode_key_state(
                button, "press", allow_emergency=allow_emergency
            )
            await self._send_frames(
                writer, (frame,), reason=f"mic_key:{button}:interactive_press"
            )
            self._interactive_key = button
            self.audit.write("mic_key_asserted", button=button)

    async def release_interactive_key(
        self, button: str, *, allow_emergency: bool = False
    ) -> None:
        """Release a held physical key and return the key state to neutral."""

        async with self._interactive_key_lock:
            held = self._interactive_key
            if held is None:
                return
            # Always release the actually held key. This makes pointer-cancel,
            # focus loss, and release-outside fail safe even if the UI's target changed.
            writer = self._mic_writer
            self._interactive_key = None
            if writer is None or writer.is_closing():
                raise RuntimeError("CommandMic controls are not ready")
            emergency_gate = allow_emergency or held == "emergency"
            release = encode_key_state(
                held, "release", allow_emergency=emergency_gate
            )
            neutral = encode_key_state(None, "neutral")
            await self._send_frames(
                writer, (release,), reason=f"mic_key:{held}:interactive_release"
            )
            await _sleep_with_1ms_timer(0.002)
            await self._send_frames(
                writer, (neutral,), reason=f"mic_key:{held}:interactive_neutral"
            )
            self.audit.write("mic_key_released", button=held)

    async def press_interactive_ptt(self) -> None:
        """Assert PTT and begin the prewarmed live source after radio acknowledgement."""

        async with self._interactive_ptt_lock:
            if not self.config.interactive_tx:
                raise RuntimeError("interactive TX is not armed")
            if self._mic_ptt_asserted:
                return
            writer = self._mic_writer
            if writer is None or writer.is_closing():
                raise RuntimeError("CommandMic controls are not ready")
            if not isinstance(self._udp_protocol, VerifiedMicUdpProtocol):
                raise RuntimeError("verified mic UDP transport unavailable")
            if self._mic_audio_source is None:
                raise RuntimeError("live microphone source is not prewarmed")

            self._mic_tx_active.clear()
            self._mic_tx_closed.clear()
            self._interactive_tx_stop.clear()
            ptt_sent_at = time.perf_counter()
            await self._send_frames(writer, (MIC_PTT_DOWN,), reason="mic_ptt:interactive_press")
            self._mic_ptt_asserted = True
            self.audit.write("mic_ptt_asserted", mode="interactive", monotonic=ptt_sent_at)
            try:
                await asyncio.wait_for(self._mic_tx_active.wait(), timeout=1.0)
            except BaseException:
                await self._release_interactive_ptt_locked(fail_closed=True)
                raise
            self._interactive_tx_task = asyncio.create_task(
                self._udp_protocol.send_live_transmit_until(
                    self._mic_audio_source,
                    self._interactive_tx_stop,
                    first_packet_deadline=ptt_sent_at + 0.030,
                    device=self.config.tx_live_device,
                    device_buffer_ms=self.config.tx_device_buffer_ms,
                    capture_queue_packets=self.config.tx_capture_queue_packets,
                )
            )

    async def release_interactive_ptt(self) -> None:
        """Release PTT immediately, then preserve the observed RTP release tail."""

        async with self._interactive_ptt_lock:
            await self._release_interactive_ptt_locked(fail_closed=False)

    async def _release_interactive_ptt_locked(self, *, fail_closed: bool) -> None:
        writer = self._mic_writer
        if self._mic_ptt_asserted and writer is not None and not writer.is_closing():
            await self._send_frames(
                writer,
                (MIC_PTT_UP,),
                reason=(
                    "mic_ptt:interactive_fail_closed_release"
                    if fail_closed
                    else "mic_ptt:interactive_release"
                ),
            )
        was_asserted = self._mic_ptt_asserted
        self._mic_ptt_asserted = False
        self._interactive_tx_stop.set()
        task = self._interactive_tx_task
        self._interactive_tx_task = None
        if task is not None:
            try:
                packets = await asyncio.wait_for(task, timeout=1.0)
                self.audit.write(
                    "mic_interactive_tx_audio_completed", packets=packets
                )
            except BaseException as exc:
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                if not fail_closed:
                    raise RuntimeError("interactive microphone audio failed") from exc
        if was_asserted:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._mic_tx_closed.wait(), timeout=1.0)
            self.audit.write(
                "mic_ptt_released", mode="interactive", monotonic=time.perf_counter()
            )

    async def _mic_control_loop(self, writer: asyncio.StreamWriter) -> None:
        while not writer.is_closing():
            button, hold, allow_emergency = await self._mic_control_queue.get()
            if button == "power":
                press = encode_power_state("press")
                release = encode_power_state("release")
                neutral = None
            else:
                press, release, neutral = encode_key_tap(
                    button, allow_emergency=allow_emergency
                )
            try:
                await self._send_frames(
                    writer, (press,), reason=f"mic_key:{button}:press"
                )
                await _sleep_with_1ms_timer(hold)
                await self._send_frames(
                    writer, (release,), reason=f"mic_key:{button}:release"
                )
                if neutral is not None:
                    await _sleep_with_1ms_timer(0.002)
                    await self._send_frames(
                        writer, (neutral,), reason=f"mic_key:{button}:neutral"
                    )
                self.audit.write(
                    "mic_key_tap_completed", button=button, hold_seconds=hold
                )
            finally:
                self._mic_control_queue.task_done()

    async def _run_mic_key_script(self, writer: asyncio.StreamWriter) -> None:
        if self.config.mic_key_start_delay_seconds:
            self.audit.write(
                "mic_key_script_delay_started",
                seconds=self.config.mic_key_start_delay_seconds,
            )
            await asyncio.sleep(self.config.mic_key_start_delay_seconds)
        for button in self.config.mic_key_script:
            self.queue_key_tap(button)
            await self._mic_control_queue.join()
            if self.config.mic_key_interval_seconds:
                await asyncio.sleep(self.config.mic_key_interval_seconds)
        self.audit.write("mic_key_script_completed", taps=len(self.config.mic_key_script))
        self._mic_script_complete.set()
        if self.config.exit_after_key_script:
            writer.close()

    async def _sleep_until(self, deadline: float) -> None:
        """Yield against an absolute monotonic deadline without chained drift."""

        while deadline > time.perf_counter():
            await asyncio.sleep(0)

    async def _run_mic_tx_script(self, writer: asyncio.StreamWriter) -> None:
        """Run one bounded, acknowledgement-gated software-CommandMic TX."""

        if not isinstance(self._udp_protocol, VerifiedMicUdpProtocol):
            self._mic_tx_error = RuntimeError("verified mic UDP transport unavailable")
            self._mic_tx_complete.set()
            writer.close()
            return
        audio_task: asyncio.Task[int] | None = None
        ptt_sent_at: float | None = None
        try:
            if self.config.tx_start_delay_seconds:
                self.audit.write(
                    "mic_tx_script_delay_started",
                    seconds=self.config.tx_start_delay_seconds,
                )
                await asyncio.sleep(self.config.tx_start_delay_seconds)
            self._mic_tx_active.clear()
            self._mic_tx_closed.clear()
            ptt_sent_at = time.perf_counter()
            await self._send_frames(writer, (MIC_PTT_DOWN,), reason="mic_ptt:press")
            self._mic_ptt_asserted = True
            self.audit.write("mic_ptt_asserted", monotonic=ptt_sent_at)
            await asyncio.wait_for(self._mic_tx_active.wait(), timeout=1.0)

            # Physical CommandMic captures begin RTP 30.3-32.4 ms after PTT.
            first_packet_deadline = ptt_sent_at + 0.030
            if self.config.tx_live_device:
                if self._mic_audio_source is None:
                    raise RuntimeError("live microphone source was not prewarmed")
                hold_seconds = self.config.tx_hold_seconds
                source = "live_microphone"
                source_fields = {
                    "device": self.config.tx_live_device,
                    "device_buffer_ms": self.config.tx_device_buffer_ms,
                    "capture_queue_packets": self.config.tx_capture_queue_packets,
                }
                packet_count = math.ceil(
                    (hold_seconds + 0.220 - 0.030) / 0.020
                )
                payloads = None
            elif self.config.tx_wav:
                payloads, source_samples = load_s16be_wav_payloads(
                    self.config.tx_wav, max_seconds=30.0
                )
                hold_seconds = source_samples / 8000.0
                source = "wav"
                source_fields: dict[str, object] = {
                    "wav": self.config.tx_wav,
                    "source_samples": source_samples,
                }
            else:
                hold_seconds = self.config.tx_hold_seconds
                source = "tone"
                source_fields = {
                    "frequency_hz": self.config.tx_tone_hz,
                    "level_dbfs": self.config.tx_level_dbfs,
                }
                # Include the verified approximately 220 ms post-release RTP
                # tail while preserving one 20 ms packet at a time.
                audio_seconds = hold_seconds + 0.220 - 0.030
                payloads = generate_s16be_tone_payloads(
                    frequency_hz=self.config.tx_tone_hz,
                    level_dbfs=self.config.tx_level_dbfs,
                    packet_count=math.ceil(audio_seconds / 0.020),
                )
            if self.config.tx_wav:
                tail_packets = math.ceil((0.220 - 0.030) / 0.020)
                payloads.extend([bytes(320)] * tail_packets)
            if self.config.tx_live_device:
                assert self._mic_audio_source is not None
                audio_task = asyncio.create_task(
                    self._udp_protocol.send_live_transmit(
                        self._mic_audio_source,
                        packet_count=packet_count,
                        source=source,
                        first_packet_deadline=first_packet_deadline,
                        **source_fields,
                    )
                )
            else:
                assert payloads is not None
                audio_task = asyncio.create_task(
                    self._udp_protocol.send_transmit_payloads(
                        payloads,
                        source=source,
                        first_packet_deadline=first_packet_deadline,
                        **source_fields,
                    )
                )
            await self._sleep_until(ptt_sent_at + hold_seconds)
            await self._send_frames(writer, (MIC_PTT_UP,), reason="mic_ptt:release")
            self._mic_ptt_asserted = False
            self.audit.write("mic_ptt_released", monotonic=time.perf_counter())
            packet_count = await audio_task
            audio_task = None
            await asyncio.wait_for(self._mic_tx_closed.wait(), timeout=1.0)
            self.audit.write(
                "mic_tx_script_completed",
                source=source,
                packets=packet_count,
                hold_seconds=hold_seconds,
            )
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                self.audit.write("mic_tx_script_cancelled")
            else:
                self._mic_tx_error = exc
                self.audit.write(
                    "mic_tx_script_failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            if audio_task is not None:
                if not audio_task.done():
                    audio_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await audio_task
            if self._mic_ptt_asserted and not writer.is_closing():
                with contextlib.suppress(ConnectionError, OSError):
                    await self._send_frames(
                        writer, (MIC_PTT_UP,), reason="mic_ptt:fail_closed_release"
                    )
                self._mic_ptt_asserted = False
            if not isinstance(exc, asyncio.CancelledError):
                writer.close()
        finally:
            self._mic_tx_complete.set()
            if self.config.exit_after_tx_script and not writer.is_closing():
                writer.close()

    def _start_mic_controls(self, writer: asyncio.StreamWriter, *, reason: str) -> None:
        """Start ordinary controls once a stable radio display is established."""

        if self._mic_control_task is not None or writer.is_closing():
            return
        self._mic_writer = writer
        self._mic_control_task = asyncio.create_task(self._mic_control_loop(writer))
        self.audit.write("mic_controls_ready", reason=reason)
        if self.config.mic_key_script:
            self._mic_script_task = asyncio.create_task(
                self._run_mic_key_script(writer)
            )
        if self.config.enable_tx:
            self._mic_tx_task = asyncio.create_task(self._run_mic_tx_script(writer))

    async def _mic_ready_after_single_display(
        self, writer: asyncio.StreamWriter
    ) -> None:
        """Handle radios that omit opening text during a warm reconnect."""

        await asyncio.sleep(3.0)
        self._start_mic_controls(writer, reason="single_display_grace_elapsed")

    async def _mic_probe_response_after_special_prompt(
        self, writer: asyncio.StreamWriter
    ) -> None:
        """Answer the captured probe prompt, including process-restart attach."""

        await asyncio.sleep(0.005)
        if writer.is_closing():
            return
        await self._send_frames(
            writer,
            MIC_PROBE_RESPONSE,
            reason="mic_probe_response",
            interval=0.001,
        )

    async def _send_display(
        self,
        writer: asyncio.StreamWriter,
        text: str,
        *,
        tail: bytes = DISPLAY_SUFFIX,
    ) -> None:
        await self._send_frames(
            writer,
            encode_display_transaction(DisplayBuffer.from_primary_text(text, tail=tail)),
            reason=f"display:{text}",
        )

    def _display_frame(self, text: str, *, tail: bytes | None = None) -> bytes:
        """Compatibility wrapper around the shared display composer.

        New integrations should construct ``DisplayBuffer`` and call
        ``encode_display_transaction`` directly.
        """

        display = DisplayBuffer.from_primary_text(
            text,
            tail=DISPLAY_SUFFIX if tail is None else tail,
        )
        return encode_display_transaction(display)[1]

    @staticmethod
    def _tail_with_offset56(value: int) -> bytes:
        if value not in (0x00, 0x88, 0x8A, 0xFA):
            raise ValueError("offset 56 test value must be observed in a real capture")
        tail = bytearray(DISPLAY_SUFFIX)
        tail[56 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset56_low_candidate(value: int) -> bytes:
        if value not in (0x00, 0x08, 0x80, 0x88):
            raise ValueError("LOW candidate test is restricted to masks 00, 08, 80, 88")
        tail = bytearray(DISPLAY_SUFFIX)
        tail[56 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset56_rssi_candidate(value: int) -> bytes:
        if value not in tuple(range(0x80, 0x100, 0x10)):
            raise ValueError("RSSI ladder is restricted to 80,90,a0,b0,c0,d0,e0,f0")
        tail = bytearray(DISPLAY_SUFFIX)
        tail[56 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset56_remaining_candidate(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x04, 0x05):
            raise ValueError("remaining-bit test is restricted to 00,01,04,05")
        tail = bytearray(DISPLAY_SUFFIX)
        tail[56 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset57_candidate(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 57 bit scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[57 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset58_candidate(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 58 bit scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[58 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset59_candidate(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 59 bit scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[59 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset59_low_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x0F):
            raise ValueError("offset 59 all-visible test requires 00,01,02,04,08,0f")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0 | value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset60_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 60 all-visible scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0
        tail[60 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset61_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 61 all-visible scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0
        tail[61 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset62_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 62 all-visible scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0
        tail[62 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset63_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 63 all-visible scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0
        tail[63 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset64_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 64 all-visible scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0
        tail[64 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset65_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 65 all-visible scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0
        tail[65 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset66_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 66 all-visible scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0
        tail[66 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_with_offset67_and_all_visible(value: int) -> bytes:
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("offset 67 all-visible scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0xFF
        tail[57 - 8] = 0xFF
        tail[58 - 8] = 0xFF
        tail[59 - 8] = 0xF0
        tail[67 - 8] = value
        return bytes(tail)

    @staticmethod
    def _tail_for_offsets8_33_observed_probe(stage: str) -> bytes:
        if stage not in {"plain", "keypad_base", "offset32", "offset33"}:
            raise ValueError("unknown offsets 8-33 observed-probe stage")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[56 - 8] = 0x88
        if stage != "plain":
            tail[0:20] = b" " * 20  # Absolute payload offsets 8..27.
        if stage == "offset32":
            tail[32 - 8] = 0x80
        elif stage == "offset33":
            tail[33 - 8] = 0x80
        return bytes(tail)

    @staticmethod
    def _tail_for_character_blink_position(position: int) -> bytes:
        if position not in range(1, 9):
            raise ValueError("character blink position must be 1 through 8")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[0:20] = b" " * 20
        tail[(28 + position - 1) - 8] = 0x80
        tail[56 - 8] = 0x88
        return bytes(tail)

    @staticmethod
    def _tail_for_character_attribute_value(value: int, position: int = 5) -> bytes:
        if position not in range(1, 9):
            raise ValueError("character attribute position must be 1 through 8")
        if value not in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            raise ValueError("character attribute scan requires zero or one set bit")
        tail = bytearray(DISPLAY_BUFFER_SIZE - 8)
        tail[0:20] = b" " * 20
        tail[(28 + position - 1) - 8] = value
        tail[56 - 8] = 0x88
        return bytes(tail)

    async def _run_display_offset56_test(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x88, 0x8A, 0xFA, 0x00):
            self.audit.write(
                "display_offset56_test_state",
                value_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
            )
            await self._send_display(
                writer,
                self._display_test_text,
                tail=self._tail_with_offset56(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write("display_offset56_test_complete", restored_value_hex="88")
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset56_low_bit_test(
        self, writer: asyncio.StreamWriter
    ) -> None:
        # Start and finish at the verified LOW state so the operator has a
        # reference and the endpoint is never left in an experimental state.
        for value in (0x88, 0x08, 0x80, 0x00):
            self.audit.write(
                "display_offset56_low_bit_test_state",
                value_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value in (0x08, 0x80),
            )
            await self._send_display(
                writer,
                self._display_test_text,
                tail=self._tail_with_offset56_low_candidate(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset56_low_bit_test_complete", restored_value_hex="88"
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset56_rssi_ladder_test(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for level, value in enumerate(range(0x80, 0x100, 0x10)):
            self.audit.write(
                "display_offset56_rssi_ladder_state",
                value_hex=f"{value:02x}",
                candidate_level=level,
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x80,
            )
            await self._send_display(
                writer,
                self._display_test_text,
                tail=self._tail_with_offset56_rssi_candidate(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset56_rssi_ladder_complete", restored_value_hex="88"
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset56_remaining_bits_test(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x04, 0x05):
            self.audit.write(
                "display_offset56_remaining_bits_state",
                value_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                self._display_test_text,
                tail=self._tail_with_offset56_remaining_candidate(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset56_remaining_bits_complete", restored_value_hex="88"
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset57_bit_scan(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset57_bit_scan_state",
                value_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                self._display_test_text,
                tail=self._tail_with_offset57_candidate(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset57_bit_scan_complete",
            restored_offset56_hex="88",
            restored_offset57_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset58_bit_scan(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset58_bit_scan_state",
                value_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                self._display_test_text,
                tail=self._tail_with_offset58_candidate(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset58_bit_scan_complete",
            restored_offset56_hex="88",
            restored_offset58_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset59_bit_scan(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset59_bit_scan_state",
                value_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                self._display_test_text,
                tail=self._tail_with_offset59_candidate(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset59_bit_scan_complete",
            restored_offset56_hex="88",
            restored_offset59_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset59_low_all_visible_test(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x0F):
            self.audit.write(
                "display_offset59_low_all_visible_state",
                offset56_hex="ff",
                offset57_hex="ff",
                offset58_hex="ff",
                offset59_hex=f"{0xF0 | value:02x}",
                candidate_low_nibble_hex=f"{value:01x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset59_low_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset59_low_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset58_hex="00",
            restored_offset59_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset60_bit_scan_all_visible(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset60_bit_scan_all_visible_state",
                offset60_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset60_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset60_bit_scan_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset60_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset61_bit_scan_all_visible(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset61_bit_scan_all_visible_state",
                offset61_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset61_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset61_bit_scan_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset61_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset62_bit_scan_all_visible(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset62_bit_scan_all_visible_state",
                offset62_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset62_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset62_bit_scan_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset62_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset63_bit_scan_all_visible(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset63_bit_scan_all_visible_state",
                offset63_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset63_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset63_bit_scan_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset63_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset64_bit_scan_all_visible(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset64_bit_scan_all_visible_state",
                offset64_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset64_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset64_bit_scan_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset64_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset65_bit_scan_all_visible(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset65_bit_scan_all_visible_state",
                offset65_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset65_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset65_bit_scan_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset65_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset66_bit_scan_all_visible(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset66_bit_scan_all_visible_state",
                offset66_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset66_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset66_bit_scan_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset66_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offset67_bit_scan_all_visible(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_offset67_bit_scan_all_visible_state",
                offset67_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value != 0x00,
            )
            await self._send_display(
                writer,
                "88888888",
                tail=self._tail_with_offset67_and_all_visible(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offset67_bit_scan_all_visible_complete",
            restored_offset56_hex="88",
            restored_offset67_hex="00",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_offsets8_33_observed_probe(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for stage in ("plain", "keypad_base", "offset32", "offset33"):
            self.audit.write(
                "display_offsets8_33_observed_probe_state",
                stage=stage,
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=stage != "plain",
            )
            await self._send_display(
                writer,
                "ABCDEFGH",
                tail=self._tail_for_offsets8_33_observed_probe(stage),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_offsets8_33_observed_probe_complete",
            restored_offset56_hex="88",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_character_blink_position_scan(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for position in range(1, 9):
            self.audit.write(
                "display_character_blink_position_state",
                position=position,
                absolute_offset=28 + position - 1,
                value_hex="80",
                hold_seconds=self.config.display_test_hold_seconds,
            )
            await self._send_display(
                writer,
                "ABCDEFGH",
                tail=self._tail_for_character_blink_position(position),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_character_blink_position_scan_complete",
            restored_offset56_hex="88",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_display_character_attribute_bit_scan(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            self.audit.write(
                "display_character_attribute_bit_state",
                position=5,
                absolute_offset=32,
                value_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
                experimental=value not in (0x00, 0x80),
            )
            await self._send_display(
                writer,
                "ABCDEFGH",
                tail=self._tail_for_character_attribute_value(value),
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_display(writer, self._current_channel_text)
        self.audit.write(
            "display_character_attribute_bit_scan_complete",
            restored_offset56_hex="88",
        )
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_status_led_observed_scan(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for value in (0x00, 0x02, 0x04, 0x06):
            self.audit.write(
                "status_led_observed_state",
                status_hex=f"{value:02x}",
                hold_seconds=self.config.display_test_hold_seconds,
            )
            await self._send_frames(
                writer,
                (build_frame(0x02, 0x02, bytes((value,))),),
                reason=f"status_led_observed_{value:02x}",
            )
            await asyncio.sleep(self.config.display_test_hold_seconds)
        await self._send_frames(
            writer,
            (RADIO_AUDIO_STATUS_CLOSED,),
            reason="status_led_observed_restore_idle",
        )
        self.audit.write("status_led_observed_scan_complete", restored_status_hex="00")
        self._display_test_complete = True
        await asyncio.sleep(1.0)
        writer.close()

    async def _run_backlight_timeout_wake_test(
        self, writer: asyncio.StreamWriter
    ) -> None:
        for cycle in (1, 2):
            self.audit.write(
                "backlight_timeout_observation",
                cycle=cycle,
                seconds=8.0,
                heartbeat_continues=True,
            )
            await asyncio.sleep(8.0)
            self.audit.write("backlight_display_refresh", cycle=cycle)
            await self._send_display(writer, self._current_channel_text)
        await asyncio.sleep(2.0)
        self.audit.write("backlight_timeout_wake_test_complete")
        self._display_test_complete = True
        writer.close()

    @property
    def _current_channel_text(self) -> str:
        if self._zone_index == 1:
            return "ZONE TWO"
        return ("CHANNEL1", "CHANNEL2")[self._channel_index]

    @property
    def _display_test_text(self) -> str:
        return "" if self.config.display_test_blank_text else self._current_channel_text

    def _schedule_restore(
        self, writer: asyncio.StreamWriter, delay: float
    ) -> None:
        if self._restore_task:
            self._restore_task.cancel()

        async def restore() -> None:
            await asyncio.sleep(delay)
            await self._send_display(writer, self._current_channel_text)

        self._restore_task = asyncio.create_task(restore())

    async def _handle_verified_key(self, writer: asyncio.StreamWriter, message: object) -> None:
        metadata = getattr(message, "metadata", {})
        if metadata.get("key_action") != "press":
            return
        button = metadata.get("key_button")
        if not self.config.automatic_key_responses:
            self.audit.write(
                "withheld_key_response", button=button, reason="automatic_responses_disabled"
            )
            return
        if button == "up":
            self._channel_index = (self._channel_index + 1) % 2
            await self._send_display(writer, self._current_channel_text)
        elif button == "down":
            self._channel_index = (self._channel_index - 1) % 2
            await self._send_display(writer, self._current_channel_text)
        elif button == "right":
            self._zone_index = (self._zone_index + 1) % 2
            self._channel_index = 0
            await self._send_display(writer, f"ZONE {self._zone_index + 1}")
            self._schedule_restore(writer, 2.25)
        elif button == "left":
            self._zone_index = (self._zone_index - 1) % 2
            self._channel_index = 0
            await self._send_display(writer, f"ZONE {self._zone_index + 1}")
            self._schedule_restore(writer, 2.25)
        elif button == "volume_up":
            self._volume_level = min(32, self._volume_level + 1)
            await self._send_display(writer, f" VOL {self._volume_level:>2}")
            self._schedule_restore(writer, 1.0)
        elif button == "volume_down":
            self._volume_level = max(0, self._volume_level - 1)
            await self._send_display(writer, f" VOL {self._volume_level:>2}")
            self._schedule_restore(writer, 1.0)
        else:
            self.audit.write("withheld_key_response", button=button, reason="not_allowlisted")

    async def _stable_startup(self, writer: asyncio.StreamWriter) -> None:
        await self._send_frames(
            writer,
            radio_stable_sync(
                self.config.mic_gain,
                self.config.experimental_mic_gain_companion,
                self.config.backlight_state,
            ),
            reason="stable_sync",
            interval=0.001,
        )
        # Real-radio opening frames use an all-zero tail; ordinary channel and
        # volume screens use the distinct capture-derived baseline tail.
        await self._send_display(
            writer, self.config.startup_opening_text, tail=bytes(60)
        )
        await asyncio.sleep(0.11)
        if self.config.startup_status_carousel:
            await self._send_frames(
                writer, RADIO_STATUS_CAROUSEL, reason="startup_status", interval=0.125
            )
            await asyncio.sleep(1.0)
        idle_text = (
            self._current_channel_text
            if self.config.startup_idle_text is None
            else self.config.startup_idle_text
        )
        await self._send_display(writer, idle_text)
        if self.config.display_offset56_test:
            await asyncio.sleep(1.0)
            await self._run_display_offset56_test(writer)
            return
        if self.config.display_offset56_low_bit_test:
            await asyncio.sleep(1.0)
            await self._run_display_offset56_low_bit_test(writer)
            return
        if self.config.display_offset56_rssi_ladder_test:
            await asyncio.sleep(1.0)
            await self._run_display_offset56_rssi_ladder_test(writer)
            return
        if self.config.display_offset56_remaining_bits_test:
            await asyncio.sleep(1.0)
            await self._run_display_offset56_remaining_bits_test(writer)
            return
        if self.config.display_offset57_bit_scan:
            await asyncio.sleep(1.0)
            await self._run_display_offset57_bit_scan(writer)
            return
        if self.config.display_offset58_bit_scan:
            await asyncio.sleep(1.0)
            await self._run_display_offset58_bit_scan(writer)
            return
        if self.config.display_offset59_bit_scan:
            await asyncio.sleep(1.0)
            await self._run_display_offset59_bit_scan(writer)
            return
        if self.config.display_offset59_low_all_visible_test:
            await asyncio.sleep(1.0)
            await self._run_display_offset59_low_all_visible_test(writer)
            return
        if self.config.display_offset60_bit_scan_all_visible:
            await asyncio.sleep(1.0)
            await self._run_display_offset60_bit_scan_all_visible(writer)
            return
        if self.config.display_offset61_bit_scan_all_visible:
            await asyncio.sleep(1.0)
            await self._run_display_offset61_bit_scan_all_visible(writer)
            return
        if self.config.display_offset62_bit_scan_all_visible:
            await asyncio.sleep(1.0)
            await self._run_display_offset62_bit_scan_all_visible(writer)
            return
        if self.config.display_offset63_bit_scan_all_visible:
            await asyncio.sleep(1.0)
            await self._run_display_offset63_bit_scan_all_visible(writer)
            return
        if self.config.display_offset64_bit_scan_all_visible:
            await asyncio.sleep(1.0)
            await self._run_display_offset64_bit_scan_all_visible(writer)
            return
        if self.config.display_offset65_bit_scan_all_visible:
            await asyncio.sleep(1.0)
            await self._run_display_offset65_bit_scan_all_visible(writer)
            return
        if self.config.display_offset66_bit_scan_all_visible:
            await asyncio.sleep(1.0)
            await self._run_display_offset66_bit_scan_all_visible(writer)
            return
        if self.config.display_offset67_bit_scan_all_visible:
            await asyncio.sleep(1.0)
            await self._run_display_offset67_bit_scan_all_visible(writer)
            return
        if self.config.display_offsets8_33_observed_probe:
            await asyncio.sleep(1.0)
            await self._run_display_offsets8_33_observed_probe(writer)
            return
        if self.config.display_character_blink_position_scan:
            await asyncio.sleep(1.0)
            await self._run_display_character_blink_position_scan(writer)
            return
        if self.config.display_character_attribute_bit_scan:
            await asyncio.sleep(1.0)
            await self._run_display_character_attribute_bit_scan(writer)
            return
        if self.config.status_led_observed_scan:
            await asyncio.sleep(1.0)
            await self._run_status_led_observed_scan(writer)
            return
        if self.config.backlight_timeout_wake_test:
            await asyncio.sleep(1.0)
            await self._run_backlight_timeout_wake_test(writer)
            return
        if self.config.enable_rx_audio:
            await self._run_receive_audio(writer)
        elif self.config.key_beep:
            await self._run_key_beep(writer)
        else:
            self.audit.write("startup_complete", role="radio")

    async def _run_key_beep(self, writer: asyncio.StreamWriter) -> None:
        """Play one key-touch beep without the receive-status/LED transaction."""

        if self._udp_protocol is None:
            self.audit.write("key_beep_withheld", reason="udp_protocol_unavailable")
            return
        profile = get_key_beep_profile(
            self.config.key_beep or "", self.config.beep_level
        )
        await self._send_frames(
            writer, (RADIO_AUDIO_OPEN,), reason="key_beep_audio_gate_open"
        )
        await asyncio.sleep(0.01)
        try:
            await self._udp_protocol.send_key_beep(
                profile.name, beep_level=profile.beep_level
            )
        finally:
            await asyncio.sleep(0.008)
            with contextlib.suppress(ConnectionError, OSError):
                await self._send_frames(
                    writer, (RADIO_AUDIO_CLOSE,), reason="key_beep_audio_gate_closed"
                )

    async def _run_receive_audio(self, writer: asyncio.StreamWriter) -> None:
        if self._udp_protocol is None:
            self.audit.write("rx_audio_withheld", reason="udp_protocol_unavailable")
            return
        await self._send_frames(
            writer, (RADIO_AUDIO_OPEN,), reason="rx_audio_state_open"
        )
        await self._send_display(writer, self.config.startup_idle_text or "")
        await self._send_frames(
            writer, (RADIO_AUDIO_STATUS_OPEN,), reason="rx_audio_status_open"
        )
        await asyncio.sleep(0.01)
        try:
            if self.config.rx_open_only_seconds is not None:
                self.audit.write(
                    "rx_audio_open_only_started",
                    duration_seconds=self.config.rx_open_only_seconds,
                    rtp_packets=0,
                )
                await asyncio.sleep(self.config.rx_open_only_seconds)
                self.audit.write(
                    "rx_audio_open_only_completed",
                    duration_seconds=self.config.rx_open_only_seconds,
                    rtp_packets=0,
                )
            elif self.config.rx_wav:
                await self._udp_protocol.send_wav(self.config.rx_wav)
            else:
                await self._udp_protocol.send_tone(
                    frequency_hz=self.config.rx_tone_hz,
                    level_dbfs=self.config.rx_level_dbfs,
                    duration_seconds=self.config.rx_tone_seconds,
                )
        finally:
            await asyncio.sleep(0.008)
            with contextlib.suppress(ConnectionError, OSError):
                await self._send_frames(
                    writer,
                    (RADIO_AUDIO_CLOSE, RADIO_AUDIO_STATUS_CLOSED),
                    reason="rx_audio_state_closed",
                )

    async def _heartbeat_loop(self, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(2.0)
        while not writer.is_closing():
            await self._send_frames(
                writer, (RADIO_IDLE_HEARTBEAT,), reason="idle_heartbeat"
            )
            await asyncio.sleep(2.0)

    async def _verified_radio_session(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        session_kind = "probe" if self._radio_session_count == 0 else "stable"
        self._radio_session_count += 1
        self.audit.write("verified_session", session_kind=session_kind)
        if session_kind == "stable":
            self._radio_writer = writer
        await self._send_frames(writer, (RADIO_STARTUP_HELLO,), reason="startup_hello")
        remainder = b""
        startup_task: asyncio.Task[None] | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(65536), self.config.read_timeout)
                except TimeoutError:
                    self.audit.write("watchdog_timeout", seconds=self.config.read_timeout)
                    return
                if not data:
                    return
                messages, remainder = parse_stream(
                    remainder + data, Direction.MIC_TO_RADIO
                )
                for message in messages:
                    self.audit.write(
                        "received",
                        kind=message.kind.value,
                        length=message.length,
                        raw_hex=message.raw.hex(),
                        metadata=message.metadata,
                    )
                    message_class = message.metadata.get("message_class")
                    command = message.metadata.get("command")
                    if message_class == 0x05 and command == 0x06 and message.body == b"\x00":
                        await self._send_frames(
                            writer, (RADIO_STARTUP_READY,), reason="startup_ready"
                        )
                    elif message_class == 0x05 and command == 0x02 and len(message.body) == 26:
                        if session_kind == "probe":
                            await self._send_frames(
                                writer, RADIO_PROBE_HEAD, reason="probe_sync", interval=0.001
                            )
                        elif startup_task is None:
                            startup_task = asyncio.create_task(self._stable_startup(writer))
                            heartbeat_task = asyncio.create_task(self._heartbeat_loop(writer))
                    elif (
                        session_kind == "probe"
                        and message_class == 0x05
                        and command == 0x04
                        and message.body == b"\x01"
                    ):
                        await self._send_frames(
                            writer, RADIO_PROBE_TAIL, reason="probe_complete", interval=0.001
                        )
                        return
                    elif session_kind == "stable" and message.kind is MessageKind.KEY_STATE:
                        await self._handle_verified_key(writer, message)
                    elif session_kind == "stable" and message.kind is MessageKind.PTT_STATE:
                        capture = (
                            self._udp_protocol
                            if isinstance(self._udp_protocol, VerifiedRadioUdpProtocol)
                            and self._udp_protocol.mic_capture_enabled
                            else None
                        )
                        active = bool(message.metadata["ptt_active"])
                        capture_ready = False
                        if capture is not None:
                            capture_ready = (
                                capture.start_mic_recording()
                                if active
                                else capture.release_mic_recording()
                            )
                        if not self.config.automatic_ptt_responses:
                            # Passive applications still need microphone RTP for
                            # meters and recording. Opening the local capture gate
                            # sends nothing to the peer; only the optional radio
                            # response frames below are suppressed.
                            self.audit.write(
                                "ptt_response_withheld",
                                reason="automatic_responses_disabled",
                                ptt_active=active,
                                passive_capture=capture_ready,
                            )
                        elif capture is not None:
                            if active:
                                if not capture_ready:
                                    self.audit.write(
                                        "ptt_response_withheld",
                                        reason="mic_recording_unavailable",
                                    )
                                    continue
                                await _sleep_with_1ms_timer(0.008)
                                await self._send_frames(
                                    writer,
                                    (RADIO_TX_ACTIVE,),
                                    reason="tx_capture_state_active",
                                )
                                await _sleep_with_1ms_timer(0.0055)
                                await self._send_frames(
                                    writer,
                                    (RADIO_TX_STATUS_ACTIVE,),
                                    reason="tx_capture_status_active",
                                )
                            else:
                                if not capture_ready:
                                    self.audit.write(
                                        "ptt_response_withheld",
                                        reason="no_active_mic_recording_session",
                                    )
                                    continue
                                await _sleep_with_1ms_timer(0.220)
                                await self._send_frames(
                                    writer,
                                    (RADIO_AUDIO_STATUS_CLOSED,),
                                    reason="tx_capture_status_closed",
                                )
                                await _sleep_with_1ms_timer(0.0015)
                                await self._send_frames(
                                    writer,
                                    (RADIO_AUDIO_CLOSE,),
                                    reason="tx_capture_state_closed",
                                )
                        else:
                            self.audit.write(
                                "ptt_response_withheld",
                                reason="mic_recording_not_enabled",
                            )
                    elif message.raw == MIC_IDLE_HEARTBEAT:
                        self.audit.write("received_heartbeat_response")
                    else:
                        self.audit.write("withheld_unknown_response", reason="fail_closed")
        finally:
            if self._radio_writer is writer:
                self._radio_writer = None
            for task in (startup_task, heartbeat_task, self._restore_task):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            self._restore_task = None

    async def _verified_mic_session(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        session_kind = "probe" if self._mic_session_count == 0 else "stable"
        self._mic_session_count += 1
        self.audit.write("verified_mic_session", session_kind=session_kind)
        remainder = b""
        startup_sync_sent = False
        identity_sent = False
        probe_response_sent = False
        stable_display_count = 0
        while True:
            try:
                data = await asyncio.wait_for(reader.read(65536), self.config.read_timeout)
            except TimeoutError:
                self.audit.write("watchdog_timeout", seconds=self.config.read_timeout)
                return
            if not data:
                return
            messages, remainder = parse_stream(
                remainder + data, Direction.RADIO_TO_MIC
            )
            for message in messages:
                display_event = self.display_state.consume(message)
                self.audit.write(
                    "received",
                    kind=message.kind.value,
                    length=message.length,
                    raw_hex=message.raw.hex(),
                    metadata=message.metadata,
                )
                if display_event is not None:
                    self.audit.write("display_event", **display_event.to_dict())
                message_class = message.metadata.get("message_class")
                command = message.metadata.get("command")
                if message.raw == RADIO_STARTUP_HELLO and not startup_sync_sent:
                    await self._send_frames(
                        writer,
                        MIC_STARTUP_SYNC,
                        reason="mic_startup_sync",
                        interval=0.001,
                    )
                    startup_sync_sent = True
                elif message.raw == RADIO_STARTUP_READY and not identity_sent:
                    if isinstance(self._udp_protocol, VerifiedMicUdpProtocol):
                        self._udp_protocol.send_boot()
                    await self._send_frames(
                        writer,
                        (MIC_IDENTITY,),
                        reason="mic_identity",
                    )
                    identity_sent = True
                elif (
                    session_kind == "probe"
                    and message.raw == RADIO_PROBE_HEAD[1]
                    and not probe_response_sent
                ):
                    probe_response_sent = True
                    self._mic_probe_response_task = asyncio.create_task(
                        self._mic_probe_response_after_special_prompt(writer)
                    )
                elif (
                    isinstance(self._udp_protocol, VerifiedMicUdpProtocol)
                    and message.kind is MessageKind.AUDIO_STATE
                ):
                    audio_state = message.metadata.get("audio_state")
                    if audio_state == "receive_open":
                        self._udp_protocol.set_radio_audio_gate(True)
                    elif audio_state == "transmit_active":
                        self._mic_tx_active.set()
                        self.audit.write("accepted_verified_tx_active")
                    elif audio_state == "closed":
                        self._udp_protocol.set_radio_audio_gate(False)
                        if self._mic_ptt_asserted or self._mic_tx_active.is_set():
                            self._mic_tx_closed.set()
                    self.audit.write(
                        "accepted_verified_radio_audio_state",
                        audio_state=audio_state,
                    )
                elif message.raw == DISPLAY_AFTER:
                    await self._send_frames(
                        writer,
                        (MIC_DISPLAY_ACK,),
                        reason="mic_display_ack",
                    )
                    if session_kind == "stable":
                        stable_display_count += 1
                        if stable_display_count == 1:
                            self._mic_ready_task = asyncio.create_task(
                                self._mic_ready_after_single_display(writer)
                            )
                        elif stable_display_count >= 2:
                            if self._mic_ready_task:
                                self._mic_ready_task.cancel()
                                self._mic_ready_task = None
                            self._start_mic_controls(
                                writer, reason="second_stable_display"
                            )
                elif message.raw == RADIO_IDLE_HEARTBEAT:
                    await self._send_frames(
                        writer,
                        (MIC_IDLE_HEARTBEAT,),
                        reason="mic_heartbeat_response",
                    )
                else:
                    self.audit.write(
                        "accepted_verified_radio_state",
                        kind=message.kind.value,
                    )

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.audit.write("connected", peer=peer, role=self.config.role)
        remainder = b""
        radio_stable_session = (
            self.config.role == "radio"
            and self.config.verified_startup
            and self._radio_session_count > 0
        )
        try:
            if self.config.role == "radio" and self.config.verified_startup:
                await self._verified_radio_session(reader, writer)
                return
            if self.config.role == "mic" and self.config.verified_startup:
                await self._verified_mic_session(reader, writer)
                return
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(65536), self.config.read_timeout)
                except TimeoutError:
                    self.audit.write("watchdog_timeout", seconds=self.config.read_timeout)
                    break
                if not data:
                    break
                messages, remainder = parse_stream(remainder + data, self.incoming_direction)
                for message in messages:
                    self.audit.write(
                        "received",
                        kind=message.kind.value,
                        length=message.length,
                        raw_hex=message.raw.hex(),
                    )
                    if message.kind is MessageKind.HEARTBEAT and message.raw == self.expected_heartbeat:
                        writer.write(self.response_heartbeat)
                        await writer.drain()
                        self.audit.write(
                            "sent_observed_heartbeat",
                            length=len(self.response_heartbeat),
                            raw_hex=self.response_heartbeat.hex(),
                        )
                    else:
                        self.audit.write("withheld_unknown_response", reason="fail_closed")
        finally:
            current_task = asyncio.current_task()
            if isinstance(self._udp_protocol, VerifiedMicUdpProtocol):
                # Control loss invalidates the receive-audio gate even when the
                # normal 01/04 close frame never arrives.
                self._udp_protocol.set_radio_audio_gate(False)
            elif isinstance(self._udp_protocol, VerifiedRadioUdpProtocol):
                # A vanished CommandMic cannot leave an application capture
                # active while this endpoint reconnects.
                self._udp_protocol.finish_mic_recording()
            if radio_stable_session:
                # A restarted CommandMic begins with the observed probe
                # session again. Reset before the outbound loop reconnects so
                # both peers agree on probe versus stable startup state.
                self._radio_session_count = 0
            if self._mic_ptt_asserted and not writer.is_closing():
                with contextlib.suppress(ConnectionError, OSError):
                    await self._send_frames(
                        writer,
                        (MIC_PTT_UP,),
                        reason="mic_ptt:session_fail_closed_release",
                    )
            self._mic_ptt_asserted = False
            self._interactive_tx_stop.set()
            for task in (
                self._mic_probe_response_task,
                self._mic_ready_task,
                self._mic_script_task,
                self._mic_tx_task,
                self._mic_control_task,
                self._interactive_tx_task,
            ):
                if task and task is not current_task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            self._mic_probe_response_task = None
            self._mic_ready_task = None
            self._mic_script_task = None
            self._mic_tx_task = None
            self._mic_control_task = None
            self._interactive_tx_task = None
            self._mic_writer = None
            writer.close()
            with contextlib.suppress(TimeoutError, ConnectionError, OSError):
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            self.audit.write("disconnected", peer=peer)

    def _accept_session(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Own accepted-session tasks so listener shutdown cannot leak them."""

        task = asyncio.create_task(self._session(reader, writer))
        self._server_session_tasks.add(task)
        task.add_done_callback(self._server_session_done)

    def _server_session_done(self, task: asyncio.Task[None]) -> None:
        self._server_session_tasks.discard(task)
        if not task.cancelled():
            with contextlib.suppress(ConnectionError, OSError):
                task.exception()

    async def _open_outbound_connection(
        self, *, local_port: int | None = None
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if local_port is None:
            local_port = self.config.port

        async def connect(source_port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.setblocking(False)
                sock.bind((self.config.local_ip, source_port))
                await asyncio.get_running_loop().sock_connect(
                    sock, (self.config.peer_ip, self.config.port)
                )
                return await asyncio.open_connection(sock=sock)
            except BaseException:
                sock.close()
                raise

        try:
            return await connect(local_port)
        except OSError as exc:
            # An OS can retain an actively closed four-tuple and reject an
            # immediate endpoint restart even with SO_REUSEADDR.
            # Preserve the observed source port in the normal path, but recover
            # from a bind collision with an audited ephemeral source port.
            retained_tuple = (
                getattr(exc, "winerror", None) == 52
                or exc.errno == errno.EADDRINUSE
            )
            if not retained_tuple:
                raise
            self.audit.write(
                "source_port_fallback",
                requested_port=local_port,
                reason="retained_tcp_tuple",
                error=str(exc),
            )
            return await connect(0)

    async def run(self) -> None:
        if self.config.enable_tx:
            LOGGER.warning(
                "TX IS ARMED: one bounded software-CommandMic PTT/audio transaction will "
                "key the radio. Keep the RF dummy load connected."
            )
        if self.config.interactive_tx:
            LOGGER.warning(
                "INTERACTIVE TX IS ARMED: GUI PTT can key the radio using the selected "
                "live microphone. Keep the RF dummy load connected."
            )
        if self.config.enable_rx_audio:
            if self.config.rx_open_only_seconds is not None:
                LOGGER.warning(
                    "RX AUDIO DIAGNOSTIC IS ENABLED: open state with no RTP for %.2f seconds",
                    self.config.rx_open_only_seconds,
                )
            elif self.config.rx_wav:
                LOGGER.warning("RX AUDIO IS ENABLED: bounded WAV playback from %s", self.config.rx_wav)
            else:
                LOGGER.warning(
                    "RX AUDIO IS ENABLED: bounded %.1f Hz tone at %.1f dBFS for %.2f seconds",
                    self.config.rx_tone_hz,
                    self.config.rx_level_dbfs,
                    self.config.rx_tone_seconds,
                )
        if self.config.key_beep:
            profile = get_key_beep_profile(
                self.config.key_beep, self.config.beep_level
            )
            LOGGER.warning(
                "KEY BEEP IS ENABLED: one bounded %s profile at fixed level %d, %.0f Hz, %d RTP packets / %.0f ms",
                profile.name,
                profile.beep_level,
                profile.frequency_hz,
                profile.packet_count,
                profile.duration_seconds * 1000,
            )
        if self.config.record_mic_wav:
            LOGGER.warning(
                "ISOLATED MIC AUDIO CAPTURE IS ENABLED: PTT acknowledgements will be "
                "replayed and received RTP will be recorded to %s; no RF endpoint is present",
                self.config.record_mic_wav,
            )
        if self.config.record_radio_wav:
            LOGGER.warning(
                "SOFTWARE MIC RADIO-AUDIO CAPTURE IS ENABLED: only verified, "
                "TCP-gated radio RTP will be recorded to %s (maximum %.1f seconds); "
                "PTT and microphone audio remain disabled",
                self.config.record_radio_wav,
                self.config.radio_recording_max_seconds,
            )
        if self.config.mic_key_script:
            LOGGER.warning(
                "SOFTWARE MIC KEY SCRIPT IS ENABLED: %d ordinary taps after stable display; Emergency, Power and PTT are excluded",
                len(self.config.mic_key_script),
            )
        if self.config.display_offset56_test:
            LOGGER.warning(
                "DISPLAY-ONLY OFFSET 56 TEST: observed values 88, 8a, fa, 00; "
                "%.1f seconds each; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset56_low_bit_test:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY LOW BIT TEST: 88, 08, 80, 00; "
                "%.1f seconds each; real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset56_rssi_ladder_test:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY RSSI LADDER: 80 through f0 in 0x10 steps; "
                "%.1f seconds each; real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset56_remaining_bits_test:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY REMAINING-BIT TEST: 00, 01, 04, 05; "
                "%.1f seconds each; real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset57_bit_scan:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 57 BIT SCAN: 00 then 01 through 80; "
                "%.1f seconds each; real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset58_bit_scan:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 58 BIT SCAN: 00 then 01 through 80; "
                "%.1f seconds each; real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset59_bit_scan:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 59 BIT SCAN: 00 then 01 through 80; "
                "%.1f seconds each; real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset59_low_all_visible_test:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 59 ALL-VISIBLE INTERACTION: text=88888888, "
                "offset56/57/58=ff, offset59=f0/f1/f2/f4/f8/ff; %.1f seconds each; "
                "real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset60_bit_scan_all_visible:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 60 ALL-VISIBLE BIT SCAN: 00 then "
                "01 through 80; %.1f seconds each; real radio must be disconnected; "
                "audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset61_bit_scan_all_visible:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 61 ALL-VISIBLE BIT SCAN: 00 then "
                "01 through 80; %.1f seconds each; real radio must be disconnected; "
                "audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset62_bit_scan_all_visible:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 62 ALL-VISIBLE BIT SCAN: 00 then "
                "01 through 80; %.1f seconds each; real radio must be disconnected; "
                "audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset63_bit_scan_all_visible:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 63 ALL-VISIBLE BIT SCAN: 00 then "
                "01 through 80; %.1f seconds each; real radio must be disconnected; "
                "audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset64_bit_scan_all_visible:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 64 ALL-VISIBLE BIT SCAN: 00 then "
                "01 through 80; %.1f seconds each; real radio must be disconnected; "
                "audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset65_bit_scan_all_visible:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 65 ALL-VISIBLE BIT SCAN: 00 then "
                "01 through 80; %.1f seconds each; real radio must be disconnected; "
                "audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset66_bit_scan_all_visible:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 66 ALL-VISIBLE BIT SCAN: 00 then "
                "01 through 80; %.1f seconds each; real radio must be disconnected; "
                "audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offset67_bit_scan_all_visible:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSET 67 ALL-VISIBLE BIT SCAN: 00 then "
                "01 through 80; %.1f seconds each; real radio must be disconnected; "
                "audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_offsets8_33_observed_probe:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY OFFSETS 8-33 OBSERVED-VALUE PROBE: "
                "plain, offsets8-27=20, then observed offset32/33=80 variants; "
                "%.1f seconds each; real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_character_blink_position_scan:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY CHARACTER BLINK POSITION SCAN: "
                "offsets28 through 35 set to observed 80 one at a time; %.1f seconds each; "
                "real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.display_character_attribute_bit_scan:
            LOGGER.warning(
                "EXPERIMENTAL DISPLAY-ONLY CHARACTER ATTRIBUTE BIT SCAN: "
                "offset32 values 00 then 01 through 80; %.1f seconds each; "
                "real radio must be disconnected; audio and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.status_led_observed_scan:
            LOGGER.warning(
                "OBSERVED-VALUE STATUS/LED SCAN: 02/02 values 00,02,04,06; "
                "%.1f seconds each; real radio must be disconnected; audio, RTP and TX are disabled",
                self.config.display_test_hold_seconds,
            )
        if self.config.backlight_timeout_wake_test:
            LOGGER.warning(
                "BACKLIGHT TIMEOUT/WAKE TEST: two 8-second heartbeat-only waits, each "
                "followed by an unchanged verified display refresh; real radio must be "
                "disconnected; audio and TX are disabled"
            )
        if self.config.listen:
            self._server = await asyncio.start_server(
                self._accept_session, self.config.local_ip, self.config.port
            )
            addresses = [str(sock.getsockname()) for sock in self._server.sockets or []]
            self.audit.write("listening", addresses=addresses)
            try:
                if self.config.exit_after_key_script or self.config.exit_after_tx_script:
                    completion = (
                        self._mic_tx_complete
                        if self.config.exit_after_tx_script
                        else self._mic_script_complete
                    )
                    await completion.wait()
                    self._server.close()
                    # Let the accepted connection observe EOF and finish its
                    # audit/finally path before run_emulator closes the log.
                    await asyncio.sleep(0.1)
                    if self._mic_tx_error is not None:
                        raise RuntimeError("software-mic TX failed") from self._mic_tx_error
                else:
                    # start_server() is already accepting connections. Avoid
                    # both serve_forever() and the Server async context: on
                    # Python 3.12+ their cancellation exits await active
                    # connections before our finally block can cancel the
                    # owned session tasks, which deadlocks endpoint shutdown.
                    await asyncio.Event().wait()
            finally:
                self._server.close()
                tasks = tuple(self._server_session_tasks)
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                self._server_session_tasks.clear()
                # Python 3.12+ Server.wait_closed() can wait for accepted
                # connections as well as listener sockets. Cancel and gather
                # our owned session tasks first so shutdown cannot deadlock
                # waiting for a connection whose task is cancelled afterward.
                await self._server.wait_closed()
            return

        while True:
            try:
                local_port = self.config.port
                if (
                    self.config.role == "radio"
                    and self.config.verified_startup
                    and self._radio_session_count == 0
                ):
                    # Windows retains an actively closed connection tuple long enough
                    # to block the observed two-second reconnect. Reserve the verified
                    # 52001 source port for the long-lived stable session and use a
                    # separate, configurable source port for the short probe only.
                    local_port = self.config.probe_source_port
                reader, writer = await self._open_outbound_connection(
                    local_port=local_port
                )
                await self._session(reader, writer)
                if (
                    self.config.display_offset56_test
                    or self.config.display_offset56_low_bit_test
                    or self.config.display_offset56_rssi_ladder_test
                    or self.config.display_offset56_remaining_bits_test
                    or self.config.display_offset57_bit_scan
                    or self.config.display_offset58_bit_scan
                    or self.config.display_offset59_bit_scan
                    or self.config.display_offset59_low_all_visible_test
                    or self.config.display_offset60_bit_scan_all_visible
                    or self.config.display_offset61_bit_scan_all_visible
                    or self.config.display_offset62_bit_scan_all_visible
                    or self.config.display_offset63_bit_scan_all_visible
                    or self.config.display_offset64_bit_scan_all_visible
                    or self.config.display_offset65_bit_scan_all_visible
                    or self.config.display_offset66_bit_scan_all_visible
                    or self.config.display_offset67_bit_scan_all_visible
                    or self.config.display_offsets8_33_observed_probe
                    or self.config.display_character_blink_position_scan
                    or self.config.display_character_attribute_bit_scan
                    or self.config.status_led_observed_scan
                    or self.config.backlight_timeout_wake_test
                ) and self._display_test_complete:
                    return
            except (ConnectionError, OSError) as exc:
                self.audit.write("connection_failed", error=str(exc))
            await asyncio.sleep(self.config.reconnect_delay)


class VerifiedRadioUdpProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        peer_ip: str,
        peer_port: int,
        audit: AuditLog,
        *,
        record_mic_wav: str | Path | None = None,
        mic_recording_max_seconds: float = 30.0,
        mic_audio_callback: Callable[[bytes], None] | None = None,
    ) -> None:
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.audit = audit
        self.transport: asyncio.DatagramTransport | None = None
        self._peer_ready = False
        self._sequence = RADIO_RTP_SEQUENCE
        self._timestamp = RADIO_RTP_TIMESTAMP
        self._record_mic_wav = Path(record_mic_wav) if record_mic_wav else None
        self._mic_audio_callback = mic_audio_callback
        self._mic_recording_max_packets = math.ceil(mic_recording_max_seconds / 0.02)
        self._mic_recording = False
        self._mic_ptt_session_active = False
        self._mic_recording_complete = False
        self._mic_recording_complete_event = asyncio.Event()
        self._mic_recording_complete_event.set()
        self._mic_payloads: list[bytes] = []
        self._mic_packet_count = 0
        self._mic_first_sequence: int | None = None
        self._mic_last_sequence: int | None = None
        self._mic_last_timestamp: int | None = None
        self._mic_sequence_errors = 0
        self._mic_timestamp_errors = 0
        self._mic_rtp_withheld_packets = 0
        self._mic_finalize_handle: asyncio.TimerHandle | None = None

    @property
    def mic_capture_enabled(self) -> bool:
        return self._record_mic_wav is not None or self._mic_audio_callback is not None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.audit.write("udp_received", peer=addr, length=len(data))
        valid_peer_rtp = (
            addr == (self.peer_ip, self.peer_port)
            and len(data) == 332
            and data[:2] == b"\x80\x7d"
        )
        if not valid_peer_rtp:
            self.audit.write("udp_response_withheld", reason="invalid_peer_or_rtp_shape")
            return
        if self._mic_recording:
            self._record_mic_rtp(data)
            return
        if not any(data[12:]) and self.transport is not None:
            self._peer_ready = True
            self.transport.sendto(RADIO_BOOT_RTP, addr)
            self.audit.write(
                "udp_sent_verified_boot_rtp", peer=addr, length=len(RADIO_BOOT_RTP)
            )
            return
        self._mic_rtp_withheld_packets += 1
        if self._mic_rtp_withheld_packets == 1:
            self.audit.write("mic_rtp_withheld", reason="ptt_capture_not_active")

    def start_mic_recording(self) -> bool:
        if not self.mic_capture_enabled:
            self.audit.write("mic_recording_withheld", reason="output_path_not_configured")
            return False
        if self._mic_recording_complete and self._record_mic_wav is not None:
            self.audit.write("mic_recording_withheld", reason="single_capture_already_complete")
            return False
        if self._mic_finalize_handle:
            self._mic_finalize_handle.cancel()
            self._mic_finalize_handle = None
        self._mic_recording = True
        self._mic_ptt_session_active = True
        self._mic_recording_complete_event.clear()
        self._mic_payloads.clear()
        self._mic_packet_count = 0
        self._mic_first_sequence = None
        self._mic_last_sequence = None
        self._mic_last_timestamp = None
        self._mic_sequence_errors = 0
        self._mic_timestamp_errors = 0
        self._mic_rtp_withheld_packets = 0
        self.audit.write(
            "mic_recording_started",
            output=str(self._record_mic_wav),
            max_packets=self._mic_recording_max_packets,
        )
        return True

    def release_mic_recording(self, tail_seconds: float = 0.35) -> bool:
        if not self._mic_ptt_session_active:
            return False
        self._mic_ptt_session_active = False
        if self._mic_recording:
            if self._mic_finalize_handle:
                self._mic_finalize_handle.cancel()
            self._mic_finalize_handle = asyncio.get_running_loop().call_later(
                tail_seconds, self.finish_mic_recording
            )
        self.audit.write(
            "mic_recording_release_seen",
            tail_seconds=tail_seconds,
            packets=self._mic_packet_count,
            withheld_packets=self._mic_rtp_withheld_packets,
        )
        return True

    async def wait_mic_recording_complete(self) -> None:
        """Wait until the current physical-PTT capture tail is fully closed."""

        await self._mic_recording_complete_event.wait()

    def _record_mic_rtp(self, data: bytes) -> None:
        _, _, sequence, timestamp, ssrc = struct.unpack("!BBHII", data[:12])
        if ssrc != MIC_RTP_SSRC:
            self.audit.write(
                "mic_rtp_withheld",
                reason="unexpected_ssrc",
                ssrc=f"{ssrc:08x}",
            )
            return
        if self._mic_last_sequence is not None:
            if sequence != ((self._mic_last_sequence + 1) & 0xFFFF):
                self._mic_sequence_errors += 1
            if timestamp != ((self._mic_last_timestamp + 160) & 0xFFFFFFFF):
                self._mic_timestamp_errors += 1
        else:
            self._mic_first_sequence = sequence
        self._mic_last_sequence = sequence
        self._mic_last_timestamp = timestamp
        self._mic_packet_count += 1
        if self._record_mic_wav is not None:
            self._mic_payloads.append(data[12:])
        if self._mic_audio_callback is not None:
            try:
                self._mic_audio_callback(data[12:])
            except Exception as exc:
                self.audit.write(
                    "mic_audio_callback_error", error=f"{type(exc).__name__}: {exc}"
                )
        if self._mic_packet_count >= self._mic_recording_max_packets:
            self.audit.write("mic_recording_limit_reached", packets=self._mic_packet_count)
            self.finish_mic_recording()

    def finish_mic_recording(self) -> None:
        if not self._mic_recording:
            return
        if self._mic_finalize_handle:
            self._mic_finalize_handle.cancel()
            self._mic_finalize_handle = None
        self._mic_recording = False
        self._mic_recording_complete = True
        self._mic_recording_complete_event.set()
        if self._record_mic_wav is None:
            self.audit.write(
                "mic_capture_completed",
                packets=self._mic_packet_count,
                duration_seconds=self._mic_packet_count * 0.02,
                first_sequence=self._mic_first_sequence,
                last_sequence=self._mic_last_sequence,
                sequence_errors=self._mic_sequence_errors,
                timestamp_errors=self._mic_timestamp_errors,
                withheld_packets=self._mic_rtp_withheld_packets,
            )
            self._mic_payloads.clear()
            return
        if self._record_mic_wav.exists():
            self.audit.write(
                "mic_recording_write_withheld",
                reason="output_already_exists",
                output=str(self._record_mic_wav),
            )
            return
        payload = b"".join(self._mic_payloads)
        write_wav(
            self._record_mic_wav,
            payload,
            codec="s16be",
            sample_rate=8000,
        )
        self.audit.write(
            "mic_recording_completed",
            output=str(self._record_mic_wav),
            packets=len(self._mic_payloads),
            samples=len(payload) // 2,
            duration_seconds=len(payload) / 16000.0,
            first_sequence=self._mic_first_sequence,
            last_sequence=self._mic_last_sequence,
            sequence_errors=self._mic_sequence_errors,
            timestamp_errors=self._mic_timestamp_errors,
        )

    def close(self) -> None:
        self.finish_mic_recording()


    async def send_tone(
        self, *, frequency_hz: float, level_dbfs: float, duration_seconds: float
    ) -> int:
        samples_per_packet = 160
        packet_count = math.ceil(duration_seconds / 0.02)
        payloads = generate_s16be_tone_payloads(
            frequency_hz=frequency_hz,
            level_dbfs=level_dbfs,
            packet_count=packet_count,
        )
        return await self._send_audio_payloads(
            payloads,
            source="tone",
            frequency_hz=frequency_hz,
            level_dbfs=level_dbfs,
            requested_duration_seconds=duration_seconds,
            source_samples=packet_count * samples_per_packet,
        )

    async def send_payloads(self, payloads: list[bytes], *, source: str) -> int:
        """Send already-composed 20 ms s16be payloads with verified RTP pacing."""

        return await self._send_audio_payloads(
            payloads,
            source=source,
            source_samples=len(payloads) * 160,
        )

    async def send_key_beep(self, profile_name: str, *, beep_level: int = 3) -> int:
        profile = get_key_beep_profile(profile_name, beep_level)
        payloads = generate_s16be_tone_payloads(
            frequency_hz=profile.frequency_hz,
            level_dbfs=profile.level_dbfs,
            packet_count=profile.packet_count,
        )
        return await self._send_audio_payloads(
            payloads,
            source="key_beep",
            profile=profile.name,
            beep_level=profile.beep_level,
            frequency_hz=profile.frequency_hz,
            level_dbfs=profile.level_dbfs,
            observed_rms_dbfs=profile.observed_rms_dbfs,
            requested_duration_seconds=profile.duration_seconds,
            source_samples=profile.packet_count * 160,
        )

    async def send_wav(self, path: str | Path) -> int:
        wav_path = Path(path)
        with wave.open(str(wav_path), "rb") as source:
            if source.getcomptype() != "NONE":
                raise ValueError("receive WAV must be uncompressed PCM")
            if source.getnchannels() != 1:
                raise ValueError("receive WAV must be mono")
            if source.getframerate() != 8000:
                raise ValueError("receive WAV must use an 8000 Hz sample rate")
            if source.getsampwidth() != 2:
                raise ValueError("receive WAV must use 16-bit samples")
            frame_count = source.getnframes()
            if frame_count < 160:
                raise ValueError("receive WAV must contain at least 0.02 seconds")
            if frame_count > 8000 * 30:
                raise ValueError("receive WAV must not exceed 30 seconds")
            little_endian = source.readframes(frame_count)
        big_endian = b"".join(
            struct.pack(">h", sample[0])
            for sample in struct.iter_unpack("<h", little_endian)
        )
        packet_bytes = 320
        payloads = [
            big_endian[offset : offset + packet_bytes].ljust(packet_bytes, b"\x00")
            for offset in range(0, len(big_endian), packet_bytes)
        ]
        return await self._send_audio_payloads(
            payloads,
            source="wav",
            wav=str(wav_path),
            requested_duration_seconds=frame_count / 8000.0,
            source_samples=frame_count,
        )

    async def _send_audio_payloads(
        self, payloads: list[bytes], *, source: str, **audit_fields: object
    ) -> int:
        if not self._peer_ready or self.transport is None:
            self.audit.write("rx_audio_withheld", reason="verified_udp_peer_not_ready")
            return 0

        sample_rate = 8000
        samples_per_packet = 160
        packet_interval = samples_per_packet / sample_rate
        packet_count = len(payloads)
        destination = (self.peer_ip, self.peer_port)
        deadline = time.perf_counter()
        first_send: float | None = None
        max_late_seconds = 0.0
        pacing_resyncs = 0
        self.audit.write(
            "rx_audio_started",
            source=source,
            codec="s16be",
            sample_rate=sample_rate,
            packet_count=packet_count,
            **audit_fields,
        )
        timer_resolution_active = False
        winmm = None
        mmcss_handle = None
        avrt = None
        if sys.platform == "win32":
            winmm = ctypes.WinDLL("winmm")
            timer_resolution_active = winmm.timeBeginPeriod(1) == 0
            self.audit.write(
                "rx_audio_timer_resolution",
                requested_ms=1,
                active=timer_resolution_active,
            )
            avrt = ctypes.WinDLL("avrt", use_last_error=True)
            avrt.AvSetMmThreadCharacteristicsW.argtypes = [
                ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            avrt.AvSetMmThreadCharacteristicsW.restype = ctypes.c_void_p
            avrt.AvRevertMmThreadCharacteristics.argtypes = [ctypes.c_void_p]
            avrt.AvRevertMmThreadCharacteristics.restype = ctypes.c_bool
            task_index = ctypes.c_uint32(0)
            mmcss_handle = avrt.AvSetMmThreadCharacteristicsW(
                "Pro Audio", ctypes.byref(task_index)
            )
            self.audit.write(
                "rx_audio_mmcss",
                task="Pro Audio",
                active=bool(mmcss_handle),
                error=None if mmcss_handle else ctypes.get_last_error(),
            )
        try:
            for packet_index, payload in enumerate(payloads):
                while deadline > time.perf_counter():
                    await asyncio.sleep(0)
                sent_at = time.perf_counter()
                if first_send is None:
                    first_send = sent_at
                max_late_seconds = max(max_late_seconds, sent_at - deadline)
                header = struct.pack(
                    "!BBHII",
                    0x80,
                    0x7D,
                    self._sequence,
                    self._timestamp,
                    RADIO_RTP_SSRC,
                )
                self.transport.sendto(header + payload, destination)
                self._sequence = (self._sequence + 1) & 0xFFFF
                self._timestamp = (self._timestamp + samples_per_packet) & 0xFFFFFFFF
                if packet_index + 1 < packet_count:
                    next_deadline = deadline + packet_interval
                    # Do not compress a late packet into a catch-up burst. Keep
                    # absolute phase for normal jitter, but rebase when less
                    # than 18 ms remains before the next 20 ms frame.
                    if next_deadline - sent_at < 0.018:
                        next_deadline = sent_at + packet_interval
                        pacing_resyncs += 1
                    deadline = next_deadline
        finally:
            if mmcss_handle and avrt is not None:
                avrt.AvRevertMmThreadCharacteristics(mmcss_handle)
                self.audit.write("rx_audio_mmcss_restored", task="Pro Audio")
            if timer_resolution_active and winmm is not None:
                winmm.timeEndPeriod(1)
                self.audit.write("rx_audio_timer_resolution_restored", requested_ms=1)
        self.audit.write(
            "rx_audio_completed",
            packet_count=packet_count,
            first_send_monotonic=first_send,
            max_late_ms=max_late_seconds * 1000.0,
            pacing_resyncs=pacing_resyncs,
        )
        return packet_count


class VerifiedMicUdpProtocol(asyncio.DatagramProtocol):
    """Verified CommandMic-side UDP bootstrap and gated radio-audio receiver."""

    def __init__(
        self,
        peer_ip: str,
        peer_port: int,
        audit: AuditLog,
        *,
        record_radio_wav: str | Path | None = None,
        radio_recording_max_seconds: float = 30.0,
        radio_audio_callback: Callable[[RadioAudioPacket], None] | None = None,
        radio_audio_gate_callback: Callable[[RadioAudioGateEvent], None] | None = None,
    ) -> None:
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.audit = audit
        self.transport: asyncio.DatagramTransport | None = None
        self._boot_sent = False
        self._radio_boot_verified = False
        self._record_radio_wav = (
            Path(record_radio_wav) if record_radio_wav is not None else None
        )
        self._radio_audio_callback = radio_audio_callback
        self._radio_audio_gate_callback = radio_audio_gate_callback
        self._radio_recording_max_packets = max(
            1, round(radio_recording_max_seconds / 0.02)
        )
        self._radio_audio_gate_open = False
        self._radio_recording_complete = False
        self._radio_payloads: list[bytes] = []
        self._radio_gate_sessions = 0
        self._radio_gate_packet_start = 0
        self._radio_total_packets = 0
        self._radio_first_sequence: int | None = None
        self._radio_last_sequence: int | None = None
        self._radio_last_timestamp: int | None = None
        self._radio_sequence_errors = 0
        self._radio_timestamp_errors = 0
        self._radio_withheld_packets = 0
        _, _, boot_sequence, boot_timestamp, _ = struct.unpack(
            "!BBHII", MIC_BOOT_RTP[:12]
        )
        self._mic_tx_sequence = (boot_sequence + 1) & 0xFFFF
        self._mic_tx_timestamp = (boot_timestamp + 160) & 0xFFFFFFFF

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def send_boot(self) -> bool:
        if self.transport is None:
            self.audit.write("mic_udp_boot_withheld", reason="transport_unavailable")
            return False
        destination = (self.peer_ip, self.peer_port)
        self.transport.sendto(MIC_BOOT_RTP, destination)
        self._boot_sent = True
        self.audit.write(
            "mic_udp_boot_sent",
            peer=destination,
            length=len(MIC_BOOT_RTP),
        )
        return True

    async def send_transmit_payloads(
        self,
        payloads: list[bytes],
        *,
        source: str,
        first_packet_deadline: float | None = None,
        **audit_fields: object,
    ) -> int:
        """Send verified mic-to-radio RTP on an absolute 20 ms timeline."""

        if not payloads or any(len(payload) != 320 for payload in payloads):
            raise ValueError("TX requires one or more exact 320-byte payloads")
        return await self._send_transmit_stream(
            packet_count=len(payloads),
            payload_at=payloads.__getitem__,
            source=source,
            first_packet_deadline=first_packet_deadline,
            **audit_fields,
        )

    async def send_live_transmit(
        self,
        microphone: MicrophoneAudioSource,
        *,
        packet_count: int,
        source: str = "live_microphone",
        first_packet_deadline: float | None = None,
        **audit_fields: object,
    ) -> int:
        """Send the newest prewarmed microphone frame at each 20 ms deadline."""

        if packet_count < 1:
            raise ValueError("live TX packet_count must be positive")
        try:
            return await self._send_transmit_stream(
                packet_count=packet_count,
                payload_at=lambda _: microphone.latest_payload(),
                source=source,
                first_packet_deadline=first_packet_deadline,
                **audit_fields,
            )
        finally:
            self.audit.write(
                "mic_live_capture_stats",
                stats=asdict(microphone.stats),
            )

    async def send_live_transmit_until(
        self,
        microphone: MicrophoneAudioSource,
        stop_event: asyncio.Event,
        *,
        first_packet_deadline: float | None = None,
        release_tail_packets: int = 11,
        **audit_fields: object,
    ) -> int:
        """Stream the newest live frame until PTT release, then send its RTP tail.

        The source is sampled only at each 20 ms wire deadline. Its bounded
        latest-frame queue therefore cannot accumulate stale microphone audio.
        """

        if release_tail_packets < 0 or release_tail_packets > 25:
            raise ValueError("release_tail_packets must be between 0 and 25")
        if not self._radio_boot_verified or self.transport is None:
            raise RuntimeError("verified radio UDP peer is not ready for TX")

        deadline = (
            time.perf_counter()
            if first_packet_deadline is None
            else first_packet_deadline
        )
        destination = (self.peer_ip, self.peer_port)
        timer_resolution_active = False
        winmm = None
        if sys.platform == "win32":
            winmm = ctypes.WinDLL("winmm")
            timer_resolution_active = winmm.timeBeginPeriod(1) == 0
        packet_count = 0
        tail_remaining: int | None = None
        first_send: float | None = None
        max_late_seconds = 0.0
        pacing_resyncs = 0
        self.audit.write(
            "mic_tx_audio_started",
            source="interactive_live_microphone",
            codec="s16be",
            sample_rate=8000,
            release_tail_packets=release_tail_packets,
            **audit_fields,
        )
        try:
            while True:
                while deadline > time.perf_counter():
                    await asyncio.sleep(0)
                sent_at = time.perf_counter()
                payload = microphone.latest_payload()
                if len(payload) != 320:
                    raise ValueError("TX source returned a non-320-byte payload")
                if first_send is None:
                    first_send = sent_at
                max_late_seconds = max(max_late_seconds, sent_at - deadline)
                header = struct.pack(
                    "!BBHII",
                    0x80,
                    0x7D,
                    self._mic_tx_sequence,
                    self._mic_tx_timestamp,
                    MIC_RTP_SSRC,
                )
                self.transport.sendto(header + payload, destination)
                self._mic_tx_sequence = (self._mic_tx_sequence + 1) & 0xFFFF
                self._mic_tx_timestamp = (self._mic_tx_timestamp + 160) & 0xFFFFFFFF
                packet_count += 1

                if tail_remaining is None and stop_event.is_set():
                    tail_remaining = release_tail_packets
                if tail_remaining is not None:
                    if tail_remaining == 0:
                        break
                    tail_remaining -= 1

                next_deadline = deadline + 0.020
                if next_deadline - sent_at < 0.018:
                    next_deadline = sent_at + 0.020
                    pacing_resyncs += 1
                deadline = next_deadline
        finally:
            if timer_resolution_active and winmm is not None:
                winmm.timeEndPeriod(1)
            self.audit.write(
                "mic_live_capture_stats", stats=asdict(microphone.stats)
            )
        self.audit.write(
            "mic_tx_audio_completed",
            source="interactive_live_microphone",
            packet_count=packet_count,
            first_send_monotonic=first_send,
            max_late_ms=max_late_seconds * 1000.0,
            pacing_resyncs=pacing_resyncs,
        )
        return packet_count

    async def _send_transmit_stream(
        self,
        *,
        packet_count: int,
        payload_at: Callable[[int], bytes],
        source: str,
        first_packet_deadline: float | None,
        **audit_fields: object,
    ) -> int:
        if not self._radio_boot_verified or self.transport is None:
            raise RuntimeError("verified radio UDP peer is not ready for TX")
        deadline = (
            time.perf_counter()
            if first_packet_deadline is None
            else first_packet_deadline
        )
        destination = (self.peer_ip, self.peer_port)
        timer_resolution_active = False
        winmm = None
        if sys.platform == "win32":
            winmm = ctypes.WinDLL("winmm")
            timer_resolution_active = winmm.timeBeginPeriod(1) == 0
        first_send: float | None = None
        max_late_seconds = 0.0
        pacing_resyncs = 0
        self.audit.write(
            "mic_tx_audio_started",
            source=source,
            codec="s16be",
            sample_rate=8000,
            packet_count=packet_count,
            **audit_fields,
        )
        try:
            for packet_index in range(packet_count):
                while deadline > time.perf_counter():
                    await asyncio.sleep(0)
                sent_at = time.perf_counter()
                payload = payload_at(packet_index)
                if len(payload) != 320:
                    raise ValueError("TX source returned a non-320-byte payload")
                if first_send is None:
                    first_send = sent_at
                max_late_seconds = max(max_late_seconds, sent_at - deadline)
                header = struct.pack(
                    "!BBHII",
                    0x80,
                    0x7D,
                    self._mic_tx_sequence,
                    self._mic_tx_timestamp,
                    MIC_RTP_SSRC,
                )
                self.transport.sendto(header + payload, destination)
                self._mic_tx_sequence = (self._mic_tx_sequence + 1) & 0xFFFF
                self._mic_tx_timestamp = (self._mic_tx_timestamp + 160) & 0xFFFFFFFF
                if packet_index + 1 < packet_count:
                    next_deadline = deadline + 0.020
                    # Never compress a late packet into a catch-up burst. Keep
                    # the absolute phase for normal jitter, but reset it when
                    # less than 18 ms would remain before the next frame.
                    if next_deadline - sent_at < 0.018:
                        next_deadline = sent_at + 0.020
                        pacing_resyncs += 1
                    deadline = next_deadline
        finally:
            if timer_resolution_active and winmm is not None:
                winmm.timeEndPeriod(1)
        self.audit.write(
            "mic_tx_audio_completed",
            packet_count=packet_count,
            first_send_monotonic=first_send,
            max_late_ms=max_late_seconds * 1000.0,
            pacing_resyncs=pacing_resyncs,
        )
        return packet_count

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.audit.write("mic_udp_received", peer=addr, length=len(data))
        valid_radio_boot = (
            self._boot_sent
            and addr == (self.peer_ip, self.peer_port)
            and data == RADIO_BOOT_RTP
        )
        if valid_radio_boot:
            self._radio_boot_verified = True
            self.audit.write("mic_udp_radio_boot_verified", peer=addr)
            return

        valid_radio_rtp = (
            self._radio_boot_verified
            and addr == (self.peer_ip, self.peer_port)
            and len(data) == 332
            and data[0] == 0x80
            and (data[1] & 0x7F) == 0x7D
        )
        if not valid_radio_rtp:
            self.audit.write(
                "mic_udp_payload_withheld", reason="unverified_peer_or_rtp_shape"
            )
            return
        if self._record_radio_wav is None and self._radio_audio_callback is None:
            self.audit.write(
                "mic_udp_payload_withheld", reason="radio_audio_sink_not_configured"
            )
            return
        if not self._radio_audio_gate_open or self._radio_recording_complete:
            self._radio_withheld_packets += 1
            if self._radio_withheld_packets == 1:
                self.audit.write(
                    "mic_udp_payload_withheld", reason="radio_audio_gate_not_open"
                )
            return
        self._record_radio_rtp(data)

    def set_radio_audio_gate(self, open_: bool) -> None:
        """Apply the verified radio-to-mic 01/04 receive-audio gate."""

        if open_:
            if (
                self._record_radio_wav is None
                and self._radio_audio_callback is None
            ) or self._radio_recording_complete:
                self.audit.write(
                    "radio_audio_gate_ignored",
                    reason=(
                        "sink_not_configured"
                        if self._record_radio_wav is None
                        and self._radio_audio_callback is None
                        else "capture_complete"
                    ),
                )
                return
            self._radio_audio_gate_open = True
            self._radio_gate_sessions += 1
            self._radio_gate_packet_start = self._radio_total_packets
            self._radio_last_sequence = None
            self._radio_last_timestamp = None
            self._radio_withheld_packets = 0
            self.audit.write(
                "radio_audio_gate_opened",
                session=self._radio_gate_sessions,
                output=(str(self._record_radio_wav) if self._record_radio_wav else None),
            )
            self._notify_radio_gate(True, 0)
            return

        if not self._radio_audio_gate_open:
            return
        self._radio_audio_gate_open = False
        self.audit.write(
            "radio_audio_gate_closed",
            session=self._radio_gate_sessions,
            packets=(self._radio_total_packets - self._radio_gate_packet_start),
            total_packets=self._radio_total_packets,
        )
        self._notify_radio_gate(
            False, self._radio_total_packets - self._radio_gate_packet_start
        )

    def _notify_radio_gate(self, open_: bool, packet_count: int) -> None:
        if self._radio_audio_gate_callback is None:
            return
        event = RadioAudioGateEvent(
            session=self._radio_gate_sessions,
            open=open_,
            packet_count=packet_count,
        )
        try:
            self._radio_audio_gate_callback(event)
        except Exception as exc:
            self.audit.write(
                "radio_audio_gate_callback_error",
                session=event.session,
                open=event.open,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _record_radio_rtp(self, data: bytes) -> None:
        _, _, sequence, timestamp, ssrc = struct.unpack("!BBHII", data[:12])
        if ssrc != RADIO_RTP_SSRC:
            self.audit.write(
                "mic_udp_payload_withheld",
                reason="unexpected_radio_ssrc",
                ssrc=f"{ssrc:08x}",
            )
            return
        if self._radio_last_sequence is not None:
            if sequence != ((self._radio_last_sequence + 1) & 0xFFFF):
                self._radio_sequence_errors += 1
            if timestamp != ((self._radio_last_timestamp + 160) & 0xFFFFFFFF):
                self._radio_timestamp_errors += 1
        elif self._radio_first_sequence is None:
            self._radio_first_sequence = sequence
        self._radio_last_sequence = sequence
        self._radio_last_timestamp = timestamp
        payload = data[12:]
        self._radio_total_packets += 1
        if self._record_radio_wav is not None:
            self._radio_payloads.append(payload)
        if self._radio_audio_callback is not None:
            packet = RadioAudioPacket(
                session=self._radio_gate_sessions,
                sequence=sequence,
                timestamp=timestamp,
                ssrc=ssrc,
                payload_s16be=payload,
            )
            try:
                self._radio_audio_callback(packet)
            except Exception as exc:
                self.audit.write(
                    "radio_audio_callback_error",
                    session=packet.session,
                    sequence=packet.sequence,
                    error=f"{type(exc).__name__}: {exc}",
                )
        if (
            self._record_radio_wav is not None
            and len(self._radio_payloads) >= self._radio_recording_max_packets
        ):
            self.audit.write(
                "radio_audio_recording_limit_reached",
                packets=len(self._radio_payloads),
            )
            self.finish_radio_recording()

    def finish_radio_recording(self) -> None:
        if self._record_radio_wav is None or self._radio_recording_complete:
            return
        self._radio_audio_gate_open = False
        self._radio_recording_complete = True
        if self._record_radio_wav.exists():
            self.audit.write(
                "radio_audio_recording_write_withheld",
                reason="output_already_exists",
                output=str(self._record_radio_wav),
            )
            return
        payload = b"".join(self._radio_payloads)
        write_wav(
            self._record_radio_wav,
            payload,
            codec="s16be",
            sample_rate=8000,
        )
        self.audit.write(
            "radio_audio_recording_completed",
            output=str(self._record_radio_wav),
            gate_sessions=self._radio_gate_sessions,
            packets=len(self._radio_payloads),
            samples=len(payload) // 2,
            duration_seconds=len(payload) / 16000.0,
            first_sequence=self._radio_first_sequence,
            last_sequence=self._radio_last_sequence,
            sequence_errors=self._radio_sequence_errors,
            timestamp_errors=self._radio_timestamp_errors,
        )

    def close(self) -> None:
        self.finish_radio_recording()


async def run_emulator(config: EmulatorConfig, audit_path: str | Path | None = None) -> None:
    audit = AuditLog(audit_path)
    udp_transport: asyncio.DatagramTransport | None = None
    udp_protocol: VerifiedRadioUdpProtocol | VerifiedMicUdpProtocol | None = None
    audio_sink: FfplayRadioAudioSink | None = None
    microphone_source: FfmpegMicrophoneSource | None = None
    playback_error: Exception | None = None
    try:
        if config.tx_live_device:
            microphone_source = FfmpegMicrophoneSource(
                config.tx_live_device,
                queue_packets=config.tx_capture_queue_packets,
                device_buffer_ms=config.tx_device_buffer_ms,
            )
            await microphone_source.start()
            audit.write(
                "mic_live_capture_started",
                device=config.tx_live_device,
                device_buffer_ms=config.tx_device_buffer_ms,
                queue_packets=config.tx_capture_queue_packets,
            )
        if config.verified_startup:
            loop = asyncio.get_running_loop()
            if config.role == "radio":
                protocol = VerifiedRadioUdpProtocol(
                    config.peer_ip,
                    config.voice_port,
                    audit,
                    record_mic_wav=config.record_mic_wav,
                    mic_recording_max_seconds=config.mic_recording_max_seconds,
                )
            else:
                if config.play_radio_audio:
                    audio_sink = FfplayRadioAudioSink(
                        prebuffer_packets=config.radio_jitter_packets
                    )
                    audio_sink.start()
                    audit.write(
                        "radio_audio_playback_started",
                        backend="ffplay",
                        prebuffer_packets=config.radio_jitter_packets,
                    )
                protocol = VerifiedMicUdpProtocol(
                    config.peer_ip,
                    config.voice_port,
                    audit,
                    record_radio_wav=config.record_radio_wav,
                    radio_recording_max_seconds=config.radio_recording_max_seconds,
                    radio_audio_callback=(audio_sink.on_packet if audio_sink else None),
                    radio_audio_gate_callback=(audio_sink.on_gate if audio_sink else None),
                )
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=(config.local_ip, config.voice_port),
            )
            udp_transport = transport  # type: ignore[assignment]
            udp_protocol = protocol
            audit.write("udp_listening", address=(config.local_ip, config.voice_port))
        await CommandMicEmulator(
            config,
            audit,
            udp_protocol,
            mic_audio_source=microphone_source,
        ).run()
    finally:
        if udp_protocol:
            udp_protocol.close()
        if udp_transport:
            udp_transport.close()
        if audio_sink:
            try:
                audio_sink.close()
                audit.write(
                    "radio_audio_playback_stopped",
                    stats=asdict(audio_sink.jitter.stats),
                    backend_queue_drops=audio_sink.backend_queue_drops,
                )
            except Exception as exc:
                audit.write(
                    "radio_audio_playback_error",
                    error=f"{type(exc).__name__}: {exc}",
                )
                playback_error = exc
        if microphone_source:
            stats = asdict(microphone_source.stats)
            await microphone_source.close()
            audit.write("mic_live_capture_stopped", stats=stats)
        audit.close()
        if playback_error is not None and sys.exc_info()[0] is None:
            raise RuntimeError("radio audio playback failed") from playback_error
