from __future__ import annotations

import shutil
from pathlib import Path


WINDOWS_WIRESHARK_DIR = Path(r"C:\Program Files\Wireshark")


def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    candidate = WINDOWS_WIRESHARK_DIR / f"{name}.exe"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(
        f"{name!r} was not found on PATH or in {WINDOWS_WIRESHARK_DIR}"
    )
