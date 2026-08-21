from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


def sum8(data: bytes) -> int:
    return sum(data) & 0xFF


def xor8(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def crc16(data: bytes, *, poly: int, init: int, refin: bool = False) -> int:
    crc = init
    if refin:
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
    else:
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc & 0xFFFF


CRC16_ALGORITHMS: dict[str, Callable[[bytes], int]] = {
    "crc16_ccitt_false": lambda data: crc16(data, poly=0x1021, init=0xFFFF),
    "crc16_xmodem": lambda data: crc16(data, poly=0x1021, init=0x0000),
    "crc16_modbus": lambda data: crc16(data, poly=0xA001, init=0xFFFF, refin=True),
    "crc16_arc": lambda data: crc16(data, poly=0xA001, init=0x0000, refin=True),
}


@dataclass(frozen=True, slots=True)
class ChecksumCandidate:
    algorithm: str
    covered_slice: str
    byte_order: str
    matches: int
    total: int

    @property
    def match_ratio(self) -> float:
        return self.matches / self.total if self.total else 0.0


def rank_crc16_candidates(frames: Iterable[bytes]) -> list[ChecksumCandidate]:
    """Rank common CRC-16 hypotheses without asserting that a CRC exists.

    Tests the two bytes immediately before the 0xfd terminator, with coverage
    beginning at byte zero or after the known two-byte magic.
    """

    usable = [frame for frame in frames if len(frame) >= 5 and frame[-1] == 0xFD]
    results: list[ChecksumCandidate] = []
    for name, algorithm in CRC16_ALGORITHMS.items():
        for start, label in (
            (0, "frame_without_crc_or_terminator"),
            (1, "after_start_byte"),
            (2, "after_magic"),
        ):
            body = [frame[start:-3] for frame in usable]
            expected = [frame[-3:-1] for frame in usable]
            for byte_order in ("big", "little"):
                matches = sum(
                    algorithm(candidate).to_bytes(2, byte_order) == target
                    for candidate, target in zip(body, expected, strict=True)
                )
                results.append(
                    ChecksumCandidate(name, label, byte_order, matches, len(usable))
                )
    return sorted(results, key=lambda item: (-item.matches, item.algorithm, item.byte_order))
