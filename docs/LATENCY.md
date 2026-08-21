# Audio latency requirements

Low latency is a primary API and implementation requirement for both endpoint
roles. Correct audio that is delayed by an entire gate or allowed to accumulate
as stale queued speech is a failure.

## Protocol constraints

- Audio is mono 8 kHz signed-16-bit PCM in 160-sample/20 ms RTP payloads.
- Implementations must not batch multiple RTP payloads before delivering a
  callback or sending a transmit packet.
- Receive callbacks are invoked immediately after peer, gate, RTP and SSRC
  validation. The core callback layer adds no jitter queue.
- Transmit sources will emit each packet as soon as its 160 samples are ready,
  paced against an absolute monotonic timeline rather than chained sleeps.

## Receive profiles

- `direct`: callback delivery with no library buffering; applications own their
  audio-device policy.
- `minimum`: one-packet playout buffer for controlled wired LANs; no intentional
  extra packet interval after the first packet arrives.
- `default`: two-packet buffer, adding approximately one 20 ms packet interval
  while retaining one packet of reorder tolerance.
- `resilient`: explicitly configured larger buffer for routed or impaired
  networks. It must never become the default silently.

The output-backend queue is bounded. When a renderer cannot keep up, stale audio
is dropped and sequence state resynchronizes at current RTP; old speech must not
be replayed seconds later. Queue drops, concealment, discontinuities, buffered
depth and backend failures are observable metrics.

## Render and capture devices

Audio devices should be opened and warmed before a radio gate or PTT event.
Initialization silence belongs only to the local device backend and must not
enter protocol callbacks, RTP, or evidence WAVs. Device adapters must expose
their chosen endpoint and buffering where the platform permits it.

## Transmit requirements

- TX remains disabled until explicitly armed and the radio is RF-contained.
- PTT lead and tail are limited to values established by packet/RF evidence;
  arbitrary safety padding must not accumulate into conversational delay.
- Microphone capture queues are bounded to a small number of 20 ms frames.
- On overrun, disconnect, missing source, or timing failure, drop stale samples,
  send no new audio, release PTT, and require a fresh explicit TX action.
- Echo cancellation, resampling and application bridges must run outside the
  protocol event loop and publish their added buffering.

## Instrumentation and acceptance

Every reference implementation must timestamp packet receipt/capture, validated
callback, queue entry/exit and device write using a monotonic clock. Report at
least median, p95 and maximum software latency plus queue depth/drop counts.

Targets for the controlled wired lab, excluding RF propagation and unavoidable
audio-device hardware latency:

- receive callback: within the same event-loop turn as packet validation;
- default receive software buffering: no more than one packet interval/20 ms;
- minimum receive profile: no intentional buffer interval;
- transmit packetization: one 20 ms frame, with no multi-frame batching;
- no stale-audio replay; and
- measured end-to-end mouth-to-speaker and microphone-to-RF latency documented
  before Phase 1 release.

E-092 verifies usable live receive voice without backend drops or the former
whole-gate delay. It does not yet provide synchronized end-to-end latency, which
remains an explicit acceptance item.

E-093 verifies the transmit network scheduler against the real radio. Its 160
packets averaged 19.9995 ms with a 19.9406–20.0536 ms wire range, no catch-up
burst, no sequence/timestamp error, 30.043 ms PTT-to-first-RTP latency, and
0.014 ms maximum sender-deadline lateness. Live capture-device and RF audio
latency remain acceptance items.

E-094 verifies the prewarmed live capture path through real-radio acceptance.
The source uses a 20 ms DirectShow device buffer and one-packet latest-frame
queue. It delivered all 510 requested frames with zero underruns; stale prewarm
frames were overwritten rather than replayed. Wire cadence averaged 19.99998 ms
over 10.2 seconds, sender deadline lateness peaked at 0.024 ms, and the operator
reported perfect operation. These metrics bound software capture/transport
behavior but are not a synchronized mouth-to-RF latency measurement.

The alpha.18 hardware-free public-wrapper gate adds a repeatable software
baseline. Across five fresh one-second bidirectional runs, every run delivered
50/50 radio RTP packets and 62 continuous microphone RTP packets. The
UDP-relay-receipt to validated receive-callback median was 0.309–0.371 ms, p95
was 0.579–0.961 ms and maximum was 0.628–2.470 ms. Maximum sender-deadline
lateness was 0.596–1.097 ms for radio RTP and 0.320–5.948 ms for microphone RTP;
no run compressed packets into a catch-up burst. These are local software-path
metrics, not synchronized acoustic, device, RF or routed-network latency.
