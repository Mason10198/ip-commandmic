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
2. Publish a GitHub prerelease from the accepted commit using the exact CI-built
   wheel and source archive, attach a SHA-256 manifest, then download and install
   the public wheel into a new environment.
3. A TestPyPI smoke is optional when clean wheel and sdist installations have
   already passed from the exact accepted artifacts. It is not a separate
   product-acceptance gate.
4. Create the immutable Git tag from the accepted commit. The tag, GitHub
   release, wheel and sdist must all use the same version and SHA-256 values.
5. Run the native `Publish to PyPI` workflow with the accepted CI run ID. It
   rejects artifacts from any commit other than the tagged commit, downloads
   the CI-built files and publishes those exact bytes through PyPI trusted
   publishing. Do not rebuild between acceptance and upload.
6. Verify a normal index install, documentation links and release hashes, then
   mark the matching readiness publication items complete.

Repository remote creation, package-index credentials, branch protection and
the final upload are maintainer actions. Local verification never implies that
an artifact has been published.
