# IP CommandMic roadmap

This roadmap tracks work that remains after the `ip-commandmic` 1.0 release.
Protocol coverage is reported separately in [FEATURE_MATRIX.md](FEATURE_MATRIX.md);
verified wire details live in [PROTOCOL.md](PROTOCOL.md) and
[MESSAGE_CATALOG.md](MESSAGE_CATALOG.md).

## Project goal

Provide an open, evidence-backed interface to both sides of the Ethernet link
between an Icom F5330D/F6330D radio and its CommandMic:

- software can replace the CommandMic and operate a real radio; and
- software can replace the radio and operate a physical CommandMic.

The library exposes controls, display state, indicators, power state and
bidirectional audio as application APIs. It is intended as infrastructure, not
only as the backend for the project's own applications.

Example integrations include:

- a radioless AllStarLink node built around a physical CommandMic;
- a local or network gateway that presents a radio through a browser;
- dispatch, logging, accessibility or automation software;
- one control surface coordinating multiple radios under explicit arbitration;
- mapping CommandMic buttons, PTT and audio into a simulator or game controller.

Multi-radio coordination and application-specific policies belong above the
protocol library. The library provides endpoint primitives and never decides
which radio should receive a user action.

## Released foundation

Version 1.0 provides:

- lossless TCP framing, stuffing, CRC validation and stream reassembly;
- typed messages for verified controls and device state;
- software-CommandMic and software-radio endpoint implementations;
- startup, heartbeat, reconnect and soft-power state handling;
- the primary 68-byte display model, mapped indicators, LED and backlight;
- all 23 mapped ordinary controls, separately gated PTT, Power and Emergency;
- RTP audio in both directions with bounded buffering and observable metrics;
- application-fed microphone audio and application-consumed receive audio;
- sanitized fixtures, conformance tests and a Wireshark dissector.

The release passed hardware-free bidirectional conformance, bounded physical
stability/restart tests in both roles, and functional tests against the real
radio and physical CommandMic. Exact scope and exclusions are recorded in
[V1_SCOPE.md](V1_SCOPE.md) and [CONFORMANCE.md](CONFORMANCE.md).

## Active product work

### Unified gateway

[`ip-commandmic-gateway`](https://github.com/Mason10198/ip-commandmic-gateway)
is the primary application under development. It will run either endpoint role
and expose a locally hosted browser/PWA interface. Its first release focuses on
one attached endpoint, explicit control ownership, bounded audio and fail-closed
PTT. See that repository's `GATEWAY_PLAN.md` for implementation milestones.

### Reference applications

- [`ip-commandmic-desktop`](https://github.com/Mason10198/ip-commandmic-desktop)
  is a physically tested software CommandMic for Windows.
- [`ip-commandmic-lab`](https://github.com/Mason10198/ip-commandmic-lab) is a
  physically tested software-radio endpoint and diagnostic console for Windows.

They remain useful examples and conformance tools. New general-purpose product
features should normally be implemented in the gateway.

## Protocol backlog

### Near term

- Expand startup, routed-address and abnormal reconnect coverage.
- Finish auxiliary display-byte and extended-glyph mapping.
- Verify key repeat, long-hold, chord and hook/accessory behavior.
- Add small, sanitized fixtures for each newly verified mapping.
- Keep the specification, Python implementation, tests and dissector synchronized.

### Later investigation

- Scan, priority, call/signaling and user-set-mode semantics.
- VOX, hook, horn, GPS and Bluetooth-related link behavior.
- Remaining beep/ringer variants and calibrated acoustic volume behavior.
- Synchronized end-to-end audio latency characterization.
- Multi-radio orchestration as a separate integration layer.

### Separately gated work

Emergency, remote-destructive actions and firmware-sensitive operations require
a written safety plan, suitable test hardware and explicit authorization. They
must not be inferred or fuzzed on operational equipment.

## How completion is recorded

Every feature family remains in [FEATURE_MATRIX.md](FEATURE_MATRIX.md) until it
is verified, blocked by a named prerequisite, or demonstrated not to travel
over the CommandMic link. A protocol claim should include repeatable evidence,
a sanitized fixture when possible, an evidence identifier, implementation
coverage and a regression test. Unknown bytes remain lossless and explicitly
unknown.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the contribution workflow.
