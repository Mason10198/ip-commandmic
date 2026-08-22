# CommandMic exhaustive bidirectional protocol master plan

## Objective

Understand and document the complete Ethernet protocol between the Icom
F5330D/F6330D and its PoE CommandMic well enough to build either replacement:

1. a software CommandMic that exposes 100% of CommandMic functionality to a
   real radio; and
2. a software radio endpoint that exposes 100% of real-CommandMic functionality.

The target includes every function discoverable in the CPS/help, every physical
control, every display/indicator/audio behavior, every configuration-dependent
variant, and all normal and abnormal connection states. The earlier limited v1
scope and ordinary-test exclusions are superseded by this plan.

Absolute mathematical proof that no inaccessible firmware state exists is not
possible from black-box observation. Project completion therefore means
**exhaustive tested coverage of the declared feature universe**, with unavailable
hardware/licensing prerequisites and genuinely opaque fields explicitly listed.
Nothing may be counted complete merely because it was not seen.

## Current handoff checkpoint (2026-08-21)

The independently packaged components are `ip-commandmic 1.0.0rc3`,
`ip-commandmic-desktop 0.1.0-alpha.9`, and `ip-commandmic-lab
0.1.0-alpha.32`. The library rc3 and Lab alpha.32 prereleases are public on
GitHub; TestPyPI and PyPI remain pending. Automated suites
pass (199
library tests plus 5 subtests, 3
Desktop tests, and 19 Lab tests). The `ip-commandmic-ui` and
`ip-commandmic-web` repositories are initialized contract scaffolds and are not
release products yet.

The physical-CommandMic Lab matrix is accepted through alpha.32, including live
gain changes, display restoration, fresh audio statistics/spectrum, recording,
Parrot, the full volume range, file playback/stop, backlight and status LED.
The real-radio/software-CommandMic matrix also accepts all codeplug-enabled
ordinary keys, RX/TX audio and PTT, the complete volume range, display and LED
projection, and physically verified soft-off, heartbeat-only standby and wake.
Earlier alpha.19 audit evidence showed valid PTT press/release and
an open local capture gate but zero RTP packets. This established that the
physical CommandMic requires the verified radio TX-active/status response
before it emits microphone RTP. Alpha.20 enables that response only after an
actual physical PTT press while leaving ordinary key feedback disabled. Its
first hardware audit sent the verified active/close transactions and completed
a 24.88-second capture containing 1,244 RTP packets with no callback error.
Wire/audio delivery is therefore verified; explicit operator confirmation of
the spectrum/peak/RMS rendering and a saved/listened WAV remain open.

Alpha.21 added bounded in-memory Parrot capture/replay, a verified-range 0-32
application speaker-volume state with mute/clamping and physical F2/F3 overlay
handling, and an LED-off post-startup state. Its first physical audit proved
that Parrot captured and transmitted RTP, but also exposed an ordering bug: the
fixed 225 ms replay timer opened the speaker before the delayed PTT close frame,
which immediately closed the new path.

Alpha.22 waits for the actual 350 ms capture-tail completion event before
speaker-open, applies bounded speech normalization, sends an icon-free
`-PARROT-` display, and restores the exact prior 68-byte screen on disable. It
also corrects Dot 1–8 builder ordering and the display SVG's nonsequential dot
path mapping. Volume 0 and 32 remain exact mute/unity boundaries; levels 1–32
now span a best-effort perceptually uniform 48 dB curve. The exact acoustic
radio/CommandMic transfer law remains unmeasured and is not claimed as mapped.
Alpha.23 additionally makes steady decimal-point checkboxes and primary-text
period modifiers bidirectional, enforces the eight non-dot character limit in
the GUI, and selects application speaker volume 25 by default.

Lab alpha.25 and Desktop alpha.9 complete the current public-alpha release
hardening pass. Both applications use one visual palette and obtain protocol
dimensions, typed device values, supplied-SVG decimal-point geometry, endpoint
sessions and audio behavior from `ip-commandmic 0.2.0a12`. Common-file decode,
resampling and packetization moved into the shared audio layer. Windows x64
packages retain pywebview's complete maintained Windows loader set and must pass
a frozen native-backend initialization smoke test before packaging. Runtime
audits/settings use per-user writable locations. Each app packages a
`RELEASE_READINESS.md` that distinguishes the verified public-alpha scope from
open hardware/protocol acceptance gates.

The shared library now has a hardware-free public-wrapper conformance baseline.
It runs the software-radio and software-CommandMic endpoints on loopback and
verifies stable startup, exact icon-free display delivery, LED state, ordinary
key press/release, gated radio RTP, fail-closed disconnect and immediate
software-radio restart. Version a14 adds a public, thread-safe injectable
application-audio source and extends the baseline through acknowledged PTT,
nonzero mic RTP, bounded newest-frame overwrite, fail-silent underrun, zero
sequence/timestamp errors and clean release, so both media directions now pass
without local audio hardware. Sustained audio load, latency, soak and both
physical-hardware matrices remain open. See `CONFORMANCE.md`.

Version a15 separates the optional UDP audio peer from the TCP control peer for
explicit relay/conformance use. Its loopback proxy injects one microphone-RTP
drop, duplicate and reordered pair, verifies sequence/timestamp fault detection
and safe PTT release, then proves the next clean capture resets to zero errors.
No physical-peer addressing behavior is inferred from the test hook.

Version a16 adds the matching optional TCP control-peer route on the radio-side
wrapper. A loopback relay now fragments one frame-bearing transaction and
coalesces multiple complete frames in each direction, then verifies exact
display delivery and key press/release through the public endpoints. Repeated
fresh-session runs pass. Radio-to-CommandMic RTP jitter/concealment remains the
next deterministic impairment gap.

Version a17 adds a public injectable `RadioAudioSink` contract to the software
CommandMic wrapper without opening local audio hardware. The bidirectional UDP
relay now drops, duplicates and reorders radio RTP; conformance proves one exact
silence concealment frame, duplicate rejection, ordered bounded-reorder playout
and a clean following receive gate. Deterministic TCP and RTP impairment now
pass in both directions; sustained stress, cancellation, restart and measured
latency are the next software-only media gates.

Version a18 aligns radio RTP with the microphone sender's no-catch-up 20 ms
pacing policy and adds first-send, maximum-lateness and resynchronization audit
metrics. Its public-wrapper gate sustains 50 radio packets and 62 PTT-gated
microphone packets per run with continuous RTP. Five fresh runs measured
sub-2.5 ms maximum receive callback latency and sub-6.0 ms maximum sender
deadline lateness. These are hardware-free software-path bounds, not acoustic
or RF latency.

Version a19 adds deterministic mid-stream endpoint cancellation and same-object
restart in both media directions. Stopping the CommandMic during PTT and the
radio during speaker playback now explicitly closes the corresponding UDP
media gate/capture, cancels and gathers all event-loop work before reuse, emits
no RTP after stop, fails control/PTT/audio state closed, and establishes a
clean fresh media session after restart. Three fresh full conformance runs
passed consecutively under Python 3.11, and the built wheel passed the same
13-check gate in a clean Python 3.14 environment. The listener now owns its
lifetime directly and cancels accepted-session tasks before awaiting server
closure, avoiding the reversed shutdown order in newer asyncio implementations.
Longer soak and process/network restart matrices remain open.

Version a20 parameterizes sustained media duration and fresh endpoint-object
restart cycles. Its accepted hardware-free stress run carried 500 continuous
radio RTP packets over 10 seconds and 512 continuous microphone RTP packets
over 10.24 seconds, then reconstructed both public endpoint roles ten times
with alternating mic-first/radio-first ordering and fresh display, key and audio
transactions on every cycle. Sustained traffic also proved that the bounded UI
event ring cannot serve as durable completion state, so `EndpointState` now
retains an independent capture counter and last capture summary. True process
replacement and routed TCP/UDP interruption now pass; the 30-minute soak remains
open. The built
a20 wheel also passed all 14 baseline checks from a clean Python 3.14
environment.

The workspace-level `START_HERE.md` records exact release locations, the
next-session procedure and repository/publication status.

The scoped stable-library release contract is maintained in `V1_SCOPE.md`.
It deliberately separates the version 1 interoperable SDK gate from later
exhaustive P4/P5 semantic closure; deferred rows remain visible in the feature
matrix.

The 2026-08-21 release-candidate hardware-free gate passed all 19 public-wrapper
checks in 3,676.282 seconds. Its two 30-minute sustained directions carried
90,000 continuous radio RTP packets and 90,012 continuous microphone RTP
packets, followed by ten fresh-object restart cycles, routed-link interruption
and abrupt child-process replacement. Hardware-free v1 conformance is complete.
E-098 closes both physical restart/stability gates from the published rc3 wheel
with 20/20 recoveries and two bounded five-minute soaks. Only final
artifact/package-index publication remains a scoped v1 release blocker;
synchronized acoustic/RF latency is post-v1 product characterization.

## Delivery priorities

The investigation is ordered around two usable products. Protocol semantics that
are unnecessary for transparent endpoint replacement must not delay them.

1. **Primary product — software CommandMic for a real radio.** With the physical
   CommandMic disconnected, software must establish and maintain the complete
   session, reproduce the screen and indicators, provide every physical control,
   and carry live receive and transmit audio. This is the shortest path to using
   the F5330D/F6330D without any physical CommandMic.
2. **Secondary product — software radio for a physical CommandMic.** With the
   radio disconnected, software must boot and operate the physical CommandMic,
   render arbitrary screen/indicator state, receive every control and PTT event,
   and exchange live audio. A reference bridge will expose these capabilities to
   applications such as an AllStarLink node.
3. **Later exhaustive closure.** Advanced radio-feature semantics, uncommon
   accessories and safety-critical functions remain in the feature matrix, but
   are investigated after both transparent endpoint products work. Generic key
   transport and display reproduction can provide access to many such functions
   before their radio-side meanings are individually decoded.

“Every button” means the endpoint can generate or receive the physical control's
wire event, including press, release, hold and repeat behavior where present. It
does not require decoding the meaning of every possible CPS assignment before
the endpoint can be released. Emergency and other hazardous controls remain
capability-gated even when their ordinary wire representation is known.

## Deliverable architecture

The protocol knowledge must not be embedded only in either end-user program.
The project will publish one language-independent specification, one reference
library, and several thin applications built on that library.

### Protocol specification

`docs/PROTOCOL.md` and its linked evidence ledger are the normative description
of the wire protocol. They must be sufficient for an independent implementation
in another language and include transport, framing, messages, state machines,
screen layout, input events, audio, timing, errors and confidence/evidence IDs.

### Reference Python package: `ip-commandmic`

Python 3.11+ remains the reference implementation because it supports rapid
protocol iteration, networking, audio, automated tests and desktop tooling. The
package is divided into stable layers so applications do not manipulate raw
packets unless they explicitly opt into a research interface:

1. **Wire layer** — lossless frames, stuffing, CRC, typed messages, unknown-byte
   preservation, stream reassembly and exact encoders.
2. **Session layer** — both endpoint roles, startup, identity, acknowledgements,
   heartbeats, timers, watchdogs, reconnect and capability gates.
3. **Device-model layer** — screen regions/icons, LEDs, backlight, beeps, keys,
   PTT, volume/status, speaker, microphone and observable state/events.
4. **Audio layer** — RTP lifecycle, sequence/timestamp handling, 8 kHz PCM,
   live-device/WAV sources and sinks, buffering, gain/mute and recording.
5. **Integration layer** — asynchronous application API, raw-event access and
   adapters that keep AllStarLink or GUI policy out of the protocol core.

The public package must support both high-level operations such as setting text,
playing audio and subscribing to button events, and a lossless expert interface
for continued research. Protocol documents, fixtures and generated bytes remain
the compatibility authority; Python is the reference, not a language lock-in.

### Programs built on the package

1. **Virtual CommandMic application (primary product).** A real-radio client
   with a faithful virtual screen, indicators, every key, selectable PC speaker
   and microphone, PTT safety lock, logging and reconnect status.
2. **CommandMic Lab Console (investigation tool and secondary-product UI).** A
   software-radio client that can send text and complete visual/LED/backlight/
   beep state to a physical mic; play tones, WAV or live audio; monitor and
   record microphone audio; show all key/PTT events and timing; and export raw
   and decoded traces. It has a safe operator view and a separately enabled
   expert protocol view. A minimal version grows during Phases 0–1 to accelerate
   research; its complete supported product is accepted in Phase 2.
3. **AllStarLink-style bridge.** A thin, optional adapter mapping CommandMic
   microphone/speaker audio, PTT, COR/status, keys and display state onto a
   generic node interface. AllStar-specific behavior must not enter the core
   protocol library.
4. **Analysis utilities.** Capture/decode, live monitor, differential analysis,
   audio extraction, fixture generation and the Wireshark dissector.

### Distribution and compatibility

- Publish the specification, Python package, sanitized fixtures, dissector,
  command-line tools, example integrations and both reference applications.
- Package end-user applications so normal users do not need a Python development
  environment; editable Python installs remain available to researchers.
- Version the wire/message API separately from application UI releases and keep
  saved captures readable across compatible releases.
- If non-Python consumers need direct integration, first expose the stable device
  model through a documented local IPC/WebSocket/JSON service; independent native
  implementations can then be built from the normative protocol specification.
- Keep raw voice/configuration captures private by default and publish only
  minimized sanitized evidence fixtures.

## Scope boundary

In scope:

- Ethernet discovery, addressing, ports, routing, ARP, TCP control, UDP/RTP,
  reconnection, timeout, and peer-identification behavior;
- every CommandMic physical input, hold/repeat/chord behavior, hook/accessory
  state, and every CPS-assignable function;
- every display character/region, icon, LED, backlight, beep/ringer, speaker,
  microphone, gain/DSP, PTT, VOX, monitor, squelch, scan, channel, zone, call,
  signaling, emergency, GPS, Bluetooth, lock, light, set-mode, and system state
  that is represented across the radio–CommandMic link;
- analog and NXDN operating modes and every available signaling/call mode;
- configuration-dependent startup and runtime state, error handling, malformed
  input behavior, endpoint/link restart, and long-duration operation;
- firmware/configuration/programming transfers only if observation proves they
  traverse this CommandMic Ethernet protocol.

Out of scope unless evidence shows it is carried by this link:

- NXDN RF air-interface reverse engineering;
- Bluetooth/BLE protocols between the radio and separate Bluetooth devices;
- CS-F5330D cloning/programming protocols that communicate directly with the
  radio rather than through the CommandMic protocol;
- cryptographic bypass, firmware extraction, or defeating access controls.

## Definition of complete

Every row in `FEATURE_MATRIX.md` must reach one of these terminal states:

- **Verified bidirectional**: real-radio/real-mic traces define the behavior;
  both software endpoints reproduce it; conformance tests pass against both
  the opposite software endpoint and the applicable real endpoint.
- **Verified receive-only/transmit-only by design**: directionality is proven,
  represented in the API, and tested at the applicable endpoint.
- **Unavailable prerequisite**: the exact missing option, license, accessory,
  subscriber, RF generator, or mode is documented, along with the experiment
  that established the block. This is an explicit limitation, not completion
  of that function.
- **Not carried by CommandMic link**: synchronized negative captures prove the
  function uses another interface or remains entirely internal.

For every carried message, the final catalogue must include:

- direction, transport, framing, class/command/type, length, stuffing and CRC;
- byte/bit layout, data types, byte order, allowed values, unknown/reserved bits;
- state preconditions, trigger, acknowledgement, timing, repeats and timeout;
- positive, boundary, negative, malformed and reconnect behavior;
- configuration and operating-mode dependencies;
- at least three reproducible traces where the operation is repeatable;
- encoder and decoder fixtures and matching Wireshark fields;
- evidence identifiers and confidence level.

No application byte in accepted fixtures may disappear silently. Unknown bytes
must remain preserved and searchable until resolved or explicitly classified as
opaque/reserved through differential evidence.

## Coverage inventory

Build the feature universe from four independent sources and reconcile them:

1. CS-F5330D help topics, model/map data, label resources, enums, key-function
   lists, configuration pages, and CommandMic artwork;
2. radio and CommandMic operating/service documentation;
3. every menu, display, indicator, key, accessory and operating mode visible on
   the physical hardware;
4. every distinct message, value, length, state transition, and endpoint action
   found in full unfiltered captures.

The inventory must include at minimum:

- P1–P4, Side1–Side3/F1–F3, four-way rocker, Power, Emergency, PTT, keypad
  0–9/*/#/A–D legends, hook and any supported chord/hold/repeat behavior;
- all CPS key assignments, including Home, Shift, CH/Zone/MR-CH, Monitor,
  High/Low, scan, talk-around, lock, light, user set mode, GPS, Bluetooth,
  call/signaling and transmit-affecting assignments;
- channel, zone, scan, priority, signaling, call list, DTMF, emergency, lone
  worker, VOX, horn, backlight, beep/ringer, AF/SQL, mic gain, RF power,
  display/opening text, timers, hook behavior and network settings;
- all display regions/icons and orange/green LED states;
- analog/NXDN receive and transmit audio, silence, levels, clipping, loss,
  cadence, jitter, mute, gating and codec/format invariance;
- startup from every prior power state and endpoint order; link losses of
  multiple durations; address/port changes; routed operation; peer mismatch;
- unsupported, invalid, duplicate, out-of-order, fragmented, coalesced and
  checksum-corrupt messages.

## Evidence and safety tiers

### Tier 0 — offline/read-only

Documentation/resource inventory, passive capture, decode, differential
analysis, replay into software only, checksum/framing research and fixture
generation. May proceed without hardware mutation.

### Tier 1 — inert controls

Normal UI controls and one-variable codeplug changes that cannot transmit,
signal, reconfigure a remote unit, or enter emergency. Requires backup/readback
and the isolated mirrored lab.

### Tier 2 — contained RF/PTT/signaling

PTT, VOX, DTMF, analog/NXDN audio and signaling into the rated dummy load and
service-monitor attenuation path. Requires an explicit TX gate, physical kill,
bounded duration, complete capture and post-test verification.

### Tier 3 — emergency/destructive/firmware-sensitive

Emergency, remote monitor/automatic transmit, stun/kill/revive, firmware,
cloning and any state that may persist or affect another subscriber. These are
in the feature inventory but require a dedicated reversible test design,
non-operational identifiers, isolated sacrificial/test targets where applicable,
backup/recovery procedure, and explicit per-experiment authorization. Passive
observation, inert assignment and software-only reproduction come first. No
broad fuzzing is permitted against hardware at any tier.

## Workstreams

### 1. Transport and framing

- Exhaustively validate all observed frame formats, length rules, stuffing,
  CRC coverage, TCP segmentation/coalescing and special `f5` messages.
- Determine connection initiator/ports for every boot mode, UDP boot purpose,
  discovery traffic, address/port configuration, routed behavior and MAC/IP
  identity requirements.
- Map watchdogs, retry/backoff, simultaneous connections, duplicate peers,
  link flaps and power-state restoration.

### 2. Radio-to-mic behavior

- Resolve every startup message and all `01/04`, `02/01`, `02/02`, `02/06`,
  `02/0d`, `05/*`, `06/*` values; complete the verified `02/0b` immediate
  off/dim/on mapping by testing the opposite Dim Auto external-input branch.
- Map full display buffer layout, icons, LEDs, backlight, beep/ringer and every
  state/status transition.
- Map receive audio control, loss/mute/squelch/monitor behavior and all analog
  and NXDN mode variations.

### 3. Mic-to-radio behavior

- Map every physical input independently from its assigned CPS function.
- Map press, release, hold, repeat, chord, timeout and hook behavior.
- Map all control/event semantics, PTT/VOX/transmit audio, keypad/DTMF, call,
  signaling, scan, emergency and configuration-dependent actions.

### 4. Audio and DSP

- Fully specify RTP headers, sequence/timestamp/SSRC lifecycle, packet cadence,
  sample format and stream-open/close state.
- Measure both directions with calibrated silence, multi-tone, speech, impulse,
  clipping and packet-loss stimuli at every gain/volume/mute boundary.
- Determine mic-gain transaction semantics, Gain-5 processing, speaker noise,
  AGC/limiter/gate behavior and mode dependence.

### 5. Endpoint implementations

- Provide typed lossless models and encoders for every verified message.
- Implement a complete software radio endpoint for the real CommandMic.
- Implement a complete software CommandMic endpoint for the real radio.
- Expose every function through the shared device-model, audio and asynchronous
  application APIs; keep the CLI, GUIs and AllStar adapter as library clients.
- Maintain the Virtual CommandMic and CommandMic Lab Console as reference clients
  and conformance instruments rather than independent protocol implementations.
- Separate capability gates for UI, receive audio, TX, signaling, emergency and
  persistent actions.
- Default to fail-closed after malformed input, missing state, disconnect,
  restart or incomplete configuration.

### 6. Conformance and interoperability

- Build sanitized fixtures for every feature/state/boundary and arbitrary TCP
  fragmentation/coalescing.
- Cross-check Python and Wireshark field values automatically.
- Run software-radio ↔ software-mic exhaustive state-machine tests.
- Run real mic ↔ software radio and software mic ↔ real radio conformance
  matrices, including restart and five-minute stability gates.
- Compare generated exchanges field-for-field and timing-within-tolerance to
  real traces; document every intentional difference.

## Delivery phases

Status snapshot (2026-08-13): Phase 0 is substantially complete. Phases 1A–1C
have working public APIs, a packaged reference application and real-hardware
evidence, but not every Phase 1D acceptance result. Phases 2A–2B now have a
public `SoftwareRadioEndpoint` and packaged Lab GUI, but still require
the real-mic restart/soak matrix, continuous arbitrary application-audio input
and the node bridge. Phase 3 API consolidation began with package `0.2.0`.
Phases 4–5 remain open. Implemented is never treated as fully mapped or accepted.

### Phase 0 — Shared protocol foundation and safe lab (substantially complete)

Deliver the lossless parser/encoder, ordinary framing/stuffing/CRC, TCP stream
reassembly, RTP PCM format, capture manifests and sanitized fixtures, role-aware
startup, heartbeats, reconnect scaffolding, Wireshark fields and safety gates.
Keep both software roles usable as test peers so hardware traffic is never the
first place a new encoder is exercised.

Exit gate:

- all accepted fixture bytes are consumed or explicitly retained as unknown;
- arbitrary TCP fragmentation/coalescing and corrupted frames are handled;
- both software roles complete the known probe/stable session in isolation;
- TX is disabled by default and fails closed after malformed input or restart.

### Phase 1 — Primary product: software CommandMic for the real radio

#### Phase 1A — Session, radio state and complete screen receiver

- Reproduce the CommandMic boot identity, UDP/TCP setup, acknowledgements,
  heartbeats, watchdogs and orderly recovery while bound to the mic address.
- Decode the entire display transaction: all character regions, icons, LEDs,
  backlight and other visual state, while preserving unresolved/reserved bits.
- Implement the shared canonical screen/state model, public event API and the
  first reference virtual display. Add the same model to the Lab Console so it
  can inspect and replay known screen states against software peers.
- Verify cold radio boot, radio-first/mic-first ordering, soft-power state,
  Ethernet interruption and radio restart without the physical mic attached.

Current Phase 1A integration: the native cross-platform IP CommandMic
desktop app now switches among supplied exact LED faceplates and renders the
live lossless display with the exact paths extracted from the supplied display
SVG. It is a conventional resizable native-webview window with standard OS
controls and no HTTP server; the cog opens a separate settings window with live
connection controls and a bounded protocol console.
Protocol/network/direct-native-audio work is isolated from the renderer thread.
Remaining Phase 1A work is auxiliary display-byte closure, uncommon screen
corpus coverage and recovery acceptance.

#### Phase 1B — Every virtual CommandMic control

- Add API, CLI and reference-UI controls for P1–P4, four directions, F1–F3,
  keypad keys, Power, PTT, Emergency and any hook/accessory input found.
- Match press, release, hold, repeat, debounce and chord behavior from real traces.
- Treat key wire codes separately from CPS-assigned function meanings so all
  buttons become usable as soon as their physical event format is verified.
- Require explicit capability gates for Power, TX/PTT, Emergency and any
  persistent or destructive action.

Current Phase 1B integration: all 23 ordinary controls, inert-mapped Emergency,
PTT and the verified Power tap are exposed through the public endpoint and GUI.
Mouse and keyboard controls preserve press/hold/release and fail-safe release on
focus or pointer loss. Protocol repeat/chord behavior, long-Power semantics and
hook/accessory input remain open.

#### Phase 1C — Live bidirectional audio and PTT

- Treat `docs/LATENCY.md` as a normative requirement for library callbacks,
  buffering, audio-device adapters, TX pacing, metrics and acceptance.
- Stream radio RTP to a software speaker/audio-device interface with sequence,
  jitter, loss, mute, level and reconnect handling.
- Stream a live software microphone or WAV source to the radio using the proven
  8 kHz mono signed-big-endian PCM cadence and correct RTP lifecycle.
- Implement PTT timing, audio start/stop, underrun behavior and fail-closed TX.
- Validate transmit only through the rated dummy load with the explicit TX gate.
- Measure and report median/p95/maximum software and end-to-end audio latency;
  delayed replay of stale queued audio is a release-blocking failure.

Current Phase 1C evidence: E-090 through E-092 verify bounded recording and
usable live radio-to-PC playback. E-093 verifies explicitly gated software PTT
plus bounded tone/WAV mic-to-radio RTP against the real dummy-loaded radio with
physical-mic-equivalent timing. E-094 verifies the selectable prewarmed live PC
microphone source through the same real-radio path with no underruns and a
successful operator report. The GUI adds a prewarmed, hold-to-talk interactive
PTT stream while preserving the
same 20 ms latest-frame pacing and fail-closed release paths. Scoped v1
underrun/recovery and reconnect/failure acceptance are complete. Synchronized
RF/end-to-end latency remains optional product characterization.

#### Phase 1D — Primary-product acceptance and release

The Phase 1 gate requires, with the physical CommandMic absent:

- ten clean cold-start/reconnect cycles and a bounded five-minute operating soak;
- field-for-field screen and indicator parity for the exercised state corpus;
- every physical control available in software with verified event timing;
- intelligible, stable live receive and transmit audio, including silence and
  loss/recovery tests;
- median, p95 and maximum software callback/pacing measurements meeting the
  budgets in `docs/LATENCY.md`;
- no unintended PTT, Emergency, power or persistent action after malformed
  input, disconnect, process restart or missing configuration;
- a documented stable Python API, CLI and packaged reference virtual-CommandMic
  application that all use the same library session/device models.

### Phase 2 — Secondary product: physical CommandMic as a software peripheral

Current implementation: public `SoftwareRadioEndpoint` and the IP CommandMic
Lab GUI provides lossless display composition, LEDs/backlight,
button/PTT/Power events, library-decoded common audio-file and tone output,
0–32 volume, bounded Parrot replay, live microphone spectrum/metering,
streaming WAV recording and validated expert raw frames. They reuse the shared
startup, heartbeat, ACK, RTP, display metadata, media and parser implementation.
This is a packaged public-alpha research tool, not completion of the Phase 2
hardware acceptance gates.

#### Phase 2A — Complete software-radio session and output composer

- Cold-boot the physical CommandMic with no radio attached and maintain the
  session across PoE/link and software restarts.
- Encode arbitrary text, all display regions/icons, LEDs, backlight, beep/ringer,
  volume/status and other output state through a canonical screen/output API.
- Match required acknowledgements, status snapshots, watchdogs and timing.

#### Phase 2B — Complete physical-input and live-audio API

- Publish every button, PTT, Power, Emergency, hold/repeat/chord and hook event
  to applications without baking in a radio-specific CPS meaning.
- Stream microphone audio from the physical CommandMic to software continuously.
- Stream application audio to its speaker with low-latency buffering, explicit
  gain/mute control, RTP loss handling and clean start/stop transitions.
- Expose generic PTT, COR/squelch and status primitives suitable for radio-node
  software while retaining raw messages for future features.

#### Phase 2C — Reference radioless-node bridge and acceptance

- Provide a documented reference adapter for an AllStarLink-style audio/PTT/COR
  interface, kept modular so other applications can use the same endpoint API.
- Validate arbitrary screen changes, every control, bidirectional live audio,
  PTT/application state, ten restarts and a bounded five-minute soak with the real
  radio disconnected.
- Confirm the physical mic remains usable and recovers cleanly after the bridge
  or network disappears, without stale PTT or uncontrolled audio transmission.
- Release the complete CommandMic Lab Console with safe operator and gated expert
  views as the reference debugger and manual conformance client.

### Phase 3 — Shared SDK, packaging and conformance hardening

- Stabilize typed message/state/audio APIs and package both endpoint roles.
- Keep Python, Wireshark and generated encoders in field-level agreement.
- Add corpus tests for fragmentation, coalescing, loss, duplicates, ordering,
  invalid lengths/checksums, endpoint restarts and every verified screen/input.
- Run software-radio ↔ software-mic conformance plus both real-hardware matrices.
- Publish endpoint integration guides and compatibility/limitations records.
- Produce standalone end-user packages and a documented local service interface
  for applications that do not embed Python.

### Phase 4 — Advanced feature-semantic mapping

After both products pass their gates, map radio meanings and state machines for
scan/priority, set mode, call lists, analog/NXDN signaling, DTMF, VOX, hook/horn,
GPS/Bluetooth, accessories and configuration/mode variations. Expand the CPS
one-variable matrix and calibrated RF/audio tests only where these semantics add
application-level control beyond the already working raw buttons, screen and
audio paths.

### Phase 5 — Safety-critical and exhaustive closure

Use separately authorized Tier-3 experiments for Emergency, remote monitor,
stun/kill/revive and any firmware/configuration traffic found on the link. Close
every remaining feature-matrix row as verified, unavailable-prerequisite or
not-on-link; resolve or explicitly classify every unknown field; and perform the
final reproducibility and limitations audit.

## Immediate next actions

1. Repeat the complete Lab matrix against the physical CommandMic, including
   controls, display, volume, recording, Parrot, live gain changes, playback,
   ten PoE cycles and a bounded five-minute idle/active soak.
2. Retain synchronized acoustic/RF latency as post-v1 product characterization;
   the software callback/pacing and device/network failure gates are complete.
3. Finish auxiliary display-byte and uncommon screen-corpus mapping, feeding
   every result into the existing lossless GUI display model.
4. Map repeat/chord behavior, long-Power semantics and hook/accessory input. Keep Emergency
   behind its separately authorized safety phase.
5. Complete both products' cold-start, control, screen, audio, reconnect and soak
   gate before broadening advanced CPS feature semantics.
6. Add a generic continuous application-audio source and reference
   AllStarLink-style adapter on top of `SoftwareRadioEndpoint`.

## Progress reporting

Do not report a single global percentage without also reporting:

- matrix rows by state and safety tier;
- known versus unresolved message types/values;
- real-radio and real-mic conformance results separately;
- functions blocked by missing prerequisites;
- parser/dissector/encoder coverage and fixture-byte consumption;
- implementation versus documentation completion.
