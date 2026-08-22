# Contributing

Contributions from people and coding agents are welcome. Keep changes small,
reviewable and tied to an issue or clearly stated objective. Generated code or
prose is held to the same requirements as human-authored work: the contributor
must understand it, verify it, remove filler and accept responsibility for it.

Protocol claims must be evidence-backed. A new mapping should update the
language-neutral specification, message catalogue, Python model/composer,
sanitized fixture, regression test and Wireshark dissector when applicable.

Create a Python 3.11 or newer virtual environment and install
`.[audio,dev]`. Before submitting a change, run `python -m pytest -q` and
`git diff --check`. Changes to a stable v1 API must update `V1_SCOPE.md` or
explain why they are backward-compatible. Distribution changes must also run
the procedure in `docs/RELEASING.md`.

Clearly distinguish verified observations, strong inferences and unresolved
hypotheses. Preserve unknown bytes losslessly. Do not submit copyrighted Icom
software or documentation, unsanitized captures, codeplugs, or recorded voice.
Tests involving real hardware must state which endpoint was disconnected and
what RF containment was used. Software-only tests must not be presented as new
physical protocol evidence.

## Where work belongs

- Protocol bytes, endpoint state machines, audio transport and device models:
  this repository.
- Browser product behavior and orchestration: `ip-commandmic-gateway`.
- Windows reference-client defects: `ip-commandmic-desktop`.
- Physical-mic diagnostics and experiments: `ip-commandmic-lab`.

Use [PROJECT_STATUS.md](docs/PROJECT_STATUS.md) to find an incomplete area and
[FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md) for its exact evidence status.

## Pull-request checklist

- Add or update tests for behavior changes.
- Update the specification and message catalogue when wire knowledge changes.
- Update the feature matrix without overstating physical verification.
- Keep unknown bytes round-trippable.
- Run `python -m pytest -q` and `git diff --check`.
- Exclude captures, codeplugs, credentials, serial numbers and recorded voice.
