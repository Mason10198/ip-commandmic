from __future__ import annotations

import argparse
import asyncio
import copy
import math
import struct
import threading
import time
import wave
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from .audio import load_s16be_audio_file_payloads, load_s16be_wav_payloads
from .display import DisplayBuffer, verified_display_bit_controls
from .emulator import AuditLog, CommandMicEmulator, EmulatorConfig, VerifiedRadioUdpProtocol


def _asset_text(name: str) -> str:
    return files("ip_commandmic").joinpath("assets", "test_app", name).read_text(encoding="utf-8")


def build_test_html() -> str:
    display = files("ip_commandmic").joinpath(
        "assets", "desktop", "mic_display_vector.svg"
    ).read_text(encoding="utf-8")
    if display.startswith("<?xml"):
        display = display.split("?>", 1)[1].lstrip()
    return _asset_text("index.html").replace("__DISPLAY_SVG__", display)


@dataclass(slots=True)
class SoftwareRadioConfig:
    __test__ = False
    local_ip: str = "192.168.0.1"
    mic_ip: str = "192.168.0.2"
    control_port: int = 52001
    control_peer_ip: str | None = None
    control_source_port: int | None = None
    audio_port: int = 50000
    audio_peer_ip: str | None = None
    mic_gain: int = 3
    backlight: str = "on"
    automatic_key_responses: bool = False
    automatic_ptt_responses: bool = False
    startup_opening_text: str = ""
    startup_idle_text: str = ""
    startup_status_carousel: bool = False
    speaker_volume: int = 22
    handle_volume_keys: bool = False
    idle_display_text: str = ""


class EndpointState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._data: dict[str, Any] = {
            "connection": "disconnected",
            "session": None,
            "controls_ready": False,
            "buttons": {},
            "ptt": False,
            "audio_peak": 0.0,
            "audio_rms": 0.0,
            "waveform": [],
            "audio_packets": 0,
            "mic_capture_count": 0,
            "last_mic_capture": None,
            "recording": False,
            "recorded_packets": 0,
            "speaker_volume": 22,
            "mic_gain": 3,
            "parrot_enabled": False,
            "parrot_status": "disabled",
            "parrot_packets": 0,
            "last_error": None,
            "events": [],
        }

    def update(self, **values: Any) -> None:
        with self._lock:
            self._data.update(values)
            self._revision += 1

    def event(self, event: str, **data: Any) -> None:
        with self._lock:
            events = self._data["events"]
            events.append({"time": time.time(), "event": event, **data})
            del events[:-200]
            self._revision += 1

    def snapshot(self, *, include_events: bool = True) -> dict[str, Any]:
        with self._lock:
            snapshot = {"revision": self._revision, **self._data}
            snapshot["buttons"] = dict(self._data["buttons"])
            snapshot["waveform"] = list(self._data["waveform"])
            snapshot["last_mic_capture"] = copy.deepcopy(
                self._data["last_mic_capture"]
            )
            snapshot["events"] = (
                copy.deepcopy(self._data["events"]) if include_events else []
            )
            return snapshot


class SoftwareRadioEndpoint:
    """High-level radio-side endpoint for physical or software CommandMics.

    Protocol work runs on a private asyncio thread. Applications consume
    snapshots and invoke typed display, LED, audio, raw-frame, and recording
    operations without constructing startup, heartbeat, RTP, or PTT messages.
    """

    def __init__(self, config: SoftwareRadioConfig, audit_path: Path) -> None:
        self.config = config
        self.audit_path = audit_path
        self.state = EndpointState()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._emulator: CommandMicEmulator | None = None
        self._protocol: VerifiedRadioUdpProtocol | None = None
        self._record_lock = threading.RLock()
        self._recording = False
        self._record_writer: wave.Wave_write | None = None
        self._record_path: Path | None = None
        self._recorded_packets = 0
        self._media_lock = threading.RLock()
        self._speaker_volume = self._validate_speaker_volume(config.speaker_volume)
        self._idle_display_text = self._validate_display_text(config.idle_display_text)
        self._last_display = self._text_only_display(self._idle_display_text)
        self._parrot_display: DisplayBuffer | None = None
        self._volume_overlay_task: asyncio.Task[None] | None = None
        self._parrot_enabled = False
        self._parrot_capturing = False
        self._parrot_payloads: list[bytes] = []
        self._parrot_task: asyncio.Task[None] | None = None
        self._parrot_max_packets = 1500
        self._mic_gain = self._validate_mic_gain(config.mic_gain)
        self.state.update(speaker_volume=self._speaker_volume, mic_gain=self._mic_gain)

    @staticmethod
    def _validate_mic_gain(level: int) -> int:
        value = int(level)
        if value not in (1, 2, 3, 4, 5):
            raise ValueError("microphone gain must be one of the observed values: 1 through 5")
        return value

    @staticmethod
    def _validate_speaker_volume(level: int) -> int:
        value = int(level)
        if not 0 <= value <= 32:
            raise ValueError("speaker volume must be between 0 and 32")
        return value

    @staticmethod
    def _validate_display_text(text: str) -> str:
        value = str(text).upper()
        if len(value) > 8:
            raise ValueError("idle display text must contain at most 8 characters")
        return value

    @staticmethod
    def _text_only_display(text: str) -> DisplayBuffer:
        """Compose text without the capture-derived LOW/RSSI baseline icons."""

        encoded = str(text).upper().encode("ascii", errors="replace")[:8]
        return DisplayBuffer(encoded.ljust(8, b"\x00") + bytes(60))

    @staticmethod
    def speaker_volume_gain(level: int) -> float:
        """Map the verified 0-32 UI range onto app-side PCM attenuation.

        Zero is mute and 32 is unity. Nonzero levels span an approximately
        perceptually uniform 48 dB range. This is the closest evidence-bounded
        application approximation until the radio's acoustic curve is measured.
        """

        value = SoftwareRadioEndpoint._validate_speaker_volume(level)
        if value == 0:
            return 0.0
        attenuation_db = (value - 32) * (48.0 / 31.0)
        return 10.0 ** (attenuation_db / 20.0)

    @staticmethod
    def _normalize_parrot_payloads(payloads: list[bytes]) -> list[bytes]:
        """Lift quiet microphone PCM to a useful replay level without clipping."""

        peak = max(
            (abs(sample[0]) for payload in payloads for sample in struct.iter_unpack(">h", payload)),
            default=0,
        )
        if peak == 0:
            return list(payloads)
        target_peak = round(32767 * (10.0 ** (-9.0 / 20.0)))
        gain = min(10.0 ** (24.0 / 20.0), max(1.0, target_peak / peak))
        if gain == 1.0:
            return list(payloads)
        normalized: list[bytes] = []
        for payload in payloads:
            normalized.append(
                b"".join(
                    struct.pack(">h", max(-32768, min(32767, round(sample[0] * gain))))
                    for sample in struct.iter_unpack(">h", payload)
                )
            )
        return normalized

    @classmethod
    def _scale_payloads(cls, payloads: list[bytes], level: int) -> list[bytes]:
        gain = cls.speaker_volume_gain(level)
        if gain == 0.0:
            return []
        if gain == 1.0:
            return list(payloads)
        scaled: list[bytes] = []
        for payload in payloads:
            samples = (
                max(-32768, min(32767, round(sample[0] * gain)))
                for sample in struct.iter_unpack(">h", payload)
            )
            scaled.append(b"".join(struct.pack(">h", sample) for sample in samples))
        return scaled

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="commandmic-test-protocol")
        self._thread.start()
        if not self._started.wait(10):
            raise RuntimeError("test protocol runtime did not start")

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._run())
        self._started.set()
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.state.update(connection="error", controls_ready=False, last_error=f"{type(exc).__name__}: {exc}")
        finally:
            pending = tuple(asyncio.all_tasks(self._loop))
            for task in pending:
                task.cancel()
            if pending:
                _, still_pending = self._loop.run_until_complete(
                    asyncio.wait(pending, timeout=1.0)
                )
                if still_pending:
                    LOGGER.warning(
                        "test protocol runtime forced bounded shutdown with %d pending task(s)",
                        len(still_pending),
                    )
            self._loop.close()

    def _on_audit(self, record: dict[str, object]) -> None:
        event = str(record.get("event", "event"))
        self.state.event(event, data={k: v for k, v in record.items() if k != "event"})
        if event == "connected":
            self.state.update(connection="negotiating", last_error=None)
        elif event == "verified_session":
            self.state.update(session=record.get("session_kind"))
        elif event == "startup_complete":
            self.state.update(connection="connected", controls_ready=True)
        elif event == "disconnected":
            self._discard_transient_media()
            self.state.update(connection="reconnecting", controls_ready=False, buttons={}, ptt=False)
        elif event == "connection_failed":
            self._discard_transient_media()
            self.state.update(connection="reconnecting", controls_ready=False, last_error=record.get("error"))
        elif event == "mic_capture_completed":
            snapshot = self.state.snapshot(include_events=False)
            self.state.update(
                mic_capture_count=int(snapshot["mic_capture_count"]) + 1,
                last_mic_capture={
                    key: value for key, value in record.items() if key != "event"
                },
            )
        elif event == "received":
            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                return
            kind = record.get("kind")
            if kind == "key_state":
                button = metadata.get("key_button")
                action = metadata.get("key_action")
                if button:
                    buttons = dict(self.state.snapshot(include_events=False)["buttons"])
                    buttons[str(button)] = action == "press"
                    self.state.update(buttons=buttons)
                    if (
                        self.config.handle_volume_keys
                        and action == "press"
                        and button in {"volume_up", "volume_down"}
                    ):
                        delta = 1 if button == "volume_up" else -1
                        level = self.adjust_speaker_volume(delta)
                        self._schedule_volume_overlay(level)
            elif kind == "ptt_state":
                active = bool(metadata.get("ptt_active"))
                self.state.update(
                    ptt=active,
                    **({} if active else {"audio_peak": 0.0, "audio_rms": 0.0, "waveform": []}),
                )
                if active:
                    self._begin_parrot_capture()
                else:
                    self._schedule_parrot_playback()
            elif kind == "power_state":
                buttons = dict(self.state.snapshot(include_events=False)["buttons"])
                buttons["power"] = bool(metadata.get("power_active"))
                self.state.update(buttons=buttons)

    def _on_audio(self, payload: bytes) -> None:
        samples = [value[0] for value in struct.iter_unpack(">h", payload)]
        peak = max((abs(value) for value in samples), default=0) / 32768.0
        rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples))) / 32768.0
        # Preserve the full 20 ms / 160-sample 8 kHz frame. Consumers may
        # decimate it for a time-domain trace, while spectrum renderers retain
        # the complete 0–4 kHz Nyquist bandwidth.
        waveform = [round(value / 32768.0, 4) for value in samples]
        snapshot = self.state.snapshot(include_events=False)
        self.state.update(
            audio_peak=peak,
            audio_rms=rms,
            waveform=waveform,
            audio_packets=int(snapshot["audio_packets"]) + 1,
        )
        with self._record_lock:
            if self._recording:
                assert self._record_writer is not None
                little_endian = b"".join(
                    struct.pack("<h", value[0]) for value in struct.iter_unpack(">h", payload)
                )
                self._record_writer.writeframesraw(little_endian)
                self._recorded_packets += 1
                self.state.update(recorded_packets=self._recorded_packets)
        with self._media_lock:
            if self._parrot_enabled and self._parrot_capturing:
                if len(self._parrot_payloads) < self._parrot_max_packets:
                    self._parrot_payloads.append(bytes(payload))
                    self.state.update(parrot_packets=len(self._parrot_payloads))

    async def _run(self) -> None:
        audit = AuditLog(self.audit_path, self._on_audit)
        transport: asyncio.DatagramTransport | None = None
        try:
            protocol = VerifiedRadioUdpProtocol(
                self.config.audio_peer_ip or self.config.mic_ip,
                self.config.audio_port,
                audit,
                mic_recording_max_seconds=3600.0,
                mic_audio_callback=self._on_audio,
            )
            self._protocol = protocol
            loop = asyncio.get_running_loop()
            udp, _ = await loop.create_datagram_endpoint(
                lambda: protocol, local_addr=(self.config.local_ip, self.config.audio_port)
            )
            transport = udp  # type: ignore[assignment]
            config = EmulatorConfig(
                role="radio",
                local_ip=self.config.local_ip,
                peer_ip=self.config.control_peer_ip or self.config.mic_ip,
                port=self.config.control_port,
                source_port=self.config.control_source_port,
                verified_startup=True,
                voice_port=self.config.audio_port,
                mic_gain=self.config.mic_gain,
                backlight_state=self.config.backlight,
                startup_opening_text=self.config.startup_opening_text,
                startup_idle_text=self.config.startup_idle_text,
                startup_status_carousel=self.config.startup_status_carousel,
                automatic_key_responses=self.config.automatic_key_responses,
                automatic_ptt_responses=self.config.automatic_ptt_responses,
                read_timeout=10.0,
            )
            emulator = CommandMicEmulator(config, audit, protocol)
            self._emulator = emulator
            self.state.update(connection="connecting")
            await emulator.run()
        finally:
            self._emulator = None
            self._protocol = None
            if transport:
                transport.close()
            audit.close()
            self.state.update(connection="disconnected", controls_ready=False, buttons={}, ptt=False)

    def set_speaker_volume(self, level: int) -> int:
        value = self._validate_speaker_volume(level)
        with self._media_lock:
            self._speaker_volume = value
        self.state.update(speaker_volume=value)
        return value

    def set_mic_gain(self, level: int) -> int:
        value = self._validate_mic_gain(level)
        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        self._run_action(emulator.send_interactive_mic_gain(value))
        self._mic_gain = value
        self.config.mic_gain = value
        self.state.update(mic_gain=value)
        return value

    def adjust_speaker_volume(self, delta: int) -> int:
        with self._media_lock:
            target = max(0, min(32, self._speaker_volume + int(delta)))
        return self.set_speaker_volume(target)

    def set_idle_display_text(self, text: str, *, send: bool = False) -> str:
        value = self._validate_display_text(text)
        with self._media_lock:
            self._idle_display_text = value
        if send:
            self.send_display(self._text_only_display(value))
        return value

    def set_parrot_enabled(
        self, enabled: bool, *, mode_display: DisplayBuffer | bytes | None = None
    ) -> bool:
        active = bool(enabled)
        display_to_send: DisplayBuffer | None = None
        with self._media_lock:
            self._parrot_enabled = active
            self._parrot_capturing = False
            self._parrot_payloads = []
            task = self._parrot_task
            if active and mode_display is not None:
                self._parrot_display = (
                    mode_display
                    if isinstance(mode_display, DisplayBuffer)
                    else DisplayBuffer(mode_display)
                )
                display_to_send = self._parrot_display
            elif not active:
                self._parrot_display = None
                display_to_send = self._last_display
        if (
            self._loop is not None
            and not self._loop.is_closed()
            and task is not None
            and not task.done()
        ):
            self._loop.call_soon_threadsafe(task.cancel)
        self.state.update(
            parrot_enabled=active,
            parrot_status="ready" if active else "disabled",
            parrot_packets=0,
        )
        if display_to_send is not None and self._emulator is not None:
            self._run_action(self._emulator.send_interactive_display(display_to_send))
        return active

    def _discard_transient_media(self) -> None:
        with self._media_lock:
            self._parrot_capturing = False
            self._parrot_payloads = []
            parrot_task = self._parrot_task
            volume_task = self._volume_overlay_task
            status = "ready" if self._parrot_enabled else "disabled"
        for task in (parrot_task, volume_task):
            if task is not None and not task.done():
                task.cancel()
        self.state.update(parrot_status=status, parrot_packets=0)

    def _begin_parrot_capture(self) -> None:
        with self._media_lock:
            if not self._parrot_enabled:
                return
            if self._parrot_task is not None and not self._parrot_task.done():
                self._parrot_task.cancel()
            self._parrot_payloads = []
            self._parrot_capturing = True
        self.state.update(parrot_status="recording", parrot_packets=0)

    def _schedule_parrot_playback(self) -> None:
        with self._media_lock:
            if not self._parrot_enabled or not self._parrot_capturing:
                return

        async def replay() -> None:
            try:
                # Wait for the capture-owned 350 ms RTP tail to finish. The first
                # hardware run proved that a fixed 225 ms delay can race the
                # asynchronous TX-close frame and immediately close the newly
                # opened speaker path.
                protocol = self._protocol
                if protocol is None:
                    raise RuntimeError("CommandMic audio transport disconnected")
                await asyncio.wait_for(protocol.wait_mic_recording_complete(), timeout=1.0)
                with self._media_lock:
                    self._parrot_capturing = False
                    payloads = list(self._parrot_payloads)
                    level = self._speaker_volume
                scaled = self._scale_payloads(self._normalize_parrot_payloads(payloads), level)
                if not scaled:
                    self.state.update(parrot_status="ready")
                    return
                emulator = self._emulator
                if emulator is None:
                    raise RuntimeError("CommandMic disconnected before parrot playback")
                self.state.update(parrot_status="playing")
                await emulator.send_interactive_audio_payloads(scaled, source="parrot")
                self.state.update(parrot_status="ready")
            except asyncio.CancelledError:
                self.state.update(
                    parrot_status="ready" if self._parrot_enabled else "disabled"
                )
                raise
            except Exception as exc:
                self.state.update(
                    parrot_status="error", last_error=f"{type(exc).__name__}: {exc}"
                )

        self._parrot_task = asyncio.create_task(replay())

    def _schedule_volume_overlay(self, level: int) -> None:
        async def show() -> None:
            emulator = self._emulator
            if emulator is None:
                return
            await emulator.send_interactive_display(self._text_only_display(f" VOL {level:>2}"))
            await asyncio.sleep(1.0)
            with self._media_lock:
                restore = self._parrot_display or self._last_display
            await emulator.send_interactive_display(restore)

        if self._volume_overlay_task is not None and not self._volume_overlay_task.done():
            self._volume_overlay_task.cancel()
        self._volume_overlay_task = asyncio.create_task(show())

    def stop(self) -> None:
        try:
            self.set_parrot_enabled(False)
        except RuntimeError:
            # Shutdown must remain idempotent after the peer has already torn
            # down the control session. Parrot state is cleared before its
            # optional display restore is attempted, so there is nothing left
            # to recover through a disconnected writer.
            pass
        with self._record_lock:
            if self._recording and self._record_writer is not None:
                self._recording = False
                self._record_writer.close()
                self._record_writer = None
                self._record_path = None
                self.state.update(recording=False, recorded_packets=0)
        if (
            self._loop is not None
            and not self._loop.is_closed()
            and self._task is not None
            and not self._task.done()
        ):
            self._loop.call_soon_threadsafe(self._task.cancel)
        if self._thread:
            self._thread.join(20)
            if self._thread.is_alive():
                raise RuntimeError("test protocol runtime did not stop within 20 seconds")
        self._thread = None
        self._loop = None
        self._task = None
        self._started.clear()

    def _run_action(self, coroutine: Any, timeout: float = 35.0) -> Any:
        if self._loop is None or self._task is None or self._task.done():
            raise RuntimeError("test protocol runtime is not running")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout)

    @staticmethod
    def _audio_action_timeout(duration_seconds: float) -> float:
        """Allow a paced media operation to finish plus bounded control overhead."""

        duration = float(duration_seconds)
        if not math.isfinite(duration) or duration <= 0.0:
            return 35.0
        return max(35.0, duration + 10.0)

    def send_display(self, display: DisplayBuffer | bytes) -> None:
        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        model = display if isinstance(display, DisplayBuffer) else DisplayBuffer(display)
        with self._media_lock:
            self._last_display = model
            parrot_display = self._parrot_display
        if parrot_display is not None:
            return
        self._run_action(emulator.send_interactive_display(model))

    def send_led(self, color: str) -> None:
        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        self._run_action(emulator.send_interactive_status_led(color))

    def send_backlight(self, state: str) -> None:
        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        self._run_action(emulator.send_interactive_backlight(state))

    def send_raw(self, frame: bytes) -> None:
        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        self._run_action(emulator.send_interactive_raw_frame(frame))

    def send_tone(self, frequency: float, level: float, duration: float) -> int:
        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        with self._media_lock:
            volume = self._speaker_volume
        gain = self.speaker_volume_gain(volume)
        if gain == 0.0:
            return 0
        adjusted_level = float(level) + 20.0 * math.log10(gain)
        return int(
            self._run_action(
                emulator.send_interactive_audio_tone(
                    frequency_hz=frequency,
                    level_dbfs=adjusted_level,
                    duration_seconds=duration,
                ),
                timeout=self._audio_action_timeout(duration),
            )
        )

    def send_wav(self, path: str) -> int:
        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        payloads, _ = load_s16be_wav_payloads(path)
        with self._media_lock:
            volume = self._speaker_volume
        scaled = self._scale_payloads(payloads, volume)
        if not scaled:
            return 0
        return int(
            self._run_action(
                emulator.send_interactive_audio_payloads(scaled, source="wav"),
                timeout=self._audio_action_timeout(len(scaled) * 0.020),
            )
        )

    def send_audio_file(self, path: str) -> int:
        """Decode and send a bounded common audio file through the shared layer."""

        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        payloads, _ = load_s16be_audio_file_payloads(path, max_seconds=30.0)
        with self._media_lock:
            volume = self._speaker_volume
        scaled = self._scale_payloads(payloads, volume)
        if not scaled:
            return 0
        return int(
            self._run_action(
                emulator.send_interactive_audio_payloads(scaled, source="audio_file"),
                timeout=self._audio_action_timeout(len(scaled) * 0.020),
            )
        )

    def send_polyphonic(
        self,
        steps: tuple[tuple[int, int, tuple[float, ...]], ...],
        *,
        level_dbfs: float = -18.0,
    ) -> int:
        emulator = self._emulator
        if emulator is None:
            raise RuntimeError("CommandMic is not connected")
        with self._media_lock:
            volume = self._speaker_volume
        gain = self.speaker_volume_gain(volume)
        if gain == 0.0:
            return 0
        adjusted_level = float(level_dbfs) + 20.0 * math.log10(gain)
        duration_seconds = sum(delay + length for delay, length, _ in steps) / 1000.0
        return int(
            self._run_action(
                emulator.send_interactive_polyphonic(
                    steps, level_dbfs=adjusted_level
                ),
                timeout=self._audio_action_timeout(duration_seconds),
            )
        )

    def start_recording(self, output: str) -> dict[str, Any]:
        with self._record_lock:
            if self._recording:
                raise RuntimeError("recording is already active")
            if not output:
                raise ValueError("recording output path is required")
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            writer = wave.open(str(path), "wb")
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8000)
            self._record_writer = writer
            self._record_path = path
            self._recorded_packets = 0
            self._recording = True
            self.state.update(recording=True, recorded_packets=0)
            return {"path": str(path)}

    def stop_recording(self) -> dict[str, Any]:
        with self._record_lock:
            if not self._recording or self._record_writer is None or self._record_path is None:
                raise RuntimeError("recording is not active")
            self._recording = False
            writer, self._record_writer = self._record_writer, None
            path, self._record_path = self._record_path, None
            packets = self._recorded_packets
            writer.close()
        self.state.update(recording=False, recorded_packets=0)
        return {"path": str(path), "samples": packets * 160, "seconds": packets * 0.02}


class CommandMicTestService:
    def __init__(self, audit_root: Path) -> None:
        self.audit_root = audit_root
        self.config = SoftwareRadioConfig()
        self.runtime: SoftwareRadioEndpoint | None = None

    def _result(self, operation: Any) -> dict[str, Any]:
        try:
            value = operation()
            return {"ok": True, "result": value}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def connect(self, raw: dict[str, Any]) -> dict[str, Any]:
        def action() -> None:
            self.disconnect()
            self.config = SoftwareRadioConfig(
                local_ip=str(raw.get("local_ip", "192.168.0.1")),
                mic_ip=str(raw.get("mic_ip", "192.168.0.2")),
                control_port=int(raw.get("control_port", 52001)),
                audio_port=int(raw.get("audio_port", 50000)),
                mic_gain=int(raw.get("mic_gain", 3)),
                backlight=str(raw.get("backlight", "on")),
                automatic_key_responses=bool(raw.get("automatic_key_responses", False)),
                automatic_ptt_responses=bool(raw.get("automatic_ptt_responses", False)),
            )
            stamp = time.strftime("%Y%m%dT%H%M%S")
            self.runtime = SoftwareRadioEndpoint(self.config, self.audit_root / f"{stamp}_test_app.jsonl")
            self.runtime.start()
        return self._result(action)

    def disconnect(self) -> dict[str, Any]:
        runtime, self.runtime = self.runtime, None
        if runtime:
            runtime.stop()
        return {"ok": True}

    def snapshot(self) -> dict[str, Any]:
        if self.runtime:
            return self.runtime.state.snapshot()
        return EndpointState().snapshot()

    def capabilities(self) -> dict[str, Any]:
        return {
            "display_size": 68,
            "primary_text_size": 8,
            "display_bits": list(verified_display_bit_controls()),
            "status_led_colors": ["off", "red", "green", "orange"],
        }

    def send_display(self, raw_hex: str) -> dict[str, Any]:
        return self._result(lambda: self._require().send_display(bytes.fromhex(raw_hex)))

    def decode_display(self, raw_hex: str) -> dict[str, Any]:
        return self._result(lambda: DisplayBuffer(bytes.fromhex(raw_hex)).to_dict())

    def send_led(self, color: str) -> dict[str, Any]:
        return self._result(lambda: self._require().send_led(color))

    def send_backlight(self, state: str) -> dict[str, Any]:
        return self._result(lambda: self._require().send_backlight(state))

    def send_raw(self, raw_hex: str) -> dict[str, Any]:
        return self._result(lambda: self._require().send_raw(bytes.fromhex(raw_hex)))

    def send_tone(self, frequency: float, level: float, duration: float) -> dict[str, Any]:
        return self._result(lambda: self._require().send_tone(float(frequency), float(level), float(duration)))

    def send_wav(self, path: str) -> dict[str, Any]:
        return self._result(lambda: self._require().send_wav(path))

    def start_recording(self, output: str) -> dict[str, Any]:
        return self._result(lambda: self._require().start_recording(output))

    def stop_recording(self) -> dict[str, Any]:
        return self._result(self._require().stop_recording)

    def _require(self) -> SoftwareRadioEndpoint:
        if self.runtime is None:
            raise RuntimeError("not connected")
        return self.runtime

    def shutdown(self) -> None:
        self.disconnect()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IP CommandMic Lab & Demo")
    parser.add_argument("--audit-directory", type=Path, default=Path("artifacts/test_app"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import webview

    service = CommandMicTestService(args.audit_directory)
    window = webview.create_window(
        "IP CommandMic Lab & Demo",
        html=build_test_html(),
        js_api=service,
        width=1240,
        height=820,
        min_size=(900, 620),
        background_color="#0d1117",
        text_select=False,
    )
    window.events.closed += service.shutdown
    webview.start(debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
