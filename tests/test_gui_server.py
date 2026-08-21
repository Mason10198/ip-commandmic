from __future__ import annotations

import asyncio

import pytest

from ip_commandmic.audio import BufferedMicrophoneSource, MicrophoneCaptureStats
from ip_commandmic.emulator import (
    AuditLog,
    EmulatorConfig,
    MIC_BOOT_RTP,
    RADIO_BOOT_RTP,
    VerifiedMicUdpProtocol,
)
from ip_commandmic.gui_server import GuiState, InteractiveMicRuntime


class _FakeTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, destination: tuple[str, int]) -> None:
        self.sent.append((data, destination))


class _FakeMicrophone:
    def __init__(self) -> None:
        self.payload = bytes.fromhex("0102") * 160

    def latest_payload(self) -> bytes:
        return self.payload

    @property
    def stats(self) -> object:
        return MicrophoneCaptureStats(
            captured=1,
            delivered=1,
            overwritten=0,
            underruns=0,
            buffered=0,
        )


class _FakeControlEndpoint:
    controls_ready = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def queue_key_tap(self, button: str, *, allow_emergency: bool = False) -> None:
        self.calls.append((button, allow_emergency))

    async def send_interactive_power_tap(self) -> None:
        self.calls.append(("power", True))

    async def press_interactive_key(
        self, button: str, *, allow_emergency: bool = False
    ) -> None:
        self.calls.append((f"press:{button}", allow_emergency))

    async def release_interactive_key(
        self, button: str, *, allow_emergency: bool = False
    ) -> None:
        self.calls.append((f"release:{button}", allow_emergency))


def test_gui_state_projects_protocol_events() -> None:
    state = GuiState(tx_available=True, microphone_device="Test microphone")
    state.on_protocol_event({"event": "connected"})
    state.on_protocol_event(
        {"event": "display_event", "display": {"primary_text": "QTH NODE"}}
    )
    state.on_protocol_event({"event": "mic_controls_ready"})
    state.on_protocol_event(
        {"event": "accepted_verified_radio_audio_state", "audio_state": "receive_open"}
    )
    state.on_protocol_event(
        {
            "event": "received",
            "kind": "audio_status",
            "metadata": {"status_led_color": "green"},
        }
    )
    snapshot = state.snapshot()
    assert snapshot["connection"] == "connected"
    assert snapshot["controls_ready"] is True
    assert snapshot["display"] == {"primary_text": "QTH NODE"}
    assert snapshot["rx_audio_open"] is True
    assert snapshot["status_led"] == "green"


def test_gui_state_uses_exact_audio_status_led_color() -> None:
    state = GuiState(tx_available=False, microphone_device=None)
    state.on_protocol_event(
        {
            "event": "received",
            "kind": "audio_status",
            "metadata": {"status_led_color": "orange"},
        }
    )
    assert state.snapshot()["status_led"] == "orange"


def test_gui_state_uses_orange_led_while_waiting_for_radio() -> None:
    state = GuiState(tx_available=False, microphone_device=None)
    assert state.snapshot()["status_led"] == "orange"
    state.on_protocol_event({"event": "connected"})
    assert state.snapshot()["status_led"] == "orange"
    state.on_protocol_event({"event": "disconnected"})
    snapshot = state.snapshot()
    assert snapshot["connection"] == "waiting_for_radio"
    assert snapshot["status_led"] == "orange"


def test_gui_state_projects_powered_off_standby_until_wake_display() -> None:
    state = GuiState(tx_available=True, microphone_device="Test microphone")
    state.on_protocol_event(
        {"event": "display_event", "display": {"primary_text": "462.700"}}
    )
    state.on_protocol_event({"event": "mic_controls_ready"})

    state.on_protocol_event(
        {"event": "mic_power_transition_prompt", "transition": "shutdown"}
    )
    standby = state.snapshot()
    assert standby["connection"] == "standby"
    assert standby["powered_off"] is True
    assert standby["controls_ready"] is False
    assert standby["display"] is None
    assert standby["status_led"] == "off"

    state.on_protocol_event({"event": "disconnected"})
    state.on_protocol_event({"event": "connected"})
    assert state.snapshot()["connection"] == "standby"

    state.on_protocol_event(
        {"event": "mic_power_transition_prompt", "transition": "wake"}
    )
    assert state.snapshot()["connection"] == "powering_on"
    state.on_protocol_event(
        {"event": "display_event", "display": {"primary_text": "BATT137V"}}
    )
    assert state.snapshot()["powered_off"] is False


def test_desktop_routes_edge_controls_with_explicit_emergency_gate(tmp_path) -> None:
    runtime = InteractiveMicRuntime(
        local_ip="127.0.0.2",
        radio_ip="127.0.0.1",
        microphone_device=None,
        enable_tx=True,
        play_rx_audio=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    endpoint = _FakeControlEndpoint()
    runtime._emulator = endpoint  # type: ignore[assignment]

    async def exercise() -> None:
        await runtime._tap("f1")
        await runtime._tap("volume_up")
        await runtime._tap("volume_down")
        await runtime._tap("emergency")
        await runtime._tap("power")

    asyncio.run(exercise())
    assert endpoint.calls == [
        ("f1", False),
        ("volume_up", False),
        ("volume_down", False),
        ("emergency", True),
        ("power", True),
    ]


def test_desktop_allows_power_before_ordinary_controls_are_ready(tmp_path) -> None:
    runtime = InteractiveMicRuntime(
        local_ip="127.0.0.2",
        radio_ip="127.0.0.1",
        microphone_device=None,
        enable_tx=True,
        play_rx_audio=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    endpoint = _FakeControlEndpoint()
    endpoint.controls_ready = False
    runtime._emulator = endpoint  # type: ignore[assignment]

    asyncio.run(runtime._tap("power"))

    assert endpoint.calls == [("power", True)]


def test_application_audio_source_keeps_explicit_tx_gate_and_device_exclusivity(
    tmp_path,
) -> None:
    source = BufferedMicrophoneSource()
    common = {
        "local_ip": "127.0.0.2",
        "radio_ip": "127.0.0.1",
        "play_rx_audio": False,
        "audit_path": tmp_path / "audit.jsonl",
    }
    with pytest.raises(ValueError, match="enable_tx=True"):
        InteractiveMicRuntime(
            **common,
            microphone_device=None,
            enable_tx=False,
            tx_audio_source=source,
        )
    with pytest.raises(ValueError, match="mutually exclusive"):
        InteractiveMicRuntime(
            **common,
            microphone_device="Test microphone",
            enable_tx=True,
            tx_audio_source=source,
        )
    runtime = InteractiveMicRuntime(
        **common,
        microphone_device=None,
        enable_tx=True,
        tx_audio_source=source,
    )
    assert runtime.tx_audio_source is source
    assert runtime.state.snapshot()["tx_available"] is True


def test_application_receive_sink_is_mutually_exclusive_with_native_playback(
    tmp_path,
) -> None:
    class Sink:
        def start(self) -> None:
            pass

        def on_packet(self, packet) -> None:
            pass

        def on_gate(self, event) -> None:
            pass

        def close(self) -> None:
            pass

    sink = Sink()
    common = {
        "local_ip": "127.0.0.2",
        "radio_ip": "127.0.0.1",
        "microphone_device": None,
        "enable_tx": False,
        "audit_path": tmp_path / "audit.jsonl",
    }
    with pytest.raises(ValueError, match="mutually exclusive"):
        InteractiveMicRuntime(
            **common,
            play_rx_audio=True,
            rx_audio_sink=sink,
        )
    runtime = InteractiveMicRuntime(
        **common,
        play_rx_audio=False,
        rx_audio_sink=sink,
    )
    assert runtime.rx_audio_sink is sink


def test_desktop_routes_physical_key_down_and_up_separately(tmp_path) -> None:
    runtime = InteractiveMicRuntime(
        local_ip="127.0.0.2",
        radio_ip="127.0.0.1",
        microphone_device=None,
        enable_tx=True,
        play_rx_audio=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    endpoint = _FakeControlEndpoint()
    runtime._emulator = endpoint  # type: ignore[assignment]

    async def exercise() -> None:
        await runtime._key("volume_up", "press")
        await runtime._key("volume_up", "release")
        await runtime._key("emergency", "press")
        await runtime._key("emergency", "release")

    asyncio.run(exercise())
    assert endpoint.calls == [
        ("press:volume_up", False),
        ("release:volume_up", False),
        ("press:emergency", True),
        ("release:emergency", True),
    ]


def test_interactive_tx_config_requires_explicit_live_device() -> None:
    with pytest.raises(ValueError, match="tx_live_device"):
        EmulatorConfig(
            role="mic",
            local_ip="192.168.0.2",
            peer_ip="192.168.0.1",
            listen=True,
            verified_startup=True,
            interactive_tx=True,
        )
    config = EmulatorConfig(
        role="mic",
        local_ip="192.168.0.2",
        peer_ip="192.168.0.1",
        listen=True,
        verified_startup=True,
        interactive_tx=True,
        tx_live_device="Test microphone",
    )
    assert config.interactive_tx is True


def test_interactive_stream_stops_with_release_tail() -> None:
    async def exercise() -> None:
        audit = AuditLog()
        protocol = VerifiedMicUdpProtocol("192.168.0.1", 50000, audit)
        transport = _FakeTransport()
        protocol.connection_made(transport)  # type: ignore[arg-type]
        assert protocol.send_boot() is True
        protocol.datagram_received(RADIO_BOOT_RTP, ("192.168.0.1", 50000))
        assert transport.sent[0][0] == MIC_BOOT_RTP

        stop = asyncio.Event()
        microphone = _FakeMicrophone()
        task = asyncio.create_task(
            protocol.send_live_transmit_until(
                microphone,  # type: ignore[arg-type]
                stop,
                release_tail_packets=2,
            )
        )
        while len(transport.sent) < 3:
            await asyncio.sleep(0)
        stop.set()
        packet_count = await asyncio.wait_for(task, timeout=1.0)
        rtp_packets = [packet for packet, _ in transport.sent[1:]]
        assert packet_count == len(rtp_packets)
        assert packet_count >= 4
        assert all(len(packet) == 332 for packet in rtp_packets)
        assert all(packet[12:] == microphone.payload for packet in rtp_packets)

    asyncio.run(exercise())
