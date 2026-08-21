from __future__ import annotations

import asyncio
import math
import wave

from ip_commandmic import (
    DisplayBuffer,
    SoftwareRadioConfig,
    SoftwareRadioEndpoint,
    encode_mic_gain_transaction,
)
from ip_commandmic.emulator import AuditLog, VerifiedRadioUdpProtocol


def test_software_radio_defaults_to_neutral_passive_control_observation() -> None:
    config = SoftwareRadioConfig()
    assert config.startup_opening_text == ""
    assert config.startup_idle_text == ""
    assert config.startup_status_carousel is False
    assert config.automatic_key_responses is False
    assert config.automatic_ptt_responses is False
    assert config.speaker_volume == 22


def test_software_radio_default_snapshot_uses_volume_22(tmp_path) -> None:
    runtime = SoftwareRadioEndpoint(SoftwareRadioConfig(), tmp_path / "audit.jsonl")
    assert runtime.state.snapshot()["speaker_volume"] == 22


def test_realtime_backlight_uses_typed_emulator_operation(tmp_path) -> None:
    runtime = SoftwareRadioEndpoint(SoftwareRadioConfig(), tmp_path / "audit.jsonl")
    observed: list[str] = []

    class Emulator:
        async def send_interactive_backlight(self, state: str) -> None:
            observed.append(state)

    runtime._emulator = Emulator()  # type: ignore[assignment]
    runtime._run_action = lambda coroutine, timeout=35.0: asyncio.run(coroutine)  # type: ignore[method-assign]
    runtime.send_backlight("dim")
    assert observed == ["dim"]


def test_live_audio_meter_and_recording_write_pcm_wav(tmp_path) -> None:
    runtime = SoftwareRadioEndpoint(SoftwareRadioConfig(), tmp_path / "audit.jsonl")
    output = tmp_path / "mic.wav"
    samples = [round(math.sin(index / 8) * 12000) for index in range(160)]
    payload = b"".join(int(sample).to_bytes(2, "big", signed=True) for sample in samples)
    runtime.start_recording(str(output))
    runtime._on_audio(payload)
    snapshot = runtime.state.snapshot()
    assert snapshot["audio_packets"] == 1
    assert snapshot["audio_peak"] > 0.3
    assert len(snapshot["waveform"]) == 160
    result = runtime.stop_recording()
    assert result["samples"] == 160
    with wave.open(str(output), "rb") as recorded:
        assert recorded.getframerate() == 8000
        assert recorded.getnchannels() == 1
        assert recorded.getsampwidth() == 2
        assert recorded.getnframes() == 160


def test_realtime_mic_gain_uses_observed_pair_and_updates_state(tmp_path) -> None:
    runtime = SoftwareRadioEndpoint(
        SoftwareRadioConfig(mic_gain=3), tmp_path / "audit.jsonl"
    )
    observed = []

    class Emulator:
        async def send_interactive_mic_gain(self, level: int) -> None:
            observed.append((level, encode_mic_gain_transaction(level)))

    runtime._emulator = Emulator()  # type: ignore[assignment]
    runtime._run_action = lambda coroutine, timeout=35.0: asyncio.run(coroutine)  # type: ignore[method-assign]
    assert runtime.set_mic_gain(5) == 5
    assert runtime.state.snapshot()["mic_gain"] == 5
    assert observed == [(5, encode_mic_gain_transaction(5))]
    assert encode_mic_gain_transaction(5)[0] != encode_mic_gain_transaction(5)[1]
    for invalid in (0, 6):
        try:
            runtime.set_mic_gain(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid microphone gain was accepted")


def test_capture_summary_remains_durable_after_ui_event_ring_wraps(tmp_path) -> None:
    runtime = SoftwareRadioEndpoint(SoftwareRadioConfig(), tmp_path / "audit.jsonl")
    runtime._on_audit(
        {
            "event": "mic_capture_completed",
            "packets": 512,
            "sequence_errors": 0,
            "timestamp_errors": 0,
        }
    )
    for index in range(250):
        runtime._on_audit({"event": "diagnostic", "index": index})

    snapshot = runtime.state.snapshot()
    assert len(snapshot["events"]) == 200
    assert snapshot["mic_capture_count"] == 1
    assert snapshot["last_mic_capture"] == {
        "packets": 512,
        "sequence_errors": 0,
        "timestamp_errors": 0,
    }


def test_speaker_volume_uses_verified_range_with_mute_and_unity() -> None:
    assert SoftwareRadioEndpoint.speaker_volume_gain(0) == 0.0
    assert SoftwareRadioEndpoint.speaker_volume_gain(32) == 1.0
    assert SoftwareRadioEndpoint.speaker_volume_gain(31) < 1.0
    payload = (10000).to_bytes(2, "big", signed=True) * 160
    scaled = SoftwareRadioEndpoint._scale_payloads([payload], 31)
    assert 8300 < int.from_bytes(scaled[0][:2], "big", signed=True) < 8400
    assert math.isclose(
        20 * math.log10(SoftwareRadioEndpoint.speaker_volume_gain(1)),
        -48.0,
        abs_tol=0.001,
    )
    assert SoftwareRadioEndpoint._scale_payloads([payload], 0) == []


def test_long_paced_tone_extends_public_action_timeout(tmp_path) -> None:
    runtime = SoftwareRadioEndpoint(
        SoftwareRadioConfig(speaker_volume=32), tmp_path / "audit.jsonl"
    )

    class Emulator:
        async def send_interactive_audio_tone(self, **kwargs) -> int:
            return round(float(kwargs["duration_seconds"]) / 0.020)

    observed: list[float] = []

    def run_action(coroutine, timeout=35.0):
        observed.append(timeout)
        return asyncio.run(coroutine)

    runtime._emulator = Emulator()  # type: ignore[assignment]
    runtime._run_action = run_action  # type: ignore[method-assign]
    assert runtime.send_tone(1000.0, -18.0, 1800.0) == 90000
    assert observed == [1810.0]


def test_parrot_replays_current_ptt_audio_after_release_tail(tmp_path) -> None:
    async def exercise() -> None:
        runtime = SoftwareRadioEndpoint(
            SoftwareRadioConfig(speaker_volume=32), tmp_path / "audit.jsonl"
        )
        observed: list[tuple[list[bytes], str]] = []

        class Emulator:
            async def send_interactive_audio_payloads(
                self, payloads: list[bytes], *, source: str
            ) -> int:
                observed.append((payloads, source))
                return len(payloads)

        class Protocol:
            def __init__(self) -> None:
                self.complete = asyncio.Event()

            async def wait_mic_recording_complete(self) -> None:
                await self.complete.wait()

        runtime._emulator = Emulator()  # type: ignore[assignment]
        protocol = Protocol()
        runtime._protocol = protocol  # type: ignore[assignment]
        runtime.set_parrot_enabled(True)
        runtime._begin_parrot_capture()
        payload = (1234).to_bytes(2, "big", signed=True) * 160
        runtime._on_audio(payload)
        runtime._schedule_parrot_playback()
        await asyncio.sleep(0)
        assert observed == []
        protocol.complete.set()
        assert runtime._parrot_task is not None
        await runtime._parrot_task
        assert len(observed) == 1
        assert observed[0][1] == "parrot"
        assert int.from_bytes(observed[0][0][0][:2], "big", signed=True) > 1234
        assert runtime.state.snapshot()["parrot_status"] == "ready"

    asyncio.run(exercise())


def test_physical_capture_completion_event_follows_configured_tail(tmp_path) -> None:
    async def exercise() -> None:
        audit = AuditLog(tmp_path / "audit.jsonl")
        protocol = VerifiedRadioUdpProtocol(
            "192.168.0.2", 50000, audit, mic_audio_callback=lambda _payload: None
        )
        assert protocol.start_mic_recording()
        assert protocol.release_mic_recording(tail_seconds=0.01)
        waiter = asyncio.create_task(protocol.wait_mic_recording_complete())
        await asyncio.sleep(0)
        assert not waiter.done()
        await asyncio.wait_for(waiter, timeout=0.1)
        audit.close()

    asyncio.run(exercise())


def test_parrot_mode_uses_icon_free_label_and_restores_exact_last_display(tmp_path) -> None:
    runtime = SoftwareRadioEndpoint(SoftwareRadioConfig(), tmp_path / "audit.jsonl")
    shown = []

    class Emulator:
        async def send_interactive_display(self, display) -> None:
            shown.append(display)

    runtime._emulator = Emulator()  # type: ignore[assignment]
    runtime._task = type("Task", (), {"done": lambda self: False})()  # type: ignore[assignment]
    runtime._loop = asyncio.new_event_loop()
    runtime._run_action = lambda coroutine, timeout=35.0: runtime._loop.run_until_complete(coroutine)  # type: ignore[method-assign]
    original_raw = bytearray(68)
    original_raw[:8] = b"ORIGINAL"
    original_raw[57] = 0x40
    runtime.send_display(bytes(original_raw))
    label = DisplayBuffer(b"-PARROT-" + bytes(60))
    runtime.set_parrot_enabled(True, mode_display=label)
    queued_raw = bytearray(original_raw)
    queued_raw[:8] = b"LAST ONE"
    runtime.send_display(bytes(queued_raw))
    runtime.set_parrot_enabled(False)
    assert [display.raw for display in shown] == [bytes(original_raw), label.raw, bytes(queued_raw)]
    assert shown[1].raw[56] == 0
    assert shown[1].raw[57] == 0
    runtime._loop.close()


def test_physical_volume_press_clamps_and_shows_verified_overlay(tmp_path) -> None:
    async def exercise() -> None:
        runtime = SoftwareRadioEndpoint(
            SoftwareRadioConfig(
                speaker_volume=31,
                handle_volume_keys=True,
                idle_display_text="-PARROT-",
            ),
            tmp_path / "audit.jsonl",
        )
        displayed: list[str] = []

        class Emulator:
            async def send_interactive_display(self, display) -> None:
                displayed.append(display.primary_text)

        runtime._emulator = Emulator()  # type: ignore[assignment]
        runtime._on_audit(
            {
                "event": "received",
                "kind": "key_state",
                "metadata": {"key_button": "volume_up", "key_action": "press"},
            }
        )
        await asyncio.sleep(0)
        assert runtime.state.snapshot()["speaker_volume"] == 32
        assert displayed == [" VOL 32"]
        assert runtime._volume_overlay_task is not None
        runtime._volume_overlay_task.cancel()

    asyncio.run(exercise())


def test_disconnect_discards_pending_parrot_audio(tmp_path) -> None:
    async def exercise() -> None:
        runtime = SoftwareRadioEndpoint(
            SoftwareRadioConfig(), tmp_path / "audit.jsonl"
        )
        runtime.set_parrot_enabled(True)
        runtime._begin_parrot_capture()
        runtime._on_audio((1234).to_bytes(2, "big", signed=True) * 160)
        runtime._schedule_parrot_playback()
        runtime._on_audit({"event": "disconnected"})
        await asyncio.sleep(0)
        snapshot = runtime.state.snapshot()
        assert snapshot["parrot_status"] == "ready"
        assert snapshot["parrot_packets"] == 0

    asyncio.run(exercise())
