# CommandMic exhaustive feature matrix

This is the authoritative coverage ledger for the exhaustive master plan,
reviewed against package version `1.0.0` and the independently packaged UIs.
It remains a
structured family-level ledger; later inventory passes expand each family
into one row per CPS function, setting, message value, operating mode and
boundary. Evidence IDs refer to `PROTOCOL.md`.

Status values: `verified-bidirectional`, `verified-partial`, `observed`,
`unmapped`, `unavailable-prerequisite`, `not-on-link`.

Delivery tags:

- `P0` — shared transport/framing foundation;
- `P1` — blocks the software-CommandMic replacement for a real radio;
- `P2` — blocks using a physical CommandMic with a software radio/application;
- `P3` — shared SDK/conformance hardening;
- `P4` — later advanced radio-feature semantics;
- `P5` — safety-critical or final exhaustive closure.

Rows tagged `P1/P2` are implemented in both directions, but each product has an
independent acceptance gate. A `P4` or `P5` semantic investigation does not block
transparent raw button, display or audio interoperability in Phases 1 and 2.

| Stable ID | Delivery | Feature family | Current status | Real trace | Software radio | Software mic | Safety tier | Principal gap |
|---|---|---|---|---|---|---|---:|---|
| NET-TRANSPORT | P0/P1/P2 | TCP/UDP addressing, ports and routing | verified-partial | Yes | Public wrapper passes bidirectional TCP fragmentation/coalescing through explicit relay routing | Public wrapper passes bidirectional TCP fragmentation/coalescing through explicit relay routing | 0 | configured ports/routed/address-error matrix |
| FRAME-ORDINARY | P0 | ordinary framing, stuffing, length and CRC | verified-bidirectional | Yes | Yes | Yes | 0 | broaden corpus to every message length/value |
| FRAME-SPECIAL | P0/P3 | `f5` special messages | verified-partial | Yes | Replay only | Handles and acknowledges both verified Power transition variants | 0 | map remaining special-message families and fields |
| SESSION-BOOT | P0/P1/P2 | probe/stable startup and identity | verified-partial | Yes | Yes; public fixture uses a synthetic locally administered MAC | Yes | 0 | physical-radio acceptance of the public synthetic identity, ordered endpoint boots and unknown startup fields |
| SESSION-RECOVERY | P1/P2/P3 | watchdog, reconnect, process replacement and PoE restart | verified-partial | Yes | Same-object and fresh-object restarts, abrupt peer-process replacement and routed TCP/UDP interruption pass fail-closed | Same-object and fresh-object restarts, abrupt peer-process replacement and routed TCP/UDP interruption pass fail-closed | 0 | directly retest immediate heartbeat/repeated-`f5/05/03` attach; then physical PoE restart and link-duration/address matrix |
| POWER-STATE | P1/P2 | Power key and retained DC state | verified-bidirectional | Yes | Decodes press/release in public endpoint/Lab GUI | Physically verified soft-off, heartbeat-only standby and wake with exact `f5` acknowledgements | 1 | broader codeplug/retained-DC variants are deferred |
| INPUT-PHYSICAL | P1/P2 | all known physical key wire codes | verified-partial | Yes | Public endpoint exposes all mapped key states plus PTT/Power | All 23 ordinary keys real-radio validated; Emergency explicitly gated | 1–3 | repeat/chord/hook behavior |
| DISPLAY-PRIMARY | P1/P2 | primary 68-byte display transaction | verified-partial | Yes | Public lossless composer plus exact Lab GUI | Lossless receiver/model, ACK and exact Desktop GUI | 1 | auxiliary offsets8–27/36–55, extended characters, remaining screen catalogue |
| VOLUME | P1/P2 | volume 0–32 and both clamps | verified-partial | Yes | Public 0–32 app state, mute, clamping, physical-key overlay, and best-effort 48 dB perceptual curve | Emits both keys; real-radio validated at levels 31/32 | 1 | measure the real radio/CommandMic acoustic transfer law and replace approximation |
| CHANNEL-ZONE | P1/P2 | channel and zone selection/display | verified-partial | Yes | Partial | Emits four direction keys; real-radio wire acceptance validated | 1 | raw event/output parity; advanced semantics move to P4 |
| MONITOR-RX | P1/P2 | Monitor/F1 receive open/close | verified-partial | Yes | Partial | Emits F1; real-radio short-tap/audio-gate path validated | 1 | hold threshold, squelch/status/LED fields and product audio handling |
| AUDIO-RX | P1/P2 | radio-to-mic RTP PCM / software-to-speaker | verified-partial | Yes | Public tone/WAV output with no-catch-up 20 ms pacing and audit metrics; 90,000-packet/30-minute hardware-free soak, mid-stream cancellation, no post-stop RTP and fresh restarts pass | Public native playback or injected `RadioAudioSink`; wrapper conformance proves loss concealment, duplicate rejection, bounded reorder, clean next-gate recovery, 90,000-packet/30-minute hardware-free soak and fail-closed cancellation | 1–2 | post-v1 synchronized acoustic latency and calibrated mute/level |
| AUDIO-TX | P1/P2 | mic-to-radio RTP PCM / mic-to-software | verified-partial | Yes | Public live RTP callback, meters, streaming WAV and durable capture-summary state; 90,012-packet/30-minute hardware-free soak detects zero continuity faults and survives event-ring rollover | Public live PC microphone, injectable application source and bounded tone/WAV; no-catch-up 20 ms pacing, audit metrics, 90,012-packet/30-minute hardware-free soak and no post-stop RTP | 2 | post-v1 synchronized acoustic/RF latency characterization |
| PTT | P1/P2 | PTT state and active/close response | verified-partial | Yes | Bounded acknowledgement | Explicit real-radio PTT plus double-gated hold-to-talk GUI path; public-wrapper application-audio PTT/release conformance | 2 | live GUI acceptance plus sustained disconnect/restart testing |
| MIC-GAIN | P1/P2/P4 | gain 1–5 and two-stage `02/0e` control | verified-partial | Yes | Emits | Receives | 1–2 | product-level handling; exact DSP semantics later |
| KEYPAD-DTMF | P1/P2/P4 | keypad selection and DTMF | verified-partial | Yes | No response | All 12 keypad keys real-radio validated | 1–2 | raw response parity; on-air DTMF semantics later |
| SCAN-PRIORITY | P4 | scan and priority functions | unmapped | No | No | No | 1 | complete CPS/function matrix |
| CALL-SIGNAL | P4 | call lists and analog/NXDN signaling | unmapped | No | No | No | 2 | prerequisites and controlled targets |
| UI-SETMODE | P4 | user set mode and selectable settings | unmapped | No | No | No | 1 | every setting/display/writeback behavior |
| UI-INDICATORS | P1/P2 | LEDs, backlight, icons, beep/ringer | verified-partial | Partial | LCD static/blink fields, top LED colors, backlight states `00` off/`01` dim/`02` on, OFF Auto timer, Dim Auto current-input branch, and importable/emittable Beep-ON normal/low composers with fixed levels 1–5 | Lossless named LCD fields plus decoded/emitted status-LED and backlight fields | 1 | Verify Dim Auto opposite external-input branch; map Linked beep levels, ringer/other beep families and remaining auxiliary/tail combinations |
| VOX-HOOK-HORN | P2/P4 | VOX, hanger/hook and horn behavior | unmapped | No | No | No | 1–2 | raw hook/event transport first; feature semantics later |
| GPS-BT | P4 | GPS display and Bluetooth assignments | unmapped | No | No | No | 1 | option/hardware availability and link relevance |
| EMERGENCY | P1/P2/P5 | emergency physical event and feature behavior | verified-partial | Inert key only | No | No | 3 | gated raw control first; authorized semantic testing later |
| REMOTE-DESTRUCTIVE | P5 | remote monitor, stun/kill/revive | unmapped | No | No | No | 3 | sacrificial target/recovery design and authorization |
| CONFIG-FW | P5 | configuration/firmware traffic on this link | unmapped | No | No | No | 3 | first determine whether carried by CommandMic link |
| ERROR-MALFORMED | P3/P5 | invalid/out-of-order/corrupt behavior | verified-partial | No | Public-wrapper TCP fragmentation/coalescing, routed interruption and bidirectional RTP impairment/recovery; lower-level corrupt-frame coverage | Same public-wrapper coverage | 0–3 | broader corrupt/out-of-order transaction matrix and hardware-safe subset later |

No row may be removed because it is difficult or unsafe. It must instead be
completed through the appropriate tier or end in an explicit unavailable/not-on-
link record with evidence.
