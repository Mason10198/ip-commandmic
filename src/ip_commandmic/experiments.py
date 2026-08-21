from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path


EVENT_FIELDS = (
    "experiment_id",
    "event_time_utc",
    "event_monotonic_seconds",
    "event",
    "control",
    "value",
    "notes",
)


def append_event(
    path: str | Path,
    *,
    experiment_id: str,
    event: str,
    control: str = "",
    value: str = "",
    notes: str = "",
) -> dict[str, str]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "experiment_id": experiment_id,
        "event_time_utc": datetime.now(timezone.utc).isoformat(),
        "event_monotonic_seconds": f"{time.monotonic():.9f}",
        "event": event,
        "control": control,
        "value": value,
        "notes": notes,
    }
    needs_header = not output.exists() or output.stat().st_size == 0
    with output.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(record)
    return record
