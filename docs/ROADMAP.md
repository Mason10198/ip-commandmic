# IP CommandMic roadmap

This roadmap tracks work after the `ip-commandmic` 1.0 release. Protocol
coverage is reported in [FEATURE_MATRIX.md](FEATURE_MATRIX.md); verified wire
details live in [PROTOCOL.md](PROTOCOL.md) and
[MESSAGE_CATALOG.md](MESSAGE_CATALOG.md).

## Released foundation

Version 1.0 provides lossless framing, typed messages, both endpoint roles,
startup/heartbeat/reconnect/soft-power behavior, ordinary controls, the primary
display and indicators, and bidirectional RTP audio. It passed hardware-free
conformance and bounded physical acceptance in both roles. Exact guarantees are
listed in [V1_SCOPE.md](V1_SCOPE.md) and [CONFORMANCE.md](CONFORMANCE.md).

## Active product work

The [IP CommandMic Gateway](https://github.com/Mason10198/ip-commandmic-gateway)
is the primary application under development. Its first release will run one
endpoint role at a time through a local browser UI with explicit ownership,
bounded audio and fail-closed PTT.

Desktop and Lab remain published reference clients and conformance tools. New
general-purpose UI and orchestration work normally belongs in the gateway.

## Protocol backlog

Near-term research:

- expand startup, routed-address and abnormal reconnect coverage;
- finish auxiliary display-byte and extended-glyph mapping;
- verify key repeat, long-hold, chord and hook/accessory behavior;
- add sanitized fixtures for every newly verified mapping; and
- keep the specification, implementation, tests and dissector synchronized.

Later research:

- scan, priority, call/signaling and user-set-mode semantics;
- VOX, hook, horn, GPS and Bluetooth-related link behavior;
- remaining beep/ringer variants and calibrated acoustic volume behavior; and
- synchronized end-to-end audio latency characterization.

## Integration backlog

- Radioless AllStarLink adapter using CommandMic audio, PTT and controls.
- Multi-radio orchestration with explicit RX/TX selection, display ownership,
  collision prevention and fail-closed PTT.
- Stable local gateway API for automation and non-Python consumers.

These are application-layer integrations. They should use public endpoint APIs
rather than add application policy to the protocol library.

## Separately gated work

Emergency, remote-destructive actions and firmware-sensitive operations require
a written safety plan, suitable test hardware and explicit authorization. They
must not be inferred or fuzzed on operational equipment.

## Recording progress

Every feature family remains in [FEATURE_MATRIX.md](FEATURE_MATRIX.md) until it
is verified, blocked by a named prerequisite, or demonstrated not to travel
over the CommandMic link. A protocol claim should include repeatable evidence,
a sanitized fixture when possible, an evidence identifier, implementation
coverage and a regression test. Unknown bytes remain lossless and explicitly
unknown.
