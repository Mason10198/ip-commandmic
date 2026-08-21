# Verified radio-emulator profile

The CLI profiles here and both desktop applications use the same library
sessions. New integrations should prefer public `SoftwareCommandMicEndpoint`
and `SoftwareRadioEndpoint` APIs from [`CONTROLS_API.md`](CONTROLS_API.md).
Applications should not assemble startup, heartbeat, display-ACK or RTP traffic;
the lower-level emulator/UDP classes remain for research and conformance. See
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Verified software CommandMic profile

`emulate-mic --verified-startup --listen` implements the captured CommandMic
side of the connection for testing against a software radio endpoint. It:

- accepts the radio-initiated probe and stable TCP/52001 sessions;
- sends the exact five-frame initial neutral-state burst;
- sends the captured 26-byte Icom/MAC identity after radio ready;
- sends the exact mic RTP/PT125 all-zero UDP/50000 boot packet and validates
  the exact radio boot reply;
- completes the special probe exchange;
- acknowledges verified display transactions; and
- responds to radio heartbeats with the captured mic heartbeat.

All other radio state is parsed and logged without a response by default. With
an explicit bounded `--key-script`, the profile can emit ordinary keys after
stable display readiness. Emergency, Power, programming, PTT, and microphone
audio remain disabled by default. The
captured identity currently contains the laboratory CommandMic MAC and is used
only as a verified simulator fixture; configurable identities require a future
one-variable test. Listener mode is mandatory because packet evidence shows
that the radio initiates both TCP sessions.

An end-to-end regression runs this profile against the software radio profile,
completes the probe disconnect and stable reconnect, receives `N5LSN` and
`QTH NODE`, acknowledges both displays, and sustains heartbeat exchange.
Cold sessions start queued controls after the second display. Real-radio warm
reconnect evidence showed that opening text may be omitted; in that case a
three-second single-display grace timer starts controls without guessing the
configured opening text. Both readiness paths are regression tested.
When a powered radio presents the special `f5/05/03:01` probe prompt, the
software mic sends the two capture-derived probe-response frames after a 5 ms
defer. This matches the physical mic transcript and lets the powered radio
advance without requiring a DC cycle.

### Native virtual CommandMic desktop application

`ip-commandmic-desktop` embeds the verified listening-mic endpoint in a conventional
cross-platform native window with the operating system's title bar and window
controls. It is not a website, starts no HTTP server, and does not ship a browser
engine such as Electron. Four supplied PNG faceplates
provide exact off/red/green/orange LED artwork. The LCD renderer uses the exact
paths extracted from the supplied `mic_display_vector.svg`, including all 112
character segments, decimal points and mapped icon paths; no substitute segment
font is used. Front-key hit geometry comes directly from the operator-traced SVG
overlay aligned to the production faceplate, so it scales with the raster rather
than relying on estimated rectangles.

Use the cog in the upper-left corner of the main window to open Settings. All persistent operator
configuration is kept there: CommandMic/radio addresses, control/audio ports,
automatic connection, native playback/capture devices, receive jitter and
device buffers, scale/topmost behavior, and human-readable keyboard shortcuts.
Closing the settings window hides it and returns to the
main microphone window. The optional Developer section opens a bounded live protocol
console and the audit directory.

The transparent faceplate PNG retains smooth anti-aliased edges and a soft drop
shadow against a neutral charcoal background. The main window is resizable and
appears normally in the taskbar; Settings and the Developer Console remain
separate desktop windows.

The ordinary key API remains available whenever the stable session reports
controls ready. Desktop receive and transmit audio use direct miniaudio
callbacks; there are no FFmpeg/FFplay processes in the desktop path. RX starts
with a configurable one-to-eight packet jitter prebuffer (two by default), and
TX keeps a bounded newest-frame queue. The desktop app initializes microphone
capture at launch and makes PTT available whenever controls are ready. PTT press waits for the
verified radio TX-active response and streams the newest prewarmed microphone
frame on the 20 ms RTP clock until pointer/keyboard release. The measured RTP
release tail is preserved. Window focus loss, network disconnect, runtime
failure and process cancellation all drive fail-closed release paths.

```powershell
.\scripts\run_commandmic_desktop.ps1

.\scripts\run_commandmic_desktop.ps1 `
  -MicrophoneDevice "Microphone (2- Razer Kiyo Pro)"
```

Power, Emergency, Monitor, Volume Up, and Volume Down are active in the desktop
faceplate. Their narrow hardware edges use enlarged invisible desktop padding
around the traced or preserved physical-key outline.
Packaged macOS/Linux hardware acceptance remains pending.

The Windows release builder intentionally produces a single windowed executable:

```powershell
uv sync --extra desktop --extra build
.\scripts\build_commandmic_desktop.ps1
```

Only that executable is published. The platform webview runtime remains an OS
prerequisite, while settings JSON and optional audit logs are runtime data.

`--record-radio-wav <path>` enables bounded software-mic receive recording.
RTP is accepted only after the exact radio UDP boot is verified, only from the
configured radio IP/port, only as PT125/332-byte packets with the verified radio
SSRC, and only while TCP `01/04:01000000` has opened the receive-audio gate.
Gate-close, out-of-state, wrong-peer, malformed, and wrong-SSRC packets are
discarded and audited. The output is mono 8 kHz signed-16-bit PCM WAV;
`--radio-recording-max-seconds` caps accumulated gated audio at 30 seconds.

E-090 validates this path against the real radio using its known Beep Level 5
key-touch tone: four packets, 640 samples/80 ms, 1 kHz, -19.29 dBFS, and zero
RTP sequence/timestamp errors.

E-091 extends that validation to 5.02 seconds of continuous 1 kHz-modulated RF
receive audio: 251 consecutive RTP packets with no sequence or timestamp errors.
E-092 validates interactive real-radio voice playback: 478/478 packets played,
zero backend drops/concealment/discontinuities, a simultaneous 9.56-second WAV,
and an operator report of successful live voice without the prior gate-length
delay. Synchronized end-to-end latency measurement remains open.

### Explicit software-mic PTT and transmit audio

`--enable-tx` is a separate, active safety gate available only to the verified
listening mic role. It runs one bounded transaction and must be combined with
RF containment. The sender emits `01/00:01`, waits up to one second for the
radio's verified `01/04:08000000` response, begins RTP at the measured 30 ms
lead, and releases with `01/00:00`. RTP continues through the measured release
tail. Disconnect, missing UDP verification, missing TX-active, source error,
or task cancellation stops new audio and sends a fail-closed release whenever
the TCP writer remains usable.

The default source is a generated 1 kHz, -30 dBFS tone held for three seconds.
`--tx-wav PATH` accepts uncompressed mono 8 kHz 16-bit PCM and uses the source
duration as the PTT hold. Only a single final partial packet is zero-padded.
Sequence and timestamp continue directly from the captured mic boot RTP packet;
SSRC remains `7069c2cc`. The high-resolution pacer uses absolute deadlines,
records maximum lateness and resynchronization count, and never emits a short
catch-up burst after a late frame.

E-093 validates the implementation against the real dummy-loaded F6330D: 160
packets, zero RTP sequence/timestamp errors, 19.9995 ms mean wire interval with
a 19.9406–20.0536 ms range, first RTP at 30.043 ms, final RTP at 209.962 ms
after release, and radio close at 222.543 ms. Capture drops were 0/275.

```powershell
ip-commandmic-research emulate-mic --local-ip 192.168.0.2 --peer-ip 192.168.0.1 `
  --verified-startup --listen --enable-tx --tx-tone-hz 1000 `
  --tx-level-dbfs -30 --tx-hold-seconds 3 --exit-after-tx-script `
  --confirm-active-testing --audit-log artifacts\software_mic_tx.jsonl
```

Add `--tx-live-device "EXACT DIRECTSHOW NAME"` for a prewarmed live Windows
capture source. `--tx-device-buffer-ms` defaults to 20 ms and
`--tx-capture-queue-packets` defaults to one. The capture worker continuously
converts the selected endpoint to mono 8 kHz signed-16-bit PCM before the radio
session is ready. At every RTP deadline the sender takes only the newest frame;
older frames are overwritten and an unavailable frame becomes digital silence
plus an observable underrun. The queue is capped at three packets and never
grows without bound.

E-094 validates that live adapter through the real dummy-loaded radio using
`Microphone (2- Razer Kiyo Pro)`: 510/510 frames delivered, zero underruns,
zero RTP continuity errors, 19.99998 ms mean cadence, 0.024 ms maximum sender
deadline lateness, non-silent unclipped speech, and an operator report that it
worked perfectly. Prewarm overwrites are expected and prove old samples were
discarded; they are not packet loss. Synchronized acoustic/RF latency remains
to be measured.

```powershell
ip-commandmic-research emulate-mic --local-ip 192.168.0.2 --peer-ip 192.168.0.1 `
  --verified-startup --listen --enable-tx `
  --tx-live-device "Microphone (2- Razer Kiyo Pro)" `
  --tx-device-buffer-ms 20 --tx-capture-queue-packets 1 `
  --tx-hold-seconds 10 --exit-after-tx-script `
  --confirm-active-testing --audit-log artifacts\software_mic_live_tx.jsonl
```

### Live receive callback API

Applications may consume verified radio audio without waiting for a WAV file by
constructing `VerifiedMicUdpProtocol` with `radio_audio_callback` and optionally
`radio_audio_gate_callback`. Both callbacks run only after the exact UDP boot,
peer, RTP shape/SSRC, and TCP receive-gate checks used by the recorder.

```python
from ip_commandmic import VerifiedMicUdpProtocol

def on_audio(packet):
    # 160 mono samples / 20 ms per accepted packet.
    audio_device.write(packet.pcm_s16le)

def on_gate(event):
    print(event.session, "open" if event.open else "closed", event.packet_count)

protocol = VerifiedMicUdpProtocol(
    "192.168.0.1",
    50000,
    audit=audit_log,
    radio_audio_callback=on_audio,
    radio_audio_gate_callback=on_gate,
)
```

`RadioAudioPacket` retains the exact signed-16-bit big-endian wire payload and
also exposes `pcm_s16le`, `session`, RTP `sequence`, `timestamp`, `ssrc`, sample
count, sample rate, and duration. `RadioAudioGateEvent` identifies every open
and close boundary; close events include the accepted packet count. Exceptions
raised by application callbacks are contained and written to the audit log.
The callbacks are synchronous and must return quickly; an application should
enqueue PCM into its own playback or processing worker instead of blocking the
protocol event loop.

### Live local playback

`--play-radio-audio` connects the callback API to the installed FFplay audio
backend. Playback is disabled by default, opens no transmit path, and accepts
only the same verified gated RTP packets as WAV recording. The default
`--radio-jitter-packets 2` prebuffers two packets; the accepted range is 1 through 25
packets (20 through 500 ms). The buffer reorders packets, rejects duplicates
and late arrivals, handles RTP sequence wrap, resets at every TCP audio gate,
and substitutes one exact 20 ms digital-silence frame for a missing sequence.
The FFplay adapter prewarms its render path with one-time digital silence during
session startup, before any radio audio gate, so device initialization does not
delay the first live packet. A 100 ms drain tail follows each gate. These
samples are local render padding only: they are not network packets, do not
change callback data, and are never included in evidence WAVs.
The adapter uses the Windows default render endpoint because this FFplay build
does not expose speaker selection. It must be launched from an interactive
desktop session; process success proves PCM was accepted by FFplay, not that a
physical speaker rendered it. Use the callback API with an endpoint-selectable
application backend when deterministic device routing is required.
FFplay raw-input probing is bounded to 32 bytes with zero analysis duration and
valid `nobuffer`/`low_delay` flags. A separate backend queue is capped at 25
packets (500 ms); if the renderer blocks, new stale audio is discarded and the
jitter buffer resynchronizes at current RTP rather than replaying seconds of
old voice. Backend queue drops are included in the final audit event.

```powershell
ip-commandmic-research emulate-mic --local-ip 192.168.0.2 --peer-ip 192.168.0.1 `
  --listen --verified-startup --play-radio-audio --radio-jitter-packets 2 `
  --confirm-active-testing --audit-log artifacts\software_mic_live_rx.jsonl
```

The CLI returns a failure if FFplay rejects the stream or its worker fails.
`scripts/run_interactive_live_beep_test.cmd` is the double-clickable desktop
entry point. Its PowerShell implementation refuses a headless session and the
launcher keeps the result or error visible.

`scripts/run_interactive_live_voice_test.cmd` is the sustained real-radio
validation. It waits for verified software-mic readiness, provides a visible
and audible countdown, holds the verified F1/Monitor key for 10 seconds, and
cues the operator to transmit voice from a separate handheld. Playback, WAV,
capture, audit, and hashes are collected together; F6330D transmit remains off.

The shared display model preserves all 68 payload bytes and tracks the verified
before/buffer/after/ack transaction. Corpus-wide differential analysis showed
that the real-radio `N5LSN` opening frame uses an all-zero 60-byte tail, while
ordinary channel/zone/volume screens use offset 56=`88`. A synchronized visual
trial now verifies bit `0x08` as LOW, bit `0x02` as audible, and bit `0x80` as
the zero-bar RSSI symbol. RSSI segment bits are `0x40`=bar 1, `0x20`=bar 2,
and `0x10`=bar 3; all eight combinations `80` through `f0` were visually
verified. The display model exposes both named indicators and the exact tuple
of lit bar positions. Bits `0x04` and `0x01` are Shift and received-message;
their combined `0x05` state was also visually verified. Offset 56 is therefore
fully mapped. Other display-tail offsets remain offset-labeled.

Offset 57 is also fully mapped: `80` Bell, `40` scan, `20` scan target, `10`
encryption, `08` GPS, `04` Talk Around, `02` Lone Worker, and `01` Bluetooth.
The display decoder composes both bytes into one named indicator collection.
Offset 61 is verified as the exact blink mask for offset 57 and is exposed as
named blinking Bell, scan, scan-target, encryption, GPS, Talk Around, Lone
Worker, and Bluetooth indicators.

Offset 58 maps `80/40/20/10` to the P1/P2/P3/P4 dealer-key boxes and
`08/04/02/01` to decimal-point segments after primary character positions
1/2/3/4. The display model exposes dealer-key icons and decimal-point positions
separately.

Offset 59 high bits `80/40/20/10` continue the point bitmap at primary
positions 5/6/7/8. Its low-nibble bits produced no static visible segment when
tested alone and remain explicitly unresolved pending interaction/blink trials.
An all-visible follow-up (`88888888`, all icons, P boxes, RSSI bars and points)
cycled every lower-nibble bit individually and together for six seconds with no
static, blink, or gating effect. The raw nibble remains preserved for firmware
compatibility.

Offset 60 is the exact blink mask for offset 56: every bit flashes the matching
RSSI segment, LOW, Shift, audible, or message element. The model exposes named
blinking indicators and independently blinking RSSI bar positions.

Offsets `56↔60`, `57↔61`, `58↔62`, and `59↔63` are exact static/blink bitmap
pairs. Offset 62 exposes blinking P1–P4 icons and decimal points 1–4; offset 63
exposes blinking decimal points 5–8. The low nibbles of offsets 59 and 63 remain
losslessly preserved as unresolved/reserved after negative all-visible tests.

Offset 64 is exposed conservatively as an LCD-wide visual-control byte. Exact
one-bit observations are named as normal composition, three photographed
segment patterns, or blank display; untested combinations remain raw rather
than being inferred.

Offset 65 exposes its raw byte plus bounded one-bit negative visual results.
No one-bit value changed the LCD, backlight, or LED in the all-visible trial;
the SDK does not label the byte unused.

Offset 66 has the same bounded one-bit negative visual result and remains a raw,
losslessly preserved field pending combination, timing, or nonvisual evidence.

Offset 67 has the same bounded one-bit negative visual result. All 68 payload
bytes remain represented losslessly even where visual semantics are unresolved.

The model also exposes offsets 8–27 as a lossless auxiliary region and offsets
28–35 as eight character-attribute bytes. Bit `0x80` is verified to blink the
matching character at every position: offsets 28–35 correspond exactly to
positions 1–8. The model exposes the complete tuple of blinking positions.
At representative position 5, a full one-bit scan found no visible effect for
attribute bits `01` through `40`; only `80` blinked the character. Lower bits
remain preserved rather than labeled unused.

`--display-offset56-test` is a bounded isolated-CommandMic diagnostic that sends
only those four observed values, holds each for six seconds, and restores `88`.
It is incompatible with audio and TX modes. It exists for repeatable display
research, not as a general arbitrary-byte injection interface.

A live six-second loopback using real TCP and UDP sockets on `127.0.0.1` and
`127.0.0.2` also completed both sessions, both bidirectional UDP boot exchanges,
both display acknowledgements, and two heartbeat responses. The mic audit
SHA-256 is `5998b8f97d1cc961fc9746312066ea9d0ca90733007cc31319bca1a3de4a5643`;
the radio audit SHA-256 is
`eda14de16572f6336dc669f3cac2ba921571518b9dbfe1b71beddfb522dd3dd9`.

## Scope and safety boundary

`emulate-radio --verified-startup` is an isolated-endpoint research profile for
connecting a real CommandMic to software while the real radio is physically
disconnected from Ethernet. Every transmitted application frame is either an
exact frame from the cold-boot capture or a display frame built from the
verified display layout and CRC algorithm.

The profile can:

- complete the observed short probe session and subsequent stable session;
- answer the verified all-zero UDP/50000 boot datagram;
- send startup, opening-text, channel, zone, volume, and idle-heartbeat state;
- react to Up, Down, Left, Right, Volume Up, and Volume Down key presses; and
- log every received, sent, and deliberately withheld message as JSONL.

An independent `--record-mic-wav PATH` gate enables one isolated PTT/audio
capture while the real radio remains physically disconnected. On PTT down it
waits 9 ms, sends the captured `01/04:08000000` TX-active response, waits 6 ms,
then sends `02/02:02`. It accepts only RTP v2/PT125 packets from the configured
CommandMic address with the verified microphone SSRC `7069c2cc`, 320-byte
payloads, and records them as mono 8 kHz 16-bit PCM. On PTT up it preserves a
350 ms receive tail, sends idle status at 220 ms and TX-close 2 ms later, and
writes sequence/timestamp error counts to the audit log. The path must be new,
one invocation records at most one PTT stream, and the maximum is 30 seconds.
Received packets are never echoed.

An independent `--enable-rx-audio` gate can send a bounded sine-wave test tone
to the CommandMic speaker. It uses the verified RTP v2/PT125, signed 16-bit
big-endian, 8 kHz mono representation: 160 samples/320 payload bytes every
20 ms. The stream preserves phase, increments RTP sequence by one and timestamp
by 160, and uses the captured radio SSRC. It cannot begin until the stable
startup task and a verified CommandMic UDP boot datagram have completed.
On Windows, the bounded sender temporarily requests 1 ms timer resolution only
for the duration of the tone and always restores it in `finally`; this avoids
the paired/bursty delivery observed with the default scheduler resolution.
The final pacer also uses cooperative zero-delay event-loop yields against an
absolute deadline rather than a coalescible 20 ms timer. This trades bounded
CPU use during playback for reliable RTP cadence while continuing to service
ready TCP and heartbeat tasks.
For the bounded send section, the event-loop thread registers with Windows
MMCSS as `Pro Audio` and always reverts the registration in `finally`. This is
the Microsoft-supported multimedia scheduling mechanism and avoids using raw
time-critical thread priority.
Before RTP, the emulator sends the verified receive-open state
`01/04:01000000`, refreshes the current display, and sends `02/02:04`. In a
`finally` block after RTP it sends `01/04:00000000` and `02/02:00`, matching the
real F1/Monitor close sequence.

The corrected hardware trial used a one-second 1 kHz tone at -40 dBFS. The
CommandMic played it steadily and illuminated its green LED. The capture
contained 50 packets/8,000 samples, measured exactly 1,000 Hz, had -39.99 dBFS
peak level, and had no RTP sequence or timestamp-step discontinuities. Mean
captured wall interval was 19.53 ms; Windows delivery jitter ranged from 0.14 to
36.58 ms in short/long pairs, but the CommandMic jitter buffer produced stable
audio. Capture: `20260809T194101Z_emulator_rx_audio_smoke_r02.pcapng`, SHA-256
`1fa697fd16a07edb07992a4361199aeebd74bde18f3329faf1670ab163b667c0`.

The `02/02` byte also directly controls the top status LED independently of
audio: `00` off, `02` red, `04` green, and `06` orange (red plus green). The
parser and Wireshark dissector expose the red and green emitters plus verified
composite color. The diagnostic sent no audio, RTP, PTT, or TX state.

Volume reaches 0 for mute and stops at 32 on the upper end. Passive
real-radio capture now verifies that Volume Down at the zero floor repeats the
complete `VOL  0` overlay and one-second restore transaction instead of being
silently ignored. A second capture verifies every level 1 through 32 in order
and an additional Volume Up press repeating the identical `VOL 32` overlay.
The emulator now clamps and acknowledges both verified boundaries.

By default, the software-radio profile does **not** respond to PTT. The explicit
`--record-mic-wav` mode is the sole exception and sends only the four captured
radio TX-active/status/idle/close frames described above. Emergency, Power, P1-P4,
F1, the ten-key pad, malformed frames, and unknown commands remain unanswered.
The software-radio emulator does not originate microphone audio, configuration,
cloning, firmware, stun/kill, or emergency traffic. Its behavior is independent
of the software-mic-only `--enable-tx` gate.

Receive audio is off by default and does not use or imply `--enable-tx`. Tone
frequency is limited to 20–3500 Hz, level to -60 through -6 dBFS, and duration
to 0.02–30 seconds. Defaults are 1 kHz, -30 dBFS, and three seconds.

`--rx-wav PATH` replaces the generated tone with WAV playback. Files must be
uncompressed mono 8 kHz 16-bit PCM and contain 0.02–30 seconds of audio. WAV
little-endian samples are converted to network big-endian samples without
amplitude changes. Only the last partial 160-sample packet is zero-padded.
Unsupported formats and oversized files are rejected before any RTP is sent;
the control path still executes its guaranteed close transaction.

`--rx-open-only-seconds N` is a bounded diagnostic mode. It sends the same
verified receive-open, display refresh, status-open, and guaranteed close
transactions, but sends no RTP packets during the requested interval. It is
mutually exclusive with `--rx-wav` and still requires `--enable-rx-audio`.
Comparing this mode with an all-zero WAV distinguishes noise introduced merely
by the CommandMic's open analog output path from RTP loss/concealment noise.

The isolated hardware comparison is complete. During a 3.039-second open-only
interval, the CommandMic produced the same low white-noise floor heard in the
byte-exact zero gaps of the reference WAV. The successful capture contains no
RTP audio packets during that interval (only the earlier UDP boot exchanges).
This establishes that the noise is introduced by the CommandMic's opened
output path and is not caused by WAV data, endian conversion, or RTP cadence.
Capture: `20260809T200619Z_emulator_rx_open_only_r02.pcapng`, SHA-256
`bcb95bd5bcb5872206634e4579dfb4509173304021a447a6b299038419d0a31c`.

The first isolated microphone-capture trial also completed. The CommandMic
accepted the verified PTT active/status transaction and sent 572 continuous
mic-to-radio RTP packets during an 11.242-second physical hold. The configured
10-second ceiling stopped the WAV at exactly 500 packets/80,000 samples while
the remaining wire traffic was received but discarded. Both the full wire
stream and recorded prefix had zero RTP sequence or timestamp discontinuities;
the WAV sample bytes match the first 500 captured payloads exactly after the
documented endian conversion. It is mono 8 kHz PCM, has -43.81 dBFS RMS and
-15.56 dBFS peak, and contains no clipped samples. The PCAPNG SHA-256 is
`b9789203da0677347ad1ac91aa252c8fe3307ac2a6fed35ff74514c60a824889`;
the private WAV SHA-256 is
`dcdeec2a62956e46db506be73466d28e039c9ea136a2f96a8678dd94d4766c3a`.

That trial exposed two emulator-only issues which were corrected afterward:
startup PTT-up synchronization frames no longer elicit redundant close
responses, and Windows 1 ms timer resolution is requested only around the four
short PTT response delays so their scheduling better matches captured hardware.

## Transport behavior

The observed hardware uses TCP destination and source port 52001 for both the
short probe connection and the stable connection. On Windows, the active close
of the probe leaves that exact four-tuple unavailable longer than the observed
roughly two-second reconnect interval. The emulator therefore uses source port
52002 for only the short probe and reserves source port 52001 for the stable
session. Destination port 52001 and all application bytes are unchanged.

This is an explicit compatibility hypothesis for the first isolated trial. It
can be changed with `--probe-source-port`. If the CommandMic requires source
port 52001 even for the probe, stop and inspect the capture; do not change
system-wide TCP timers or introduce raw-packet transmission as a workaround.

A live PoE interruption subsequently exercised stable-session recovery. After
the six-second heartbeat watchdog closed the dead session, three two-second
retries occurred while the CommandMic booted; the fourth attempt completed a
new stable session. The new startup hello appeared 14.067 seconds after the
last pre-interruption mic heartbeat, followed by 41 normal heartbeat replies.
Windows reported `WinError 52` for the three unavailable attempts, but no
socket-option or system TCP-timer change was needed.

A separate 1,800-second isolated soak completed with all 898 heartbeat requests
answered, 2.164 ms mean response latency, no reconnect/watchdog or unsafe state,
and zero capture drops. This satisfies the single-session 30-minute emulator
acceptance criterion.

The repeated-reconnect criterion was then exercised with ten operator-cued PoE
cycles. Every cycle produced one fail-closed watchdog followed by a fresh stable
session and heartbeat. Cue-to-reply time ranged from 14.952 to 26.040 seconds
(18.136 seconds mean), including the physical PoE action and CommandMic boot.
The campaign produced no PTT-down, non-startup key, audio-open, emergency, or
configuration event. All ten 45-second captures had zero drops and parsed with
zero warnings. The first two cycles required seven bounded connection retries;
the remaining eight required two each. The cause of that retry-count difference
is not assigned beyond the observed endpoint/Windows connection availability.

The first Windows hardware trial also established that the process must be
elevated to connect from an explicitly bound local source port on this
workstation. A non-elevated socket could bind 52001/52002 but Windows rejected
the outbound connect locally with `WinError 5`; an elevated handshake and the
elevated emulator both succeeded. This is a workstation policy requirement,
not a CommandMic protocol behavior.

## First hardware-isolated trial

Do not start the program until all of these are true:

1. Physically unplug the real radio's Ethernet cable. Do not rely only on radio
   power state or a switch rule.
2. Leave the CommandMic on its PoE switch port.
3. Keep the radio RF output terminated in the rated dummy load even though this
   emulator cannot key it.
4. Put the research-PC switch port in normal forwarding mode on the CommandMic
   VLAN. A dedicated adapter/port is preferred; do not use a receive-only SPAN
   destination for active emulation.
5. Confirm that no other host owns `192.168.0.1` and no local process is using
   TCP/52001, TCP/52002, or UDP/50000.
6. Assign `192.168.0.1/24` to the research PC's isolated Ethernet interface.
   Remove or disable the PC's existing `192.168.0.99/24` address for this trial
   if Windows reports ambiguous routing or duplicate-address behavior.
7. Verify that an ARP request from `.1` for `.2` receives a reply from
   the configured CommandMic address. Failure blocks the emulator trial.
8. Start a full-packet capture on `Ethernet` before starting the emulator.
9. Do not pass `--enable-tx`.

Run from the repository root:

```powershell
ip-commandmic-research emulate-radio --local-ip 192.168.0.1 --peer-ip 192.168.0.2 `
  --verified-startup --mic-gain 3 --confirm-active-testing `
  --audit-log artifacts/emulator_radio.jsonl
```

The optional `--mic-gain` value is restricted to the capture-verified settings
1 through 5. It emits consecutive `02/0e` values `gain` and `gain + 1`; the
default remains 3 to reproduce the original baseline capture.

For the isolated real-CommandMic experiment only, the second `02/0e` value can
be changed independently with both
`--experimental-mic-gain-companion <1..6>` and
`--allow-experimental-gain-pair`. The real radio must be physically disconnected.
The override changes exactly one startup frame, remains behind the existing
`--confirm-active-testing` gate, and does not enable RF transmission.

The override was validated against an isolated real CommandMic with `05,05`,
`04,06`, and `04,05` pairs. Those tests show that the first value has an
approximately 2 dB gain-stage effect and the second value controls or dominates
the low-level suppression state. These non-codeplug pairs remain experimental;
the guard is intentional and must not be removed merely because the endpoint
accepted them.

Expected success is: the CommandMic completes a probe, reconnects, shows the
opening text `N5LSN`, then shows `QTH NODE`. Up/Down should alternate between
`QTH NODE` and `TEST TWO`; Left/Right should temporarily show `ZONE 1` or
`ZONE 2`; Volume Up/Down should temporarily show the verified levels `VOL 0`
through `VOL 32`.

Stop after at most one minute for the first trial. Stop immediately if PTT/TX,
Emergency, Power, continuous reconnects, malformed display, or any unexpected
state occurs. Preserve the PCAPNG and JSONL audit log before restoring the
workstation address.

### 2026-08-09 blocked preflight

With the radio Ethernet cable physically disconnected, the PC temporarily
owned `.1` and emitted five forced-source ARP requests for `.2`. No CommandMic
ARP reply was observed. The emulator was therefore not started, and the PC was
restored to `.99`. The capture is
`20260809T185913Z_emulator_preflight_arp_forced_source.pcapng` (SHA-256
`550cf42099466b436197e09cc1158b9d626472b5624a50d6d104d00adfa3f064`).

The leading hypothesis is that the UniFi SPAN destination does not forward PC
ingress traffic. CommandMic peer-MAC filtering or an endpoint power/state issue
remain alternatives. Repeat the ARP gate with the PC port in normal forwarding
mode before considering radio-MAC emulation.

### 2026-08-09 successful isolated idle trial

After placing the PC switch port in normal forwarding mode, the CommandMic
answered ARP from both `.99` and `.1` with the expected MAC. The short probe
source port 52002 was accepted, so no MAC spoofing or system-wide TCP changes
were required. The verified emulator completed:

- the probe session and clean reconnect;
- the stable session on local/remote TCP port 52001;
- two bidirectional UDP/50000 boot exchanges;
- the `N5LSN` and `QTH NODE` display transactions and acknowledgements; and
- 28 radio heartbeats with 28 microphone replies.

The 60-second capture is `20260809T191102Z_emulator_radio_idle_60s.pcapng`
(SHA-256 `10ef66ed1180044a4ec4c944d630d0bd553e5332e307485d4ba4751a3f8d046d`).
All 108 application messages parsed without warnings; response latency was
1.676–2.669 ms (2.212 ms mean), and dumpcap reported zero drops. TX remained
disabled and no controls were operated.

A dedicated visual repeat then confirmed the physical sequence: the CommandMic
orange LED illuminated briefly, the screen/backlight activated, `N5LSN`
remained visible for several seconds, and the display changed to `QTH NODE`.
The corresponding capture is
`20260809T191548Z_emulator_visual_display_confirmation.pcapng`. The orange LED
was subsequently mapped as the composition of red and green emitters in
`02/02:06`.

The verified radio emulator accepts `--backlight-state off`, `dim`, or `on`
(the default). These emit the observed immediate values `02/0b:00`, `01`, and
`02`, respectively. No unobserved backlight state value is accepted.

## Offline verification

The regression suite covers exact cold-boot frame bytes, arbitrary parser
framing, probe and stable sessions, opening and control displays, UDP response
gating, PTT withholding, and distinct probe/stable source ports. Run it with:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```
