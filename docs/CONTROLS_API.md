# Python library API

Status: public reference API for package version `1.0.0`.

The `ip_commandmic` package is the implementation shared by the primary IP
CommandMic Gateway, reference Desktop/Lab applications, capture tools and tests.
Applications should use the endpoint classes below. They should use wire-level
functions only for analyzers, dissectors, conformance tools or deliberate
research interfaces.

`V1_STABLE_EXPORTS` and `V1_ADVANCED_EXPORTS` provide a machine-readable split
of the top-level package surface described by `V1_SCOPE.md`.

## Endpoint APIs

### `SoftwareCommandMicEndpoint`

Implements the CommandMic side of the link and connects a software UI or service
to a real F5330D/F6330D radio. It owns TCP startup/reconnect, heartbeat,
display acknowledgements, UDP bootstrap, receive audio, low-latency microphone
capture and PTT timing.

```python
from pathlib import Path
from time import monotonic, sleep
from ip_commandmic import SoftwareCommandMicEndpoint


def wait_until_ready(endpoint, timeout=10.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if endpoint.state.snapshot()["controls_ready"]:
            return
        sleep(0.05)
    raise TimeoutError("CommandMic controls did not become ready")

mic = SoftwareCommandMicEndpoint(
    local_ip="192.168.0.2",
    radio_ip="192.168.0.1",
    microphone_device=None,
    enable_tx=True,
    play_rx_audio=True,
    audit_path=Path("commandmic.jsonl"),
)
mic.start()
wait_until_ready(mic)
mic.key("p1", "press")
mic.key("p1", "release")
mic.ptt("press")
mic.ptt("release")
state = mic.state.snapshot()
mic.stop()
```

Services and gateways can inject already-converted application audio without
opening a local capture device:

```python
from ip_commandmic import BufferedMicrophoneSource, SoftwareCommandMicEndpoint

source = BufferedMicrophoneSource(queue_packets=1)
mic = SoftwareCommandMicEndpoint(
    local_ip="192.168.0.2",
    radio_ip="192.168.0.1",
    microphone_device=None,
    enable_tx=True,
    play_rx_audio=False,
    audit_path=Path("commandmic.jsonl"),
    tx_audio_source=source,
)
mic.start()                         # starts and owns the source lifecycle
source.push_payload(pcm_s16be)      # exactly 320 bytes / 20 ms
```

`tx_audio_source` requires `enable_tx=True` and is mutually exclusive with a
named `microphone_device`; injection cannot bypass explicit TX arming. Sources
implement `MicrophoneAudioSource`. `BufferedMicrophoneSource` is the reference
thread-safe adapter: callers continuously push 8 kHz mono s16be frames from any
thread, stale frames are overwritten, and an underrun emits exact silence
instead of replaying old speech.

`audio_peer_ip` is an optional advanced routing hook. It leaves the TCP control
peer unchanged while sending and validating UDP voice against a distinct peer
address. Normal radio/CommandMic connections omit it. It exists for explicit
media relays, gateways and deterministic conformance proxies; changing it is
not a claim that physical hardware uses a different voice peer.

`SoftwareRadioConfig.control_peer_ip` is the corresponding optional TCP routing
hook for the radio-side endpoint. When omitted, control connects directly to
`mic_ip`; when supplied, only the TCP destination changes. The logical
CommandMic and UDP peer settings remain independent. This is intended for
explicit gateways and conformance relays, not physical-peer discovery.

`rx_audio_sink` accepts any object implementing the public `RadioAudioSink`
protocol (`start`, `on_packet`, `on_gate`, and `close`). This provides verified
gated radio RTP to applications without opening a local playback device and
lets integrations use the shared `RadioAudioJitterBuffer`. It is mutually
exclusive with `play_rx_audio=True`, so one endpoint never drives two competing
playout paths. Gate events reset session state; missing playout frames become
exact silence and stale audio is not carried into the next gate.

Both RTP senders use an absolute 20 ms monotonic schedule and rebase after a
late deadline instead of compressing subsequent packets into a catch-up burst.
Their `rx_audio_completed` and `mic_tx_audio_completed` audit records expose
the first send timestamp, maximum deadline lateness and pacing-resynchronization
count for application monitoring and conformance.

Public operations are `start()`, `stop()`, `tap(button)`,
`key(button, "press"|"release")`, `ptt("press"|"release")`, and
`set_tx_armed(bool)`. `state.snapshot()` is JSON-safe and contains connection,
session, display, LED, audio, PTT, control-readiness and error state.

`tap()` remains for compatibility and scripted tests. Interactive programs
should use `key()` so a physical mouse/key hold is reproduced on the wire.
Emergency is encoded only through its explicit gated path. PTT releases on
disconnect and shutdown.

### `SoftwareRadioEndpoint`

Implements the radio side of the link and lets software operate a physical
CommandMic or the Desktop software CommandMic. It owns the two-session startup,
heartbeat, display transaction/acknowledgement, UDP bootstrap, key/PTT decoding,
RTP receive, audio output and recording.

```python
from pathlib import Path
from time import monotonic, sleep
from ip_commandmic import DisplayBuffer, SoftwareRadioConfig, SoftwareRadioEndpoint


def wait_until_ready(endpoint, timeout=10.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if endpoint.state.snapshot()["controls_ready"]:
            return
        sleep(0.05)
    raise TimeoutError("CommandMic controls did not become ready")

radio = SoftwareRadioEndpoint(
    SoftwareRadioConfig(local_ip="192.168.0.1", mic_ip="192.168.0.2"),
    Path("software-radio.jsonl"),
)
radio.start()
wait_until_ready(radio)
radio.send_display(DisplayBuffer.from_primary_text("HELLO"))
radio.send_led("green")
radio.send_tone(1000, -24, 1.0)
state = radio.state.snapshot()       # live buttons, PTT and audio meters
radio.start_recording("mic.wav")    # streaming 8 kHz/16-bit mono WAV
radio.stop_recording()
radio.stop()
```

The endpoint also supports `send_wav(path)`, `send_audio_file(path)` and
`send_raw(frame)`. `send_wav()` is the strict verified 8 kHz/16-bit/mono PCM
path. `send_audio_file()` decodes bounded WAV, MP3, FLAC, OGG/Vorbis and AIFF
input through the shared audio layer, resamples it to the protocol format and
applies the endpoint's current speaker volume. Raw sends
accept exactly one complete, parseable CommandMic frame; malformed or multiple
frames are rejected. `send_display()` accepts a lossless 68-byte
`DisplayBuffer`, so known and unknown bytes survive round trips.

`state.snapshot()` retains `mic_capture_count` and `last_mic_capture` as
durable capture observability. The latter contains packet count, duration and
RTP continuity fields from the most recently completed PTT capture. These
fields remain available after the bounded 200-entry UI event history wraps
during a long stream.

`set_speaker_volume(0..32)` exposes the verified radio volume range to
radio-side applications. The endpoint starts at 22 unless configured
otherwise. Zero is digital mute and 32 is unity; the reference endpoint
distributes levels 1–32 over an approximately perceptually uniform
48 dB application-side range. That curve is a best-effort software policy,
not a protocol claim, because the radio's exact acoustic transfer law is not
yet measured. `handle_volume_keys=True`
lets physical Volume Up/Down presses clamp this state and show the verified
`VOL nn` overlay before restoring `idle_display_text`.

`set_parrot_enabled(bool, mode_display=...)` provides bounded in-memory
current-PTT capture state for applications such as the Lab GUI. On release,
the endpoint waits for the capture-owned 350 ms tail-completion event before it
opens the opposite-direction speaker gate. This prevents the verified delayed
TX-close transaction from racing and closing the new speaker gate. Quiet
captured speech is normalized to a -9 dBFS peak with at most 24 dB lift before
the selected speaker-volume gain is applied. A supplied mode display is sent
without replacing the exact prior application display; disabling Parrot
restores that 68-byte state. New application displays submitted during Parrot
are retained and restored when the mode ends.

Mode labels that should contain text only must use a display with offsets
56–63 cleared. `DisplayBuffer.from_primary_text()` intentionally retains the
historical capture-derived `LOW`/RSSI baseline and is not appropriate for an
icon-free overlay.

`SoftwareRadioConfig` defaults to passive control observation. Startup uses
neutral blank display synchronization, and received keys/PTT do not generate
channel, volume, LED, or audio-state traffic. Applications may explicitly opt
into demonstration key feedback with `automatic_key_responses=True` or the PTT
microphone-audio response with `automatic_ptt_responses=True`.

When a microphone-audio callback or streaming WAV recorder is configured, the
endpoint opens its local RTP capture gate for every observed PTT hold even when
automatic PTT responses are disabled. That is sufficient for software peers
that send RTP independently, but the physical CommandMic was observed to send
zero RTP until it receives the verified TX-active/status response. A radio-side
application that needs physical-microphone audio must therefore set
`automatic_ptt_responses=True`; this responds only to an actual PTT hold and
does not enable ordinary key/display feedback.

`set_mic_gain(1..5)` sends the observed two-frame `gain,gain+1` microphone-gain
transaction and updates the endpoint snapshot immediately. The complete value
mapping and its acoustic effect are verified at startup. Acceptance of changing
the same pair during an already-stable physical session remains an explicit
hardware check; the API does not claim that untested timing as new protocol
evidence.

`send_backlight("off"|"dim"|"on")` changes the physical CommandMic backlight
immediately. Like `send_display()` and `send_led()`, it is a typed endpoint
operation; applications do not need to construct protocol frames.

`send_polyphonic(steps, level_dbfs=-18)` accepts caller-defined
`(delay_ms, length_ms, frequencies)` steps and sends simultaneous frequencies
through the verified CommandMic audio path. The library intentionally does not
define named songs or animations; those presentation choices belong to the
application using these generic media and device primitives.

Display-oriented applications can generate their editors from protocol-owned
metadata instead of copying wire offsets:

```python
from ip_commandmic import (
    verified_character_blink_controls,
    verified_display_bit_controls,
    verified_display_blink_bit_controls,
    verified_display_visual_modes,
    verified_display_svg_decimal_point_paths,
)
```

`verified_display_bit_controls()` covers the four steady segment planes at
offsets 56–59. `verified_display_blink_bit_controls()` exposes their exact
verified blink-mask mirrors at offsets 60–63. Character attribute bit `0x80`
for all eight positions is returned by `verified_character_blink_controls()`,
and the synchronized whole-LCD patterns are returned by
`verified_display_visual_modes()`. Each item includes its canonical UI name and
the value/offset/mask needed to compose a `DisplayBuffer`.

For decoded offset-64 values `0x02` and `0x04`,
`DisplayBuffer.verified_offset64_pattern` provides the photographed composition
as canonical 14-segment names by character position, indicator names, and
decimal-point positions. Renderers should use this metadata instead of
approximating the patterns with ordinary text glyphs.

Decimal-point controls are returned in physical left-to-right order, Dot 1
through Dot 8. The supplied display SVG does not number its point path IDs in
physical order; renderers must use
`verified_display_svg_decimal_point_paths()` instead of assuming sequential
path IDs. `DISPLAY_BUFFER_SIZE`, `PRIMARY_TEXT_SIZE` and `STATUS_LED_COLORS` are
also public so application capability descriptions do not duplicate protocol
dimensions or typed LED choices.

### Hardware-free conformance

`run_loopback_conformance(artifact_directory, timeout_seconds=12,
sustained_audio_seconds=1, cold_restart_cycles=3)` starts both
public endpoint roles on `127.0.0.1`/`127.0.0.2` with audio devices disabled and
returns a JSON-safe `ConformanceReport`. It verifies stable startup, a synthetic
exact-display corpus, every LED/backlight state, all 23 ordinary keys, Power,
microphone gain 1–5, gated RTP in both
directions, injected nonzero application PCM, producer overwrite, fail-silent
underrun, RTP continuity, PTT release, fail-closed
disconnect, deterministic microphone-RTP drop/duplicate/reorder detection,
clean post-impairment recovery, mid-stream cancellation with fail-closed media
finalization and no post-stop RTP, clean same-object restart in both directions,
immediate software-radio reconnect, routed TCP/UDP interruption, abrupt child-
process replacement, and fresh-object reconstruction with alternating startup
order plus display/key/audio validation. Sustained duration
is bounded to 1–1800 seconds per direction and fresh-object cycles to 1–100. Each
`ConformanceCheck` is `passed`, `failed`, or `not_covered`; callers must inspect
the per-check status rather than interpreting `report.passed` as exhaustive
hardware coverage. See [CONFORMANCE.md](CONFORMANCE.md).

## Device models

- `DisplayBuffer` is the lossless 68-byte LCD payload and exposes primary text,
  static/blinking icons, RSSI segments, decimal points, P1–P4 boxes,
  character-blink attributes, visual-pattern controls and unresolved fields.
- `DisplayStateModel` consumes synchronization/buffer/ack messages without
  assuming one TCP segment equals one application message.
- `GuiState` and `EndpointState` provide thread-safe JSON snapshots suitable for
  native, web, IPC or automation front ends.
- `EndpointState.waveform` retains the latest complete 160-sample, 8 kHz audio
  frame so consumers can produce time-domain or full 0–4 kHz spectrum views.
- `RadioAudioPacket`, `RadioAudioGateEvent`, jitter-buffer types and audio-source
  classes expose the verified 8 kHz signed-big-endian PCM media path.

## Control identities

The `01/01` matrix is represented by `KEY_PRESS_VALUES`. Public canonical names:

```text
f1, volume_up, volume_down
p1, p2, p3, p4
up, down, left, right
keypad_0 ... keypad_9, keypad_star, keypad_hash
emergency
```

PTT (`01/00`) and Power (`01/09`) are separate message families. The physical
rocker has no center switch. Press/release values, aliases and human labels live
in `ip_commandmic.controls`; GUIs do not maintain their own wire-code tables.

## Wire API

```python
from ip_commandmic import (
    Direction, build_frame, encode_key_state, encode_key_tap,
    encode_display_transaction, encode_status_led, encode_backlight_state,
    encode_mic_gain_transaction, encode_ptt_state, encode_power_state, encode_audio_path,
    encode_message, parse_stream, stuff_bytes, unstuff_bytes,
)
```

- `parse_stream(data, direction) -> (messages, remainder)` handles arbitrary TCP
  fragmentation, coalescing, stuffing and resynchronization while preserving
  unexplained bytes.
- `encode_message(message)` round-trips original bytes.
- `build_frame(class_, command, payload, start_byte=0xf3)` is the expert encoder.
- `encode_key_state()` and `encode_key_tap()` are verified typed composers.
- Display, LED, backlight, microphone-gain, PTT, Power and audio-path families
  have corresponding typed `encode_*` composers; endpoint methods remain
  preferred for sessions.
- `RADIO_IDLE_HEARTBEAT` and `MIC_IDLE_HEARTBEAT` are exported reference frames.

Unknown messages are not discarded. `Message.raw`, `body`, framing/checksum
validity, direction and metadata remain available to applications.

## Audio API

RTP uses payload type 125, 160 samples per packet and a 20 ms cadence. Payloads
are signed 16-bit big-endian PCM at 8 kHz mono. Helpers include:

- `generate_s16be_tone_payloads()`;
- `MicrophoneAudioSource` and thread-safe `BufferedMicrophoneSource` for
  application-fed continuous TX audio;
- `load_s16be_wav_payloads()`;
- `load_s16be_audio_file_payloads()` for bounded common-file decoding,
  mono conversion, 8 kHz resampling and 20 ms protocol packetization;
- `FfmpegMicrophoneSource` and low-latency miniaudio implementations used by the
  desktop endpoint;
- `RadioAudioJitterBuffer` and playback-frame/statistics types;
- endpoint-level live playback, tone/WAV output, microphone capture and WAV
  recording.

End-user programs should prefer endpoint methods so RTP sequence, timestamps,
gates, startup and close tails remain correct.

## Compatibility and safety

Package API version `0.2.x` preserves raw bytes and canonical button names.
Newly mapped fields may add metadata without changing prior meanings. A future
breaking API will increment the minor/major compatibility declaration and retain
capture decoding through explicit schema versions.

Connecting an endpoint actively emits traffic. Disconnect the hardware endpoint
being replaced. Real-radio PTT requires RF containment. Raw sends and Emergency
are expert operations; broad hardware fuzzing is outside this API's safe use.
