# Changelog

All notable public-library changes are recorded here. Protocol evidence remains
in `docs/PROTOCOL.md`; this file tracks package and compatibility changes.

## Unreleased

- Update the architecture documentation after retiring the standalone UI
  migration scaffold into `ip-commandmic-gateway`.

## 1.0.1 — 2026-08-22

- Rewrites the project README around the library's bidirectional integration
  purpose, installation, endpoint selection, verified scope and example uses.
- Adds a navigable documentation index, concise implementation-status page and
  community roadmap while keeping normative protocol material versioned beside
  the implementation and tests.
- Adds concise `AGENTS.md` guidance for safe, evidence-backed contributions by
  coding agents.
- Makes no runtime or stable-API behavior changes from 1.0.0.

## 1.0.0 — 2026-08-21

- Declares the documented stable API and language-independent wire protocol
  contract supported under semantic versioning for the `1.x` series.
- Closes both physical endpoint matrices, 20/20 physical-power recovery cycles,
  and both bounded five-minute stability soaks using the published rc3 wheel.
- Retains measured callback, buffering, packetization and pacing latency as the
  library gate while classifying acoustic/RF end-to-end latency as optional
  post-v1 product characterization.
- Includes the verified soft-power state machine and final primary-display
  character/decimal-point corrections accepted during rc3 hardware testing.

## 1.0.0rc3 — 2026-08-21

- Completes physically verified real-radio soft-power off/on behavior: a
  one-second Power hold, both `f5/05/03` transition variants, their two-frame
  acknowledgement, heartbeat-only standby, and wake restoration.
- Projects powered-off standby explicitly to applications: blank display,
  status LED off, ordinary controls/PTT disabled, and Power retained.
- Decodes the high bit of a printable primary-display byte as its embedded
  decimal point while preserving the seven-bit character, verified by the
  real `BATT 13.7V` display.
- Records physically verified uppercase `B` and `V` rendering references for
  consumers of the supplied CommandMic display geometry.

## 1.0.0rc2 — 2026-08-21

- Adds cancellable bounded speaker playback through
  `SoftwareRadioEndpoint.stop_audio_playback()` and rejects overlapping audio
  playback operations.
- Records physical confirmation that microphone gain changes take effect during
  an already-connected session.

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
