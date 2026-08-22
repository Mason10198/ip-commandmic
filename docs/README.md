# IP CommandMic documentation

This directory contains the versioned documentation for the protocol and
Python reference implementation. Start with the path that matches your goal.

## Use the library

- [Python API](CONTROLS_API.md) — endpoint lifecycle, controls, display, audio
  sources/sinks and state snapshots.
- [Architecture](ARCHITECTURE.md) — ownership boundaries between the library,
  gateway and reference applications.
- [Latency](LATENCY.md) — buffering, pacing and no-stale-audio requirements.

## Implement the protocol

- [Protocol specification](PROTOCOL.md) — transport, framing, CRC, RTP, session
  timing and evidence ledger.
- [Message catalogue](MESSAGE_CATALOG.md) — observed messages, control values,
  display fields and startup inventory.
- [Version 1 contract](V1_SCOPE.md) — stable API and interoperability boundary.

## Understand project status

- [Implementation status](PROJECT_STATUS.md) — concise implemented, partial and
  planned capability map.
- [Feature matrix](FEATURE_MATRIX.md) — detailed protocol coverage ledger.
- [Roadmap](ROADMAP.md) — prioritized protocol, product and integration work.
- [Conformance](CONFORMANCE.md) — automated and physical verification boundary.

## Research and release work

- [Experiment runbook](EXPERIMENTS.md) — evidence collection and safety rules.
- [Endpoint profiles](EMULATOR.md) — endpoint behavior and physical acceptance.
- [Release procedure](RELEASING.md) — build and publication workflow.
- [1.0 release record](RELEASE_READINESS.md) — completed release evidence.

Protocol facts and public API documentation stay in this repository so a pull
request can update code, tests, fixtures and documentation atomically. A wiki
would be appropriate for informal community tutorials or troubleshooting that
does not need to track a library version; it is not the normative source.
