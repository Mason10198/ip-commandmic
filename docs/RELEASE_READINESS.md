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
- [x] Hosted CI covers Python 3.11–3.14, Windows/macOS/Linux, distribution
  inspection, installed-artifact tests and the timing-sensitive 19-check
  loopback scenario on the Windows reference host.
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
- [x] Public `v1.0.0rc1` version metadata and release notes explicitly preserve
  the remaining physical limitations. The GitHub prerelease tag resolves to
  commit `174740c35839940389404008c6fa6fabf6fe34e4`.
- [x] The physical CommandMic/Lab alpha.32 matrix passes stable connection,
  live gain 1–5, display/blink/dot restoration, fresh spectrum and absolute
  meters, WAV recording, Parrot capture/replay, volume 0–32 with startup 22,
  bounded speaker-file playback/stop, backlight and status-LED-off behavior.

## Hardware-free release blockers

None.

## Physical release blockers

- [ ] Complete the real-radio/software-CommandMic matrix for every supported
  key, display/indicator state, receive audio, live transmit audio and PTT;
  explicitly confirm acceptance of the public synthetic locally administered
  identity rather than the private laboratory device address.
- [ ] Pass ten restart/reconnect/PoE cycles for each physical endpoint role.
- [ ] Pass a 30-minute idle/active soak for each physical endpoint role.
- [ ] Record synchronized median, p95 and maximum latency and verify that no
  fault path produces stale audio, post-stop RTP or stuck PTT.

## Publication steps

- [x] Configure the public Git remote and push `main`.
- [x] Confirm hosted CI on both the release pull request and merged `main`.
- [x] Publish the CI-built `1.0.0rc1` wheel and source archive as a GitHub
  prerelease with the exact remaining physical limitations and SHA-256 manifest.
- [x] Download the public wheel, install it without the source tree, and verify
  that it imports from site-packages as version `1.0.0rc1`.
- [ ] Publish to TestPyPI/PyPI and verify an index-based clean install. The
  GitHub prerelease is intentionally not a package-index publication.
- [ ] Re-run the applicable physical gates from the exact release-candidate
  artifacts and retain sanitized results.
- [ ] Tag and publish `1.0.0` only when every v1 gate is complete.

## Published release-candidate artifacts

- Release: <https://github.com/Mason10198/ip-commandmic/releases/tag/v1.0.0rc1>
- Wheel: `ip_commandmic-1.0.0rc1-py3-none-any.whl`, SHA-256
  `6514be5b04c952c367897386667e301464436a3edab31bd4036b7c97a11da45c`
- Source: `ip_commandmic-1.0.0rc1.tar.gz`, SHA-256
  `8e6bdd2382d0287d6cae1a328e16c55aba5005c877e1511b6022c1f809725fac`

The tag is lightweight because the release environment had no configured
signing key or GPG executable. Final `1.0.0` should use a maintainer-controlled
signed tag when signing infrastructure is available.
