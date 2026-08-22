# IP CommandMic

Open protocol documentation and a Python library for integrating software with
the Ethernet CommandMic used by Icom F5330D and F6330D radios.

`ip-commandmic` implements **both ends of the connection**:

- replace the physical CommandMic with software that controls and exchanges
  audio with a real radio; or
- replace the radio with software that receives controls and microphone audio
  from a physical CommandMic while driving its display and speaker.

The goal is a reusable integration layer—not just one microphone emulator.
Projects can build radioless AllStarLink nodes, dispatch or logging systems,
browser gateways, accessibility tools, automation, multi-radio controllers, or
custom input devices without reimplementing the wire protocol.

This independent interoperability project is not affiliated with or endorsed
by Icom Incorporated.

## Status

Version **[1.0.1](https://github.com/Mason10198/ip-commandmic/releases/tag/v1.0.1)**
is stable and available from [PyPI](https://pypi.org/project/ip-commandmic/).
Both endpoint roles, ordinary controls, the primary display, indicators, soft
power, PTT and bidirectional low-latency audio have been tested against real
hardware.

Some extended display characters, auxiliary states, key chords/accessories and
advanced radio-managed functions remain under investigation. See the
[implementation status](docs/PROJECT_STATUS.md) for the concise boundary and
the [feature matrix](docs/FEATURE_MATRIX.md) for detailed evidence coverage.

## Install

The wire protocol and application-fed audio APIs have no required third-party
runtime dependencies:

```bash
python -m pip install ip-commandmic
```

Install native audio-device support when the application needs the computer's
speakers or microphone:

```bash
python -m pip install "ip-commandmic[audio]"
```

Python 3.11 or newer is required.

## Choose an endpoint role

| What is connected | Library class | Software becomes |
|---|---|---|
| Real F5330D/F6330D radio | `SoftwareCommandMicEndpoint` | The CommandMic |
| Physical or software CommandMic | `SoftwareRadioEndpoint` | The radio-side application |

### Control a real radio

```python
from pathlib import Path
from time import monotonic, sleep
from ip_commandmic import SoftwareCommandMicEndpoint

mic = SoftwareCommandMicEndpoint(
    local_ip="192.168.0.2",
    radio_ip="192.168.0.1",
    microphone_device=None,
    enable_tx=False,
    play_rx_audio=False,
    audit_path=Path("commandmic.jsonl"),
)
mic.start()
deadline = monotonic() + 10
while not mic.state.snapshot()["controls_ready"] and monotonic() < deadline:
    sleep(0.05)
if not mic.state.snapshot()["controls_ready"]:
    raise TimeoutError("CommandMic did not become ready")
mic.key("p1", "press")
mic.key("p1", "release")
mic.stop()
```

### Operate a physical CommandMic

```python
from pathlib import Path
from time import monotonic, sleep
from ip_commandmic import DisplayBuffer, SoftwareRadioConfig, SoftwareRadioEndpoint

radio = SoftwareRadioEndpoint(
    SoftwareRadioConfig(local_ip="192.168.0.1", mic_ip="192.168.0.2"),
    Path("commandmic.jsonl"),
)
radio.start()
deadline = monotonic() + 10
while not radio.state.snapshot()["controls_ready"] and monotonic() < deadline:
    sleep(0.05)
if not radio.state.snapshot()["controls_ready"]:
    raise TimeoutError("CommandMic did not become ready")
radio.send_display(DisplayBuffer.from_primary_text("HELLO"))
radio.send_led("green")
radio.stop()
```

Applications should handle endpoint errors and keep transmit explicitly gated.
The complete lifecycle, audio and state APIs are documented in the
[Python API guide](docs/CONTROLS_API.md).

## What the library provides

- Lossless TCP framing, byte stuffing, CRC and stream reassembly.
- Typed messages and raw unknown-message preservation.
- Startup, identity, heartbeat, reconnect and soft-power state machines.
- Canonical controls, PTT, display, LED, backlight, gain and volume models.
- RTP/PT125 audio: 8 kHz mono signed 16-bit big-endian PCM in 20 ms packets.
- Bounded sources, sinks, jitter handling, recording and common-file conversion.
- Hardware-free bidirectional conformance and sanitized regression fixtures.
- An independent Wireshark dissector.

The protocol specification is language-independent. Python is the tested
reference implementation, not a requirement for independent implementations.

## Documentation

Start at the [documentation index](docs/README.md):

- [Protocol specification](docs/PROTOCOL.md)
- [Message and display catalogue](docs/MESSAGE_CATALOG.md)
- [Python API](docs/CONTROLS_API.md)
- [Implementation status](docs/PROJECT_STATUS.md)
- [Roadmap](docs/ROADMAP.md)
- [Conformance and verification](docs/CONFORMANCE.md)
- [Architecture](docs/ARCHITECTURE.md)

Documentation stays beside the source so protocol claims, implementation,
fixtures and tests can be reviewed and versioned together.

## Related applications

- [IP CommandMic Gateway](https://github.com/Mason10198/ip-commandmic-gateway) —
  cross-platform gateway and browser/PWA application under development.
- [IP CommandMic Desktop](https://github.com/Mason10198/ip-commandmic-desktop) —
  published Windows software-CommandMic reference client.
- [IP CommandMic Lab](https://github.com/Mason10198/ip-commandmic-lab) —
  published Windows physical-CommandMic reference and conformance client.

## Development

```bash
python -m venv .venv
python -m pip install -e ".[audio,dev]"
python -m pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting protocol mappings.
Unknown bytes must remain lossless, and hardware claims require repeatable
evidence with privacy-safe fixtures.

## Safety

Connecting either endpoint actively sends network traffic. Disconnect the
hardware endpoint being replaced. Transmit-capable testing requires explicit
arming and suitable RF containment. Do not perform broad hardware fuzzing.

Raw captures, codeplugs, voice, device identifiers, proprietary software and
copyrighted manuals are excluded from the public repository. See
[SECURITY.md](SECURITY.md), [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
