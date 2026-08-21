# Contributing

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
