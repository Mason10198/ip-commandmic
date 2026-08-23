# Endpoint conformance

`ip-commandmic` includes a hardware-free baseline that runs the two public
endpoint wrappers against each other on the local loopback network. It never
addresses a physical radio or CommandMic and disables local capture/playback
devices.

Run it directly:

```powershell
python -m ip_commandmic.conformance --artifact-directory artifacts/conformance
```

The topology binds `127.0.0.1`, `127.0.0.2`, and `127.0.0.3` so both endpoint
roles can use the observed fixed ports. Linux and Windows provide these
loopback addresses directly. On macOS, configure the additional aliases first:

```sh
sudo ifconfig lo0 alias 127.0.0.2 255.0.0.0
sudo ifconfig lo0 alias 127.0.0.3 255.0.0.0
```

The hardware-free endpoint uses an ephemeral outbound TCP source port so fresh
object cycles do not depend on host-specific `TIME_WAIT` reuse. The normal
library default remains the observed fixed radio-side source port.

CI runs the portable test suite across Linux, macOS, Windows, and Python
3.11–3.14. The complete timing-sensitive 19-check loopback scenario runs on
the Windows reference host; shared Unix runners can introduce scheduler gaps
that invalidate its strict real-time RTP and fresh-object timing assertions.

Longer hardware-free runs use the same checks and bounded parameters:

```powershell
python -m ip_commandmic.conformance --artifact-directory artifacts/stress `
  --sustained-audio-seconds 10 --cold-restart-cycles 10 --timeout 20
```

`--sustained-audio-seconds` accepts 1–1800 seconds per media direction and
`--cold-restart-cycles` accepts 1–100 fresh endpoint-object cycles. The normal
baseline uses one second, three cycles, and a 20-second per-wait budget so the
probe and stable phases remain portable while CI stays bounded.

The scheduled extended workflow runs on the Windows reference host with 150
seconds in each media direction (five minutes total) and ten fresh-object
restart cycles. This is the maintained recurring health check. The historical
30-minute-per-direction result below remains release evidence, not a recurring
CI duration requirement.

The CLI writes `report.json` beside the two JSONL audits and also prints the
same JSON to standard output. On 2026-08-21 the release-candidate configuration
passed all 19 checks in 3,676.282 seconds with 1,800 seconds per media direction
and ten cold restart cycles. Its sustained check carried 90,000 continuous
radio RTP packets and 90,012 continuous microphone RTP packets, with zero
radio playout concealments. Receive callback median/p95/maximum was
0.320/0.658/30.836 ms and radio/microphone sender maximum lateness was
10.911/22.927 ms. These are hardware-free local software-path measurements.

The artifacts cover:

- observed probe-to-stable startup and controls-ready state;
- three exact synthetic 68-byte display buffers, including non-text bytes;
- all four status-LED states and all three backlight states;
- all 23 ordinary key press/release identities, separately typed Power, and no
  Emergency emission;
- all five verified microphone-gain transactions through the public wrapper;
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
  exact ordered RTP wire receipt and callback delivery, no catch-up burst,
  bounded sender lateness and receive callback median/p95/maximum latency
  metrics; arrival timing uses an ordered timeline so the 90,000-packet
  extended run remains lossless across 16-bit RTP sequence wraparound. The
  clocked two-packet playout model separately permits at most one isolated
  silent operating-system scheduling concealment, or 100 parts per million in
  longer runs; consecutive concealments, wire loss, duplicate delivery,
  reordering and discontinuity remain failures;
- mid-PTT CommandMic cancellation and mid-speaker-stream radio cancellation,
  including bounded endpoint shutdown, immediate fail-closed PTT/control/audio
  gates, no post-stop RTP, finalized capture/playout state, same-object restart
  and clean fresh media sessions in both directions;
- fail-closed controls, PTT and receive-audio state after peer loss;
- immediate software-radio endpoint restart and stable reconnection, including
  an audited ephemeral-source-port fallback if the host temporarily retains an
  observed fixed TCP tuple; and
- fresh construction of both endpoint roles with alternating mic-first and
  radio-first startup, followed by stable display, key and audio transactions
  on every cycle;
- routed-link interruption that tears down and rejects TCP sessions while
  blackholing UDP, followed by fail-closed state and clean restoration; and
- abrupt CommandMic child-process termination and replacement while the
  radio-side process remains alive, followed by stable display and key traffic.

The report uses `passed`, `failed`, and `not_covered` per check. A report may
pass while containing `not_covered`; consumers must inspect individual checks.
The current baseline has no `not_covered` check: both media directions run
without local audio hardware through the public wrappers.

The hardware-free v1 gate is complete, but this baseline is not the exhaustive
product gate. Remaining conformance work:

1. retain the accepted physical-CommandMic/Lab and real-radio/Desktop matrices;
2. retain the accepted ten physical restart/power cycles and bounded
   five-minute physical idle/active soak for each endpoint role;
3. treat synchronized acoustic/RF latency and calibrated volume measurements
   as post-v1 product characterization;
4. expand the synthetic display corpus and map hold/repeat/chord cases as
   post-v1 research unless the supported v1 contract is broadened; and
5. keep Emergency and other safety-critical traffic behind their separately
   authorized test phase.

Raw captures, codeplugs and hardware-derived private artifacts are not inputs to
this suite. Protocol behavior learned by later conformance runs must be added to
the shared library and normative protocol documents before application-specific
workarounds are accepted.
