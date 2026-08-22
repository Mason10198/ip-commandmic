# Implementation status

This page is the short capability map for `ip-commandmic 1.0`. The detailed
coverage ledger is [FEATURE_MATRIX.md](FEATURE_MATRIX.md).

| Area | Status | Notes |
|---|---|---|
| TCP framing, stuffing and CRC | Implemented | Lossless parsing and encoding; arbitrary TCP fragmentation/coalescing supported |
| Session startup and heartbeat | Implemented | Both endpoint roles; known cold, warm and soft-power paths |
| Reconnect and safe shutdown | Implemented | Fail-closed control/audio state; bounded physical restart tests passed |
| Ordinary controls | Implemented | 23 mapped keys; resulting radio function depends on its codeplug |
| PTT | Implemented, safety-gated | Explicit arming and fail-closed release |
| Power | Implemented | Soft-off, heartbeat-only standby and wake tested in both directions |
| Emergency | Wire code known, gated | Emergency-mode semantics are not implemented |
| Primary LCD | Implemented | Lossless 68-byte buffer, text, dots, blink attributes and mapped indicators |
| Extended glyphs and auxiliary LCD fields | Partial | Unknown values are preserved; mapping remains open |
| LED and backlight | Implemented | Verified status colors and off/dim/on states |
| Audio in both directions | Implemented | RTP/PT125; 8 kHz mono signed 16-bit big-endian PCM |
| Microphone gain | Implemented | Values 1–5; real-time changes physically verified |
| Speaker volume | Implemented with policy caveat | Range 0–32 verified; intermediate software curve is not an acoustic calibration |
| Scan, call and set-mode semantics | Not implemented | Generic key/display transport may still carry radio-managed behavior |
| Hook, VOX, horn, GPS and Bluetooth | Not implemented | Controlled captures and possibly additional hardware are required |
| Multi-radio arbitration | Not implemented in core | Belongs in a gateway or integration layer |
| AllStarLink adapter | Not implemented | Public audio/control APIs are designed to support it |

“Implemented” means the behavior exists in the public API and has automated or
physical evidence appropriate to it. It does not mean every codeplug assignment
or optional accessory has been tested.
