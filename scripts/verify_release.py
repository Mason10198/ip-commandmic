"""Inspect release archives and optionally run tests from clean installations."""

from __future__ import annotations

import argparse
import email
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path


FORBIDDEN_SUFFIXES = {
    ".exe",
    ".icf",
    ".jsonl",
    ".key",
    ".pcap",
    ".pcapng",
    ".pem",
    ".wav",
}
SUPPORTED_PYTHONS = ("3.11", "3.12", "3.13", "3.14")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assert_archive_paths(paths: list[str], archive: Path) -> None:
    for name in paths:
        normalized = name.replace("\\", "/")
        parts = Path(normalized).parts
        if normalized.startswith("/") or ".." in parts:
            raise AssertionError(f"unsafe archive member in {archive.name}: {name}")
        if Path(normalized).suffix.lower() in FORBIDDEN_SUFFIXES:
            raise AssertionError(f"private/generated file in {archive.name}: {name}")


def _inspect_wheel(path: Path, expected_version: str) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        _assert_archive_paths(names, path)
        required = {
            "ip_commandmic/py.typed",
            "ip_commandmic/_conformance_worker.py",
        }
        missing = sorted(required.difference(names))
        if missing:
            raise AssertionError(f"wheel is missing package files: {missing}")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise AssertionError(f"wheel has {len(metadata_names)} METADATA files")
        metadata = email.message_from_bytes(archive.read(metadata_names[0]))

    if metadata["Name"] != "ip-commandmic":
        raise AssertionError(f"unexpected project name: {metadata['Name']!r}")
    if metadata["Version"] != expected_version:
        raise AssertionError(
            f"wheel version {metadata['Version']!r} != {expected_version!r}"
        )
    if metadata["Requires-Python"] != ">=3.11":
        raise AssertionError(
            f"unexpected Requires-Python: {metadata['Requires-Python']!r}"
        )
    classifiers = metadata.get_all("Classifier", [])
    for version in SUPPORTED_PYTHONS:
        classifier = f"Programming Language :: Python :: {version}"
        if classifier not in classifiers:
            raise AssertionError(f"wheel metadata is missing {classifier!r}")
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "members": len(names),
    }


def _inspect_sdist(path: Path, expected_version: str) -> dict[str, object]:
    prefix = f"ip_commandmic-{expected_version}/"
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        _assert_archive_paths(names, path)
        if any(member.issym() or member.islnk() for member in members):
            raise AssertionError("sdist must not contain symbolic or hard links")
    required = {
        prefix + "docs/V1_SCOPE.md",
        prefix + "docs/RELEASE_READINESS.md",
        prefix + "scripts/verify_release.py",
        prefix + "src/ip_commandmic/py.typed",
        prefix + "src/ip_commandmic/_conformance_worker.py",
        prefix + "tests/test_v1_contract.py",
    }
    missing = sorted(required.difference(names))
    if missing:
        raise AssertionError(f"sdist is missing release files: {missing}")
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "members": len(names),
    }


def _venv_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _test_installed_artifact(artifact: Path, repository: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ip-commandmic-release-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        bundle = root / "suite"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = _venv_python(environment)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "pytest>=8",
                f"ip-commandmic[audio] @ {artifact.resolve().as_uri()}",
            ],
            check=True,
        )
        shutil.copytree(repository / "tests", bundle / "tests")
        shutil.copytree(repository / "docs", bundle / "docs")
        shutil.copytree(repository / "wireshark", bundle / "wireshark")
        clean_environment = dict(os.environ)
        clean_environment.pop("PYTHONPATH", None)
        clean_environment.pop("PYTHONHOME", None)
        location = subprocess.run(
            [str(python), "-c", "import ip_commandmic; print(ip_commandmic.__file__)"],
            cwd=bundle,
            env=clean_environment,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if str(repository.resolve()).lower() in location.lower():
            raise AssertionError(f"test imported the source tree instead of artifact: {location}")
        subprocess.run(
            [
                str(python),
                "-m",
                "pytest",
                "tests",
                "-q",
                "--basetemp",
                str(root / "pytest-temp"),
            ],
            cwd=bundle,
            env=clean_environment,
            check=True,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--test-artifacts", action="store_true")
    args = parser.parse_args(argv)

    repository = Path(__file__).resolve().parents[1]
    project = tomllib.loads((repository / "pyproject.toml").read_text("utf-8"))
    expected_version = str(project["project"]["version"])
    distribution_name = "ip_commandmic"
    wheels = sorted(
        args.dist.resolve().glob(f"{distribution_name}-{expected_version}-*.whl")
    )
    sdists = sorted(
        args.dist.resolve().glob(f"{distribution_name}-{expected_version}.tar.gz")
    )
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(
            f"expected exactly one wheel and one sdist; found {len(wheels)} and {len(sdists)}"
        )

    report = {
        "version": expected_version,
        "wheel": _inspect_wheel(wheels[0], expected_version),
        "sdist": _inspect_sdist(sdists[0], expected_version),
        "installed_tests": bool(args.test_artifacts),
    }
    if args.test_artifacts:
        _test_installed_artifact(wheels[0], repository)
        _test_installed_artifact(sdists[0], repository)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
