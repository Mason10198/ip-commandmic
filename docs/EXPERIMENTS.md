# Experiment runbook

This runbook is now governed by
[`MASTER_PLAN.md`](MASTER_PLAN.md) and the coverage ledger in
[`FEATURE_MATRIX.md`](FEATURE_MATRIX.md). The earlier campaign below remains a
useful operational sequence, but its limited scope and exclusions no longer
define project completion.

Current priority is the public-endpoint conformance gate: software endpoint
against a software endpoint first, then Desktop against the real radio and
the Lab app against the physical mic. New findings must reach
`PROTOCOL.md`, `MESSAGE_CATALOG.md`, typed library models/composers, fixtures and
the dissector before a GUI-specific behavior is accepted.

All control trials use a private baseline-configuration record retained outside
this public repository. Capture notes must name a different private record if
that codeplug changes.

## Safety gate

- Use an isolated VLAN and mirror both endpoint ports in both directions.
- Confirm the radio RF port is terminated into a correctly rated dummy load.
- Use a test codeplug with emergency and operational signaling made inert.
- The saved baseline is specifically unsafe for Emergency-key testing: its
  reminder is zero, repeat is Infinite, and Repeat Cancel is OFF. Use a derived
  codeplug with the CommandMic `Emer` key assigned `Null`, a finite repeat
  count, and a nonzero reminder; read it back and verify before capture.
- Back up the original codeplug before any controlled change.
- Firmware, cloning, stun/kill, remote-monitor and emergency work is prohibited
  in ordinary trials. These functions remain in the exhaustive feature matrix
  and may be investigated only under the separately authorized Tier-3 process
  in `MASTER_PLAN.md`, beginning with passive/inert/software-only evidence.
- Keep an accessible physical radio power/TX inhibit control.

## Naming and event logging

Use `<date>_<category>_<action>_<repetition>` labels. Start each capture at least
five seconds before the action and stop at least five seconds after it. Repeat an
action three times in separate captures.

Copy `experiments/event_log.template.csv` beside each experiment and record event
time from the same PC clock used by Wireshark. Record “no action” explicitly for
idle controls.

For experiments requiring a physical action, use this handshake adapted to the
Codex UI (user messages may be queued while a capture command is running):

1. Operator explicitly replies `ready` before capture begins.
2. Capture starts and the recorder explicitly reports `recording`.
3. Operator performs only the named action; no reply is required while the
   capture command is running.
4. After capture and analysis finish, the recorder asks what was performed and
   the operator confirms or rejects the trial.
5. A trial without post-capture operator confirmation remains provisional even
   if its packets appear to contain the expected event.

## Ordered campaign

1. Capture 10-minute idle and 30-minute idle sessions. (10-minute complete.)
2. Capture cold boot, then radio-first, mic-first, and simultaneous boot.
   (Simultaneous cold boot complete; ordered boots remain.)
3. Capture 1-, 5-, and 30-second radio/mic link interruptions.
4. Capture one normal key press/release at a time, then holds and encoder detents.
5. Capture one codeplug value change at a time, including one-character labels.
6. With the RF dummy load verified, capture PTT timing without microphone audio.
7. Inject 300 Hz, 1 kHz, and 2.5 kHz analog FM from the 8935 at recorded level
   and deviation settings; capture silence before and after each tone.
8. Capture microphone silence, known tones, speech, and clipping during TX into
   the dummy load.
9. Repeat representative traffic in analog and NXDN modes, labeling unsupported
   NXDN receive stimulus as such.

Before each active phase, decode all prior captures, add sanitized regression
fixtures, and update the protocol evidence ledger.
