"""Hardware-free conformance checks for the two public endpoint roles."""

from __future__ import annotations

import argparse
import json
import math
import queue
import socket
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .audio import (
    BufferedMicrophoneSource,
    RadioAudioGateEvent,
    RadioAudioJitterBuffer,
    RadioAudioPacket,
)
from .controls import ORDINARY_KEY_BUTTONS
from .display import DisplayBuffer
from .gui_server import SoftwareCommandMicEndpoint
from .test_app import SoftwareRadioConfig, SoftwareRadioEndpoint


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    checks: tuple[ConformanceCheck, ...]
    elapsed_seconds: float
    commandmic_audit: Path
    radio_audit: Path

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.status != "failed" for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "commandmic_audit": str(self.commandmic_audit),
            "radio_audit": str(self.radio_audit),
            "checks": [asdict(check) for check in self.checks],
        }


def _rtp_callback_latencies_ms(
    arrivals: list[tuple[int, float]],
    callbacks: list[tuple[int, float]],
) -> list[float]:
    """Match ordered RTP events without losing 16-bit sequence wraparound."""

    if len(arrivals) != len(callbacks):
        raise AssertionError(
            "receive callback timing did not cover every sustained packet"
        )
    latencies: list[float] = []
    for index, ((arrival_sequence, arrived_at), (callback_sequence, callback_at)) in enumerate(
        zip(arrivals, callbacks, strict=True)
    ):
        if arrival_sequence != callback_sequence:
            raise AssertionError(
                "receive callback sequence diverged at packet "
                f"{index}: arrival={arrival_sequence}, callback={callback_sequence}"
            )
        latency_ms = (float(callback_at) - float(arrived_at)) * 1000.0
        if latency_ms < 0.0:
            raise AssertionError(
                f"receive callback preceded arrival at packet {index}: {latency_ms:.3f} ms"
            )
        latencies.append(latency_ms)
    return latencies


def _assert_continuous_rtp_timeline(
    timeline: list[tuple[int, float]], *, label: str
) -> None:
    """Require an ordered RTP timeline with no loss, duplication, or reordering."""

    for index, ((prior, _), (current, _)) in enumerate(
        zip(timeline, timeline[1:]), start=1
    ):
        expected = (prior + 1) & 0xFFFF
        if current != expected:
            raise AssertionError(
                f"{label} RTP sequence diverged at packet {index}: "
                f"expected={expected}, actual={current}"
            )


def _compact_audio_summary(summary: dict[str, object]) -> dict[str, object]:
    """Retain actionable audio diagnostics without embedding long packet arrays."""

    fields = (
        "session",
        "source_packets",
        "received",
        "played",
        "concealed",
        "duplicates",
        "late",
        "discontinuities",
        "concealment_is_silence",
    )
    compact = {field: summary.get(field) for field in fields}
    sequences = list(summary.get("sequences", []))
    callbacks = list(summary.get("callback_times", []))
    concealed = list(summary.get("concealed_sequences", []))
    compact.update(
        {
            "sequence_count": len(sequences),
            "callback_count": len(callbacks),
            "concealed_sequences": concealed[:20],
            "concealed_sequences_truncated": len(concealed) > 20,
        }
    )
    return compact


def _validate_sustained_radio_playout(
    summary: dict[str, object], *, expected_packets: int
) -> tuple[int, int]:
    """Validate exact delivery plus a bounded set of isolated scheduler misses.

    Wire receipt and callback delivery remain lossless. The clocked two-packet
    playout model may conceal one isolated operating-system scheduling outlier,
    or up to 100 parts per million in longer runs.
    """

    compact = _compact_audio_summary(summary)
    concealed_sequences = [
        int(sequence) for sequence in summary.get("concealed_sequences", [])
    ]
    source_packets = int(summary.get("source_packets", -1))
    received = int(summary.get("received", -1))
    played = int(summary.get("played", -1))
    concealed = int(summary.get("concealed", -1))
    duplicates = int(summary.get("duplicates", -1))
    late = int(summary.get("late", -1))
    discontinuities = int(summary.get("discontinuities", -1))
    sequence_count = len(list(summary.get("sequences", [])))
    callback_count = len(list(summary.get("callback_times", [])))

    exact_delivery = (
        source_packets == expected_packets
        and played == expected_packets
        and sequence_count == expected_packets
        and callback_count == expected_packets
        and duplicates == 0
        and discontinuities == 0
        and received + late == expected_packets
        and late == concealed == len(concealed_sequences)
        and bool(summary.get("concealment_is_silence"))
    )
    if not exact_delivery:
        raise AssertionError(
            f"sustained radio playout accounting failed: {compact}"
        )

    outlier_budget = max(1, math.ceil(expected_packets * 0.0001))
    if concealed > outlier_budget:
        raise AssertionError(
            "sustained radio playout exceeded the isolated scheduling-outlier "
            f"budget ({concealed}>{outlier_budget}): {compact}"
        )
    for prior, current in zip(concealed_sequences, concealed_sequences[1:]):
        if current == ((prior + 1) & 0xFFFF):
            raise AssertionError(
                "sustained radio playout had consecutive concealments: "
                f"{compact}"
            )
    return concealed, outlier_budget


class _ConformanceRadioAudioSink:
    """Device-free clocked receive sink with per-gate jitter summaries."""

    def __init__(self, *, prebuffer_packets: int = 2) -> None:
        self.jitter = RadioAudioJitterBuffer(prebuffer_packets)
        self._lock = threading.Lock()
        self._started = False
        self._baseline: dict[str, int] | None = None
        self._frames: list[object] = []
        self._packet_times: list[tuple[int, float]] = []
        self._packet_time_start = 0
        self._frame_start = 0
        self._summaries: list[dict[str, object]] = []
        self._next_playout: float | None = None
        self._gate_open = False

    def start(self) -> None:
        with self._lock:
            self._started = True

    def on_packet(self, packet: RadioAudioPacket) -> None:
        with self._lock:
            if not self._started:
                raise RuntimeError("receive sink is not started")
            received_at = time.perf_counter()
            self._packet_times.append((packet.sequence, received_at))
            self.jitter.push(packet)
            if (
                self._next_playout is None
                and self.jitter.stats.buffered >= self.jitter.prebuffer_packets
            ):
                # The second default-profile packet starts playout of the first,
                # adding one intentional packet interval from first arrival.
                self._next_playout = received_at
            while (
                self._next_playout is not None
                and self._next_playout <= received_at
            ):
                frame = self.jitter.pop()
                if frame is None:
                    break
                self._frames.append(frame)
                self._next_playout += 0.020

    def on_gate(self, event: RadioAudioGateEvent) -> None:
        with self._lock:
            if event.open:
                self._gate_open = True
                self.jitter.start_session(event.session)
                self._baseline = asdict(self.jitter.stats)
                self._frame_start = len(self._frames)
                self._packet_time_start = len(self._packet_times)
                self._next_playout = None
                return
            self._gate_open = False
            while self.jitter.stats.buffered:
                frame = self.jitter.pop()
                if frame is None:
                    break
                self._frames.append(frame)
            baseline = self._baseline or asdict(self.jitter.stats)
            current = asdict(self.jitter.stats)
            frames = self._frames[self._frame_start :]
            self._summaries.append(
                {
                    "session": event.session,
                    "source_packets": event.packet_count,
                    **{
                        name: int(current[name]) - int(baseline[name])
                        for name in (
                            "received",
                            "played",
                            "concealed",
                            "duplicates",
                            "late",
                            "discontinuities",
                        )
                    },
                    "sequences": [frame.sequence for frame in frames],
                    "concealed_sequences": [
                        frame.sequence for frame in frames if frame.concealed
                    ],
                    "concealment_is_silence": all(
                        frame.pcm_s16le == bytes(320)
                        for frame in frames
                        if frame.concealed
                    ),
                    "callback_times": list(
                        self._packet_times[self._packet_time_start :]
                    ),
                }
            )
            self._next_playout = None

    @property
    def summaries(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(summary) for summary in self._summaries]

    @property
    def callback_count(self) -> int:
        with self._lock:
            return len(self._packet_times)

    @property
    def gate_open(self) -> bool:
        with self._lock:
            return self._gate_open

    def close(self) -> None:
        with self._lock:
            self._started = False
            self._gate_open = False


class _LoopbackUdpImpairmentProxy:
    """Route endpoint RTP on loopback and optionally impair mic payloads."""

    def __init__(
        self,
        *,
        listen_ip: str,
        port: int,
        radio_address: tuple[str, int],
        mic_address: tuple[str, int],
    ) -> None:
        self._radio_address = radio_address
        self._mic_address = mic_address
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((listen_ip, port))
        self._socket.settimeout(0.1)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._interrupted = False
        self._thread = threading.Thread(
            target=self._run, name="commandmic-conformance-udp-proxy", daemon=True
        )
        self._impair_mic_rtp = False
        self._mic_payload_index = 0
        self._mic_held: bytes | None = None
        self._mic_stats = {"dropped": 0, "duplicated": 0, "reordered": 0}
        self._mic_arrival_times: list[tuple[int, float]] = []
        self._impair_radio_rtp = False
        self._radio_payload_index = 0
        self._radio_held: bytes | None = None
        self._radio_stats = {"dropped": 0, "duplicated": 0, "reordered": 0}
        self._radio_arrival_times: list[tuple[int, float]] = []

    def start(self) -> None:
        self._thread.start()

    def set_mic_rtp_impairment(self, enabled: bool) -> None:
        with self._lock:
            self._impair_mic_rtp = bool(enabled)
            self._mic_payload_index = 0
            self._mic_held = None
            self._mic_stats = {"dropped": 0, "duplicated": 0, "reordered": 0}

    def set_radio_rtp_impairment(self, enabled: bool) -> None:
        with self._lock:
            self._impair_radio_rtp = bool(enabled)
            self._radio_payload_index = 0
            self._radio_held = None
            self._radio_stats = {"dropped": 0, "duplicated": 0, "reordered": 0}

    def set_interrupted(self, interrupted: bool) -> None:
        """Blackhole datagrams while the routed loopback link is interrupted."""

        with self._lock:
            self._interrupted = bool(interrupted)

    def reset_radio_timing(self) -> None:
        with self._lock:
            self._radio_arrival_times = []

    def reset_mic_timing(self) -> None:
        with self._lock:
            self._mic_arrival_times = []

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._mic_stats)

    @property
    def radio_stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._radio_stats)

    @property
    def radio_arrival_times(self) -> list[tuple[int, float]]:
        with self._lock:
            return list(self._radio_arrival_times)

    @property
    def mic_arrival_times(self) -> list[tuple[int, float]]:
        with self._lock:
            return list(self._mic_arrival_times)

    def _send(self, data: bytes, target: tuple[str, int]) -> None:
        self._socket.sendto(data, target)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, source = self._socket.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                return
            with self._lock:
                if self._interrupted:
                    continue
            if source == self._radio_address:
                with self._lock:
                    if (
                        len(data) == 332
                        and data[:2] == b"\x80\x7d"
                        and any(data[12:])
                    ):
                        self._radio_arrival_times.append(
                            (int.from_bytes(data[2:4], "big"), time.perf_counter())
                        )
                    impair = (
                        self._impair_radio_rtp
                        and len(data) == 332
                        and data[:2] == b"\x80\x7d"
                        and any(data[12:])
                    )
                    if not impair:
                        action = "pass"
                    else:
                        self._radio_payload_index += 1
                        action = {
                            2: "drop",
                            4: "duplicate",
                            6: "hold",
                            7: "release_held_after_current",
                        }.get(self._radio_payload_index, "pass")
                    held = self._radio_held
                    if action == "drop":
                        self._radio_stats["dropped"] += 1
                        continue
                    if action == "hold":
                        self._radio_held = data
                        continue
                    if action == "release_held_after_current":
                        self._radio_held = None
                        self._radio_stats["reordered"] += 1
                    if action == "duplicate":
                        self._radio_stats["duplicated"] += 1
                self._send(data, self._mic_address)
                if action == "duplicate":
                    self._send(data, self._mic_address)
                elif action == "release_held_after_current" and held is not None:
                    self._send(held, self._mic_address)
                continue
            if source != self._mic_address:
                continue

            with self._lock:
                if (
                    len(data) == 332
                    and data[:2] == b"\x80\x7d"
                    and any(data[12:])
                ):
                    self._mic_arrival_times.append(
                        (int.from_bytes(data[2:4], "big"), time.perf_counter())
                    )
                impair = (
                    self._impair_mic_rtp
                    and len(data) == 332
                    and data[:2] == b"\x80\x7d"
                    and any(data[12:])
                )
                if not impair:
                    action = "pass"
                else:
                    self._mic_payload_index += 1
                    index = self._mic_payload_index
                    action = {
                        2: "drop",
                        4: "duplicate",
                        6: "hold",
                        7: "release_held_after_current",
                    }.get(index, "pass")
                held = self._mic_held
                if action == "drop":
                    self._mic_stats["dropped"] += 1
                    continue
                if action == "hold":
                    self._mic_held = data
                    continue
                if action == "release_held_after_current":
                    self._mic_held = None
                    self._mic_stats["reordered"] += 1
                if action == "duplicate":
                    self._mic_stats["duplicated"] += 1

            self._send(data, self._radio_address)
            if action == "duplicate":
                self._send(data, self._radio_address)
            elif action == "release_held_after_current" and held is not None:
                self._send(held, self._radio_address)

    def close(self) -> None:
        self._stop.set()
        self._socket.close()
        self._thread.join(timeout=1.0)


class _LoopbackTcpImpairmentProxy:
    """Relay loopback control traffic with one-shot stream transformations."""

    _DIRECTIONS = ("radio_to_mic", "mic_to_radio")
    _ACTIONS = ("fragment", "coalesce")

    def __init__(
        self,
        *,
        listen_ip: str,
        port: int,
        target_address: tuple[str, int],
    ) -> None:
        self._target_address = target_address
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((listen_ip, port))
        self._listener.listen()
        self._listener.settimeout(0.1)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._interrupted = False
        self._actions: dict[str, str | None] = {
            direction: None for direction in self._DIRECTIONS
        }
        self._stats = {
            f"{direction}_{action}": 0
            for direction in self._DIRECTIONS
            for action in self._ACTIONS
        }
        self._stats.update(
            {
                f"{direction}_coalesce_timeout": 0
                for direction in self._DIRECTIONS
            }
        )
        self._session_sockets: set[socket.socket] = set()
        self._session_threads: list[threading.Thread] = []
        self._thread = threading.Thread(
            target=self._run,
            name="commandmic-conformance-tcp-proxy",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def arm(self, direction: str, action: str) -> None:
        if direction not in self._DIRECTIONS:
            raise ValueError(f"unknown TCP direction: {direction}")
        if action not in self._ACTIONS:
            raise ValueError(f"unknown TCP impairment action: {action}")
        with self._lock:
            if self._actions[direction] is not None:
                raise RuntimeError(f"TCP action already armed for {direction}")
            self._actions[direction] = action

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def set_interrupted(self, interrupted: bool) -> None:
        """Tear down and reject sessions while the routed link is interrupted."""

        with self._lock:
            self._interrupted = bool(interrupted)
            streams = tuple(self._session_sockets) if interrupted else ()
        for stream in streams:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                stream.close()
            except OSError:
                pass

    @staticmethod
    def _frame_count(data: bytes) -> int:
        return data.count(b"\xf3\x41\x71") + data.count(b"\xf5\x41\x71")

    def _take_action(self, direction: str) -> str | None:
        with self._lock:
            action = self._actions[direction]
            self._actions[direction] = None
            return action

    def _record(self, name: str) -> None:
        with self._lock:
            self._stats[name] += 1

    def _coalesce(self, source: socket.socket, first: bytes) -> tuple[bytes, bool]:
        combined = bytearray(first)
        deadline = time.monotonic() + 0.05
        previous_timeout = source.gettimeout()
        try:
            while self._frame_count(combined) < 2:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                source.settimeout(remaining)
                try:
                    part = source.recv(65535)
                except TimeoutError:
                    break
                if not part:
                    break
                combined.extend(part)
        finally:
            source.settimeout(previous_timeout)
        return bytes(combined), self._frame_count(combined) >= 2

    def _forward(
        self,
        source: socket.socket,
        target: socket.socket,
        direction: str,
    ) -> None:
        try:
            while not self._stop.is_set():
                data = source.recv(65535)
                if not data:
                    try:
                        target.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    return
                action = self._take_action(direction)
                if action == "fragment":
                    offsets = (1, 3, 6, 11)
                    start = 0
                    for end in (*offsets, len(data)):
                        if end <= start:
                            continue
                        target.sendall(data[start:end])
                        start = end
                        time.sleep(0.002)
                    self._record(f"{direction}_fragment")
                    continue
                if action == "coalesce":
                    data, complete = self._coalesce(source, data)
                    target.sendall(data)
                    self._record(
                        f"{direction}_coalesce"
                        if complete
                        else f"{direction}_coalesce_timeout"
                    )
                    continue
                target.sendall(data)
        except OSError:
            return

    def _serve(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            with self._lock:
                if self._interrupted:
                    return
            upstream = socket.create_connection(self._target_address, timeout=1.0)
            upstream.settimeout(None)
            client.settimeout(None)
            with self._lock:
                self._session_sockets.add(upstream)
            workers = (
                threading.Thread(
                    target=self._forward,
                    args=(client, upstream, "radio_to_mic"),
                    daemon=True,
                ),
                threading.Thread(
                    target=self._forward,
                    args=(upstream, client, "mic_to_radio"),
                    daemon=True,
                ),
            )
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        except OSError:
            return
        finally:
            for stream in (client, upstream):
                if stream is None:
                    continue
                with self._lock:
                    self._session_sockets.discard(stream)
                try:
                    stream.close()
                except OSError:
                    pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with self._lock:
                interrupted = self._interrupted
                if not interrupted:
                    self._session_sockets.add(client)
            if interrupted:
                client.close()
                continue
            session = threading.Thread(
                target=self._serve,
                args=(client,),
                name="commandmic-conformance-tcp-session",
                daemon=True,
            )
            self._session_threads.append(session)
            session.start()

    def close(self) -> None:
        self._stop.set()
        self._listener.close()
        with self._lock:
            streams = tuple(self._session_sockets)
        for stream in streams:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                stream.close()
            except OSError:
                pass
        self._thread.join(timeout=1.0)
        for session in self._session_threads:
            session.join(timeout=1.0)


def _free_port(socket_type: socket.SocketKind) -> int:
    with socket.socket(socket.AF_INET, socket_type) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for(predicate: Callable[[], bool], timeout: float, description: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise TimeoutError(f"timed out waiting for {description}")


def _read_worker_response(
    process: subprocess.Popen[str], timeout: float
) -> dict[str, object]:
    if process.stdout is None:
        raise RuntimeError("conformance worker stdout is unavailable")
    result: queue.Queue[str] = queue.Queue(maxsize=1)
    reader = threading.Thread(
        target=lambda: result.put(process.stdout.readline()),
        name="commandmic-conformance-worker-reader",
        daemon=True,
    )
    reader.start()
    try:
        line = result.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("timed out waiting for conformance worker response") from exc
    if not line:
        stderr = ""
        if process.poll() is not None and process.stderr is not None:
            stderr = process.stderr.read().strip()
        raise RuntimeError(
            "conformance worker exited without a response"
            + (f": {stderr}" if stderr else "")
        )
    response = json.loads(line)
    if not isinstance(response, dict):
        raise RuntimeError(f"invalid conformance worker response: {response!r}")
    if response.get("ok") is not True:
        raise RuntimeError(f"conformance worker rejected request: {response!r}")
    return response


def _start_commandmic_worker(
    *,
    local_ip: str,
    radio_ip: str,
    control_port: int,
    audio_port: int,
    audit_path: Path,
    timeout: float,
) -> subprocess.Popen[str]:
    command = [
        sys.executable,
        "-m",
        "ip_commandmic._conformance_worker",
        "--local-ip",
        local_ip,
        "--radio-ip",
        radio_ip,
        "--control-port",
        str(control_port),
        "--audio-port",
        str(audio_port),
        "--audit-path",
        str(audit_path),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        creationflags=(
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        ),
    )
    try:
        _read_worker_response(process, timeout)
    except Exception:
        process.kill()
        process.wait(timeout=5.0)
        raise
    return process


def _worker_request(
    process: subprocess.Popen[str], request: dict[str, object], timeout: float
) -> dict[str, object]:
    if process.stdin is None or process.poll() is not None:
        raise RuntimeError("conformance worker is not running")
    process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    process.stdin.flush()
    return _read_worker_response(process, timeout)


def _stop_commandmic_worker(process: subprocess.Popen[str], timeout: float) -> None:
    if process.poll() is not None:
        return
    try:
        _worker_request(process, {"op": "stop"}, timeout)
        process.wait(timeout=timeout)
    except Exception:
        process.kill()
        process.wait(timeout=5.0)


def _run_subprocess_replacement_conformance(
    artifact_root: Path, timeout_seconds: float
) -> str:
    """Abruptly replace one endpoint process while its peer remains alive."""

    control_port = _free_port(socket.SOCK_STREAM)
    audio_port = _free_port(socket.SOCK_DGRAM)
    while audio_port == control_port:
        audio_port = _free_port(socket.SOCK_DGRAM)
    radio_ip = "127.0.0.1"
    mic_ip = "127.0.0.2"
    radio = SoftwareRadioEndpoint(
        SoftwareRadioConfig(
            local_ip=radio_ip,
            mic_ip=mic_ip,
            control_port=control_port,
            audio_port=audio_port,
            startup_opening_text="",
            startup_idle_text="SUBPROC",
            startup_status_carousel=False,
            idle_display_text="SUBPROC",
        ),
        artifact_root / "subprocess-radio.jsonl",
    )
    worker: subprocess.Popen[str] | None = None
    replacement: subprocess.Popen[str] | None = None
    try:
        worker = _start_commandmic_worker(
            local_ip=mic_ip,
            radio_ip=radio_ip,
            control_port=control_port,
            audio_port=audio_port,
            audit_path=artifact_root / "subprocess-commandmic-1.jsonl",
            timeout=timeout_seconds,
        )
        radio.start()

        def both_ready(process: subprocess.Popen[str]) -> bool:
            response = _worker_request(
                process, {"op": "snapshot"}, timeout_seconds
            )
            state = response.get("state")
            return (
                isinstance(state, dict)
                and state.get("controls_ready") is True
                and state.get("session") == "stable"
                and radio.state.snapshot(include_events=False)["controls_ready"]
                is True
            )

        _wait_for(
            lambda: both_ready(worker),
            timeout_seconds,
            "initial cross-process endpoints to reach stable controls",
        )
        _worker_request(
            worker,
            {"op": "key", "button": "p1", "action": "press"},
            timeout_seconds,
        )
        _wait_for(
            lambda: radio.state.snapshot(include_events=False)["buttons"].get("p1")
            is True,
            timeout_seconds,
            "cross-process P1 press",
        )
        _worker_request(
            worker,
            {"op": "key", "button": "p1", "action": "release"},
            timeout_seconds,
        )
        _wait_for(
            lambda: radio.state.snapshot(include_events=False)["buttons"].get("p1")
            is False,
            timeout_seconds,
            "cross-process P1 release",
        )

        worker.kill()
        worker.wait(timeout=5.0)
        _wait_for(
            lambda: not bool(
                radio.state.snapshot(include_events=False)["controls_ready"]
            )
            and not bool(radio.state.snapshot(include_events=False)["ptt"])
            and radio.state.snapshot(include_events=False)["buttons"] == {},
            timeout_seconds,
            "radio endpoint to fail closed after abrupt peer-process death",
        )

        replacement = _start_commandmic_worker(
            local_ip=mic_ip,
            radio_ip=radio_ip,
            control_port=control_port,
            audio_port=audio_port,
            audit_path=artifact_root / "subprocess-commandmic-2.jsonl",
            timeout=timeout_seconds,
        )
        _wait_for(
            lambda: both_ready(replacement),
            timeout_seconds,
            "replacement CommandMic process to reach stable controls",
        )
        expected = DisplayBuffer(b"NEWPROC!" + bytes(60))
        radio.send_display(expected)

        def replacement_has_display() -> bool:
            response = _worker_request(
                replacement, {"op": "snapshot"}, timeout_seconds
            )
            state = response.get("state")
            return isinstance(state, dict) and (
                state.get("display") or {}
            ).get("raw_hex") == expected.raw.hex()

        _wait_for(
            replacement_has_display,
            timeout_seconds,
            "exact display delivery to replacement CommandMic process",
        )
        _worker_request(
            replacement,
            {"op": "key", "button": "p2", "action": "press"},
            timeout_seconds,
        )
        _wait_for(
            lambda: radio.state.snapshot(include_events=False)["buttons"].get("p2")
            is True,
            timeout_seconds,
            "replacement-process P2 press",
        )
        _worker_request(
            replacement,
            {"op": "key", "button": "p2", "action": "release"},
            timeout_seconds,
        )
        _wait_for(
            lambda: radio.state.snapshot(include_events=False)["buttons"].get("p2")
            is False,
            timeout_seconds,
            "replacement-process P2 release",
        )
        return (
            "an abruptly terminated CommandMic child process cleared the live "
            "radio endpoint state; a fresh child reached stable operation and "
            "passed exact display plus bidirectional key checks"
        )
    finally:
        radio.stop()
        if replacement is not None:
            _stop_commandmic_worker(replacement, timeout_seconds)
        if worker is not None:
            _stop_commandmic_worker(worker, timeout_seconds)


def run_loopback_conformance(
    artifact_directory: str | Path,
    *,
    timeout_seconds: float = 20.0,
    sustained_audio_seconds: float = 1.0,
    cold_restart_cycles: int = 3,
) -> ConformanceReport:
    """Exercise both public endpoints entirely on the local loopback network.

    No physical radio, CommandMic, microphone, speaker, or external network is
    addressed. Both audio directions use deterministic in-process sources and
    sinks; no local capture or playback device is opened.
    """

    if sustained_audio_seconds < 1.0 or sustained_audio_seconds > 1800.0:
        raise ValueError("sustained_audio_seconds must be between 1 and 1800")
    if cold_restart_cycles < 1 or cold_restart_cycles > 100:
        raise ValueError("cold_restart_cycles must be between 1 and 100")

    started = time.monotonic()
    artifact_root = Path(artifact_directory)
    artifact_root.mkdir(parents=True, exist_ok=True)
    mic_audit = artifact_root / "software-commandmic.jsonl"
    radio_audit = artifact_root / "software-radio.jsonl"
    control_port = _free_port(socket.SOCK_STREAM)
    audio_port = _free_port(socket.SOCK_DGRAM)
    while audio_port == control_port:
        audio_port = _free_port(socket.SOCK_DGRAM)

    radio_ip = "127.0.0.1"
    mic_ip = "127.0.0.2"
    proxy_ip = "127.0.0.3"
    udp_proxy = _LoopbackUdpImpairmentProxy(
        listen_ip=proxy_ip,
        port=audio_port,
        radio_address=(radio_ip, audio_port),
        mic_address=(mic_ip, audio_port),
    )
    tcp_proxy = _LoopbackTcpImpairmentProxy(
        listen_ip=proxy_ip,
        port=control_port,
        target_address=(mic_ip, control_port),
    )
    udp_proxy.start()
    tcp_proxy.start()

    def make_endpoints() -> tuple[
        BufferedMicrophoneSource,
        _ConformanceRadioAudioSink,
        SoftwareCommandMicEndpoint,
        SoftwareRadioEndpoint,
    ]:
        source = BufferedMicrophoneSource(queue_packets=1)
        sink = _ConformanceRadioAudioSink(prebuffer_packets=2)
        commandmic = SoftwareCommandMicEndpoint(
            local_ip=mic_ip,
            radio_ip=radio_ip,
            microphone_device=None,
            enable_tx=True,
            play_rx_audio=False,
            audit_path=mic_audit,
            control_port=control_port,
            audio_port=audio_port,
            audio_peer_ip=proxy_ip,
            tx_audio_source=source,
            rx_audio_sink=sink,
        )
        software_radio = SoftwareRadioEndpoint(
            SoftwareRadioConfig(
                local_ip=radio_ip,
                mic_ip=mic_ip,
                control_port=control_port,
                control_peer_ip=proxy_ip,
                control_source_port=0,
                audio_port=audio_port,
                audio_peer_ip=proxy_ip,
                startup_opening_text="",
                startup_idle_text="IDLE",
                startup_status_carousel=False,
                speaker_volume=25,
                idle_display_text="IDLE",
                automatic_ptt_responses=True,
            ),
            radio_audit,
        )
        return source, sink, commandmic, software_radio

    tx_source, rx_sink, mic, radio = make_endpoints()
    checks: list[ConformanceCheck] = []

    def check(name: str, action: Callable[[], str]) -> bool:
        try:
            detail = action()
        except Exception as exc:
            checks.append(
                ConformanceCheck(name, "failed", f"{type(exc).__name__}: {exc}")
            )
            return False
        checks.append(ConformanceCheck(name, "passed", detail))
        return True

    def mic_capture_count() -> int:
        return int(
            radio.state.snapshot(include_events=False)["mic_capture_count"]
        )

    def last_mic_capture() -> dict[str, object]:
        capture = radio.state.snapshot(include_events=False)["last_mic_capture"]
        if not isinstance(capture, dict):
            raise AssertionError("microphone capture summary is unavailable")
        return capture

    try:
        mic.start()
        radio.start()

        def stable_startup() -> str:
            _wait_for(
                lambda: bool(mic.state.snapshot()["controls_ready"])
                and bool(radio.state.snapshot(include_events=False)["controls_ready"]),
                timeout_seconds,
                "both public endpoints to reach controls-ready",
            )
            mic_state = mic.state.snapshot()
            radio_state = radio.state.snapshot(include_events=False)
            if mic_state["session"] != "stable" or radio_state["session"] != "stable":
                raise AssertionError(
                    f"unexpected sessions: mic={mic_state['session']!r}, "
                    f"radio={radio_state['session']!r}"
                )
            return "both endpoints reached a stable, controls-ready session"

        ready = check("stable_startup", stable_startup)
        if ready:
            def display_round_trip() -> str:
                corpus = (
                    DisplayBuffer(bytes(68)),
                    DisplayBuffer(b"CONFTEST" + bytes(60)),
                    DisplayBuffer(bytes(range(68))),
                )
                for index, expected in enumerate(corpus, start=1):
                    radio.send_display(expected)
                    _wait_for(
                        lambda expected=expected: (
                            mic.state.snapshot().get("display") or {}
                        ).get("raw_hex")
                        == expected.raw.hex(),
                        timeout_seconds,
                        f"exact sanitized display corpus member {index}",
                    )
                return "3 exact synthetic 68-byte display buffers arrived through the typed API"

            check("display_round_trip", display_round_trip)

            def led_round_trip() -> str:
                colors = ("off", "red", "green", "orange")
                for color in colors:
                    radio.send_led(color)
                    _wait_for(
                        lambda color=color: mic.state.snapshot()["status_led"] == color,
                        timeout_seconds,
                        f"{color} status LED state",
                    )
                return "all 4 status LED states arrived through the typed API"

            check("status_led_round_trip", led_round_trip)

            def key_round_trip() -> str:
                for button in ORDINARY_KEY_BUTTONS:
                    mic.key(button, "press")
                    _wait_for(
                        lambda button=button: radio.state.snapshot(
                            include_events=False
                        )["buttons"].get(button)
                        is True,
                        timeout_seconds,
                        f"{button} press",
                    )
                    mic.key(button, "release")
                    _wait_for(
                        lambda button=button: radio.state.snapshot(
                            include_events=False
                        )["buttons"].get(button)
                        is False,
                        timeout_seconds,
                        f"{button} release",
                    )
                return "all 23 ordinary key identities completed press and release"

            check("key_press_release", key_round_trip)

            def power_round_trip() -> str:
                started_at = time.time()
                mic.tap("power")

                def power_states() -> list[bool]:
                    states: list[bool] = []
                    for event in radio.state.snapshot()["events"]:
                        if event.get("time", 0.0) < started_at:
                            continue
                        data = event.get("data")
                        if not isinstance(data, dict) or data.get("kind") != "power_state":
                            continue
                        metadata = data.get("metadata")
                        if isinstance(metadata, dict):
                            states.append(bool(metadata.get("power_active")))
                    return states

                _wait_for(
                    lambda: power_states()[-2:] == [True, False],
                    timeout_seconds,
                    "Power press and release",
                )
                return "Power press and release arrived through the typed API"

            check("power_press_release", power_round_trip)

            def backlight_round_trip() -> str:
                for state in ("off", "dim", "on"):
                    cursor, _ = mic.state.debug_events(0)
                    radio.send_backlight(state)

                    def observed(state: str = state, cursor: int = cursor) -> bool:
                        _, events = mic.state.debug_events(cursor)
                        return any(
                            event["event"] == "received"
                            and event["data"].get("kind") == "backlight_state"
                            and isinstance(event["data"].get("metadata"), dict)
                            and event["data"]["metadata"].get("backlight_state") == state
                            for event in events
                        )

                    _wait_for(
                        observed,
                        timeout_seconds,
                        f"{state} backlight state",
                    )
                return "off, dim and on backlight states arrived through the typed API"

            check("backlight_round_trip", backlight_round_trip)

            def mic_gain_round_trip() -> str:
                for level in range(1, 6):
                    cursor, _ = mic.state.debug_events(0)
                    observed_level = radio.set_mic_gain(level)
                    if observed_level != level:
                        raise AssertionError(
                            f"set_mic_gain({level}) returned {observed_level!r}"
                        )

                    def gain_pair(level: int = level, cursor: int = cursor) -> bool:
                        _, events = mic.state.debug_events(cursor)
                        values = [
                            event["data"]["metadata"].get("mic_gain_value")
                            for event in events
                            if event["event"] == "received"
                            and event["data"].get("kind") == "mic_gain"
                            and isinstance(event["data"].get("metadata"), dict)
                        ]
                        return values[-2:] == [level, level + 1]

                    _wait_for(
                        gain_pair,
                        timeout_seconds,
                        f"microphone gain {level}/{level + 1} transaction",
                    )
                return "all verified microphone gain transactions 1 through 5 arrived"

            check("microphone_gain_round_trip", mic_gain_round_trip)

            def tcp_fragmentation_coalescing() -> str:
                fragmented_display = DisplayBuffer(b"FRAGMENT" + bytes(60))
                tcp_proxy.arm("radio_to_mic", "fragment")
                radio.send_display(fragmented_display)
                _wait_for(
                    lambda: (mic.state.snapshot().get("display") or {}).get("raw_hex")
                    == fragmented_display.raw.hex(),
                    timeout_seconds,
                    "fragmented radio-to-CommandMic display transaction",
                )

                tcp_proxy.arm("mic_to_radio", "fragment")
                mic.key("p1", "press")
                _wait_for(
                    lambda: radio.state.snapshot(include_events=False)["buttons"].get("p1")
                    is True,
                    timeout_seconds,
                    "fragmented CommandMic-to-radio key press",
                )

                coalesced_display = DisplayBuffer(b"COALESCE" + bytes(60))
                tcp_proxy.arm("radio_to_mic", "coalesce")
                radio.send_display(coalesced_display)
                _wait_for(
                    lambda: (mic.state.snapshot().get("display") or {}).get("raw_hex")
                    == coalesced_display.raw.hex(),
                    timeout_seconds,
                    "coalesced radio-to-CommandMic display transaction",
                )

                tcp_proxy.arm("mic_to_radio", "coalesce")
                mic.key("p1", "release")
                _wait_for(
                    lambda: radio.state.snapshot(include_events=False)["buttons"].get("p1")
                    is False,
                    timeout_seconds,
                    "coalesced CommandMic-to-radio key release and neutral",
                )

                expected = {
                    "radio_to_mic_fragment": 1,
                    "radio_to_mic_coalesce": 1,
                    "mic_to_radio_fragment": 1,
                    "mic_to_radio_coalesce": 1,
                }
                stats = tcp_proxy.stats
                observed = {name: stats[name] for name in expected}
                if observed != expected:
                    raise AssertionError(f"unexpected TCP relay actions: {stats}")
                if any(
                    value
                    for name, value in stats.items()
                    if name.endswith("coalesce_timeout")
                ):
                    raise AssertionError(f"TCP coalescing timed out: {stats}")
                return (
                    "both endpoint parsers accepted intentionally fragmented "
                    "frames and coalesced multi-frame writes in both directions"
                )

            check("tcp_fragmentation_coalescing", tcp_fragmentation_coalescing)

            def radio_audio_round_trip() -> str:
                cursor, _ = mic.state.debug_events(0)
                packets = radio.send_tone(800.0, -12.0, 0.04)
                if packets != 2:
                    raise AssertionError(f"expected 2 tone packets, got {packets}")

                def audio_complete() -> bool:
                    _, events = mic.state.debug_events(cursor)
                    names = [str(event["event"]) for event in events]
                    states = [
                        event["data"].get("audio_state")
                        for event in events
                        if event["event"] == "accepted_verified_radio_audio_state"
                    ]
                    return (
                        names.count("mic_udp_received") >= 2
                        and "receive_open" in states
                        and "closed" in states
                    )

                _wait_for(audio_complete, timeout_seconds, "radio audio open, RTP, and close")
                return "2 RTP packets arrived between verified receive-open and close states"

            check("radio_to_commandmic_audio", radio_audio_round_trip)

            def radio_rtp_impairment_recovery() -> str:
                def run_audio(*, impaired: bool, duration: float) -> dict[str, object]:
                    prior_summaries = len(rx_sink.summaries)
                    udp_proxy.set_radio_rtp_impairment(impaired)
                    packets = radio.send_tone(1000.0, -12.0, duration)
                    _wait_for(
                        lambda: len(rx_sink.summaries) > prior_summaries,
                        timeout_seconds,
                        "radio RTP jitter-buffer gate summary",
                    )
                    summary = rx_sink.summaries[-1]
                    if int(summary["source_packets"]) != packets:
                        # One drop and one duplicate leave the protocol-facing
                        # packet count equal to the source count.
                        raise AssertionError(
                            f"unexpected radio gate packet count: {summary}"
                        )
                    return summary

                impaired = run_audio(impaired=True, duration=0.20)
                impairment_stats = udp_proxy.radio_stats
                if impairment_stats != {
                    "dropped": 1,
                    "duplicated": 1,
                    "reordered": 1,
                }:
                    raise AssertionError(
                        f"unexpected radio RTP impairment actions: {impairment_stats}"
                    )
                if impaired["concealed"] != 1:
                    raise AssertionError(f"lost packet was not concealed once: {impaired}")
                if impaired["duplicates"] != 1:
                    raise AssertionError(f"duplicate was not rejected once: {impaired}")
                if impaired["late"] != 0 or impaired["discontinuities"] != 0:
                    raise AssertionError(f"bounded reorder was not recovered: {impaired}")
                if impaired["concealed_sequences"] == []:
                    raise AssertionError(f"concealed sequence was not recorded: {impaired}")
                if impaired["concealment_is_silence"] is not True:
                    raise AssertionError(f"concealment was not exact silence: {impaired}")
                sequences = list(impaired["sequences"])
                if len(sequences) != 10 or any(
                    current != ((prior + 1) & 0xFFFF)
                    for prior, current in zip(sequences, sequences[1:])
                ):
                    raise AssertionError(f"playout was not continuous: {impaired}")

                recovered = run_audio(impaired=False, duration=0.12)
                for field in ("concealed", "duplicates", "late", "discontinuities"):
                    if recovered[field] != 0:
                        raise AssertionError(
                            f"clean receive gate retained {field}: {recovered}"
                        )
                recovered_sequences = list(recovered["sequences"])
                if len(recovered_sequences) != 6 or any(
                    current != ((prior + 1) & 0xFFFF)
                    for prior, current in zip(
                        recovered_sequences, recovered_sequences[1:]
                    )
                ):
                    raise AssertionError(
                        f"clean receive playout was not continuous: {recovered}"
                    )
                return (
                    "one lost radio RTP frame became exact silence, a duplicate "
                    "was rejected, bounded reorder played in sequence, and the "
                    "next receive gate was clean"
                )

            check("radio_rtp_impairment_recovery", radio_rtp_impairment_recovery)

            def commandmic_audio_round_trip() -> str:
                prior_capture_count = mic_capture_count()
                before = int(
                    radio.state.snapshot(include_events=False)["audio_packets"]
                )
                payload = b"\x10\x00" * 160
                feeder_stop = threading.Event()

                def feed() -> None:
                    while not feeder_stop.is_set():
                        try:
                            tx_source.push_payload(payload)
                        except RuntimeError:
                            return
                        time.sleep(0.005)

                feeder = threading.Thread(
                    target=feed, name="commandmic-conformance-audio", daemon=True
                )
                feeder.start()
                try:
                    mic.ptt("press")
                    _wait_for(
                        lambda: bool(
                            radio.state.snapshot(include_events=False)["ptt"]
                        )
                        and int(
                            radio.state.snapshot(include_events=False)["audio_packets"]
                        )
                        >= before + 3
                        and float(
                            radio.state.snapshot(include_events=False)["audio_rms"]
                        )
                        > 0.0,
                        timeout_seconds,
                        "PTT-gated application audio at the radio endpoint",
                    )
                    if tx_source.stats.overwritten < 1:
                        raise AssertionError(
                            "fast producer did not exercise newest-frame overwrite"
                        )
                    feeder_stop.set()
                    feeder.join(timeout=1.0)
                    silence_start = int(
                        radio.state.snapshot(include_events=False)["audio_packets"]
                    )
                    _wait_for(
                        lambda: int(
                            radio.state.snapshot(include_events=False)["audio_packets"]
                        )
                        >= silence_start + 3
                        and float(
                            radio.state.snapshot(include_events=False)["audio_rms"]
                        )
                        == 0.0,
                        timeout_seconds,
                        "fail-silent application-audio underrun",
                    )
                    mic.ptt("release")
                    _wait_for(
                        lambda: not bool(mic.state.snapshot()["ptt_active"])
                        and not bool(
                            radio.state.snapshot(include_events=False)["ptt"]
                        ),
                        timeout_seconds,
                        "PTT release at both endpoints",
                    )

                    _wait_for(
                        lambda: mic_capture_count() > prior_capture_count,
                        timeout_seconds,
                        "microphone RTP capture continuity summary",
                    )
                finally:
                    feeder_stop.set()
                    feeder.join(timeout=1.0)
                    if mic.state.snapshot()["ptt_active"]:
                        mic.ptt("release")
                delivered = tx_source.stats.delivered
                if delivered < 1:
                    raise AssertionError("application source delivered no frames")
                if tx_source.stats.underruns < 3:
                    raise AssertionError("application source underrun was not exercised")
                completion = last_mic_capture()
                if completion.get("sequence_errors") != 0:
                    raise AssertionError(
                        f"microphone RTP sequence errors: {completion}"
                    )
                if completion.get("timestamp_errors") != 0:
                    raise AssertionError(
                        f"microphone RTP timestamp errors: {completion}"
                    )
                return (
                    "overwriting application-fed s16be audio produced continuous "
                    "PTT-gated RTP, then underrun silence and clean release "
                    f"({completion.get('packets')} packets)"
                )

            check("commandmic_to_radio_live_audio", commandmic_audio_round_trip)

            def mic_rtp_impairment_recovery() -> str:
                def run_hold(*, impaired: bool) -> dict[str, object]:
                    prior_completions = mic_capture_count()
                    prior_packets = int(
                        radio.state.snapshot(include_events=False)["audio_packets"]
                    )
                    stop_feed = threading.Event()
                    payload = b"\x18\x00" * 160

                    def feed() -> None:
                        while not stop_feed.is_set():
                            try:
                                tx_source.push_payload(payload)
                            except RuntimeError:
                                return
                            time.sleep(0.005)

                    udp_proxy.set_mic_rtp_impairment(impaired)
                    feeder = threading.Thread(
                        target=feed,
                        name="commandmic-impairment-audio",
                        daemon=True,
                    )
                    feeder.start()
                    try:
                        mic.ptt("press")
                        _wait_for(
                            lambda: bool(
                                radio.state.snapshot(include_events=False)["ptt"]
                            )
                            and int(
                                radio.state.snapshot(include_events=False)[
                                    "audio_packets"
                                ]
                            )
                            >= prior_packets + 9,
                            timeout_seconds,
                            "impaired microphone RTP hold",
                        )
                        mic.ptt("release")
                        _wait_for(
                            lambda: not bool(mic.state.snapshot()["ptt_active"])
                            and not bool(
                                radio.state.snapshot(include_events=False)["ptt"]
                            ),
                            timeout_seconds,
                            "impaired PTT release",
                        )
                        _wait_for(
                            lambda: mic_capture_count() > prior_completions,
                            timeout_seconds,
                            "impaired microphone capture summary",
                        )
                    finally:
                        stop_feed.set()
                        feeder.join(timeout=1.0)
                        if mic.state.snapshot()["ptt_active"]:
                            mic.ptt("release")
                    return last_mic_capture()

                impaired = run_hold(impaired=True)
                impairment_stats = udp_proxy.stats
                if impairment_stats != {
                    "dropped": 1,
                    "duplicated": 1,
                    "reordered": 1,
                }:
                    raise AssertionError(
                        f"unexpected impairment actions: {impairment_stats}"
                    )
                if int(impaired.get("sequence_errors", 0)) < 1:
                    raise AssertionError(f"packet loss/order was not detected: {impaired}")
                if int(impaired.get("timestamp_errors", 0)) < 1:
                    raise AssertionError(f"timestamp disorder was not detected: {impaired}")

                recovered = run_hold(impaired=False)
                if recovered.get("sequence_errors") != 0:
                    raise AssertionError(f"sequence recovery failed: {recovered}")
                if recovered.get("timestamp_errors") != 0:
                    raise AssertionError(f"timestamp recovery failed: {recovered}")
                return (
                    "deterministic drop, duplicate, and reorder were detected; "
                    "the next PTT capture recovered with zero continuity errors"
                )

            check("mic_rtp_impairment_recovery", mic_rtp_impairment_recovery)

            def sustained_bidirectional_audio() -> str:
                sustained_packets = round(sustained_audio_seconds / 0.020)
                sustained_duration = sustained_packets * 0.020
                sustained_timeout = max(
                    timeout_seconds, sustained_duration + 5.0
                )

                def percentile(samples: list[float], fraction: float) -> float:
                    ordered = sorted(samples)
                    index = min(
                        len(ordered) - 1,
                        int((len(ordered) - 1) * fraction + 0.999999),
                    )
                    return ordered[index]

                udp_proxy.set_radio_rtp_impairment(False)
                udp_proxy.reset_radio_timing()
                prior_summaries = len(rx_sink.summaries)
                radio_packets = radio.send_tone(
                    1200.0, -15.0, sustained_duration
                )
                if radio_packets != sustained_packets:
                    raise AssertionError(
                        f"expected {sustained_packets} sustained radio packets, "
                        f"got {radio_packets}"
                    )
                _wait_for(
                    lambda: len(rx_sink.summaries) > prior_summaries,
                    sustained_timeout,
                    "sustained radio receive summary",
                )
                radio_summary = rx_sink.summaries[-1]
                radio_arrivals = udp_proxy.radio_arrival_times
                callback_times = list(radio_summary["callback_times"])
                if len(radio_arrivals) != sustained_packets:
                    raise AssertionError(
                        f"radio timing covered only {len(radio_arrivals)} packets"
                    )
                _assert_continuous_rtp_timeline(
                    radio_arrivals, label="sustained radio wire"
                )
                callback_latency_ms = _rtp_callback_latencies_ms(
                    radio_arrivals, callback_times
                )
                concealed, concealment_budget = _validate_sustained_radio_playout(
                    radio_summary, expected_packets=sustained_packets
                )
                callback_median = statistics.median(callback_latency_ms)
                callback_p95 = percentile(callback_latency_ms, 0.95)
                callback_max = max(callback_latency_ms)
                if callback_p95 > 20.0 or callback_max > 100.0:
                    raise AssertionError(
                        "receive validation-to-callback latency exceeded its "
                        "p95/max budget: "
                        f"p95={callback_p95:.3f} ms, max={callback_max:.3f} ms"
                    )
                radio_wire_span = (
                    radio_arrivals[-1][1] - radio_arrivals[0][1]
                )
                minimum_radio_span = (sustained_packets - 1) * 0.018
                if radio_wire_span < minimum_radio_span:
                    raise AssertionError(
                        "radio RTP compressed into a catch-up burst: "
                        f"{radio_wire_span:.3f}s < {minimum_radio_span:.3f}s"
                    )
                radio_completion = next(
                    event["data"]
                    for event in reversed(radio.state.snapshot()["events"])
                    if event["event"] == "rx_audio_completed"
                    and event["data"].get("packet_count") == sustained_packets
                )
                radio_late = float(radio_completion["max_late_ms"])
                if radio_late > 100.0:
                    raise AssertionError(
                        f"radio sender deadline lateness exceeded 100 ms: {radio_completion}"
                    )

                udp_proxy.set_mic_rtp_impairment(False)
                udp_proxy.reset_mic_timing()
                prior_completions = mic_capture_count()
                prior_packets = int(
                    radio.state.snapshot(include_events=False)["audio_packets"]
                )
                cursor, _ = mic.state.debug_events(0)
                stop_feed = threading.Event()
                payload = b"\x20\x00" * 160

                def feed() -> None:
                    while not stop_feed.is_set():
                        try:
                            tx_source.push_payload(payload)
                        except RuntimeError:
                            return
                        time.sleep(0.005)

                feeder = threading.Thread(
                    target=feed,
                    name="commandmic-sustained-audio",
                    daemon=True,
                )
                feeder.start()
                try:
                    mic.ptt("press")
                    _wait_for(
                        lambda: int(
                            radio.state.snapshot(include_events=False)["audio_packets"]
                        )
                        >= prior_packets + sustained_packets,
                        sustained_timeout,
                        f"{sustained_packets} sustained microphone RTP packets",
                    )
                    mic.ptt("release")
                    _wait_for(
                        lambda: mic_capture_count() > prior_completions,
                        sustained_timeout,
                        "sustained microphone capture summary",
                    )
                    _wait_for(
                        lambda: not bool(mic.state.snapshot()["ptt_active"])
                        and not bool(
                            radio.state.snapshot(include_events=False)["ptt"]
                        ),
                        sustained_timeout,
                        "sustained PTT release",
                    )
                finally:
                    stop_feed.set()
                    feeder.join(timeout=1.0)
                    if mic.state.snapshot()["ptt_active"]:
                        mic.ptt("release")
                mic_completion = last_mic_capture()
                if mic_completion.get("sequence_errors") != 0 or mic_completion.get(
                    "timestamp_errors"
                ) != 0:
                    raise AssertionError(
                        f"sustained microphone continuity failed: {mic_completion}"
                    )
                if int(mic_completion.get("packets", 0)) < sustained_packets:
                    raise AssertionError(
                        f"sustained microphone capture was too short: {mic_completion}"
                    )
                _, mic_events = mic.state.debug_events(cursor)
                mic_tx_completion = next(
                    event["data"]
                    for event in reversed(mic_events)
                    if event["event"] == "mic_tx_audio_completed"
                )
                mic_late = float(mic_tx_completion["max_late_ms"])
                if mic_late > 100.0:
                    raise AssertionError(
                        f"microphone sender deadline lateness exceeded 100 ms: "
                        f"{mic_tx_completion}"
                    )
                mic_arrivals = udp_proxy.mic_arrival_times
                if len(mic_arrivals) < sustained_packets:
                    raise AssertionError(
                        f"microphone timing covered only {len(mic_arrivals)} packets"
                    )
                mic_wire_span = mic_arrivals[-1][1] - mic_arrivals[0][1]
                minimum_span = (len(mic_arrivals) - 1) * 0.018
                if mic_wire_span < minimum_span:
                    raise AssertionError(
                        f"microphone RTP compressed into a catch-up burst: "
                        f"{mic_wire_span:.3f}s < {minimum_span:.3f}s"
                    )
                return (
                    f"{sustained_packets} radio RTP packets and "
                    f"{mic_completion.get('packets')} "
                    "microphone RTP packets remained continuous; radio playout "
                    f"isolated concealments/budget={concealed}/{concealment_budget}; "
                    "receive callback "
                    f"latency median/p95/max={callback_median:.3f}/"
                    f"{callback_p95:.3f}/{callback_max:.3f} ms; sender max lateness "
                    f"radio/mic={radio_late:.3f}/{mic_late:.3f} ms"
                )

            check("sustained_bidirectional_audio", sustained_bidirectional_audio)

            def midstream_cancellation_recovery() -> str:
                udp_proxy.set_mic_rtp_impairment(False)
                udp_proxy.reset_mic_timing()
                prior_completions = mic_capture_count()
                prior_packets = int(
                    radio.state.snapshot(include_events=False)["audio_packets"]
                )
                stop_feed = threading.Event()
                payload = b"\x28\x00" * 160

                def feed() -> None:
                    while not stop_feed.is_set():
                        try:
                            tx_source.push_payload(payload)
                        except RuntimeError:
                            return
                        time.sleep(0.005)

                feeder = threading.Thread(
                    target=feed,
                    name="commandmic-cancelled-audio",
                    daemon=True,
                )
                feeder.start()
                try:
                    mic.ptt("press")
                    _wait_for(
                        lambda: bool(
                            radio.state.snapshot(include_events=False)["ptt"]
                        )
                        and int(
                            radio.state.snapshot(include_events=False)["audio_packets"]
                        )
                        >= prior_packets + 10,
                        timeout_seconds,
                        "active microphone stream before endpoint cancellation",
                    )
                    stop_started = time.perf_counter()
                    mic.stop()
                    mic_stop_seconds = time.perf_counter() - stop_started
                finally:
                    stop_feed.set()
                    feeder.join(timeout=1.0)
                if mic_stop_seconds > 3.0:
                    raise AssertionError(
                        f"CommandMic mid-PTT stop took {mic_stop_seconds:.3f}s"
                    )
                _wait_for(
                    lambda: not bool(
                        radio.state.snapshot(include_events=False)["ptt"]
                    )
                    and not bool(
                        radio.state.snapshot(include_events=False)["controls_ready"]
                    )
                    and mic_capture_count() > prior_completions,
                    timeout_seconds,
                    "radio fail-closed state after CommandMic cancellation",
                )
                cancelled_capture = last_mic_capture()
                if cancelled_capture.get("sequence_errors") != 0 or cancelled_capture.get(
                    "timestamp_errors"
                ) != 0:
                    raise AssertionError(
                        f"cancelled microphone capture was discontinuous: "
                        f"{cancelled_capture}"
                    )
                mic_arrivals_after_stop = len(udp_proxy.mic_arrival_times)
                time.sleep(0.10)
                if len(udp_proxy.mic_arrival_times) != mic_arrivals_after_stop:
                    raise AssertionError("microphone RTP continued after endpoint stop")

                mic.start()
                _wait_for(
                    lambda: bool(mic.state.snapshot()["controls_ready"])
                    and bool(
                        radio.state.snapshot(include_events=False)["controls_ready"]
                    ),
                    timeout_seconds,
                    "CommandMic restart after mid-PTT cancellation",
                )

                fresh_prior = mic_capture_count()
                fresh_packets = int(
                    radio.state.snapshot(include_events=False)["audio_packets"]
                )
                fresh_stop = threading.Event()

                def feed_fresh() -> None:
                    while not fresh_stop.is_set():
                        try:
                            tx_source.push_payload(b"\x30\x00" * 160)
                        except RuntimeError:
                            return
                        time.sleep(0.005)

                fresh_feeder = threading.Thread(
                    target=feed_fresh,
                    name="commandmic-post-cancel-audio",
                    daemon=True,
                )
                fresh_feeder.start()
                try:
                    mic.ptt("press")
                    _wait_for(
                        lambda: int(
                            radio.state.snapshot(include_events=False)["audio_packets"]
                        )
                        >= fresh_packets + 5,
                        timeout_seconds,
                        "fresh microphone RTP after restart",
                    )
                    mic.ptt("release")
                    _wait_for(
                        lambda: mic_capture_count() > fresh_prior,
                        timeout_seconds,
                        "fresh microphone capture completion after restart",
                    )
                finally:
                    fresh_stop.set()
                    fresh_feeder.join(timeout=1.0)
                    if mic.state.snapshot()["ptt_active"]:
                        mic.ptt("release")
                fresh_capture = last_mic_capture()
                if fresh_capture.get("sequence_errors") != 0 or fresh_capture.get(
                    "timestamp_errors"
                ) != 0:
                    raise AssertionError(
                        f"microphone restart retained stale state: {fresh_capture}"
                    )

                udp_proxy.set_radio_rtp_impairment(False)
                udp_proxy.reset_radio_timing()
                callback_start = rx_sink.callback_count
                summary_start = len(rx_sink.summaries)
                send_outcome: dict[str, object] = {}

                def send_radio_audio() -> None:
                    try:
                        send_outcome["packets"] = radio.send_tone(
                            1400.0, -15.0, 2.0
                        )
                    except BaseException as exc:
                        send_outcome["error"] = f"{type(exc).__name__}: {exc}"

                sender = threading.Thread(
                    target=send_radio_audio,
                    name="radio-cancelled-audio",
                    daemon=True,
                )
                sender.start()
                _wait_for(
                    lambda: rx_sink.gate_open
                    and rx_sink.callback_count >= callback_start + 10,
                    timeout_seconds,
                    "active radio stream before endpoint cancellation",
                )
                stop_started = time.perf_counter()
                radio.stop()
                radio_stop_seconds = time.perf_counter() - stop_started
                sender.join(timeout=3.0)
                if sender.is_alive():
                    raise AssertionError("radio audio API action survived endpoint stop")
                if radio_stop_seconds > 3.0:
                    raise AssertionError(
                        f"radio mid-audio stop took {radio_stop_seconds:.3f}s"
                    )
                _wait_for(
                    lambda: not bool(mic.state.snapshot()["controls_ready"])
                    and not bool(mic.state.snapshot()["rx_audio_open"])
                    and not rx_sink.gate_open
                    and len(rx_sink.summaries) > summary_start,
                    timeout_seconds,
                    "CommandMic fail-closed state after radio cancellation",
                )
                radio_arrivals_after_stop = len(udp_proxy.radio_arrival_times)
                time.sleep(0.10)
                if len(udp_proxy.radio_arrival_times) != radio_arrivals_after_stop:
                    raise AssertionError("radio RTP continued after endpoint stop")

                radio.start()
                _wait_for(
                    lambda: bool(mic.state.snapshot()["controls_ready"])
                    and bool(
                        radio.state.snapshot(include_events=False)["controls_ready"]
                    ),
                    timeout_seconds,
                    "radio restart after mid-stream cancellation",
                )
                clean_summary_start = len(rx_sink.summaries)
                if radio.send_tone(1500.0, -15.0, 0.12) != 6:
                    raise AssertionError("post-restart radio tone packet count mismatch")
                _wait_for(
                    lambda: len(rx_sink.summaries) > clean_summary_start,
                    timeout_seconds,
                    "fresh radio receive gate after restart",
                )
                clean_summary = rx_sink.summaries[-1]
                if clean_summary["received"] != 6 or clean_summary["played"] != 6:
                    raise AssertionError(
                        f"post-restart radio audio was incomplete: {clean_summary}"
                    )
                if any(
                    clean_summary[field] != 0
                    for field in ("concealed", "duplicates", "late", "discontinuities")
                ):
                    raise AssertionError(
                        f"radio restart retained stale jitter state: {clean_summary}"
                    )
                return (
                    "mid-PTT CommandMic and mid-audio radio stops completed in "
                    f"{mic_stop_seconds * 1000.0:.1f}/{radio_stop_seconds * 1000.0:.1f} "
                    "ms, emitted no post-stop RTP, failed closed, and recovered "
                    "with clean fresh media gates"
                )

            check("midstream_cancellation_recovery", midstream_cancellation_recovery)

            def network_interruption_recovery() -> str:
                tcp_proxy.set_interrupted(True)
                udp_proxy.set_interrupted(True)
                try:
                    _wait_for(
                        lambda: not bool(mic.state.snapshot()["controls_ready"])
                        and not bool(mic.state.snapshot()["ptt_active"])
                        and not bool(mic.state.snapshot()["rx_audio_open"])
                        and not bool(
                            radio.state.snapshot(include_events=False)["controls_ready"]
                        )
                        and not bool(
                            radio.state.snapshot(include_events=False)["ptt"]
                        ),
                        timeout_seconds,
                        "both endpoints to fail closed during routed-link interruption",
                    )
                    # Keep the link down across at least one outbound retry.
                    time.sleep(0.25)
                finally:
                    udp_proxy.set_interrupted(False)
                    tcp_proxy.set_interrupted(False)

                _wait_for(
                    lambda: bool(mic.state.snapshot()["controls_ready"])
                    and bool(
                        radio.state.snapshot(include_events=False)["controls_ready"]
                    ),
                    timeout_seconds,
                    "both endpoints to recover after routed-link restoration",
                )
                expected = DisplayBuffer(b"NETRESTO" + bytes(60))
                radio.send_display(expected)
                _wait_for(
                    lambda: (mic.state.snapshot().get("display") or {}).get("raw_hex")
                    == expected.raw.hex(),
                    timeout_seconds,
                    "display transaction after routed-link restoration",
                )
                mic.key("p2", "press")
                _wait_for(
                    lambda: radio.state.snapshot(include_events=False)["buttons"].get(
                        "p2"
                    )
                    is True,
                    timeout_seconds,
                    "P2 press after routed-link restoration",
                )
                mic.key("p2", "release")
                _wait_for(
                    lambda: radio.state.snapshot(include_events=False)["buttons"].get(
                        "p2"
                    )
                    is False,
                    timeout_seconds,
                    "P2 release after routed-link restoration",
                )
                return (
                    "real TCP sessions were torn down and rejected while UDP was "
                    "blackholed; both endpoints failed closed and returned to "
                    "stable display/key operation after link restoration"
                )

            check("network_interruption_recovery", network_interruption_recovery)

            def fail_closed_disconnect() -> str:
                radio.stop()
                _wait_for(
                    lambda: not bool(mic.state.snapshot()["controls_ready"])
                    and not bool(mic.state.snapshot()["ptt_active"])
                    and not bool(mic.state.snapshot()["rx_audio_open"]),
                    timeout_seconds,
                    "CommandMic endpoint fail-closed disconnect state",
                )
                return "controls, PTT, and receive-audio gate became inactive"

            disconnected = check("fail_closed_disconnect", fail_closed_disconnect)

            if disconnected:
                def reconnect() -> str:
                    radio.start()
                    _wait_for(
                        lambda: bool(mic.state.snapshot()["controls_ready"])
                        and bool(
                            radio.state.snapshot(include_events=False)["controls_ready"]
                        ),
                        timeout_seconds,
                        "both endpoints to reconnect",
                    )
                    if mic.state.snapshot()["session"] != "stable":
                        raise AssertionError("both sessions did not return to stable")
                    return "a restarted radio endpoint returned both peers to stable operation"

                reconnected = check("endpoint_reconnect", reconnect)

                if reconnected:
                    def cold_object_restart_matrix() -> str:
                        nonlocal tx_source, rx_sink, mic, radio

                        orders: list[str] = []
                        for cycle in range(1, cold_restart_cycles + 1):
                            radio.stop()
                            mic.stop()
                            # Let the routed proxy observe both FIN paths before
                            # fresh listeners and sessions reuse the topology.
                            time.sleep(0.25)
                            tx_source, rx_sink, mic, radio = make_endpoints()

                            if cycle % 2:
                                orders.append("mic-first")
                                mic.start()
                                radio.start()
                            else:
                                orders.append("radio-first")
                                radio.start()
                                mic.start()

                            _wait_for(
                                lambda: bool(mic.state.snapshot()["controls_ready"])
                                and bool(
                                    radio.state.snapshot(include_events=False)[
                                        "controls_ready"
                                    ]
                                ),
                                timeout_seconds,
                                f"fresh endpoint objects in restart cycle {cycle}",
                            )
                            if (
                                mic.state.snapshot()["session"] != "stable"
                                or radio.state.snapshot(include_events=False)["session"]
                                != "stable"
                            ):
                                raise AssertionError(
                                    f"restart cycle {cycle} did not reach stable sessions"
                                )

                            expected_display = DisplayBuffer(
                                f"RST{cycle:05d}".encode("ascii") + bytes(60)
                            )
                            radio.send_display(expected_display)
                            _wait_for(
                                lambda: (
                                    mic.state.snapshot().get("display") or {}
                                ).get("raw_hex")
                                == expected_display.raw.hex(),
                                timeout_seconds,
                                f"fresh display transaction in restart cycle {cycle}",
                            )

                            mic.key("p1", "press")
                            _wait_for(
                                lambda: bool(
                                    radio.state.snapshot(include_events=False)[
                                        "buttons"
                                    ].get("p1")
                                ),
                                timeout_seconds,
                                f"fresh P1 press in restart cycle {cycle}",
                            )
                            mic.key("p1", "release")
                            _wait_for(
                                lambda: not bool(
                                    radio.state.snapshot(include_events=False)[
                                        "buttons"
                                    ].get("p1")
                                ),
                                timeout_seconds,
                                f"fresh P1 release in restart cycle {cycle}",
                            )

                            summary_start = len(rx_sink.summaries)
                            if radio.send_tone(900.0 + cycle, -18.0, 0.04) != 2:
                                raise AssertionError(
                                    f"restart cycle {cycle} tone packet mismatch"
                                )
                            _wait_for(
                                lambda: len(rx_sink.summaries) > summary_start,
                                timeout_seconds,
                                f"fresh audio gate in restart cycle {cycle}",
                            )
                            summary = rx_sink.summaries[-1]
                            if summary["received"] != 2 or summary["played"] != 2:
                                raise AssertionError(
                                    f"restart cycle {cycle} audio was incomplete: "
                                    f"{summary}"
                                )
                            if any(
                                summary[field] != 0
                                for field in (
                                    "concealed",
                                    "duplicates",
                                    "late",
                                    "discontinuities",
                                )
                            ):
                                raise AssertionError(
                                    f"restart cycle {cycle} retained stale audio: "
                                    f"{summary}"
                                )

                        return (
                            f"{cold_restart_cycles} fresh-object restart cycles "
                            f"passed stable display, key, and audio checks with "
                            f"alternating startup order ({', '.join(orders)})"
                        )

                    check("cold_object_restart_matrix", cold_object_restart_matrix)

    finally:
        radio.stop()
        mic.stop()
        tcp_proxy.close()
        udp_proxy.close()

    check(
        "subprocess_replacement_recovery",
        lambda: _run_subprocess_replacement_conformance(
            artifact_root, timeout_seconds
        ),
    )

    return ConformanceReport(
        checks=tuple(checks),
        elapsed_seconds=time.monotonic() - started,
        commandmic_audit=mic_audit,
        radio_audit=radio_audit,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-directory", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--sustained-audio-seconds", type=float, default=1.0)
    parser.add_argument("--cold-restart-cycles", type=int, default=3)
    args = parser.parse_args(argv)
    report = run_loopback_conformance(
        args.artifact_directory,
        timeout_seconds=args.timeout,
        sustained_audio_seconds=args.sustained_audio_seconds,
        cold_restart_cycles=args.cold_restart_cycles,
    )
    serialized = json.dumps(report.to_dict(), indent=2)
    report_path = args.artifact_directory / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
