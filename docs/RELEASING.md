# Release procedure

This procedure is intentionally conservative because a package release turns
research interfaces into a compatibility commitment. `V1_SCOPE.md` defines the
contract and `RELEASE_READINESS.md` is the live gate ledger.

## Prepare a candidate

1. Finish every applicable readiness gate. A release candidate may retain a
   finite physical limitation only when it is listed prominently in its notes;
   final `1.0.0` may not.
2. Update `CHANGELOG.md`, `pyproject.toml`, `ip_commandmic.__version__` and the
   version assertion in `tests/test_public_api.py` together.
3. Run the complete source suite:

   ```powershell
   python -m pytest -q
   ```

4. Build a clean wheel and source distribution in an otherwise empty `dist`
   directory:

   ```powershell
   python -m build
   python -m twine check dist/*
   python scripts/verify_release.py --dist dist --test-artifacts
   ```

5. Confirm the Python 3.11–3.14 and Windows/macOS/Linux hosted CI matrix. Run
   the extended conformance workflow manually and retain its `report.json` plus
   both JSONL audits.
6. Re-run the applicable physical acceptance matrices from the exact candidate
   commit and record sanitized results in the release notes.

## Publish

1. Review `git status`, `git diff --check`, the archive member report and the
   public-data audit. Generated captures, WAV files and JSONL audits never enter
   the repository or distribution.
2. Publish the candidate to TestPyPI first and install it by version into a new
   environment. Repeat the typed-composer smoke test and baseline conformance.
3. Create the immutable Git tag only from the accepted commit. The tag, GitHub
   release, wheel and sdist must all use the same version and SHA-256 values.
4. Publish those exact files to PyPI. Do not rebuild between acceptance and
   upload.
5. Verify a normal index install, documentation links and release hashes, then
   mark the matching readiness publication items complete.

Repository remote creation, package-index credentials, branch protection and
the final upload are maintainer actions. Local verification never implies that
an artifact has been published.
