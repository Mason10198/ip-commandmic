# Endpoint profiles and acceptance

`ip-commandmic` provides both sides of the mapped Ethernet CommandMic link.
Applications should use the public endpoint wrappers documented in
[`CONTROLS_API.md`](CONTROLS_API.md):

- `SoftwareCommandMicEndpoint` replaces a physical CommandMic for a radio; and
- `SoftwareRadioEndpoint` replaces a radio for a physical or software
  CommandMic.

The lower-level `CommandMicEmulator`, `EmulatorConfig` and verified UDP
protocol classes remain importable for research and conformance, but their
constructor details and timing internals are outside the stable v1 contract.
The separately packaged Desktop, Web and Lab applications build on the same
public wrappers; this library does not install their GUI assets or legacy
research console scripts.

## Safety boundary

Connecting either endpoint sends active TCP and UDP traffic. Disconnect the
hardware endpoint being replaced. Keep the real radio disconnected during
software-only work. Any later test involving a radio must use the containment,
authorization and explicit TX gates in [`MASTER_PLAN.md`](MASTER_PLAN.md).

Emergency is not part of ordinary conformance. Arbitrary `send_raw()` traffic,
programming, firmware, destructive radio features and broad hardware fuzzing
are outside the supported workflow.

## Software CommandMic profile

`SoftwareCommandMicEndpoint` listens because the observed radio initiates both
the probe and stable TCP sessions. The wrapper owns:

- the five-frame neutral startup burst;
- the protocol-shaped 26-byte identity response;
- the mic and radio UDP boot exchange;
- the special probe response and stable reconnect;
- lossless display parsing and verified display acknowledgement;
- heartbeat replies, connection watchdog and fail-closed recovery;
- ordinary key, Power and explicitly gated PTT state;
- gated radio-audio playout or an injected `RadioAudioSink`; and
- live-device or injected `MicrophoneAudioSource` RTP transmission.

The published identity uses the synthetic locally administered MAC
`02:00:00:00:00:01`. It never replays the laboratory CommandMic address.
Hardware-free conformance verifies the message shape and both software roles;
acceptance of this public synthetic identity by the physical radio remains a
v1 release-candidate gate.

Minimal lifecycle:

```python
from pathlib import Path

from ip_commandmic import SoftwareCommandMicEndpoint

mic = SoftwareCommandMicEndpoint(
    local_ip="192.168.0.2",
    radio_ip="192.168.0.1",
    microphone_device=None,
    enable_tx=False,
    play_rx_audio=False,
    audit_path=Path("artifacts/commandmic.jsonl"),
)
mic.start()
try:
    # Wait for mic.state.snapshot()["controls_ready"] before sending controls.
    pass
finally:
    mic.stop()
```

Controls remain unavailable until the stable session reports readiness. TX is
disabled unless `enable_tx=True`, and PTT still requires the runtime TX gate.
Stopping or losing the peer clears readiness, PTT and audio state before a
subsequent session can become active.

## Software radio profile

`SoftwareRadioEndpoint` initiates the observed probe/stable sequence and owns:

- startup sync, heartbeat and display transactions;
- all four status-LED values and three backlight states;
- microphone-gain transactions for verified levels 1 through 5;
- application speaker volume state from 0 through 32;
- receive-audio gates and paced tone, WAV or common-file playback;
- live mic-RTP callback, absolute PCM statistics and bounded WAV recording;
- Record/Save and Parrot workflows in the Lab application; and
- fail-closed stop, peer-loss and restart behavior.

Minimal lifecycle:

```python
from pathlib import Path

from ip_commandmic import DisplayBuffer, SoftwareRadioConfig, SoftwareRadioEndpoint

radio = SoftwareRadioEndpoint(
    SoftwareRadioConfig(
        local_ip="192.168.0.1",
        mic_ip="192.168.0.2",
        mic_gain=3,
        speaker_volume=22,
    ),
    Path("artifacts/radio"),
)
radio.start()
try:
    # Send these only after radio.state.snapshot()["controls_ready"] is true.
    radio.send_backlight("on")
    radio.set_mic_gain(4)
    radio.send_display(DisplayBuffer.from_primary_text("V1 TEST"))
finally:
    radio.stop()
```

The default policy is neutral: startup and heartbeat traffic are necessary,
but received keys do not invent channel, zone or radio semantics. Applications
may subscribe to state and audit events or enable only the automatic response
policies they explicitly need.

## Media behavior

Both directions use RTP payload type 125 carrying signed 16-bit big-endian,
8 kHz mono PCM in 160-sample/20 ms packets. Media opens only inside its matching
control gate. Queues are bounded, underrun is fail-silent, stale frames are
discarded across gates and sender pacing does not compress missed deadlines
into catch-up bursts.

Application audio is injectable without local devices. A gateway can supply
microphone frames through `BufferedMicrophoneSource`, while a consumer can
implement `RadioAudioSink` for received radio frames. Native miniaudio support
is optional through the `audio` package extra.

Recorded WAV data is a byte-order conversion of accepted PCM; no hidden gain is
applied. Absolute capture statistics report samples, frames, bytes, elapsed
seconds, RMS/peak dBFS, clipping and RTP continuity counts. See
[`LATENCY.md`](LATENCY.md) for the software timing contract and remaining
physical measurement gate.

## Hardware-free acceptance

Run the public-wrapper baseline without a radio, CommandMic or local audio
device:

```powershell
python -m ip_commandmic.conformance `
  --artifact-directory artifacts/conformance
```

The extended v1 gate uses 1,800 seconds in each media direction and ten fresh
endpoint-object restart cycles. It also performs routed TCP/UDP interruption
and abrupt child-process replacement. The CLI writes `report.json` beside both
JSONL audits. Exact coverage and thresholds are in
[`CONFORMANCE.md`](CONFORMANCE.md).

Hardware-free success proves implementation consistency, not new physical wire
semantics.

## Bounded physical acceptance runner

`scripts/run_physical_acceptance.py` automates the ten-cycle and five-minute
physical reliability gate while leaving only peer power removal/restoration to
the operator. It emits audible cues, detects loss and recovery, rejects any
transient instability during the soak, fails on PTT or endpoint errors, and
writes a sanitized JSON summary beside a private JSONL audit.

For a software CommandMic and dummy-loaded real radio:

```powershell
python scripts/run_physical_acceptance.py `
  --role software-commandmic --dummy-load-confirmed `
  --cycles 10 --soak-seconds 300 `
  --output artifacts/software-mic-physical-acceptance.json
```

For a real CommandMic and software radio, with the real radio disconnected:

```powershell
python scripts/run_physical_acceptance.py `
  --role software-radio --real-radio-disconnected `
  --cycles 10 --soak-seconds 300 `
  --output artifacts/software-radio-physical-acceptance.json
```

The software-CommandMic role always starts with microphone transmission and
receive playback disabled. The software-radio role always disables automatic
PTT and ordinary-key responses. Run the script using the clean environment in
which the exact release-candidate wheel was installed.

## Remaining physical acceptance

Before final `1.0.0`, the exact candidate must still pass:

1. physical-CommandMic/Lab display, LED/backlight, gain, volume, recording,
   Parrot and speaker-playback checks;
2. real-radio/software-CommandMic startup with the synthetic identity, all
   supported controls, display/indicators, receive audio, live transmit audio
   and PTT;
3. ten restart/reconnect/PoE cycles for each physical endpoint role;
4. a bounded five-minute idle/active soak for each role.

Synchronized acoustic/RF end-to-end latency is useful post-v1 product
characterization, not a protocol-library release gate.

The current gate ledger is [`RELEASE_READINESS.md`](RELEASE_READINESS.md).
Normative wire claims and their retained evidence identifiers are in
[`PROTOCOL.md`](PROTOCOL.md); message layouts and confidence are in
[`MESSAGE_CATALOG.md`](MESSAGE_CATALOG.md).
