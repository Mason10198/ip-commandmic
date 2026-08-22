# Icom IP CommandMic protocol and Python library

An evidence-backed, language-neutral protocol specification and Python reference
implementation for the Ethernet CommandMic used with Icom F5330D/F6330D radios.

Status: **[1.0.0 stable](https://github.com/Mason10198/ip-commandmic/releases/tag/v1.0.0)**,
published on [PyPI](https://pypi.org/project/ip-commandmic/1.0.0/).
The stable API contract and hardware-free release gates are complete. Major
everyday controls, the LCD, status LED,
startup, reconnection, PTT and bidirectional low-latency audio are implemented
and tested against real hardware. Final `1.0.0` remains blocked only by final
artifact and package-index publication steps
listed in [the release-readiness ledger](docs/RELEASE_READINESS.md). Some
auxiliary display controls, uncommon state messages and error branches remain
explicitly deferred from the scoped v1 contract.

This is an independent interoperability project and is not affiliated with or
endorsed by Icom Incorporated.

## Repository contents

- `src/ip_commandmic`: lossless parser, typed composers, display/control
  models, audio transport and both endpoint roles;
- `docs/PROTOCOL.md`: normative working protocol specification;
- `docs/MESSAGE_CATALOG.md`: byte layouts, confidence and examples;
- `docs/CONTROLS_API.md`: public Python API;
- `docs/CONFORMANCE.md`: hardware-free endpoint baseline and remaining gates;
- `docs/V1_SCOPE.md`: stable 1.x API boundary, release gates and exclusions;
- `docs/RELEASE_READINESS.md`: live v1 completion and publication checklist;
- `docs/RELEASING.md`: reproducible candidate verification and publication procedure;
- `docs/MASTER_PLAN.md`: phased reverse-engineering and acceptance plan;
- `wireshark/ip_commandmic.lua`: independent Wireshark dissector;
- `tests`: sanitized fixtures and regression/conformance tests.

Package-level changes are summarized in [`CHANGELOG.md`](CHANGELOG.md).

Applications and shared presentation live separately:

- [`@ip-commandmic/ui`](https://github.com/mason10198/ip-commandmic-ui) — shared
  semantic UI contracts, renderer components and visual theme;
- [IP CommandMic Desktop](https://github.com/mason10198/ip-commandmic-desktop) —
  Windows/macOS native-webview application;
- [IP CommandMic Web](https://github.com/mason10198/ip-commandmic-web) — browser
  gateway and PWA;
- [IP CommandMic Lab](https://github.com/mason10198/ip-commandmic-lab) —
  physical-mic hardware lab and protocol exerciser.

## Install for development

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[audio,dev]"
.\.venv\Scripts\python -m pytest
```

Run the public-wrapper loopback baseline without hardware or audio devices:

```powershell
.\.venv\Scripts\python -m ip_commandmic.conformance --artifact-directory artifacts/conformance
```

## Public endpoint roles

```python
from pathlib import Path
from time import monotonic, sleep
from ip_commandmic import SoftwareCommandMicEndpoint

mic = SoftwareCommandMicEndpoint(
    local_ip="192.168.0.2",
    radio_ip="192.168.0.1",
    microphone_device=None,
    enable_tx=True,
    play_rx_audio=True,
    audit_path=Path("commandmic.jsonl"),
)
mic.start()
deadline = monotonic() + 10.0
while not mic.state.snapshot()["controls_ready"] and monotonic() < deadline:
    sleep(0.05)
if not mic.state.snapshot()["controls_ready"]:
    raise TimeoutError("CommandMic controls did not become ready")
mic.key("p1", "press")
mic.key("p1", "release")
mic.stop()
```

`SoftwareCommandMicEndpoint` replaces a physical CommandMic on a real radio.
`SoftwareRadioEndpoint` implements the opposite role for a physical or software
CommandMic. Gateways may provide continuous 20 ms PCM frames through the public
thread-safe `BufferedMicrophoneSource` without opening a local capture device.
Lower-level framing and models are available for integrations that need direct
protocol access. See [the API guide](docs/CONTROLS_API.md).

## Verified transport summary

- control: TCP port 52001;
- audio: RTP/UDP port 50000, payload type 125;
- media: signed 16-bit big-endian PCM, 8 kHz mono;
- packetization: 160 samples / 320 payload bytes every 20 ms;
- TCP application messages use byte stuffing and CRC-16/Modbus;
- TCP segmentation is unrelated to application-message boundaries.

Unknown bytes and messages are preserved losslessly. The project distinguishes
verified observations, strong inference and unresolved hypotheses throughout
the specification.

## Safety and evidence policy

Connecting either endpoint actively transmits network traffic. Disconnect the
hardware endpoint being replaced and use appropriate RF containment for every
transmit test. Raw hardware fuzzing is outside the supported workflow.

Raw captures, codeplugs, voice recordings, serial numbers, proprietary software
and copyrighted manuals are intentionally excluded. Contributions should use
minimal sanitized fixtures and stable evidence identifiers.

Original project code and documentation are available under the
[MIT License](LICENSE). See [NOTICE.md](NOTICE.md) for trademark and third-party
asset limitations.
