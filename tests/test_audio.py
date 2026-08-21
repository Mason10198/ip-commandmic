import asyncio
import math
import io
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from ip_commandmic.audio import (
    BufferedMicrophoneSource,
    KEY_BEEP_PROFILES,
    FfplayRadioAudioSink,
    FfmpegMicrophoneSource,
    MicrophoneCaptureStats,
    MiniaudioRadioAudioSink,
    RadioAudioGateEvent,
    RadioAudioJitterBuffer,
    RadioAudioPacket,
    decode_candidate_audio,
    generate_s16be_tone_payloads,
    generate_s16be_polyphonic_payloads,
    get_key_beep_profile,
    load_s16be_audio_file_payloads,
)


class AudioTests(unittest.TestCase):
    def test_buffered_application_source_is_latest_frame_and_fail_silent(self):
        source = BufferedMicrophoneSource(queue_packets=2)
        first = struct.pack(">h", 1000) * 160
        second = struct.pack(">h", 2000) * 160
        third = struct.pack(">h", 3000) * 160

        with self.assertRaisesRegex(RuntimeError, "not started"):
            source.push_payload(first)

        async def exercise():
            await source.start()
            with self.assertRaisesRegex(ValueError, "320 bytes"):
                source.push_payload(b"short")
            source.push_payload(first)
            source.push_payload(second)
            source.push_payload(third)
            self.assertEqual(third, source.latest_payload())
            self.assertEqual(bytes(320), source.latest_payload())
            await source.close()

        asyncio.run(exercise())
        self.assertEqual(
            MicrophoneCaptureStats(3, 1, 1, 1, 0), source.stats
        )
        with self.assertRaisesRegex(RuntimeError, "not started"):
            source.latest_payload()

    def test_common_audio_file_decode_resamples_and_packetizes_in_shared_layer(self):
        samples = [
            round(8000 * math.sin(2 * math.pi * 1000 * index / 16000))
            for index in range(1600)
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stereo-16khz.wav"
            with wave.open(str(source), "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(
                    b"".join(struct.pack("<hh", sample, sample) for sample in samples)
                )
            payloads, frames = load_s16be_audio_file_payloads(source)
        self.assertEqual(800, frames)
        self.assertEqual(5, len(payloads))
        self.assertTrue(all(len(payload) == 320 for payload in payloads))
        self.assertGreater(max(abs(sample[0]) for sample in struct.iter_unpack(">h", b"".join(payloads))), 7000)

    def test_polyphonic_score_preserves_delay_and_packetized_duration(self):
        payloads = generate_s16be_polyphonic_payloads((
            (250, 100, (330.0, 440.0)),
            (0, 100, (440.0, 660.0)),
            (0, 100, (660.0, 880.0)),
        ))
        self.assertEqual(28, len(payloads))  # 550 ms padded to 560 ms.
        silence = b"".join(payloads)[: 250 * 16]
        self.assertEqual({0}, set(silence))
        self.assertNotEqual({0}, set(b"".join(payloads)[250 * 16 : 350 * 16]))
    def test_ffmpeg_microphone_source_uses_bounded_directshow_capture(self):
        source = FfmpegMicrophoneSource(
            "Microphone (Test Device)",
            executable="ffmpeg.exe",
            queue_packets=1,
            device_buffer_ms=20,
        )
        command = source.command
        self.assertIn("audio=Microphone (Test Device)", command)
        self.assertEqual("20", command[command.index("-audio_buffer_size") + 1])
        self.assertEqual("8000", command[command.index("-ar") + 1])
        self.assertEqual("1", command[command.index("-ac") + 1])
        self.assertEqual("pipe:1", command[-1])
        self.assertEqual(1, source.queue_packets)

    @staticmethod
    def radio_packet(sequence, *, session=1, value=1):
        return RadioAudioPacket(
            session=session,
            sequence=sequence,
            timestamp=sequence * 160,
            ssrc=0xB1947EF9,
            payload_s16be=struct.pack(">h", value) * 160,
        )

    def test_s16be_converts_to_wav_little_endian(self):
        source = struct.pack(">hhh", -32768, 0, 32767)
        decoded, width = decode_candidate_audio(source, "s16be")
        self.assertEqual(2, width)
        self.assertEqual(struct.pack("<hhh", -32768, 0, 32767), decoded)

    def test_capture_backed_key_beep_profiles(self):
        normal = get_key_beep_profile("normal")
        low = get_key_beep_profile("low")
        self.assertEqual((1000.0, 4, 0.08), (
            normal.frequency_hz, normal.packet_count, normal.duration_seconds
        ))
        self.assertEqual((500.0, 7, 0.14), (
            low.frequency_hz, low.packet_count, low.duration_seconds
        ))
        self.assertEqual({"normal", "low"}, set(KEY_BEEP_PROFILES))
        self.assertEqual(3, normal.beep_level)
        with self.assertRaisesRegex(ValueError, "unknown key beep profile"):
            get_key_beep_profile("unverified")

    def test_fixed_beep_levels_use_measured_six_db_law(self):
        normal = [get_key_beep_profile("normal", level) for level in range(1, 6)]
        low = [get_key_beep_profile("low", level) for level in range(1, 6)]
        self.assertAlmostEqual(-43.296935, normal[0].observed_rms_dbfs, places=6)
        self.assertAlmostEqual(-19.214833, normal[-1].observed_rms_dbfs, places=6)
        self.assertAlmostEqual(-42.557205, low[0].observed_rms_dbfs, places=6)
        self.assertAlmostEqual(-18.495399, low[-1].observed_rms_dbfs, places=6)
        for profiles in (normal, low):
            increments = [
                current.observed_rms_dbfs - prior.observed_rms_dbfs
                for prior, current in zip(profiles, profiles[1:])
            ]
            self.assertTrue(all(5.98 < increment < 6.04 for increment in increments))
        with self.assertRaisesRegex(ValueError, "1 through 5"):
            get_key_beep_profile("normal", 6)

    def test_key_beep_generator_has_verified_packet_shape_frequency_and_level(self):
        for profile in KEY_BEEP_PROFILES.values():
            payloads = generate_s16be_tone_payloads(
                frequency_hz=profile.frequency_hz,
                level_dbfs=profile.level_dbfs,
                packet_count=profile.packet_count,
            )
            self.assertEqual(profile.packet_count, len(payloads))
            self.assertTrue(all(len(payload) == 320 for payload in payloads))
            samples = [
                sample[0]
                for payload in payloads
                for sample in struct.iter_unpack(">h", payload)
            ]
            crossings = sum(
                prior <= 0 < current for prior, current in zip(samples, samples[1:])
            )
            measured_hz = crossings / (len(samples) / 8000.0)
            rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
            measured_rms_dbfs = 20.0 * math.log10(rms / 32768.0)
            self.assertAlmostEqual(profile.frequency_hz, measured_hz, delta=15.0)
            self.assertAlmostEqual(profile.observed_rms_dbfs, measured_rms_dbfs, delta=0.05)

    def test_jitter_buffer_reorders_and_prebuffers_three_packets(self):
        jitter = RadioAudioJitterBuffer(prebuffer_packets=3)
        self.assertTrue(jitter.push(self.radio_packet(100)))
        self.assertTrue(jitter.push(self.radio_packet(102, value=3)))
        self.assertIsNone(jitter.pop())
        self.assertTrue(jitter.push(self.radio_packet(101, value=2)))
        frames = [jitter.pop(), jitter.pop(), jitter.pop()]
        self.assertEqual([100, 101, 102], [frame.sequence for frame in frames])
        self.assertTrue(all(not frame.concealed for frame in frames))
        self.assertEqual(struct.pack("<h", 2) * 160, frames[1].pcm_s16le)

    def test_jitter_buffer_conceals_loss_and_rejects_late_and_duplicate(self):
        jitter = RadioAudioJitterBuffer(prebuffer_packets=2)
        self.assertTrue(jitter.push(self.radio_packet(10)))
        self.assertFalse(jitter.push(self.radio_packet(10)))
        self.assertTrue(jitter.push(self.radio_packet(12)))
        first = jitter.pop()
        missing = jitter.pop()
        third = jitter.pop()
        self.assertEqual((10, False), (first.sequence, first.concealed))
        self.assertEqual((11, True, bytes(320)), (
            missing.sequence, missing.concealed, missing.pcm_s16le
        ))
        self.assertEqual((12, False), (third.sequence, third.concealed))
        self.assertFalse(jitter.push(self.radio_packet(11)))
        self.assertEqual((3, 1, 1, 1), (
            jitter.stats.played,
            jitter.stats.concealed,
            jitter.stats.duplicates,
            jitter.stats.late,
        ))

    def test_jitter_buffer_handles_sequence_wrap_and_gate_reset(self):
        jitter = RadioAudioJitterBuffer(prebuffer_packets=2)
        jitter.push(self.radio_packet(0xFFFF))
        jitter.push(self.radio_packet(0))
        self.assertEqual([0xFFFF, 0], [jitter.pop().sequence, jitter.pop().sequence])
        jitter.push(self.radio_packet(50, session=2))
        self.assertIsNone(jitter.pop())
        jitter.push(self.radio_packet(51, session=2))
        self.assertEqual((2, 50), (jitter.pop().session, 50))

    def test_jitter_buffer_validates_prebuffer(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 25"):
            RadioAudioJitterBuffer(0)
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            RadioAudioJitterBuffer(max_gap_packets=0)

    def test_jitter_buffer_rejects_unbounded_sequence_discontinuity(self):
        jitter = RadioAudioJitterBuffer(prebuffer_packets=2, max_gap_packets=5)
        self.assertTrue(jitter.push(self.radio_packet(10)))
        self.assertFalse(jitter.push(self.radio_packet(1000)))
        self.assertEqual(1, jitter.stats.discontinuities)
        self.assertEqual(1, jitter.stats.buffered)

    def test_native_playback_gate_stops_concealment_and_stale_audio(self):
        sink = MiniaudioRadioAudioSink(prebuffer_packets=1, device_buffer_ms=20)
        playback = sink._playback()
        self.assertEqual(b"", next(playback))
        self.assertEqual(bytes(320), playback.send(160))

        sink.on_gate(RadioAudioGateEvent(1, True, 0))
        sink.on_packet(self.radio_packet(10, value=123))
        self.assertEqual(struct.pack("<h", 123) * 160, playback.send(160))
        concealed_before_close = sink.jitter.stats.concealed

        sink.on_gate(RadioAudioGateEvent(1, False, 1))
        for _ in range(5):
            self.assertEqual(bytes(320), playback.send(160))
        self.assertEqual(concealed_before_close, sink.jitter.stats.concealed)

    def test_ffplay_sink_uses_raw_8khz_pcm_and_drains_short_gate(self):
        class FakeProcess:
            def __init__(self):
                class Buffer(io.BytesIO):
                    def close(self):
                        pass
                self.stdin = Buffer()
                self.stderr = io.BytesIO()
                self.returncode = 0

            def wait(self, timeout=None):
                return 0

            def terminate(self):
                pass

        process = FakeProcess()
        with mock.patch("ip_commandmic.audio.subprocess.Popen", return_value=process) as popen:
            sink = FfplayRadioAudioSink(prebuffer_packets=3, executable="ffplay-test")
            sink.start()
            sink.on_gate(RadioAudioGateEvent(1, True, 0))
            for sequence in range(4):
                sink.on_packet(self.radio_packet(sequence, value=sequence + 1))
            sink.on_gate(RadioAudioGateEvent(1, False, 4))
            sink.close()
        command = popen.call_args.args[0]
        self.assertIn("s16le", command)
        self.assertIn("8000", command)
        self.assertIn("nobuffer", command)
        self.assertIn("low_delay", command)
        self.assertNotIn("audio_buffer_size", command)
        self.assertEqual((5 + 4 + 5) * 320, len(process.stdin.getvalue()))

    def test_ffplay_sink_validates_render_padding(self):
        with self.assertRaisesRegex(ValueError, "startup_silence_packets"):
            FfplayRadioAudioSink(startup_silence_packets=26, executable="test")
        with self.assertRaisesRegex(ValueError, "tail_silence_packets"):
            FfplayRadioAudioSink(tail_silence_packets=-1, executable="test")
        with self.assertRaisesRegex(ValueError, "max_backend_queue_packets"):
            FfplayRadioAudioSink(max_backend_queue_packets=2, executable="test")

    def test_ffplay_sink_reports_backend_failure(self):
        class FailedProcess:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stderr = io.BytesIO(b"no render endpoint")
                self.returncode = 1

            def wait(self, timeout=None):
                return self.returncode

            def terminate(self):
                pass

        with mock.patch(
            "ip_commandmic.audio.subprocess.Popen", return_value=FailedProcess()
        ):
            sink = FfplayRadioAudioSink(executable="ffplay-test")
            sink.start()
            with self.assertRaisesRegex(RuntimeError, "no render endpoint"):
                sink.close()

    def test_ffplay_sink_bounds_backend_packet_queue(self):
        sink = FfplayRadioAudioSink(
            executable="ffplay-test", max_backend_queue_packets=3
        )
        for sequence in range(10):
            sink.on_packet(self.radio_packet(sequence))
        self.assertEqual(7, sink.backend_queue_drops)


if __name__ == "__main__":
    unittest.main()
