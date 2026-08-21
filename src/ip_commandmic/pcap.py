from __future__ import annotations

import csv
import io
import subprocess
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import Direction, Message
from .protocol import parse_stream
from .tooling import find_tool


@dataclass(frozen=True, slots=True)
class TcpSegment:
    stream: int
    timestamp: float
    source_ip: str
    destination_ip: str
    source_port: int
    destination_port: int
    sequence: int
    payload: bytes

    @property
    def direction(self) -> Direction:
        if self.source_ip == "192.168.0.1":
            return Direction.RADIO_TO_MIC
        if self.source_ip == "192.168.0.2":
            return Direction.MIC_TO_RADIO
        return Direction.UNKNOWN

    def direction_for(self, radio_ip: str, mic_ip: str) -> Direction:
        if self.source_ip == radio_ip:
            return Direction.RADIO_TO_MIC
        if self.source_ip == mic_ip:
            return Direction.MIC_TO_RADIO
        return Direction.UNKNOWN


@dataclass(frozen=True, slots=True)
class UdpDatagram:
    timestamp: float
    source_ip: str
    destination_ip: str
    source_port: int
    destination_port: int
    payload: bytes

    def direction_for(self, radio_ip: str, mic_ip: str) -> Direction:
        if self.source_ip == radio_ip:
            return Direction.RADIO_TO_MIC
        if self.source_ip == mic_ip:
            return Direction.MIC_TO_RADIO
        return Direction.UNKNOWN

    def to_dict(self, radio_ip: str, mic_ip: str) -> dict[str, object]:
        rtp = parse_rtp(self.payload)
        return {
            "timestamp": self.timestamp,
            "direction": self.direction_for(radio_ip, mic_ip).value,
            "source_ip": self.source_ip,
            "destination_ip": self.destination_ip,
            "source_port": self.source_port,
            "destination_port": self.destination_port,
            "length": len(self.payload),
            "kind": "rtp" if rtp else "unknown",
            "prefix_hex": self.payload[:2].hex(),
            "rtp_version": rtp.version if rtp else None,
            "rtp_marker": rtp.marker if rtp else None,
            "rtp_payload_type": rtp.payload_type if rtp else None,
            "rtp_sequence": rtp.sequence if rtp else None,
            "rtp_timestamp": rtp.timestamp if rtp else None,
            "rtp_ssrc_hex": f"{rtp.ssrc:08x}" if rtp else None,
            "rtp_header_length": rtp.header_length if rtp else None,
            "rtp_payload_length": len(rtp.payload) if rtp else None,
            "rtp_payload_all_zero": not any(rtp.payload) if rtp else None,
            "raw_hex": self.payload.hex(),
        }


@dataclass(frozen=True, slots=True)
class RtpPacket:
    version: int
    marker: bool
    payload_type: int
    sequence: int
    timestamp: int
    ssrc: int
    header_length: int
    payload: bytes


def parse_rtp(data: bytes) -> RtpPacket | None:
    if len(data) < 12 or data[0] >> 6 != 2:
        return None
    padding = bool(data[0] & 0x20)
    extension = bool(data[0] & 0x10)
    csrc_count = data[0] & 0x0F
    header_length = 12 + csrc_count * 4
    if len(data) < header_length:
        return None
    if extension:
        if len(data) < header_length + 4:
            return None
        extension_words = int.from_bytes(data[header_length + 2 : header_length + 4], "big")
        header_length += 4 + extension_words * 4
        if len(data) < header_length:
            return None
    payload_end = len(data)
    if padding:
        padding_length = data[-1]
        if padding_length == 0 or padding_length > len(data) - header_length:
            return None
        payload_end -= padding_length
    return RtpPacket(
        version=2,
        marker=bool(data[1] & 0x80),
        payload_type=data[1] & 0x7F,
        sequence=int.from_bytes(data[2:4], "big"),
        timestamp=int.from_bytes(data[4:8], "big"),
        ssrc=int.from_bytes(data[8:12], "big"),
        header_length=header_length,
        payload=data[header_length:payload_end],
    )

@dataclass(frozen=True, slots=True)
class DecodedMessage:
    stream: int
    direction: Direction
    timestamp: float
    stream_offset: int
    message: Message

    def to_dict(self) -> dict[str, object]:
        return {
            "tcp_stream": self.stream,
            "timestamp": self.timestamp,
            "stream_offset": self.stream_offset,
            **self.message.to_dict(),
        }


def read_tcp_segments(capture: str | Path, port: int = 52001) -> list[TcpSegment]:
    tshark = find_tool("tshark")
    command = [
        tshark,
        "-r",
        str(capture),
        "-Y",
        f"tcp.port == {port} && tcp.len > 0",
        "-T",
        "fields",
        "-E",
        "separator=/t",
        "-E",
        "quote=d",
        "-e",
        "tcp.stream",
        "-e",
        "frame.time_epoch",
        "-e",
        "ip.src",
        "-e",
        "ip.dst",
        "-e",
        "tcp.srcport",
        "-e",
        "tcp.dstport",
        "-e",
        "tcp.seq_raw",
        "-e",
        "tcp.payload",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    rows = csv.reader(io.StringIO(completed.stdout), delimiter="\t", quotechar='"')
    segments: list[TcpSegment] = []
    for row in rows:
        if len(row) != 8 or not row[7]:
            continue
        segments.append(
            TcpSegment(
                stream=int(row[0]),
                timestamp=float(row[1]),
                source_ip=row[2],
                destination_ip=row[3],
                source_port=int(row[4]),
                destination_port=int(row[5]),
                sequence=int(row[6]),
                payload=bytes.fromhex(row[7].replace(":", "")),
            )
        )
    return segments


def read_udp_datagrams(capture: str | Path, port: int = 50000) -> list[UdpDatagram]:
    tshark = find_tool("tshark")
    command = [
        tshark,
        "-r",
        str(capture),
        "-Y",
        f"udp.port == {port} && udp.length > 8",
        "-T",
        "fields",
        "-E",
        "separator=/t",
        "-E",
        "quote=d",
        "-e",
        "frame.time_epoch",
        "-e",
        "ip.src",
        "-e",
        "ip.dst",
        "-e",
        "udp.srcport",
        "-e",
        "udp.dstport",
        "-e",
        "udp.payload",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    rows = csv.reader(io.StringIO(completed.stdout), delimiter="\t", quotechar='"')
    datagrams: list[UdpDatagram] = []
    for row in rows:
        if len(row) != 6 or not row[5]:
            continue
        datagrams.append(
            UdpDatagram(
                timestamp=float(row[0]),
                source_ip=row[1],
                destination_ip=row[2],
                source_port=int(row[3]),
                destination_port=int(row[4]),
                payload=bytes.fromhex(row[5].replace(":", "")),
            )
        )
    return datagrams


def _reassemble_direction(
    segments: Iterable[TcpSegment],
) -> tuple[bytes, list[tuple[int, float]], list[str]]:
    ordered = sorted(segments, key=lambda item: (item.sequence, item.timestamp))
    if not ordered:
        return b"", [], []
    output = bytearray()
    time_markers: list[tuple[int, float]] = []
    warnings: list[str] = []
    expected = ordered[0].sequence
    for segment in ordered:
        start = segment.sequence
        end = start + len(segment.payload)
        if end <= expected:
            continue
        if start > expected:
            warnings.append(f"TCP gap: expected sequence {expected}, got {start}")
            # Do not synthesize bytes. Start a visible unframed region instead.
            time_markers.append((len(output), segment.timestamp))
            output.extend(b"\x00" * (start - expected))
            expected = start
        overlap = max(0, expected - start)
        time_markers.append((len(output), segment.timestamp))
        output.extend(segment.payload[overlap:])
        expected = end
    return bytes(output), time_markers, warnings


def _timestamp_at_offset(markers: list[tuple[int, float]], offset: int) -> float:
    if not markers:
        return 0.0
    offsets = [item[0] for item in markers]
    index = max(0, bisect_right(offsets, offset) - 1)
    return markers[index][1]


def decode_capture(
    capture: str | Path,
    port: int = 52001,
    radio_ip: str = "192.168.0.1",
    mic_ip: str = "192.168.0.2",
) -> tuple[list[DecodedMessage], list[str]]:
    grouped: dict[tuple[int, Direction], list[TcpSegment]] = defaultdict(list)
    for segment in read_tcp_segments(capture, port):
        grouped[(segment.stream, segment.direction_for(radio_ip, mic_ip))].append(segment)

    decoded: list[DecodedMessage] = []
    warnings: list[str] = []
    for (stream, direction), segments in grouped.items():
        stream_data, time_markers, stream_warnings = _reassemble_direction(segments)
        warnings.extend(f"stream {stream} {direction.value}: {item}" for item in stream_warnings)
        messages, remainder = parse_stream(stream_data, direction)
        offset = 0
        for message in messages:
            decoded.append(
                DecodedMessage(
                    stream,
                    direction,
                    _timestamp_at_offset(time_markers, offset),
                    offset,
                    message,
                )
            )
            offset += len(message.raw)
        if remainder:
            warnings.append(
                f"stream {stream} {direction.value}: {len(remainder)} incomplete trailing bytes"
            )
            decoded.append(
                DecodedMessage(
                    stream,
                    direction,
                    _timestamp_at_offset(time_markers, offset),
                    offset,
                    Message(
                        raw=remainder,
                        direction=direction,
                        framing_valid=False,
                        evidence="incomplete trailing TCP stream data",
                    ),
                )
            )
    decoded.sort(key=lambda item: (item.timestamp, item.stream, item.direction.value, item.stream_offset))
    return decoded, warnings
