# Version 1 release readiness

This is the current execution checklist for the scoped contract in
`V1_SCOPE.md`. A checked implementation item is not a substitute for its
physical acceptance gate.

## Complete

- [x] Public repository audit excludes raw captures, codeplugs, recorded voice,
  private device/configuration identifiers, proprietary software, credentials
  and generated artifacts; author attribution remains intentional.
- [x] Intentional clean initial commit exists on `main`.
- [x] Stable and advanced top-level exports are machine-readable through
  `V1_STABLE_EXPORTS` and `V1_ADVANCED_EXPORTS`.
- [x] Stable endpoint method presence and the v1 document boundary are covered
  by regression tests.
- [x] Wheel and source distribution build successfully.
- [x] The wheel imports and exercises typed protocol composition in isolated
  Python 3.11, 3.12, 3.13 and 3.14 environments.
- [x] The distribution includes `py.typed` and declares the four supported
  Python minor versions.
- [x] The normal public-wrapper conformance baseline has no failed or
  `not_covered` result.
- [x] Public CI definitions cover Python 3.11–3.14, Windows/macOS/Linux,
  distribution inspection, installed-artifact tests and scheduled extended
  conformance. The first hosted run remains a publication step.
- [x] True child-process replacement and routed TCP/UDP interruption recover
  fail-closed through the public endpoints.
- [x] All 23 ordinary controls, Power, every LED/backlight state, microphone
  gain 1–5 and a synthetic display corpus run through the public wrappers.
- [x] Twine metadata validation and the complete suite pass from clean wheel
  and sdist installations with the source tree excluded.
- [x] Every stable typed composer is cross-referenced by the normative
  specification, message catalogue, synthetic fixture and Wireshark fields.
- [x] The retained 30-minute-per-direction hardware-free bidirectional soak
  passes all 19 checks: 90,000 continuous radio RTP packets, 90,012 continuous
  microphone RTP packets, zero radio playout concealments, ten fresh-object
  restart cycles, routed interruption and abrupt subprocess replacement.
- [x] Local `1.0.0rc1` version metadata and release notes explicitly preserve
  the remaining physical limitations.

## Hardware-free release blockers

None.

## Physical release blockers

- [ ] Complete the physical-CommandMic/Lab matrix, including stable-session
  microphone gain, display, recording, Parrot, volume and speaker playback.
- [ ] Complete the real-radio/software-CommandMic matrix for every supported
  key, display/indicator state, receive audio, live transmit audio and PTT;
  explicitly confirm acceptance of the public synthetic locally administered
  identity rather than the private laboratory device address.
- [ ] Pass ten restart/reconnect/PoE cycles for each physical endpoint role.
- [ ] Pass a 30-minute idle/active soak for each physical endpoint role.
- [ ] Record synchronized median, p95 and maximum latency and verify that no
  fault path produces stale audio, post-stop RTP or stuck PTT.

## Publication steps

- [ ] Configure the public Git remote and push `main`.
- [ ] Confirm the first hosted CI and scheduled/manual extended-conformance run,
  then configure branch/release policy.
- [ ] Publish the locally prepared `1.0.0rc1` artifacts with the exact
  remaining physical limitations.
- [ ] Re-run all release gates from the release-candidate artifacts.
- [ ] Tag and publish `1.0.0` only when every v1 gate is complete.
