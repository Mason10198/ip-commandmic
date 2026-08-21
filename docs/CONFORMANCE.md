# Endpoint conformance

`ip-commandmic` includes a hardware-free baseline that runs the two public
endpoint wrappers against each other on the local loopback network. It never
addresses a physical radio or CommandMic and disables local capture/playback
devices.

Run it directly:

```powershell
python -m ip_commandmic.conformance --artifact-directory artifacts/conformance
```

Longer hardware-free runs use the same checks and bounded parameters:

```powershell
python -m ip_commandmic.conformance --artifact-directory artifacts/stress `
  --sustained-audio-seconds 10 --cold-restart-cycles 10 --timeout 20
```

`--sustained-audio-seconds` accepts 1–1800 seconds per media direction and
`--cold-restart-cycles` accepts 1–100 fresh endpoint-object cycles. The normal
baseline uses one second and three cycles so CI remains fast.

The JSON report and the two JSONL audits cover:

- observed probe-to-stable startup and controls-ready state;
- an exact, icon-free 68-byte display transaction;
- red and off status-LED states;
- ordinary P1 press and release;
- deterministic TCP fragmentation and multi-frame coalescing in both directions,
  verified through exact display and key-state operations;
- radio-to-CommandMic receive-open, two paced RTP packets, and close;
- deterministic radio-to-CommandMic RTP loss, duplication and bounded reorder,
  including exact-silence concealment, ordered playout and a clean next gate;
- CommandMic-to-radio PTT acknowledgement, nonzero application-fed PCM, paced
  microphone RTP, newest-frame overwrite under producer overload, fail-silent
  underrun, zero RTP sequence/timestamp errors and clean PTT release;
- a deterministic microphone-RTP drop, duplicate and reordered pair, positive
  continuity-error detection, safe release, and a following clean capture with
  zero sequence/timestamp errors;
- configurable sustained load in both directions (one second/50 radio packets
  in the baseline; ten seconds/500 radio packets in the accepted stress run),
  continuous RTP, no catch-up burst, bounded sender lateness and receive
  callback median/p95/maximum latency metrics;
- mid-PTT CommandMic cancellation and mid-speaker-stream radio cancellation,
  including bounded endpoint shutdown, immediate fail-closed PTT/control/audio
  gates, no post-stop RTP, finalized capture/playout state, same-object restart
  and clean fresh media sessions in both directions;
- fail-closed controls, PTT and receive-audio state after peer loss;
- immediate software-radio endpoint restart and stable reconnection, including
  an audited ephemeral-source-port fallback if Windows temporarily retains an
  observed fixed TCP tuple; and
- fresh construction of both endpoint roles with alternating mic-first and
  radio-first startup, followed by stable display, key and audio transactions
  on every cycle.

The report uses `passed`, `failed`, and `not_covered` per check. A report may
pass while containing `not_covered`; consumers must inspect individual checks.
The current baseline has no `not_covered` check: both media directions run
without local audio hardware through the public wrappers.

This baseline is not the exhaustive product gate. Remaining conformance work:

1. complete the full 30-minute soak; configurable per-direction stress now
   passes at 10 seconds/500 radio packets/512 microphone packets, while
   synchronized hardware end-to-end latency remains a separate physical gate;
2. test every ordinary key, hold/repeat/chord behavior, Power semantics and the
   complete sanitized display corpus through the public wrappers;
3. run true subprocess/network-interruption matrices and the 30-minute
   idle/active soak; ten fresh-object cycles with alternating startup order now
   pass;
4. run the separate physical-CommandMic/Lab and real-radio/Desktop matrices,
   including synchronized latency and calibrated volume/acoustic measurements;
5. keep Emergency and other safety-critical traffic behind their separately
   authorized test phase.

Raw captures, codeplugs and hardware-derived private artifacts are not inputs to
this suite. Protocol behavior learned by later conformance runs must be added to
the shared library and normative protocol documents before application-specific
workarounds are accepted.
