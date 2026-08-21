from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .tooling import find_tool

DEFAULT_CAPTURE_FILTER = "host 192.168.0.1 or host 192.168.0.2"


def safe_label(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    if not cleaned:
        raise ValueError("capture label must contain a letter or number")
    return cleaned.lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_experiment(
    *,
    interface: str,
    duration: int,
    label: str,
    output_directory: str | Path = "captures/raw",
    capture_filter: str = DEFAULT_CAPTURE_FILTER,
    notes: str = "",
) -> tuple[Path, Path]:
    if duration < 1:
        raise ValueError("duration must be positive")
    dumpcap = find_tool("dumpcap")
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    stem = f"{started.strftime('%Y%m%dT%H%M%SZ')}_{safe_label(label)}"
    capture_path = output_directory / f"{stem}.pcapng"
    metadata_path = output_directory / f"{stem}.json"
    command = [
        dumpcap,
        "-i",
        interface,
        "-a",
        f"duration:{duration}",
        "-s",
        "0",
        "-f",
        capture_filter,
        "-w",
        str(capture_path),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    finished = datetime.now(timezone.utc)
    dumpcap_lines = [line for line in completed.stderr.splitlines() if line.strip()]
    metadata = {
        "schema_version": 1,
        "label": safe_label(label),
        "notes": notes,
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "requested_duration_seconds": duration,
        "interface": interface,
        "capture_filter": capture_filter,
        "capture_file": capture_path.name,
        "capture_sha256": sha256_file(capture_path),
        "capture_size_bytes": capture_path.stat().st_size,
        "host": platform.node(),
        "platform": platform.platform(),
        # dumpcap writes a progress line for nearly every packet. Retain only the
        # final summary so metadata stays small while preserving drop diagnostics.
        "dumpcap_summary": dumpcap_lines[-5:],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return capture_path, metadata_path
