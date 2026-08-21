from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import mimetypes
import threading
import time
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audio import (
    MicrophoneAudioSource,
    MiniaudioMicrophoneSource,
    MiniaudioRadioAudioSink,
    RadioAudioSink,
)
from .controls import ORDINARY_KEY_BUTTONS
from .emulator import (
    AuditLog,
    CommandMicEmulator,
    EmulatorConfig,
    VerifiedMicUdpProtocol,
)

LOGGER = logging.getLogger("ip_commandmic.gui")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUI_ROOT = PROJECT_ROOT / "gui"


class GuiState:
    """Small thread-safe projection of protocol events for the local UI."""

    def __init__(self, *, tx_available: bool, microphone_device: str | None) -> None:
        self._lock = threading.Lock()
        self._debug: collections.deque[dict[str, object]] = collections.deque(maxlen=1000)
        self._debug_cursor = 0
        self._state: dict[str, Any] = {
            "revision": 0,
            "connection": "starting",
            "session": None,
            "controls_ready": False,
            "display": None,
            "status_led": "orange",
            "rx_audio_open": False,
            "ptt_active": False,
            "tx_available": tx_available,
            "tx_armed": tx_available,
            "microphone_device": microphone_device,
            "last_control": None,
            "last_error": None,
            "updated_monotonic": time.monotonic(),
        }

    def update(self, **fields: Any) -> None:
        with self._lock:
            self._state.update(fields)
            self._state["revision"] += 1
            self._state["updated_monotonic"] = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def debug_events(self, after: int) -> tuple[int, list[dict[str, object]]]:
        with self._lock:
            return self._debug_cursor, [
                event for event in self._debug if int(event["cursor"]) > after
            ]

    def on_protocol_event(self, record: dict[str, object]) -> None:
        # Keep a bounded, JSON-safe diagnostic projection. Raw voice payloads
        # and other large byte strings remain in the audit file, not RAM.
        diagnostic = {
            key: value
            for key, value in record.items()
            if key not in {"raw", "payload", "frame", "display"}
        }
        try:
            diagnostic = json.loads(json.dumps(diagnostic, default=str))
        except (TypeError, ValueError):
            diagnostic = {"detail": repr(diagnostic)}
        with self._lock:
            self._debug_cursor += 1
            self._debug.append(
                {
                    "cursor": self._debug_cursor,
                    "time_unix": time.time(),
                    "event": str(record.get("event") or "event"),
                    "data": diagnostic,
                }
            )
        event = record.get("event")
        if event == "listening":
            self.update(connection="waiting_for_radio", status_led="orange")
        elif event == "connected":
            self.update(connection="negotiating", controls_ready=False, status_led="orange")
        elif event == "verified_mic_session":
            self.update(session=record.get("session_kind"))
        elif event == "mic_controls_ready":
            self.update(
                connection="connected",
                controls_ready=True,
                tx_armed=bool(self._state.get("tx_available")),
            )
        elif event == "disconnected":
            self.update(
                connection="waiting_for_radio",
                controls_ready=False,
                ptt_active=False,
                tx_armed=False,
                rx_audio_open=False,
                status_led="orange",
            )
        elif event == "display_event":
            display = record.get("display")
            if isinstance(display, dict):
                self.update(display=display)
        elif event == "received" and record.get("kind") == "audio_status":
            metadata = record.get("metadata")
            if isinstance(metadata, dict):
                color = metadata.get("status_led_color")
                if color in {"off", "red", "green", "orange"}:
                    self.update(status_led=color)
        elif event == "accepted_verified_radio_audio_state":
            audio_state = record.get("audio_state")
            self.update(
                rx_audio_open=audio_state == "receive_open",
            )
        elif event == "mic_key_queued":
            self.update(last_control=record.get("button"))
        elif event == "mic_ptt_asserted":
            self.update(ptt_active=True, status_led="red")
        elif event == "mic_ptt_released":
            self.update(ptt_active=False, status_led="off")
        elif event in {"connection_failed", "mic_tx_script_failed"}:
            self.update(last_error=record.get("error"), status_led="orange")


class SoftwareCommandMicEndpoint:
    """High-level CommandMic-side endpoint for controlling a real radio."""
    def __init__(
        self,
        *,
        local_ip: str,
        radio_ip: str,
        microphone_device: str | None,
        enable_tx: bool,
        play_rx_audio: bool,
        audit_path: Path,
        control_port: int = 52001,
        audio_port: int = 50000,
        audio_peer_ip: str | None = None,
        playback_device: str | None = None,
        rx_prebuffer_packets: int = 2,
        audio_buffer_ms: int = 20,
        tx_audio_source: MicrophoneAudioSource | None = None,
        rx_audio_sink: RadioAudioSink | None = None,
    ) -> None:
        if tx_audio_source is not None and not enable_tx:
            raise ValueError("tx_audio_source requires enable_tx=True")
        if tx_audio_source is not None and microphone_device is not None:
            raise ValueError(
                "microphone_device and tx_audio_source are mutually exclusive"
            )
        if rx_audio_sink is not None and play_rx_audio:
            raise ValueError("play_rx_audio and rx_audio_sink are mutually exclusive")
        self.local_ip = local_ip
        self.radio_ip = radio_ip
        self.microphone_device = microphone_device
        self.enable_tx = enable_tx
        self.play_rx_audio = play_rx_audio
        self.audit_path = audit_path
        self.control_port = control_port
        self.audio_port = audio_port
        self.audio_peer_ip = audio_peer_ip or radio_ip
        self.playback_device = playback_device
        self.rx_prebuffer_packets = rx_prebuffer_packets
        self.audio_buffer_ms = audio_buffer_ms
        self.tx_audio_source = tx_audio_source
        self.rx_audio_sink = rx_audio_sink
        self.state = GuiState(
            tx_available=enable_tx,
            microphone_device=microphone_device,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._emulator: CommandMicEmulator | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._started.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="commandmic-protocol",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(timeout=10.0):
            raise RuntimeError("protocol runtime did not start")

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
            LOGGER.exception("protocol runtime failed")
            self.state.update(
                connection="error",
                controls_ready=False,
                last_error=f"{type(exc).__name__}: {exc}",
            )
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
                        "protocol runtime forced bounded shutdown with %d pending task(s)",
                        len(still_pending),
                    )
            self._loop.close()

    async def _run(self) -> None:
        audit = AuditLog(self.audit_path, self.state.on_protocol_event)
        udp_transport: asyncio.DatagramTransport | None = None
        protocol: VerifiedMicUdpProtocol | None = None
        audio_sink: RadioAudioSink | None = None
        microphone: MicrophoneAudioSource | None = None
        try:
            if self.enable_tx:
                microphone = self.tx_audio_source
                if microphone is None:
                    microphone = MiniaudioMicrophoneSource(
                        self.microphone_device,
                        queue_packets=1,
                        device_buffer_ms=self.audio_buffer_ms,
                    )
                await microphone.start()
                audit.write(
                    "mic_live_capture_started",
                    device=self.microphone_device,
                    device_buffer_ms=self.audio_buffer_ms,
                    queue_packets=1,
                    backend=(
                        "miniaudio"
                        if self.tx_audio_source is None
                        else type(microphone).__name__
                    ),
                )
            if self.rx_audio_sink is not None:
                audio_sink = self.rx_audio_sink
                audio_sink.start()
                audit.write(
                    "radio_audio_playback_started",
                    backend=type(audio_sink).__name__,
                    injected=True,
                )
            elif self.play_rx_audio:
                audio_sink = MiniaudioRadioAudioSink(
                    device_name=self.playback_device,
                    prebuffer_packets=self.rx_prebuffer_packets,
                    device_buffer_ms=self.audio_buffer_ms,
                )
                audio_sink.start()
                audit.write(
                    "radio_audio_playback_started",
                    backend="miniaudio",
                    device=self.playback_device,
                    prebuffer_packets=self.rx_prebuffer_packets,
                    device_buffer_ms=self.audio_buffer_ms,
                )

            protocol = VerifiedMicUdpProtocol(
                self.audio_peer_ip,
                self.audio_port,
                audit,
                radio_audio_callback=(audio_sink.on_packet if audio_sink else None),
                radio_audio_gate_callback=(audio_sink.on_gate if audio_sink else None),
            )
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=(self.local_ip, self.audio_port),
            )
            udp_transport = transport  # type: ignore[assignment]
            audit.write("udp_listening", address=(self.local_ip, self.audio_port))

            config = EmulatorConfig(
                role="mic",
                local_ip=self.local_ip,
                peer_ip=self.radio_ip,
                port=self.control_port,
                listen=True,
                verified_startup=True,
                voice_port=self.audio_port,
                interactive_tx=self.enable_tx,
                tx_live_device=(
                    self.microphone_device
                    or (
                        type(self.tx_audio_source).__name__
                        if self.tx_audio_source is not None
                        else "System default"
                    )
                    if self.enable_tx
                    else None
                ),
                tx_device_buffer_ms=self.audio_buffer_ms,
                play_radio_audio=self.play_rx_audio,
                radio_jitter_packets=self.rx_prebuffer_packets,
            )
            self._emulator = CommandMicEmulator(
                config,
                audit,
                protocol,
                mic_audio_source=microphone,
            )
            await self._emulator.run()
        finally:
            self._emulator = None
            if protocol is not None:
                protocol.close()
            if udp_transport is not None:
                udp_transport.close()
            if audio_sink is not None:
                audio_sink.close()
                jitter = getattr(audio_sink, "jitter", None)
                stats = getattr(jitter, "stats", None)
                audit.write(
                    "radio_audio_playback_stopped",
                    stats=(asdict(stats) if stats is not None else None),
                    backend=(
                        "miniaudio"
                        if isinstance(audio_sink, MiniaudioRadioAudioSink)
                        else type(audio_sink).__name__
                    ),
                    backend_queue_drops=getattr(
                        audio_sink, "backend_queue_drops", None
                    ),
                )
            if microphone is not None:
                stats = asdict(microphone.stats)
                await microphone.close()
                audit.write("mic_live_capture_stopped", stats=stats)
            audit.close()

    def _submit(self, coroutine: Any) -> None:
        if self._loop is None or self._task is None or self._task.done():
            raise RuntimeError("protocol runtime is not running")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)

        def completed(result: object) -> None:
            try:
                result.result()  # type: ignore[attr-defined]
            except Exception as exc:
                LOGGER.exception("desktop protocol action failed")
                self.state.update(last_error=f"{type(exc).__name__}: {exc}")

        future.add_done_callback(completed)

    async def _tap(self, button: str) -> None:
        emulator = self._emulator
        if emulator is None or not emulator.controls_ready:
            raise RuntimeError("CommandMic controls are not ready")
        if button == "power":
            emulator.queue_power_tap()
        else:
            emulator.queue_key_tap(
                button,
                allow_emergency=button == "emergency",
            )

    def tap(self, button: str) -> None:
        if button not in (*ORDINARY_KEY_BUTTONS, "emergency", "power"):
            raise ValueError("button is not a verified CommandMic control")
        self._submit(self._tap(button))

    async def _key(self, button: str, action: str) -> None:
        emulator = self._emulator
        if emulator is None or not emulator.controls_ready:
            raise RuntimeError("CommandMic controls are not ready")
        if action == "press":
            await emulator.press_interactive_key(
                button, allow_emergency=button == "emergency"
            )
        elif action == "release":
            await emulator.release_interactive_key(
                button, allow_emergency=button == "emergency"
            )
        else:
            raise ValueError("key action must be press or release")

    def key(self, button: str, action: str) -> None:
        if button not in (*ORDINARY_KEY_BUTTONS, "emergency"):
            raise ValueError("button is not a verified holdable CommandMic control")
        self._submit(self._key(button, action))

    def set_tx_armed(self, armed: bool) -> None:
        if armed and not self.state.snapshot()["tx_available"]:
            raise RuntimeError("TX was not enabled when the GUI was launched")
        if not armed and self.state.snapshot()["ptt_active"]:
            self.ptt("release")
        self.state.update(tx_armed=armed)

    async def _ptt(self, action: str) -> None:
        emulator = self._emulator
        if emulator is None or not emulator.controls_ready:
            raise RuntimeError("CommandMic controls are not ready")
        if action == "press":
            await emulator.press_interactive_ptt()
        elif action == "release":
            await emulator.release_interactive_ptt()
        else:
            raise ValueError("PTT action must be press or release")

    def ptt(self, action: str) -> None:
        if action == "press" and not self.state.snapshot()["tx_available"]:
            raise RuntimeError("interactive TX audio is unavailable")
        self._submit(self._ptt(action))

    def stop(self) -> None:
        if (
            self._loop is not None
            and not self._loop.is_closed()
            and self._task is not None
            and not self._task.done()
        ):
            self._loop.call_soon_threadsafe(self._task.cancel)
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            if self._thread.is_alive():
                raise RuntimeError("protocol runtime did not stop within 10 seconds")
        self._thread = None
        self._loop = None
        self._task = None
        self._started.clear()


# Backward-compatible name retained for existing integrations.
InteractiveMicRuntime = SoftwareCommandMicEndpoint


class GuiRequestHandler(BaseHTTPRequestHandler):
    runtime: InteractiveMicRuntime

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("gui_http " + format, *args)

    def _json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 4096:
            raise ValueError("invalid request length")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON request must be an object")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/state":
            self._json_response(HTTPStatus.OK, self.runtime.state.snapshot())
            return
        static_files = {
            "/": GUI_ROOT / "index.html",
            "/index.html": GUI_ROOT / "index.html",
            "/app.js": GUI_ROOT / "app.js",
            "/style.css": GUI_ROOT / "style.css",
            "/assets/mic_front_vector.svg": GUI_ROOT / "assets" / "mic_front_vector.svg",
            "/assets/mic_display_vector.svg": GUI_ROOT / "assets" / "mic_display_vector.svg",
            "/assets/mic_front.png": GUI_ROOT / "assets" / "mic_front.png",
        }
        target = static_files.get(path)
        if target is None or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self._read_json()
            path = urlparse(self.path).path
            if path == "/api/key":
                self.runtime.tap(str(payload.get("button", "")))
            elif path == "/api/ptt":
                self.runtime.ptt(str(payload.get("action", "")))
            elif path == "/api/tx-arm":
                armed = payload.get("armed")
                if not isinstance(armed, bool):
                    raise ValueError("armed must be boolean")
                self.runtime.set_tx_armed(armed)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._json_response(HTTPStatus.OK, {"ok": True})
        except (ValueError, RuntimeError, TimeoutError) as exc:
            self._json_response(
                HTTPStatus.CONFLICT,
                {"ok": False, "error": str(exc)},
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local virtual CommandMic GUI")
    parser.add_argument("--local-ip", default="192.168.0.2")
    parser.add_argument("--radio-ip", default="192.168.0.1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--microphone-device")
    parser.add_argument("--enable-tx", action="store_true")
    parser.add_argument("--no-rx-audio", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--audit",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "gui" / "emulator_audit.jsonl",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.enable_tx and not args.microphone_device:
        raise SystemExit("--enable-tx requires --microphone-device")
    runtime = InteractiveMicRuntime(
        local_ip=args.local_ip,
        radio_ip=args.radio_ip,
        microphone_device=args.microphone_device,
        enable_tx=args.enable_tx,
        play_rx_audio=not args.no_rx_audio,
        audit_path=args.audit,
    )
    runtime.start()
    GuiRequestHandler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), GuiRequestHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Virtual CommandMic GUI: {url}")
    print("TX is disabled" if not args.enable_tx else "TX is available but disarmed in the GUI")
    if not args.no_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
