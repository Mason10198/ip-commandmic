# Version 1 support contract

Status: release-candidate contract for `1.0.0`. The hardware-free contract is
accepted; the physical gates listed below remain mandatory before the final
release. The exhaustive research plan remains broader than this contract.

## Supported purpose

Version 1 is a reusable SDK and language-independent specification for the
mapped Ethernet CommandMic transport. It supports both transparent endpoint
roles:

1. a software CommandMic connected to an Icom F5330D/F6330D radio; and
2. a software radio endpoint connected to a physical or software CommandMic.

Support means that the documented operation has a stable public API, preserves
unknown wire data where applicable, passes hardware-free conformance, and has
passed the applicable physical endpoint matrix. It does not mean that every
possible CPS assignment or internal radio feature has been semantically
decoded.

## Stable version 1 surface

The following top-level API families are covered by semantic-versioning
compatibility after `1.0.0`:

- lossless wire framing, parsing, stuffing, checksums and typed composers;
- `Direction`, `Message`, `MessageKind`, and raw unknown-message preservation;
- `DisplayBuffer`, display state, verified display metadata and dimensions;
- canonical ordinary-control identities and typed key/PTT/Power operations;
- RTP packet, source, sink, jitter-buffer and bounded audio-file contracts;
- `SoftwareCommandMicEndpoint` and its public lifecycle/control/audio methods;
- `SoftwareRadioConfig`, `SoftwareRadioEndpoint`, `EndpointState`, and their
  documented public methods and snapshot fields;
- `ConformanceCheck`, `ConformanceReport`, and `run_loopback_conformance()`.

Public signatures, accepted values, return shapes and documented snapshot keys
in these families will not be removed or incompatibly changed in a `1.x`
release. Additive fields and newly decoded metadata are allowed. A field that
preserves an unknown byte will not silently disappear when that byte is later
understood.

## Advanced and experimental surface

`AuditLog`, `CommandMicEmulator`, `EmulatorConfig`,
`VerifiedMicUdpProtocol`, and `VerifiedRadioUdpProtocol` are advanced research
interfaces. Their imports remain available in 1.0, but their internal timing,
private attributes and constructor details are not part of the stable 1.x
contract. Applications should use the endpoint wrappers.

`send_raw()` is a deliberate expert escape hatch. Its frame validation and
fail-closed connection behavior are stable; the effect of an arbitrary valid
frame is not supported or made safe by the library.

`set_mic_gain(1..5)` has a stable API and uses the fully observed startup
`gain,gain+1` transaction. Its effect when sent during an already-stable
physical CommandMic session must pass the v1 physical matrix before release;
until then that timing remains provisional rather than new protocol evidence.

## Required endpoint behavior

Version 1 must provide:

- ordinary framing over arbitrarily fragmented or coalesced TCP input;
- observed probe/stable startup, heartbeat and required powered-peer recovery;
- a privacy-safe synthetic default identity accepted by the supported physical
  radio profile;
- all 23 mapped ordinary key press/release identities;
- separately typed PTT and Power state, with Emergency excluded or explicitly
  gated;
- lossless 68-byte display transactions, status LED and backlight control;
- the verified 1–5 microphone-gain transaction and 0–32 application speaker
  volume state, defaulting to 22;
- bidirectional gated RTP/PT125 signed-16-bit big-endian 8 kHz mono audio;
- bounded queues, no stale-audio replay, no compressed catch-up bursts and
  fail-closed media/control state on stop or disconnect;
- bounded WAV/common-file operations and injectable application audio; and
- JSON-safe state, audit and conformance results.

## Release gates

`1.0.0` requires all of the following:

1. the complete automated unit suite passes on every supported Python version;
2. the public-wrapper conformance baseline contains no failed or
   `not_covered` check;
3. every v1-supported public operation has a unit or conformance regression;
4. a 30-minute hardware-free bidirectional soak passes;
5. true subprocess and network-interruption recovery matrices pass;
6. ten physical restart/reconnect cycles pass for each endpoint role;
7. a bounded five-minute physical idle/active soak passes for each endpoint
   role;
8. both physical endpoint matrices pass with no stuck PTT, stale audio,
   post-stop RTP or display divergence;
9. median, p95 and maximum software/audio latency are recorded for the
   controlled lab;
10. wheel and source distribution install and test from clean Python 3.11,
   3.12, 3.13 and 3.14 environments; and
11. the normative specification, message catalogue, API guide, feature matrix,
    sanitized fixtures and Wireshark dissector agree for supported messages.

Any unmet gate blocks `1.0.0`. A release candidate may be published with a
finite, prominently listed physical gate still open.

## Supported platforms

The pure protocol, model and hardware-free endpoint layers support Python 3.11
and newer on Windows, macOS and Linux. Native audio and physical-network claims
apply only to platform/device combinations listed in release notes as actually
accepted. Absence of a platform claim does not weaken the pure wire API.

## Explicit post-v1 research

The following do not block this scoped version 1 when their limitations remain
visible and raw data is preserved:

- individual semantics for advanced scan/priority, call lists and signaling;
- user-set-mode settings, GPS and Bluetooth functions;
- VOX, hanger/hook, horn and uncommon accessories;
- Emergency-mode behavior beyond the inert observed event;
- remote monitor, stun, kill, revive and other destructive behavior;
- firmware/configuration transfer and whether it is carried on this link;
- complete interpretation of every auxiliary display byte and extended glyph;
- the exact acoustic speaker-volume transfer curve; and
- internal names for unresolved microphone DSP behavior.

These items remain in `FEATURE_MATRIX.md`; they are deferred, not declared
complete or removed from the project.

## Evidence and safety boundary

No protocol claim becomes verified from software loopback alone. Hardware
claims require the evidence and repetition rules in `MASTER_PLAN.md`. Raw
captures, codeplugs, recorded voice, identifiers and proprietary Icom material
remain outside the public repository. RF-capable tests retain their existing
safety tier and require explicit containment and authorization.
