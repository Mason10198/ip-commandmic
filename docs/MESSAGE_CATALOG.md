# Observed TCP message catalogue

This catalogue records wire identities, not semantic guesses. Counts come from
the simultaneous cold-boot capture and include both bootstrap attempts. Every
listed message has a valid CRC after unstuffing.

Implementation status is distinct from semantic confidence: the reference
library can losslessly parse/replay unknown messages, while typed application
operations are exposed only for mapped behavior. Both endpoint sessions, the
two desktop GUIs and the Wireshark dissector consume this catalogue through the
shared parser/device models rather than maintaining independent wire tables.

## Verified message

| Direction | Start | Class | Command | Length | Payload | Count | Meaning |
|---|---:|---:|---:|---:|---|---:|---|
| Radio → mic | `f3` | `05` | `00` | 2 | `4d00` | 67 | Idle heartbeat request |
| Mic → radio | `f3` | `05` | `00` | 2 | `6d01` | 65 | Idle heartbeat response |

## Verified contrasting volume-button mapping

Three Volume Up trials and three Volume Down trials produced
distinct `01/01` values and otherwise parallel exchanges. The contrasting
captures distinguish button identity from generic key state. Both mappings have
met the three-trial acceptance threshold.

| Relative time | Direction | Class/command | Payload | Observation |
|---:|---|---|---|---|
| 15.803718 s | Mic → radio | `01/01` | `10` | Volume Up press occurred |
| 15.853316 s | Radio → mic | `02/07` | `02` | Precedes display buffer update |
| 15.854214 s | Radio → mic | `02/0a` | 68-byte buffer containing ` VOL  2` | Volume overlay |
| 15.855225 s | Radio → mic | `02/08` | `0044` | Follows display buffer |
| 15.857800 s | Mic → radio | `02/09` | `01` | Response to display sequence |
| 16.009757 s | Mic → radio | `01/01` | `90` | Paired with physical release |
| 16.011784 s | Mic → radio | `01/01` | `7f` | Post-release/neutral candidate |
| 16.854244 s | Radio → mic | `02/0a` | Buffer containing `QTH NODE` | Prior display restored after ~1 s |

For Volume Down, the corresponding sequence was:

| Relative time | Direction | Class/command | Payload | Observation |
|---:|---|---|---|---|
| 17.642850 s | Mic → radio | `01/01` | `01` | Volume Down press |
| 17.659247 s | Radio → mic | `02/07` | `02` | Precedes display update |
| 17.660172 s | Radio → mic | `02/0a` | 68-byte buffer containing ` VOL  1` | Volume overlay |
| 17.661087 s | Radio → mic | `02/08` | `0044` | Follows display buffer |
| 17.662759 s | Mic → radio | `02/09` | `01` | Display-sequence response |
| 17.840770 s | Mic → radio | `01/01` | `81` | Volume Down release |
| 17.842682 s | Mic → radio | `01/01` | `7f` | Common post-release neutral state |

The confirmed key-state values are therefore:

| Physical action | `01/01` payload |
|---|---:|
| Volume Down press | `01` |
| Volume Down release | `81` |
| Volume Up press | `10` |
| Volume Up release | `90` |
| Post-release neutral | `7f` |

For both volume buttons, release equals press with bit 7 set. The later
three-trial physical-key campaign reproduced that relationship for P1–P4 and
all four directional keys as well.
Volume Up repetition 2 reproduced `10 → 90 → 7f` exactly and displayed
`VOL  2`; its capture hash is
`81601dd02eef8d2b175721b384cada8f193b9b1d5f913b6adb486e16f7977785`.
Volume Down repetition 2 reproduced `01 → 81 → 7f` exactly and displayed
`VOL  1`; its capture hash is
`40a50845a8596b1e39cd4bfaf6fea051f77db72c0ce2c036ce8f976c5785f072`.
Volume Up repetition 3 reproduced `10 → 90 → 7f` exactly and displayed
`VOL  2`; its capture hash is
`4cbb93f47a4bd59c51d7d475ff3d1e2836beb079a16bcddc69d25412c0c71df2`.
Volume Down repetition 3 reproduced `01 → 81 → 7f` exactly and displayed
`VOL  1`; its capture hash is
`bbaa5e08394fb08d4be0e90013db6e173b8b1925d0fa9dbf416aed5bfcc07c2c`.

A later real-radio floor capture wire-verifies `VOL  0`. One Volume Down press
displayed `VOL  0`; a second press while already at the floor repeated the same
complete display transaction rather than being silently ignored:

```text
mic   01/01:01                 Volume Down press
radio 02/07:02
radio 02/0a:<buffer " VOL  0">
radio 02/08:0044
mic   02/09:01                 display acknowledgement
mic   01/01:81 -> 7f          release, neutral
radio display transaction      restore QTH NODE after 1.000 s
```

Both `VOL  0` display buffers were byte-identical. Press-to-buffer latency was
41.2 ms and 29.4 ms in the two trials. The radio therefore clamps the state at
zero but continues to acknowledge a below-floor Volume Down action visually.

The complete upward range was then captured from zero. Thirty-three distinct
Volume Up taps generated `VOL 1, 2, ... 31, 32, 32`: no level was skipped, and
the final above-ceiling tap repeated a byte-identical `VOL 32` transaction.
Every press had a corresponding release and volume overlay. The verified radio
range is therefore 0–32, with symmetric visual acknowledgement at both clamps.

Automated three-trial runs extended the same key-state structure to P1–P4 and
the four directional keys:

| Key | Press | Release |
|---|---:|---:|
| P1 / P2 / P3 / P4 | `02` / `12` / `22` / `32` | `82` / `92` / `a2` / `b2` |
| Up / Down | `20` / `21` | `a0` / `a1` |
| Left / Right | `31` / `30` | `b1` / `b0` |

Every sequence ended in `7f`, and every release was press plus `0x80`. See
`experiments/runs/20260809_button_mapping_summary.md`. The directional trials
produced no corresponding radio display/state messages because the baseline has
only one channel in one zone; there was no alternate state to select.

The reference encoder now exposes `encode_key_state(button, action)` and
`encode_key_tap(button)`. The latter produces press, release, and neutral with
the verified CRC and stuffing. The software-mic session queue does not become
active until the second stable display acknowledgement on a cold boot. A real
radio warm reconnect produced only the current `QTH NODE` display, so a tested
three-second single-display grace path handles that variant without inspecting
or guessing configured opening text. Software-only probe/stable integration
verifies exact P1 and Up sequences. E-087 additionally verifies against the
real F6330D that the first 11 ordinary taps produced all 33 expected frames
byte-for-byte. E-089 completes the sweep: F1 and the remaining keypad keys add
36 exact frames, for all 23 ordinary controls and 69 total frames. Emergency,
Power, and PTT are outside the ordinary-key queue and remain separately gated.

F1 Monitor mapped as `00` press, `80` release, and `7f` neutral in three trials.
Two sufficiently long holds also correlated with radio `01/04:01000000`, RTP
receive audio, and later `01/04:00000000`; the shortest press generated only the
physical key sequence. A controlled short/hold timing experiment is needed to
measure the activation threshold.

The receive-audio control transaction is now ordered more precisely:

| Order | Direction | Class/command | Payload | Observed role |
|---:|---|---|---|---|
| 1 | Radio → mic | `01/04` | `01000000` | Receive audio path open |
| 2–4 | Radio → mic | `02/07`, `02/0a`, `02/08` | current display | Display refresh |
| 5 | Radio → mic | `02/02` | `04` | Receive status active |
| 6 | Radio → mic | UDP RTP/PT125 | s16be PCM | Audio begins about 10 ms later |
| 7 | Radio → mic | `01/04` | `00000000` | Audio path close |
| 8 | Radio → mic | `02/02` | `00` | Idle status |

In the complete close capture, the final two control frames followed the last
RTP packet by about 8 ms. Sending valid RTP without steps 1–5 produced no sound
or receive indication on the real CommandMic. Repeating with the complete
transaction produced a stable audible tone and illuminated the CommandMic green
LED. A later isolated observed-value scan proved that `02/02` directly controls
the two-color status LED:

| `02/02` payload | Red emitter | Green emitter | Observed color |
|---:|---|---|---|
| `00` | off | off | off |
| `02` | on | off | red |
| `04` | off | on | green |
| `06` | on | on | orange |

The mapping is compositional: bits `0x02` and `0x04` independently drive the red
and green emitters. Audio, RTP, PTT, and TX were disabled during the isolated
scan, separating LED control from the audio-path transaction.

With the baseline CPS setting `Backlight: ON`, a connected isolated-emulator
trial kept `QTH NODE` continuously illuminated for roughly 19 seconds across
two eight-second heartbeat-only intervals and two byte-identical display
refreshes. There was no visible timeout or wake transition; the display went
black only after the emulator disconnected. This is a negative result for an
inactivity timeout in this configuration.

The one-variable comparison subsequently identified radio-to-mic `02/0b` as
the CommandMic immediate backlight-state message. Two otherwise byte-identical complete
Mic Gain 4 startup sequences differed at exactly this transaction:

| CPS mode | `02/0b` payload | Synchronized observation |
|---|---:|---|
| Backlight OFF | `00` | LCD content remained very dimly visible; keypad illumination off |
| Backlight ON | `02` | LCD and keypad continuously illuminated |

The LCD controller and segment updates remain active in OFF mode; `N5LSN` and
`QTH NODE` were still sent normally. The faint visibility is described as an
observation, not as evidence that OFF selects the separate CPS `Dim` mode.
An OFF Auto trial then confirmed the state-command interpretation: startup sent
`02`, followed 5.005 seconds later by `00`; P1 sent `02` 8.363 ms after
key-down, and `00` followed 4.988 seconds after key release (5.148 seconds after
the ON command). Both LCD and keypad lighting visibly followed the commands.
Thus CPS mode governs when the radio sends the state commands. A static Dim
trial mapped the third state `01`: both LCD and keypad illumination stayed
continuously dim and P1 caused neither a visible brightness change nor another
`02/0b` command.

With Dim Auto and the external DIM wiring left untouched, startup sent ON and
then DIM 105 ms later. Both LCD and keypad stayed dim, and P1 caused no visible
change or additional backlight transaction. Icom's CPS help says this phenotype
corresponds to an asserted external DIM input, but that input was not measured
electrically; the input-state conclusion is therefore an inference. A later
controlled external-input transition can verify the opposite branch.

The `01/04:01000000` plus `02/02:04` open/status transaction also opens the
CommandMic output when no RTP packets follow. In a 3.039-second zero-RTP trial,
the operator heard the same low white-noise floor previously heard during
byte-exact zero-valued WAV gaps. This localizes that noise to the CommandMic's
opened output path; it is not encoded in the RTP payload and does not require
packet-loss concealment to occur.

The same `01/04` audio-path gate is used for CPS key-touch beeps, but without
the `02/02` receive-status/LED transaction. With CPS `Beep: ON`, every audible
key press was followed by `01/04:01000000`, radio-to-mic RTP/PT125 PCM, and
`01/04:00000000`. The RTP waveform, not the TCP gate alone, contains the tone:

| Audible result | RTP payload | Media duration | Observed uses |
|---|---|---:|---|
| High/normal key beep | 1 kHz s16be/8 kHz mono, 4 packets | 80 ms | Volume Down, F1 tap, ordinary keypad entry |
| Low/error or boundary beep | 500 Hz s16be/8 kHz mono, 7 packets | 140 ms | unavailable Channel Up, Volume Up at 32, completed/invalid keypad entry |

Twenty non-null presses reproduced this complete gate/RTP/close transaction.
Three P1 presses, with P1 assigned Null, produced only their physical key-state
frames and no gate pulse, RTP burst, or audible beep. The operator independently
reported hearing every tested non-P1 beep and no P1 beep. Earlier Beep-OFF
button-mapping traces contain no immediate paired gate/RTP transaction for the
same direction, volume, and keypad controls. F1 remains context-sensitive
because its assigned Monitor function can independently open receive audio.

The reference library exposes these as `KeyBeepProfile` values named `normal`
and `low`. The software-radio emulator's `--key-beep` mode emits exactly one
bounded gate/RTP/close transaction and intentionally omits the receive-audio
display and `02/02` status frames. The initial CPS Beep Level 3 capture measured
approximately -31.30 dBFS RMS (normal) and -30.51 dBFS RMS (low), consistent
with the larger controlled calibration below.

Fixed CPS Beep Levels 1–5 are now calibrated. They preserve the tone classes
and add approximately 6.02 dB per step:

| Fixed level | Normal RMS | Low RMS |
|---:|---:|---:|
| 1 | -43.297 dBFS | -42.557 dBFS |
| 2 | -37.269 dBFS | -36.530 dBFS |
| 3 | -31.245 dBFS | -30.506 dBFS |
| 4 | -25.223 dBFS | -24.484 dBFS |
| 5 | -19.215 dBFS | -18.495 dBFS |

The low tone's seventh RTP packet is an all-zero tail, not a missing packet.
The library accepts `get_key_beep_profile(name, beep_level)` and the emulator
CLI exposes `--beep-level 1|2|3|4|5`. Linked-to-volume levels remain unmeasured.

The ten-key matrix is also verified in three trials per key:

```text
1=03  2=04  3=05
4=13  5=14  6=15
7=23  8=24  9=25
*=33  0=34  #=35
```

Release sets bit 7 and is followed by `7f`. Digit entry produced `chN__`, then
`chNN_`, then an attempted three-digit memory selection and display restore.

The physical layout fills nearly all positions in a 4×6 code matrix, but `11`
is unused. A targeted attempt established that the molded center of the
directional rocker is not a separate switch; attempts produced existing Up/Down
codes instead.

## PTT mapping

PTT is separate from the `01/01` physical-key matrix:

| Direction | Class/command | Payload | Meaning |
|---|---|---|---|
| Mic → radio | `01/00` | `01` | PTT down |
| Radio → mic | `01/04` | `08000000` | TX active response |
| Radio → mic | `02/02` | `02` | TX status correlate |
| Mic → radio | `01/00` | `00` | PTT up |
| Radio → mic | `02/02` | `00` | Idle status correlate |
| Radio → mic | `01/04` | `00000000` | TX closed response |

The first dummy-load trial observed 9.54 ms from PTT down to TX-active response
and 222.61 ms from PTT up to TX-closed response.

Across three silent dummy-load trials, TX-active acknowledgement ranged
9.00–9.97 ms, first RTP 30.32–32.42 ms after PTT down, and TX-closed response
222.61–223.53 ms after PTT up. Every RTP sequence was continuous.

An acoustic 1 kHz transmit-audio trial independently verified that the
mic-to-radio RTP payload is signed 16-bit big-endian PCM at 8 kHz mono. Its 441
packets were continuous, carried 160 samples each, and decoded at exactly
1000.0 Hz. See `experiments/runs/20260809_ptt_1khz_transmit_audio.md`.

## Power mapping

Power application and the physical Power key are distinct behaviors. When DC
was removed while the radio was last soft-powered on, reapplying DC caused a
complete unattended network/UI boot: the mic displayed `N5LSN`, then
`QTH NODE`, and entered stable heartbeat exchange. The operator pressed no key
and no `01/09` message occurred. A subsequent operator differential found that
soft-powering the radio off before removing/reapplying DC left it off. The best
current model is retained soft-power state across DC loss. The on-state path is
wire-verified; the off-state path still needs a passive capture. The exact role
of codeplug `Power SW On = Enable` is not inferred from these observations.

Power does not use the `01/01` physical-key matrix. A clean 220.096 ms quick tap
emitted mic-to-radio `01/09:01` on press and `01/09:00` on release. The radio
sent no non-heartbeat response, no UDP datagram appeared, and the control
session remained uninterrupted.

Four longer holds each began with the same `01/09:01`. Radio shutdown behavior
began 0.51–0.52 seconds later, while the button was still held, and a new control
session appeared after shutdown. Two trials released early enough to emit
`01/09:00`; two remained held until the connection vanished and therefore had
no observable release message.

| Direction | Class/command | Payload | Meaning |
|---|---|---|---|
| Mic → radio | `01/09` | `01` | Power button pressed |
| Mic → radio | `01/09` | `00` | Power button released |

Holding the press state beyond the observed threshold causes a controlled
session restart; this is not proof that either endpoint loses electrical power.
See `experiments/runs/20260809_power_button.md`.

## Emergency physical key

The dedicated Emergency function was assigned `Null` in the verified
`emergency_inert.icf` derivative before the physical button was tested. Three
short presses then produced only the ordinary `01/01` key matrix sequence:

| Physical control | Press | Release | Neutral |
|---|---:|---:|---:|
| Emergency | `40` | `c0` | `7f` |

All three trials reproduced the sequence. No radio application message beyond
normal heartbeats and no UDP/RTP packet appeared. This maps the physical key;
it does not characterize Emergency-mode signaling. Emergency remains excluded
from the automated mapper and emulator output.

## Channel/display synchronization

With two otherwise identical channels named `QTH NODE` and `TEST TWO`, each of
six channel changes produced this transaction:

| Order | Direction | Class/command | Payload | Interpretation |
|---:|---|---|---|---|
| 1 | Radio → mic | `02/07` | `02` | Display-sync marker before buffer |
| 2 | Radio → mic | `02/0a` | 68 bytes | Display buffer |
| 3 | Radio → mic | `02/08` | `0044` | Display-sync marker after buffer |
| 4 | Mic → radio | `02/09` | `01` | Display transaction acknowledgement |

Only bytes 0–7 of the two 68-byte buffers differed, and they were exactly the
ASCII channel texts. All remaining 60 bytes were identical within this
channel-name differential. The complete
transaction arrived 32.18–74.81 ms after the physical key press across the six
trials. The `02/07` and `02/08` labels describe verified ordering, not broader
semantics beyond this display transaction.

## Display indicators and corpus-wide tail inventory

The `display-inventory` tool now decodes the full 68-byte payload into a lossless
model, retains offsets 8–67 as unknown, and reports exact variants and byte-level
variation. Across 106 captures, 208 buffers in 47 captures produced no decode
warning and six distinct unknown tails:

| Payload offsets | Values | Correlated screens | Status |
|---|---|---|---|
| 8–27 | all `20` or all `00` | keypad-entry screens versus ordinary screens | Exact correlation; layout meaning unresolved |
| 32/33 | one byte `80` | alternate keypad-entry stages | Exact correlation; cursor/attribute meaning unresolved |
| 56 | `00` | real-radio opening `N5LSN`; controlled `QTH NODE` | No LOW, audible, or RSSI indicator during controlled state |
| 56 | `08` | controlled candidate-bit state | `LOW` only |
| 56 | `80` | controlled candidate-bit state | zero-bar RSSI symbol only |
| 56 | `88` | ordinary channel/zone/volume and emulator screens | `LOW` plus zero-bar RSSI symbol |
| 56 | `8a` | F1/Monitor receive trials and controlled state | `LOW`, audible (speaker), plus zero-bar RSSI symbol |
| 56 | `fa` | F1/Monitor receive trial and controlled state | `LOW`, audible, and RSSI displayed |

The full variant/capture ledger is
`artifacts/display_inventory_all_20260810.json` (SHA-256
`6b784bc26714a8530d762f27554475847ef0fd2ef2a74c89e3a11a04393e5208`).
The `r05` and `r02` synchronized visual trials promote these exact byte values
from correlations to verified indicator sets. Candidate masks `08` and `80`
separate cleanly: bit `0x08` is LOW and bit `0x80` is the RSSI symbol with no
bars. Because `88 -> 8a` changes only bit `0x02` and visually adds audible,
bit `0x02` controls the speaker icon in this state. The complete RSSI ladder
then established that bits 4–6 are independent segment bits rather than an
ordinary binary level: `0x40` lights bar 1, `0x20` bar 2, and `0x10` bar 3.
All eight masks from no bars through every combination were visually verified.
Normal radio operation is expected to use cumulative combinations, but the
wire format can address each segment independently. Other values remain unknown
and losslessly preserved.

The final two single-bit trials complete offset 56: `0x01` displays the
received-message envelope and `0x04` displays the Shift up-arrow. Value `0x05`
visually showed both simultaneously, confirming independent composition.

| Bit | Verified LCD meaning |
|---:|---|
| `0x80` | RSSI antenna/base |
| `0x40` | RSSI bar 1 |
| `0x20` | RSSI bar 2 |
| `0x10` | RSSI bar 3 |
| `0x08` | LOW output power |
| `0x04` | Shift |
| `0x02` | Audible/unmuted speaker |
| `0x01` | Received Message/Status Message envelope |

Absolute payload offset 57 contains the remaining eight official icon-area
states. A complete one-bit scan produced one distinct manual-matching icon per
bit:

| Bit | Verified LCD meaning |
|---:|---|
| `0x80` | Matching-signal Bell |
| `0x40` | Scanning / scan paused |
| `0x20` | Scan-target channel |
| `0x10` | Encryption |
| `0x08` | GPS/position |
| `0x04` | Talk Around |
| `0x02` | Lone Worker |
| `0x01` | Bluetooth |

Offsets 56 and 57 therefore account for the complete 13-icon area shown in the
Icom operating guide. The corresponding blink masks at offsets 60 and 61 are
also complete.

Absolute payload offset 58 divides into two four-bit groups:

| Bit | Verified LCD meaning |
|---:|---|
| `0x80` | P1 dealer-assignable key icon |
| `0x40` | P2 dealer-assignable key icon |
| `0x20` | P3 dealer-assignable key icon |
| `0x10` | P4 dealer-assignable key icon |
| `0x08` | Decimal-point segment after character position 1 |
| `0x04` | Decimal-point segment after character position 2 |
| `0x02` | Decimal-point segment after character position 3 |
| `0x01` | Decimal-point segment after character position 4 |

This completes static control of the four P-key boxes described by the manual.
The point segments are independently addressable and are not part of the ASCII
bytes at offsets 0–7.

Offset 59 continues the decimal-point bitmap in its high nibble:

| Bit | Verified LCD meaning |
|---:|---|
| `0x80` | Decimal point after character position 5 |
| `0x40` | Decimal point after position 6 |
| `0x20` | Decimal point after position 7 |
| `0x10` | Decimal point after position 8 |
| `0x08..0x01` | No static segment when tested individually; interaction semantics unresolved |

The long initial blank interval in the synchronized trial corresponds exactly
to reference `00` followed by lower-nibble values `01,02,04,08`. These are
verified negative static results, not evidence that the bits are unused. They
may require another segment group to be enabled or may encode blinking.

A follow-up interaction held `88888888`, every mapped icon, all RSSI bars,
P1–P4, and all eight decimal points continuously on while cycling offset 59
through `f0,f1,f2,f4,f8,ff` for six seconds each. No segment blinked,
disappeared, or changed. The low nibble is therefore verified as having no
static or blink/gating effect in this display transaction and firmware. It is
retained as unresolved/reserved rather than discarded.

Absolute payload offset 60 is the blink mask for static bitmap offset 56. With
all target segments enabled, each one-bit state made exactly the corresponding
element flash:

| Offset 60 bit | Blinking element |
|---:|---|
| `0x80` | RSSI antenna/base |
| `0x40` | RSSI bar 1 |
| `0x20` | RSSI bar 2 |
| `0x10` | RSSI bar 3 |
| `0x08` | LOW |
| `0x04` | Shift |
| `0x02` | Audible speaker |
| `0x01` | Message envelope |

Absolute payload offset 61 is the exact blink mask for static bitmap offset 57.
Two synchronized runs reproduced the same one-bit sequence:

| Offset 61 bit | Blinking element |
|---:|---|
| `0x80` | Matching-signal Bell |
| `0x40` | Scanning / scan paused |
| `0x20` | Scan-target channel |
| `0x10` | Encryption |
| `0x08` | GPS/position |
| `0x04` | Talk Around |
| `0x02` | Lone Worker |
| `0x01` | Bluetooth |

Absolute offset 62 is likewise the exact blink mask for static bitmap offset
58. The observed one-bit order was `01/02/04/08` flashing decimal points after
positions 4/3/2/1, followed by `10/20/40/80` flashing P4/P3/P2/P1.

Absolute offset 63 completes the pattern. Its high nibble `10/20/40/80` flashes
the decimal points after positions 8/7/6/5, matching offset 59 exactly. Its low
nibble `01/02/04/08` produced no visible change with every mapped element on,
mirroring the unresolved/reserved low nibble of offset 59.

All four static/blink pairs are therefore verified: `56↔60`, `57↔61`,
`58↔62`, and `59↔63`.

Absolute offset 64 controls LCD-wide visual modes. With `88888888`, every
mapped static element enabled, and all other control-tail bytes zero, the
one-bit states produced:

| Offset 64 | Verified visual result |
|---:|---|
| `00` | Normal composed all-visible display |
| `01` | Full character-segment pattern |
| `02` | Distinct lower-segment/icon pattern |
| `04` | Distinct U-segment/icon pattern |
| `08` | Blank LCD |
| `10` | Blank LCD |
| `20` | Blank LCD |
| `40` | Blank LCD |
| `80` | Blank LCD |

These labels describe synchronized photographs rather than asserting the
firmware's internal purpose. Combination values remain untested and raw values
are preserved.

Absolute offset 65 produced no visible LCD segment, icon, blink, blanking,
backlight, or LED change for reference `00` or any one-bit value `01` through
`80` under the same all-visible condition. This is a bounded negative result,
not evidence that the byte is unused; combinations and nonvisual effects remain
unresolved.

Absolute offset 66 likewise produced no visible LCD, backlight, or LED change
for reference `00` or any one-bit value under the all-visible condition. It is
retained raw, with the same bounded-negative qualification as offset 65.

Absolute offset 67, the final display-payload byte, also produced no visible
LCD, backlight, or LED change for reference `00` or any one-bit value under the
all-visible condition. The complete 64–67 one-bit visual pass is now recorded;
combination and nonvisual semantics remain open.

An observed-value differential then separated the keypad-associated region.
With fixed `ABCDEFGH`, offsets 8–27 filled with the captured `0x20` bytes caused
no visible change by themselves. Adding offset 32=`0x80` made character 5 (`E`)
blink four times during its four-second hold; moving the same bit to offset 33
made character 6 (`F`) blink four times. The verified `QTH NODE` restore preceded
the normal post-disconnect black screen. This strongly predicts offsets 28–35
are one attribute byte per character position, with bit `0x80` selecting blink;
the subsequent full scan directly confirmed that prediction.

Setting `0x80` at offsets 28, 29, 30, 31, 32, 33, 34, and 35 made `A`, `B`,
`C`, `D`, `E`, `F`, `G`, and `H` blink respectively, in exact order. Offsets
28–35 are therefore eight per-position character-attribute bytes and bit
`0x80` is the character blink attribute.

A one-bit scan of the position-5 attribute byte (offset 32) then tested
`00,01,02,04,08,10,20,40,80`. Values through `40` left `E` unchanged; only
`80` blinked it. Thus all lower seven bits have a verified negative visual
result at one representative position. They remain raw because combinations,
other positions, and nonvisual behavior have not been exhausted.

| Offset 56 value | RSSI segments |
|---:|---|
| `80` | none |
| `90` | bar 3 |
| `a0` | bar 2 |
| `b0` | bars 2+3 |
| `c0` | bar 1 |
| `d0` | bars 1+3 |
| `e0` | bars 1+2 |
| `f0` | bars 1+2+3 |

The official operating guide enumerates the complete icon area as RSSI, LOW
power, Shift, audible/unmuted, received Message/Status Message, matching-signal
Bell, scan active/paused, scan-target channel, encryption, GPS, Talk Around,
Lone Worker, and Bluetooth. A separate lower row contains P1-P4 function-state
icons. Their remaining byte positions and blink encodings require controlled
one-variable trials; the manual describes meanings, not wire layout.

## Zone selection and temporary banner

Each of six Zone Up/Down transitions produced two complete display transactions:

1. Within 18.77–58.11 ms of the physical Right/Left press, the display text was
   the zone banner `ZONE 2` or `ZONE 1`.
2. Approximately 2.25 seconds later, another transaction restored the selected
   zone's channel text, `ZONE TWO` or `QTH NODE`.

Both stages use the same `02/07 -> 02/0a -> 02/08 -> mic 02/09` transaction as
an ordinary channel change. This establishes that display-buffer offsets 0–7
are general primary display text, not exclusively channel text. The parser and
Wireshark field are therefore named `display_text` / `ipcommandmic.display_text`.

## Volume state and temporary display

The existing automated F2/F3 capture contains three Volume Up presses followed
by three Volume Down presses. The primary display text and decoded levels were:

```text
VOL 1 -> VOL 2 -> VOL 3 -> VOL 4 -> VOL 3 -> VOL 2 -> VOL 1
```

The volume display transaction began 9.64–61.88 ms after the physical key press.
For the five trials with enough trailing capture, `QTH NODE` was restored
999.95–1000.09 ms after the volume buffer. The sixth restore fell just beyond
the capture boundary. Observed one-digit volume screens are exposed as
`volume_level` / `ipcommandmic.volume_level`; the supported level range remains
unknown.

## Startup messages with unknown semantics

| Direction | Start | Class/command | Length | Observed payload variants | Count |
|---|---:|---|---:|---|---:|
| Radio → mic | `f3` | `01/04` | 4 | `00000000` | 2 |
| Radio → mic | `f3` | `01/08` | 1 | `01` | 2 |
| Radio → mic | `f3` | `02/01` | 1 | `ff` | 1 |
| Radio → mic | `f3` | `02/02` | 1 | `00`, `02`, `06`, `04` | 9 |
| Radio → mic | `f3` | `02/06` | 4 | `01000000` | 2 |
| Radio → mic | `f3` | `02/07` | 1 | `02` | 3 |
| Radio → mic | `f3` | `02/08` | 2 | `0044` | 2 |
| Radio → mic | `f3` | `02/0a` | 68 | Buffers containing `N5LSN` or `QTH NODE` | 2 |
| Radio → mic | `f3` | `02/0b` | 1 | `00`=off, `01`=dim, `02`=on | startup and key-triggered control |
| Radio → mic | `f3` | `02/0d` | 3 | `000401` | 1 |
| Radio → mic | `f3` | `02/0e` | 1 | Gain N: first `N`, then `N+1`, verified for N=1 through 5 | 2 per startup |
| Radio → mic | `f3` | `05/01` | 1 | `01` | 2 |
| Radio → mic | `f3` | `05/05` | 1 | `01` | 2 |
| Radio → mic | `f3` | `06/09` | 32 | all zero | 1 |
| Radio → mic | `f3` | `06/0a` | 10 | `7c706050423b342d2620` | 1 |
| Radio → mic | `f5` | `05/03` | 1 | `01` | 1 |
| Mic → radio | `f3` | `01/00` | 1 | `00` | 2 |
| Mic → radio | `f3` | `01/01` | 1 | `7f`, `1f` | 4 |
| Mic → radio | `f3` | `01/0a` | 1 | `00` | 2 |
| Mic → radio | `f3` | `02/09` | 1 | `01` | 2 |
| Mic → radio | `f3` | `05/02` | 26 | Includes `Icom Inc` and mic MAC `0090c7124359` | 2 |
| Mic → radio | `f3` | `05/06` | 1 | `00` | 2 |
| Mic → radio | `f5` | `05/04` | 1 | `01` | 1 |

Two additional valid-CRC special messages are:

```text
mic -> radio  f5 41 71 ee 05 03 01 18 97 fd
radio -> mic  f5 41 71 ee 05 04 01 28 95 fd
```

### Mic-gain-related startup transaction

A one-variable codeplug differential changed Mic Gain from 3 to 4. Across the
22 radio-to-mic messages from identity through the first heartbeat, only the
two consecutive `02/0e` payloads changed:

| Programmed Mic Gain | First `02/0e` | Second `02/0e` |
|---:|---:|---:|
| 1 | `01` | `02` |
| 2 | `02` | `03` |
| 3 | `03` | `04` |
| 4 | `04` | `05` |
| 5 | `05` | `06` |

Across five one-variable codeplugs, the first value equals programmed Mic Gain
and the immediately following value equals gain plus one. The radio supplies
the transaction to the CommandMic during startup. The parser and Wireshark
dissector expose these messages as `mic_gain` with numeric field
`mic_gain_value` / `ipcommandmic.mic_gain.value`. Transaction order is required to
distinguish the first and second stages because isolated values overlap.

Mic-to-radio RTP proves that the resulting gain is applied in the CommandMic
before audio reaches the radio. Gains 1-4 are approximately 2 dB apart for a
stationary low source. Gain 5 adds approximately 2 dB for strong tones but
introduces an expander/noise-gate-like knee: roughly 13 dB suppression below a
Gain 4 reference level of -61 dBFS, transitioning between about -61 and -56
dBFS, and returning to near-normal gain by about -52 dBFS.

Isolated one-field mutation separates the two stages. With the second value
held at `05`, first-value `04 -> 05` increased a fixed low tone by 2.335 dB.
With the first value held at `05`, second-value `05 -> 06` reduced the same tone
by 11.736 dB. A `04,06` control remained suppressed and was only 0.521 dB above
`05,06`. Therefore the first frame controls an approximately 2 dB gain stage,
while the second frame controls or strongly dominates the low-level
suppression state. The exact internal parameter represented by the second value
remains unknown; it should not yet be named as a specific DSP threshold or mode.

The next differential experiments should change one displayed character, key
state, encoder detent, or configured value and correlate only the affected
class/command payloads.
