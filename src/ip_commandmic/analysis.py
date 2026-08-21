from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import zip_longest
from statistics import fmean

from .models import Message


@dataclass(frozen=True, slots=True)
class ByteDifference:
    offset: int
    left: int | None
    right: int | None
    xor: int | None


def byte_differences(left: bytes, right: bytes) -> list[ByteDifference]:
    differences: list[ByteDifference] = []
    for offset, (a, b) in enumerate(zip_longest(left, right)):
        if a != b:
            differences.append(
                ByteDifference(offset, a, b, a ^ b if a is not None and b is not None else None)
            )
    return differences


def message_histogram(messages: list[Message]) -> Counter[tuple[str, str]]:
    return Counter((message.direction.value, message.raw.hex()) for message in messages)


def render_diff(left: bytes, right: bytes) -> str:
    lines = ["offset  left right xor"]
    for difference in byte_differences(left, right):
        def value(item: int | None) -> str:
            return "--" if item is None else f"{item:02x}"
        lines.append(
            f"0x{difference.offset:04x}  {value(difference.left)}   "
            f"{value(difference.right)}    {value(difference.xor)}"
        )
    return "\n".join(lines)


def distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": min(values),
        "mean": fmean(values),
        "max": max(values),
    }
