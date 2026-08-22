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
- [x] Public `v1.0.0rc2` version metadata and release notes explicitly preserve
  the remaining physical limitations. The GitHub prerelease tag resolves to
  commit `33fe1c333315217d2a77e821bc968776c5aa8d7f`.
- [x] The `1.0.0rc3` candidate physically reproduces real-radio soft-off,
  heartbeat-only standby and wake, including both `f5/05/03` variants; standby
  blanks the virtual mic and disables every control except Power.
- [x] Embedded primary-character decimal points and the real `BATT 13.7V`
  display decode are regression-tested; uppercase `B` and `V` appearances are
  operator-verified against the physical CommandMic.
- [x] The physical CommandMic/Lab alpha.32 matrix passes stable connection,
  live gain 1–5, display/blink/dot restoration, fresh spectrum and absolute
  meters, WAV recording, Parrot capture/replay, volume 0–32 with startup 22,
  bounded speaker-file playback/stop, backlight and status-LED-off behavior.

## Hardware-free release blockers

None.

## Physical release blockers

- [x] Complete the bounded real-radio/software-CommandMic functional matrix for
  all 23 ordinary keys, display/indicators, receive audio, live transmit audio,
  PTT, Power off/standby/wake, and acceptance of the public synthetic locally
  administered identity.
- [ ] Pass ten restart/reconnect/PoE cycles for each physical endpoint role.
- [ ] Pass a 30-minute idle/active soak for each physical endpoint role.
- [ ] Record synchronized median, p95 and maximum latency and verify that no
  fault path produces stale audio, post-stop RTP or stuck PTT.

## Publication steps

- [x] Configure the public Git remote and push `main`.
- [x] Confirm hosted CI on both the release pull request and merged `main`.
- [x] Publish the CI-built `1.0.0rc2` wheel and source archive as a GitHub
  prerelease with the exact remaining physical limitations and SHA-256 manifest.
- [x] Download the public wheel, install it without the source tree, and verify
  that it imports from site-packages as version `1.0.0rc2`.
- [ ] Publish to TestPyPI/PyPI and verify an index-based clean install. The
  GitHub prerelease is intentionally not a package-index publication.
- [ ] Re-run the applicable physical gates from the exact release-candidate
  artifacts and retain sanitized results.
- [x] Publish the verified `1.0.0rc3` wheel/source archives and repeat the clean
  installed-artifact smoke from the downloaded release assets.
- [ ] Tag and publish `1.0.0` only when every v1 gate is complete.

## Published release-candidate artifacts

- Release: <https://github.com/Mason10198/ip-commandmic/releases/tag/v1.0.0rc2>
- Wheel: `ip_commandmic-1.0.0rc2-py3-none-any.whl`, SHA-256
  `28e682b95298b2969f8d53069fe2b91fb04d038a4de070d7bf4671b0fb62e41e`
- Source: `ip_commandmic-1.0.0rc2.tar.gz`, SHA-256
  `be986a0a59a042e04e47abb036b481ace57cb9a63b5b2bea84e59d3c17cc121f`

The latest published candidate is:

- Release: <https://github.com/Mason10198/ip-commandmic/releases/tag/v1.0.0rc3>
- Accepted commit: `36104cc032059b7eba3779fdd1a241f4d8a6e489`
- Wheel: `ip_commandmic-1.0.0rc3-py3-none-any.whl`, SHA-256
  `e8441c08589c1b0ffbf133b5b75f5308e44ce5eedd32eeba9412166d0588d1ae`
- Source: `ip_commandmic-1.0.0rc3.tar.gz`, SHA-256
  `1e396f1d3b99e7ed47a2a5664cfbeb6807c6ba631ade702c505b9df1ccb89173`
- The public wheel was downloaded, hash-verified and imported as
  `ip_commandmic.__version__ == "1.0.0rc3"` from a clean environment.

The rc2 tag is lightweight; rc3 uses an annotated but unsigned tag because the
release environment had no configured signing key or GPG executable. Final
`1.0.0` should use a maintainer-controlled signed tag when signing
infrastructure is available.
