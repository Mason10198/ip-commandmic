# Changelog

All notable public-library changes are recorded here. Protocol evidence remains
in `docs/PROTOCOL.md`; this file tracks package and compatibility changes.

## Unreleased

No changes yet.

## 1.0.0rc1 — 2026-08-21

### Added

- Proposed version 1 support contract and machine-readable stable/advanced
  export sets.
- Cross-platform Python 3.11–3.14 CI, clean distribution tests and scheduled
  extended loopback conformance.
- Full safe-control conformance for 23 ordinary keys, Power, LEDs, backlight,
  microphone gain and synthetic displays.
- Routed TCP/UDP interruption and abrupt child-process replacement recovery.
- Inline typing marker, release archive inspection and retained JSON conformance
  reports.
- Synthetic typed-message fixture and normative composer/dissector
  cross-reference.
- A retained 30-minute-per-direction hardware-free release soak covering
  90,000 continuous radio RTP packets, 90,012 continuous microphone RTP
  packets, ten cold-object cycles, routed interruption and abrupt process
  replacement.

### Fixed

- The public software-radio configuration and disconnected state now default
  speaker volume to 22, matching the Lab application.
- Published startup fixtures and the software-CommandMic default now use an
  explicitly synthetic locally administered identity instead of a laboratory
  device MAC; physical-radio acceptance remains a v1 release gate.
- Long paced radio audio now receives an operation timeout based on its actual
  duration instead of detaching after 35 seconds.
- The Wireshark dissector now types verified `01/04` audio-path states.
- Sustained latency acceptance uses median/p95/maximum statistics and tolerates
  at most one isolated operating-system scheduling outlier, or 100 parts per
  million in longer runs, without weakening exact wire continuity, callback
  delivery or no-catch-up checks; failure reports now retain compact packet
  counts instead of multi-megabyte timing arrays.
- Extended conformance now retains an ordered RTP arrival timeline across the
  16-bit sequence wrap reached by a 90,000-packet/30-minute direction, instead
  of overwriting the first sequence cycle in a dictionary.

## 0.2.0a21 — 2026-08-20

- Initial clean public protocol-library repository snapshot.
- Both transparent endpoint roles, lossless framing, typed controls/display,
  gated bidirectional RTP, recording, Parrot support and baseline conformance.
- Runtime microphone-gain control using the observed `gain,gain+1` transaction.
