# Repository instructions

## Purpose

`ip-commandmic` is the protocol specification and Python reference library for
both sides of the Icom F5330D/F6330D Ethernet CommandMic link. Keep application
policy and user-interface behavior out of the protocol core.

## Read before changing behavior

- `README.md` — project purpose and entry points.
- `docs/README.md` — documentation map.
- `docs/PROTOCOL.md` — normative wire specification and evidence ledger.
- `docs/MESSAGE_CATALOG.md` — observed message and display mappings.
- `docs/CONTROLS_API.md` — public API.
- `docs/PROJECT_STATUS.md` and `docs/FEATURE_MATRIX.md` — implemented and open work.
- `docs/V1_SCOPE.md` — stable 1.x compatibility contract.

## Ownership boundaries

- Wire framing, messages, endpoint sessions, device models and RTP belong here.
- Gateway orchestration, browser transport and general UI belong in
  `ip-commandmic-gateway`.
- Desktop and Lab contain reference-client presentation and packaging only.
- Do not copy protocol constants or captured frames into application code.

## Protocol evidence

- Distinguish verified observations, inference and unknown behavior.
- Preserve unknown bytes losslessly; never assign semantics from a single
  unexplained capture or software-only loopback.
- A new mapping should update the specification, message catalogue, Python
  implementation, sanitized fixture, regression test and Wireshark dissector
  when applicable.
- Keep the concise status page and detailed feature matrix synchronized.

## Safety and privacy

- Do not operate physical hardware unless the task explicitly places it in scope.
- Disconnect the endpoint being replaced. Real-radio PTT requires explicit
  authorization, TX arming and suitable RF containment.
- Do not fuzz operational hardware or enable Emergency, destructive, cloning or
  firmware-sensitive behavior without a dedicated approved test plan.
- Never commit raw captures, codeplugs, voice, credentials, serial numbers,
  identifying MAC addresses, private frequencies or proprietary Icom material.

## Development and verification

Use Python 3.11 or newer and the `src/` layout:

```bash
python -m pip install -e ".[audio,dev]"
python -m pytest -q
git diff --check
```

For packaging changes also build and inspect both distributions:

```bash
python -m build --wheel --sdist
```

Do not change the package version, publish a release, or weaken a safety gate
unless the task explicitly requests it. Keep changes focused and remove
generated artifacts, speculative prose and temporary investigation notes before
committing.
