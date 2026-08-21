from __future__ import annotations

import asyncio
import contextlib
import collections
import math
import queue
import shutil
import struct
import subprocess
import sys
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


SUPPORTED_CODECS = ("u8", "s16le", "s16be", "mulaw", "alaw")


@dataclass(frozen=True, slots=True)
class KeyBeepProfile:
    """Capture-backed CommandMic key-touch beep parameters."""

    name: str
    beep_level: int
    frequency_hz: float
    packet_count: int
    level_dbfs: float
    observed_rms_dbfs: float

    @property
    def duration_seconds(self) -> float:
        return self.packet_count * 0.02


@dataclass(frozen=True, slots=True)
class RadioAudioPacket:
    """One verified radio-to-CommandMic RTP audio payload."""

    session: int
    sequence: int
    timestamp: int
    ssrc: int
    payload_s16be: bytes
    sample_rate: int = 8000

    @property
    def sample_count(self) -> int:
        return len(self.payload_s16be) // 2

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self.sample_rate

    @property
    def pcm_s16le(self) -> bytes:
        pcm, _ = decode_candidate_audio(self.payload_s16be, "s16be")
        return pcm


@dataclass(frozen=True, slots=True)
class RadioAudioGateEvent:
    """Verified receive-audio gate transition from the radio TCP channel."""

    session: int
    open: bool
    packet_count: int


@dataclass(frozen=True, slots=True)
class RadioAudioPlayoutFrame:
    """One clocked 20 ms playout frame from the receive jitter buffer."""

    session: int
    sequence: int
    pcm_s16le: bytes
    concealed: bool


@dataclass(frozen=True, slots=True)
class RadioAudioJitterStats:
    received: int
    played: int
    concealed: int
    duplicates: int
    late: int
    discontinuities: int
    buffered: int


class RadioAudioSink(Protocol):
    """Lifecycle and callback contract for CommandMic receive audio."""

    def start(self) -> None: ...

    def on_packet(self, packet: RadioAudioPacket) -> None: ...

    def on_gate(self, event: RadioAudioGateEvent) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MicrophoneCaptureStats:
    captured: int
    delivered: int
    overwritten: int
    underruns: int
    buffered: int


class MicrophoneAudioSource(Protocol):
    """Lifecycle and latest-frame contract for CommandMic transmit audio."""

    async def start(self, *, timeout_seconds: float = 8.0) -> None: ...

    def latest_payload(self) -> bytes: ...

    @property
    def stats(self) -> MicrophoneCaptureStats: ...

    async def close(self) -> None: ...


class BufferedMicrophoneSource:
    """Thread-safe application-fed source of 20 ms s16be/8 kHz mono frames.

    Producers may call :meth:`push_payload` from any thread. The RTP clock
    consumes only the newest frame; stale frames are overwritten and an
    underrun becomes exact digital silence instead of replaying old audio.
    The endpoint that receives this source owns its start/close lifecycle.
    """

    def __init__(self, *, queue_packets: int = 1) -> None:
        if not 1 <= queue_packets <= 3:
            raise ValueError("application audio queue_packets must be between 1 and 3")
        self.queue_packets = queue_packets
        self._frames: collections.deque[bytes] = collections.deque(
            maxlen=queue_packets
        )
        self._lock = threading.Lock()
        self._started = False
        self._captured = 0
        self._delivered = 0
        self._overwritten = 0
        self._underruns = 0

    async def start(self, *, timeout_seconds: float = 8.0) -> None:
        del timeout_seconds
        with self._lock:
            if self._started:
                raise RuntimeError("application audio source is already started")
            self._frames.clear()
            self._started = True

    def push_payload(self, payload_s16be: bytes) -> None:
        payload = bytes(payload_s16be)
        if len(payload) != 320:
            raise ValueError("application audio payload must contain exactly 320 bytes")
        with self._lock:
            if not self._started:
                raise RuntimeError("application audio source is not started")
            if len(self._frames) == self._frames.maxlen:
                self._overwritten += 1
            self._frames.append(payload)
            self._captured += 1

    def latest_payload(self) -> bytes:
        with self._lock:
            if not self._started:
                raise RuntimeError("application audio source is not started")
            if not self._frames:
                self._underruns += 1
                return bytes(320)
            payload = self._frames[-1]
            self._frames.clear()
            self._delivered += 1
            return payload

    @property
    def stats(self) -> MicrophoneCaptureStats:
        with self._lock:
            return MicrophoneCaptureStats(
                captured=self._captured,
                delivered=self._delivered,
                overwritten=self._overwritten,
                underruns=self._underruns,
                buffered=len(self._frames),
            )

    async def close(self) -> None:
        with self._lock:
            self._started = False
            self._frames.clear()


class FfmpegMicrophoneSource:
    """Prewarmed low-latency microphone source for 20 ms RTP frames.

    FFmpeg uses DirectShow on Windows, AVFoundation on macOS and PulseAudio on
    Linux, then converts to mono 8 kHz signed-16-bit PCM. Only the newest one
    or two frames are retained; stale microphone audio is overwritten rather
    than delivered late.
    """

    def __init__(
        self,
        device_name: str,
        *,
        executable: str | None = None,
        queue_packets: int = 1,
        device_buffer_ms: int = 20,
    ) -> None:
        if not device_name.strip():
            raise ValueError("microphone device name must not be empty")
        if not 1 <= queue_packets <= 3:
            raise ValueError("microphone queue_packets must be between 1 and 3")
        if not 5 <= device_buffer_ms <= 100:
            raise ValueError("microphone device_buffer_ms must be between 5 and 100")
        self.device_name = device_name
        self.executable = executable or shutil.which("ffmpeg")
        if not self.executable:
            raise RuntimeError("ffmpeg was not found on PATH")
        self.queue_packets = queue_packets
        self.device_buffer_ms = device_buffer_ms
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=queue_packets)
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._failure: BaseException | None = None
        self._stderr_tail = ""
        self._captured = 0
        self._delivered = 0
        self._overwritten = 0
        self._underruns = 0

    @property
    def command(self) -> list[str]:
        common = [
            self.executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
        ]
        if sys.platform == "win32":
            input_args = [
                "-f",
                "dshow",
                "-audio_buffer_size",
                str(self.device_buffer_ms),
                "-i",
                f"audio={self.device_name}",
            ]
        elif sys.platform == "darwin":
            # AVFoundation's audio-only input syntax is :<device-name-or-index>.
            input_args = ["-f", "avfoundation", "-i", f":{self.device_name}"]
        else:
            # PulseAudio accepts either an explicit source name or "default".
            input_args = ["-f", "pulse", "-i", self.device_name]
        return common + input_args + [
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-acodec",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ]

    async def start(self, *, timeout_seconds: float = 8.0) -> None:
        if self._process is not None:
            raise RuntimeError("microphone source is already started")
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout_seconds)
        except BaseException:
            await self.close()
            detail = f": {self._stderr_tail.strip()}" if self._stderr_tail.strip() else ""
            raise RuntimeError(f"microphone did not produce audio before timeout{detail}")
        if self._failure is not None:
            await self.close()
            raise RuntimeError("microphone capture failed during startup") from self._failure

    async def _reader_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while True:
                little_endian = await self._process.stdout.readexactly(320)
                big_endian = b"".join(
                    little_endian[index : index + 2][::-1]
                    for index in range(0, 320, 2)
                )
                if self._queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        self._queue.get_nowait()
                        self._overwritten += 1
                self._queue.put_nowait(big_endian)
                self._captured += 1
                self._ready.set()
        except asyncio.IncompleteReadError as exc:
            if self._process.returncode is None:
                self._failure = RuntimeError("microphone capture stream ended early")
            elif self._process.returncode != 0:
                self._failure = RuntimeError(
                    f"ffmpeg microphone capture exited with {self._process.returncode}"
                )
            if exc.partial:
                self._failure = RuntimeError("microphone emitted a partial 20 ms frame")
            self._ready.set()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._failure = exc
            self._ready.set()

    async def _stderr_loop(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while True:
            chunk = await self._process.stderr.read(1024)
            if not chunk:
                return
            self._stderr_tail = (self._stderr_tail + chunk.decode("utf-8", "replace"))[-4096:]

    def latest_payload(self) -> bytes:
        if self._failure is not None:
            raise RuntimeError("microphone capture backend failed") from self._failure
        payload: bytes | None = None
        while True:
            try:
                payload = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if payload is None:
            self._underruns += 1
            return bytes(320)
        self._delivered += 1
        return payload

    @property
    def stats(self) -> MicrophoneCaptureStats:
        return MicrophoneCaptureStats(
            captured=self._captured,
            delivered=self._delivered,
            overwritten=self._overwritten,
            underruns=self._underruns,
            buffered=self._queue.qsize(),
        )

    async def close(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            process.terminate()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), 2.0)
            if process.returncode is None:
                process.kill()
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._process = None


def enumerate_miniaudio_devices() -> dict[str, list[dict[str, object]]]:
    """Return stable, JSON-safe device descriptions without retaining C pointers."""

    try:
        import miniaudio
    except ImportError:
        return {"playback": [], "capture": []}

    devices = miniaudio.Devices()

    def serialize(items: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            {
                "name": str(item["name"]),
                "formats": [dict(entry) for entry in item.get("formats", [])],
            }
            for item in items
        ]

    return {
        "playback": serialize(devices.get_playbacks()),
        "capture": serialize(devices.get_captures()),
    }


def _miniaudio_device_id(kind: str, name: str | None) -> object | None:
    if not name:
        return None
    import miniaudio

    devices = miniaudio.Devices()
    items = devices.get_playbacks() if kind == "playback" else devices.get_captures()
    for item in items:
        if item["name"] == name:
            # The CFFI-owned copy remains valid after the enumeration context is
            # released and is consumed immediately by device initialization.
            return item["id"]
    raise ValueError(f"{kind} audio device is unavailable: {name}")


class MiniaudioMicrophoneSource:
    """Direct low-latency capture with a bounded newest-frame queue."""

    def __init__(
        self,
        device_name: str | None = None,
        *,
        queue_packets: int = 1,
        device_buffer_ms: int = 20,
    ) -> None:
        if not 1 <= queue_packets <= 3:
            raise ValueError("microphone queue_packets must be between 1 and 3")
        if not 10 <= device_buffer_ms <= 200:
            raise ValueError("device_buffer_ms must be between 10 and 200")
        self.device_name = device_name
        self.queue_packets = queue_packets
        self.device_buffer_ms = device_buffer_ms
        self._frames: collections.deque[bytes] = collections.deque(maxlen=queue_packets)
        self._partial = bytearray()
        self._lock = threading.Lock()
        self._device: object | None = None
        self._generator: object | None = None
        self._captured = 0
        self._delivered = 0
        self._overwritten = 0
        self._underruns = 0

    def _capture(self):
        chunk = yield
        while True:
            with self._lock:
                self._partial.extend(chunk)
                while len(self._partial) >= 320:
                    little_endian = bytes(self._partial[:320])
                    del self._partial[:320]
                    big_endian = b"".join(
                        little_endian[index : index + 2][::-1]
                        for index in range(0, 320, 2)
                    )
                    if len(self._frames) == self._frames.maxlen:
                        self._overwritten += 1
                    self._frames.append(big_endian)
                    self._captured += 1
            chunk = yield

    async def start(self, *, timeout_seconds: float = 8.0) -> None:
        del timeout_seconds
        if self._device is not None:
            raise RuntimeError("microphone source is already started")
        import miniaudio

        device_id = _miniaudio_device_id("capture", self.device_name)
        device = miniaudio.CaptureDevice(
            input_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=8000,
            buffersize_msec=self.device_buffer_ms,
            device_id=device_id,
            callback_periods=2,
            app_name="IP CommandMic",
        )
        generator = self._capture()
        next(generator)
        device.start(generator)
        self._device = device
        self._generator = generator

    def latest_payload(self) -> bytes:
        with self._lock:
            if not self._frames:
                self._underruns += 1
                return bytes(320)
            payload = self._frames[-1]
            self._frames.clear()
            self._delivered += 1
            return payload

    @property
    def stats(self) -> MicrophoneCaptureStats:
        with self._lock:
            return MicrophoneCaptureStats(
                captured=self._captured,
                delivered=self._delivered,
                overwritten=self._overwritten,
                underruns=self._underruns,
                buffered=len(self._frames),
            )

    async def close(self) -> None:
        device = self._device
        self._device = None
        if device is not None:
            device.close()
        generator = self._generator
        self._generator = None
        if generator is not None:
            with contextlib.suppress(Exception):
                generator.close()


class RadioAudioJitterBuffer:
    """Small deterministic sequence buffer for 20 ms CommandMic RTP audio.

    Network callbacks call :meth:`push`; a 20 ms playback clock calls
    :meth:`pop`. Missing frames become exact digital silence. A new gate
    session resets sequence and buffered state so audio never leaks between
    independent radio audio transactions.
    """

    def __init__(self, prebuffer_packets: int = 2, max_gap_packets: int = 25) -> None:
        if not 1 <= prebuffer_packets <= 25:
            raise ValueError("prebuffer_packets must be between 1 and 25")
        if not 1 <= max_gap_packets <= 100:
            raise ValueError("max_gap_packets must be between 1 and 100")
        self.prebuffer_packets = prebuffer_packets
        self.max_gap_packets = max_gap_packets
        self._session: int | None = None
        self._packets: dict[int, bytes] = {}
        self._expected: int | None = None
        self._started = False
        self._received = 0
        self._played = 0
        self._concealed = 0
        self._duplicates = 0
        self._late = 0
        self._discontinuities = 0

    @staticmethod
    def _forward_distance(sequence: int, reference: int) -> int:
        return (sequence - reference) & 0xFFFF

    def start_session(self, session: int) -> None:
        if session < 1:
            raise ValueError("session must be positive")
        self._session = session
        self._packets.clear()
        self._expected = None
        self._started = False

    def push(self, packet: RadioAudioPacket) -> bool:
        if self._session != packet.session:
            self.start_session(packet.session)
        sequence = packet.sequence
        if sequence in self._packets:
            self._duplicates += 1
            return False
        if self._started and self._expected is not None:
            distance = self._forward_distance(sequence, self._expected)
            if distance >= 0x8000:
                self._late += 1
                return False
            if distance > self.max_gap_packets:
                self._discontinuities += 1
                return False
        elif self._expected is None:
            self._expected = sequence
        else:
            distance = self._forward_distance(sequence, self._expected)
            if distance < 0x8000:
                if distance > self.max_gap_packets:
                    self._discontinuities += 1
                    return False
            else:
                earlier = self._forward_distance(self._expected, sequence)
                if earlier > self.max_gap_packets:
                    self._discontinuities += 1
                    return False
                # Before playout starts, accept a modestly earlier
                # out-of-order packet as the buffered sequence beginning.
                self._expected = sequence
        self._packets[sequence] = packet.pcm_s16le
        self._received += 1
        return True

    def pop(self) -> RadioAudioPlayoutFrame | None:
        if self._session is None or self._expected is None:
            return None
        if not self._started:
            if len(self._packets) < self.prebuffer_packets:
                return None
            self._started = True
        sequence = self._expected
        payload = self._packets.pop(sequence, None)
        concealed = payload is None
        if concealed:
            payload = bytes(320)
            self._concealed += 1
        self._played += 1
        self._expected = (sequence + 1) & 0xFFFF
        return RadioAudioPlayoutFrame(
            session=self._session,
            sequence=sequence,
            pcm_s16le=payload,
            concealed=concealed,
        )

    @property
    def stats(self) -> RadioAudioJitterStats:
        return RadioAudioJitterStats(
            received=self._received,
            played=self._played,
            concealed=self._concealed,
            duplicates=self._duplicates,
            late=self._late,
            discontinuities=self._discontinuities,
            buffered=len(self._packets),
        )


class FfplayRadioAudioSink:
    """Non-blocking live sink for verified mono 8 kHz CommandMic PCM."""

    def __init__(
        self,
        *,
        prebuffer_packets: int = 2,
        startup_silence_packets: int = 5,
        tail_silence_packets: int = 5,
        max_backend_queue_packets: int = 25,
        executable: str | None = None,
    ) -> None:
        if not 0 <= startup_silence_packets <= 25:
            raise ValueError("startup_silence_packets must be between 0 and 25")
        if not 0 <= tail_silence_packets <= 25:
            raise ValueError("tail_silence_packets must be between 0 and 25")
        if not 3 <= max_backend_queue_packets <= 100:
            raise ValueError("max_backend_queue_packets must be between 3 and 100")
        self.jitter = RadioAudioJitterBuffer(prebuffer_packets)
        self.startup_silence_packets = startup_silence_packets
        self.tail_silence_packets = tail_silence_packets
        self.max_backend_queue_packets = max_backend_queue_packets
        self.executable = executable or shutil.which("ffplay")
        if not self.executable:
            raise RuntimeError("ffplay was not found on PATH")
        self._events: queue.Queue[RadioAudioPacket | RadioAudioGateEvent | None] = queue.Queue()
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None
        self._render_path_primed = False
        self._queue_lock = threading.Lock()
        self._queued_packets = 0
        self._backend_queue_drops = 0

    @property
    def command(self) -> list[str]:
        return [
            self.executable,
            "-nodisp",
            "-autoexit",
            "-loglevel", "error",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-f", "s16le",
            "-ar", "8000",
            "-ch_layout", "mono",
            "-i", "pipe:0",
        ]

    def start(self) -> None:
        if self._thread is not None:
            return
        self._process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=(subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
        )
        # Prime FFplay and the Windows render path before the first radio gate.
        # This one-time silence is consumed during session startup rather than
        # being inserted ahead of live received audio.
        self._write(bytes(320 * self.startup_silence_packets))
        self._render_path_primed = True
        self._thread = threading.Thread(
            target=self._run, name="ip-commandmic-ffplay", daemon=True
        )
        self._thread.start()

    def on_packet(self, packet: RadioAudioPacket) -> None:
        with self._queue_lock:
            if self._queued_packets >= self.max_backend_queue_packets:
                self._backend_queue_drops += 1
                return
            self._queued_packets += 1
        self._events.put_nowait(packet)

    def on_gate(self, event: RadioAudioGateEvent) -> None:
        self._events.put_nowait(event)

    def _write(self, payload: bytes) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("ffplay stdin is unavailable")
        self._process.stdin.write(payload)
        self._process.stdin.flush()

    def _drain_one(self) -> bool:
        frame = self.jitter.pop()
        if frame is None:
            return False
        self._write(frame.pcm_s16le)
        return True

    def _run(self) -> None:
        try:
            while True:
                event = self._events.get()
                if event is None:
                    break
                if isinstance(event, RadioAudioGateEvent):
                    if event.open:
                        self.jitter.start_session(event.session)
                    else:
                        while self.jitter.stats.buffered:
                            self._drain_one()
                        self._write(bytes(320 * self.tail_silence_packets))
                    continue
                with self._queue_lock:
                    self._queued_packets -= 1
                discontinuities = self.jitter.stats.discontinuities
                accepted = self.jitter.push(event)
                if not accepted and self.jitter.stats.discontinuities > discontinuities:
                    # A blocked output backend may force queue drops. Resume at
                    # current audio instead of replaying or synthesizing a long
                    # stale gap.
                    self.jitter.start_session(event.session)
                    self.jitter.push(event)
                self._drain_one()
        except BaseException as exc:
            self._error = exc

    def close(self) -> None:
        if self._thread is None:
            return
        self._events.put(None)
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise RuntimeError("live audio worker did not stop within 2 seconds")
        if self._process is not None:
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                except OSError:
                    pass
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                self._process.wait(timeout=2.0)
            if self._process.returncode not in (0, None):
                detail = ""
                if self._process.stderr is not None:
                    detail = self._process.stderr.read().decode("utf-8", "replace").strip()
                raise RuntimeError(
                    f"ffplay exited with code {self._process.returncode}"
                    + (f": {detail}" if detail else "")
                )
        self._thread = None
        if self._error is not None:
            raise RuntimeError("live radio audio playback failed") from self._error

    @property
    def backend_queue_drops(self) -> int:
        with self._queue_lock:
            return self._backend_queue_drops


class MiniaudioRadioAudioSink:
    """Direct callback-driven playback with one bounded protocol jitter buffer."""

    def __init__(
        self,
        *,
        device_name: str | None = None,
        prebuffer_packets: int = 2,
        device_buffer_ms: int = 20,
    ) -> None:
        if not 10 <= device_buffer_ms <= 200:
            raise ValueError("device_buffer_ms must be between 10 and 200")
        self.device_name = device_name
        self.device_buffer_ms = device_buffer_ms
        self.jitter = RadioAudioJitterBuffer(prebuffer_packets)
        self._lock = threading.Lock()
        self._playout = bytearray()
        self._device: object | None = None
        self._generator: object | None = None
        self._backend_queue_drops = 0
        self._gate_open = False

    def _playback(self):
        required_frames = yield b""
        while True:
            required_bytes = required_frames * 2
            with self._lock:
                while self._gate_open and len(self._playout) < required_bytes:
                    frame = self.jitter.pop()
                    if frame is None:
                        break
                    self._playout.extend(frame.pcm_s16le)
                available = min(required_bytes, len(self._playout))
                payload = bytes(self._playout[:available]).ljust(required_bytes, b"\x00")
                del self._playout[:available]
            required_frames = yield payload

    def start(self) -> None:
        if self._device is not None:
            return
        import miniaudio

        device_id = _miniaudio_device_id("playback", self.device_name)
        device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=8000,
            buffersize_msec=self.device_buffer_ms,
            device_id=device_id,
            callback_periods=2,
            app_name="IP CommandMic",
        )
        generator = self._playback()
        next(generator)
        device.start(generator)
        self._device = device
        self._generator = generator

    def on_packet(self, packet: RadioAudioPacket) -> None:
        with self._lock:
            if self._gate_open:
                self.jitter.push(packet)

    def on_gate(self, event: RadioAudioGateEvent) -> None:
        with self._lock:
            self._playout.clear()
            self._gate_open = event.open
            if event.open:
                self.jitter.start_session(event.session)

    def close(self) -> None:
        device = self._device
        self._device = None
        if device is not None:
            device.close()
        generator = self._generator
        self._generator = None
        if generator is not None:
            with contextlib.suppress(Exception):
                generator.close()

    @property
    def backend_queue_drops(self) -> int:
        return self._backend_queue_drops


KEY_BEEP_LEVEL_RMS_DBFS = {
    "normal": {
        1: -43.296935,
        2: -37.268895,
        3: -31.245050,
        4: -25.222631,
        5: -19.214833,
    },
    "low": {
        1: -42.557205,
        2: -36.530048,
        3: -30.505766,
        4: -24.483520,
        5: -18.495399,
    },
}


def get_key_beep_profile(name: str, beep_level: int = 3) -> KeyBeepProfile:
    if beep_level not in (1, 2, 3, 4, 5):
        raise ValueError("beep_level must be one of the observed values: 1 through 5")
    try:
        observed_rms_dbfs = KEY_BEEP_LEVEL_RMS_DBFS[name][beep_level]
    except KeyError as exc:
        choices = ", ".join(KEY_BEEP_LEVEL_RMS_DBFS)
        raise ValueError(f"unknown key beep profile {name!r}; choose one of {choices}") from exc
    frequency_hz, packet_count = {
        "normal": (1000.0, 4),
        "low": (500.0, 7),
    }[name]
    return KeyBeepProfile(
        name=name,
        beep_level=beep_level,
        frequency_hz=frequency_hz,
        packet_count=packet_count,
        # A full-scale sine's RMS is 3.0103 dB below its peak. The generated
        # reference tone therefore matches the measured whole-burst RMS even
        # though the radio's exact attack/release envelope is not synthesized.
        level_dbfs=observed_rms_dbfs + 3.01029995664,
        observed_rms_dbfs=observed_rms_dbfs,
    )


KEY_BEEP_PROFILES = {
    name: get_key_beep_profile(name, 3) for name in KEY_BEEP_LEVEL_RMS_DBFS
}


def generate_s16be_tone_payloads(
    *,
    frequency_hz: float,
    level_dbfs: float,
    packet_count: int,
    sample_rate: int = 8000,
    samples_per_packet: int = 160,
) -> list[bytes]:
    """Generate phase-continuous signed-16-bit big-endian RTP payloads."""

    if not 0.0 < frequency_hz < sample_rate / 2:
        raise ValueError("frequency_hz must be between 0 and Nyquist")
    if not -90.0 <= level_dbfs <= 0.0:
        raise ValueError("level_dbfs must be between -90 and 0 dBFS")
    if packet_count < 1:
        raise ValueError("packet_count must be positive")
    amplitude = round(32767 * (10 ** (level_dbfs / 20.0)))
    payloads: list[bytes] = []
    for packet_index in range(packet_count):
        first_sample = packet_index * samples_per_packet
        payloads.append(
            b"".join(
                struct.pack(
                    ">h",
                    round(
                        amplitude
                        * math.sin(
                            2.0 * math.pi * frequency_hz
                            * (first_sample + offset) / sample_rate
                        )
                    ),
                )
                for offset in range(samples_per_packet)
            )
        )
    return payloads


def generate_s16be_polyphonic_payloads(
    steps: tuple[tuple[int, int, tuple[float, ...]], ...],
    *,
    level_dbfs: float = -18.0,
    sample_rate: int = 8000,
    samples_per_packet: int = 160,
) -> list[bytes]:
    """Generate packetized PCM for delayed polyphonic tone steps."""

    if not -90.0 <= level_dbfs <= 0.0:
        raise ValueError("level_dbfs must be between -90 and 0 dBFS")
    samples: list[int] = []
    peak = 32767 * (10 ** (level_dbfs / 20.0))
    for delay_ms, length_ms, frequencies in steps:
        if delay_ms < 0 or length_ms <= 0 or not frequencies:
            raise ValueError("sound steps require nonnegative delay, positive length and frequencies")
        if any(not 0.0 < frequency < sample_rate / 2 for frequency in frequencies):
            raise ValueError("all frequencies must be between 0 and Nyquist")
        samples.extend([0] * round(sample_rate * delay_ms / 1000))
        count = round(sample_rate * length_ms / 1000)
        divisor = len(frequencies)
        samples.extend(
            round(peak * sum(math.sin(2 * math.pi * frequency * index / sample_rate) for frequency in frequencies) / divisor)
            for index in range(count)
        )
    padding = (-len(samples)) % samples_per_packet
    samples.extend([0] * padding)
    return [
        b"".join(struct.pack(">h", sample) for sample in samples[start:start + samples_per_packet])
        for start in range(0, len(samples), samples_per_packet)
    ]


def load_s16be_wav_payloads(
    path: str | Path,
    *,
    max_seconds: float = 30.0,
    sample_rate: int = 8000,
    samples_per_packet: int = 160,
) -> tuple[list[bytes], int]:
    """Load an uncompressed mono 8 kHz/16-bit WAV into 20 ms s16be payloads.

    The final partial packet is padded with digital silence. The returned
    sample count is the unpadded source length so callers can preserve the
    exact source duration in manifests and PTT timing.
    """

    wav_path = Path(path)
    with wave.open(str(wav_path), "rb") as source:
        if source.getcomptype() != "NONE":
            raise ValueError("WAV must be uncompressed PCM")
        if source.getnchannels() != 1:
            raise ValueError("WAV must be mono")
        if source.getframerate() != sample_rate:
            raise ValueError(f"WAV must use a {sample_rate} Hz sample rate")
        if source.getsampwidth() != 2:
            raise ValueError("WAV must use 16-bit samples")
        frame_count = source.getnframes()
        if frame_count < samples_per_packet:
            raise ValueError("WAV must contain at least 0.02 seconds")
        if frame_count > round(sample_rate * max_seconds):
            raise ValueError(f"WAV must not exceed {max_seconds:g} seconds")
        little_endian = source.readframes(frame_count)
    big_endian = b"".join(
        struct.pack(">h", sample[0])
        for sample in struct.iter_unpack("<h", little_endian)
    )
    packet_bytes = samples_per_packet * 2
    payloads = [
        big_endian[offset : offset + packet_bytes].ljust(packet_bytes, b"\x00")
        for offset in range(0, len(big_endian), packet_bytes)
    ]
    return payloads, frame_count


def load_s16be_audio_file_payloads(
    path: str | Path, *, max_seconds: float = 30.0
) -> tuple[list[bytes], int]:
    """Decode a common audio file into protocol-ready 20 ms s16be payloads.

    Native 8 kHz/16-bit/mono PCM WAV files use the lightweight standard-library
    path. Other WAV variants and formats supported by miniaudio are decoded and
    resampled directly in the shared audio layer so applications do not copy
    codec, duration, endian, or packet-padding policy.
    """

    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() == ".wav":
        try:
            return load_s16be_wav_payloads(source, max_seconds=max_seconds)
        except (ValueError, wave.Error):
            pass
    try:
        import miniaudio
    except ImportError as exc:
        raise RuntimeError(
            "common audio-file decoding requires the ip-commandmic audio extra"
        ) from exc
    decoded = miniaudio.decode_file(
        str(source),
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=8000,
    )
    frame_count = int(decoded.num_frames)
    if frame_count < 160:
        raise ValueError("audio file must contain at least 0.02 seconds")
    if frame_count > round(8000 * max_seconds):
        raise ValueError(f"audio file must not exceed {max_seconds:g} seconds")
    little_endian = bytes(decoded.samples)
    big_endian = b"".join(
        struct.pack(">h", sample[0])
        for sample in struct.iter_unpack("<h", little_endian)
    )
    packet_bytes = 320
    payloads = [
        big_endian[offset : offset + packet_bytes].ljust(packet_bytes, b"\x00")
        for offset in range(0, len(big_endian), packet_bytes)
    ]
    return payloads, frame_count


def decode_candidate_audio(payload: bytes, codec: str) -> tuple[bytes, int]:
    """Decode an explicitly selected codec hypothesis to signed 16-bit PCM."""

    if codec == "s16le":
        if len(payload) % 2:
            raise ValueError("s16le candidate payload must contain an even number of bytes")
        return payload, 2
    if codec == "s16be":
        if len(payload) % 2:
            raise ValueError("s16be candidate payload must contain an even number of bytes")
        samples = struct.iter_unpack(">h", payload)
        return b"".join(struct.pack("<h", sample[0]) for sample in samples), 2
    if codec == "u8":
        samples = ((byte - 128) << 8 for byte in payload)
        return b"".join(struct.pack("<h", sample) for sample in samples), 2
    if codec == "mulaw":
        samples = []
        for byte in payload:
            value = (~byte) & 0xFF
            sample = (((value & 0x0F) << 3) + 0x84) << ((value >> 4) & 0x07)
            sample -= 0x84
            samples.append(-sample if value & 0x80 else sample)
        return b"".join(struct.pack("<h", sample) for sample in samples), 2
    if codec == "alaw":
        samples = []
        for byte in payload:
            value = byte ^ 0x55
            exponent = (value & 0x70) >> 4
            mantissa = value & 0x0F
            if exponent == 0:
                sample = (mantissa << 4) + 8
            elif exponent == 1:
                sample = (mantissa << 5) + 0x108
            else:
                sample = ((mantissa << 5) + 0x108) << (exponent - 1)
            samples.append(sample if value & 0x80 else -sample)
        return b"".join(struct.pack("<h", sample) for sample in samples), 2
    raise ValueError(f"unsupported codec {codec!r}; choose one of {SUPPORTED_CODECS}")


def write_wav(
    path: str | Path,
    payload: bytes,
    *,
    codec: str,
    sample_rate: int,
    channels: int = 1,
) -> None:
    pcm, width = decode_candidate_audio(payload, codec)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
