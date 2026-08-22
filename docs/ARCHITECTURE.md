# Library and application architecture

## Single source of protocol truth

All wire behavior belongs to `src/ip_commandmic`, never to a GUI asset:

| Layer | Modules | Responsibility |
|---|---|---|
| Wire | `checksums.py`, `protocol.py`, `models.py` | framing, stuffing, CRC, lossless parsing and typed composers |
| Device model | `controls.py`, `display.py` | canonical keys and lossless LCD/state interpretation |
| Media | `audio.py` | PCM/RTP payload conversion, live devices, jitter and WAV helpers |
| Sessions | `emulator.py`, `gui_server.py`, `test_app.py` endpoint classes | both endpoint roles, startup, heartbeat, ACKs, timers, reconnect and media lifecycle |
| Tools | `pcap.py`, `capture.py`, `analysis.py`, `experiments.py` | passive evidence collection and analysis |
| Applications | gateway plus reference Desktop/Lab clients | presentation, settings, browser transport and user interaction only |

`SoftwareCommandMicEndpoint` is the public high-level endpoint for a real radio.
`SoftwareRadioEndpoint` is the public high-level endpoint for a physical or
software CommandMic. Both are exported from `ip_commandmic`.

## GUI dependency rule

The IP CommandMic calls `SoftwareCommandMicEndpoint`; it never builds
startup, heartbeat, display ACK, key, PTT or RTP packets in JavaScript.

The IP CommandMic Lab calls `SoftwareRadioEndpoint`; it submits `DisplayBuffer`
values and typed LED/audio operations. Steady bits, blink masks, character
attributes and whole-LCD modes are generated from public display metadata in
the library. Its expert raw-frame field still passes through the library parser
before transmission.

`ip-commandmic-gateway` is the primary product. It embeds the browser-native
renderer and semantic action/event contracts, then binds them to exactly one
public endpoint role through authenticated WebSocket and bounded audio
transports. The browser never receives raw control frames or opens CommandMic
TCP/UDP sockets. The browser state, transport and theme scaffold has been folded
into the gateway and is maintained there with the service.

Desktop and Lab remain published reference/fallback clients and physical
conformance instruments. New general-purpose UI features belong in the gateway;
the reference clients change only for diagnostics, safety or hardware validation.

The radio-side endpoint defaults to a neutral, passive observer. Connection
necessarily performs the verified startup/heartbeat exchange and two blank
display synchronizations, but received controls do not trigger application
state unless an automatic response policy is explicitly enabled. Immediate
display, LED, backlight and audio actions remain typed endpoint operations.

JavaScript contains only presentation behavior: rendering the supplied decoded
display model, drawing waveforms, input hit-testing and formatting state. The
canonical key wire table, frame constants, CRC/stuffing, RTP timing and endpoint
state machines remain Python-library code. Tests assert the apps call those
public endpoints and that assets contain no protocol frame literals.

## Extension guidance

New integrations should import the package, subscribe to endpoint state/events,
and avoid copying captured byte strings. Add newly verified messages first to
the wire/device model with fixtures, then expose a typed endpoint operation, and
only then add UI. This order keeps the specification, library, dissector and
applications mutually testable.
