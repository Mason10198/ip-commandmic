from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    RADIO_TO_MIC = "radio_to_mic"
    MIC_TO_RADIO = "mic_to_radio"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: "Direction | str") -> "Direction":
        if isinstance(value, cls):
            return value
        aliases = {
            "radio": cls.RADIO_TO_MIC,
            "rx": cls.RADIO_TO_MIC,
            "radio_to_mic": cls.RADIO_TO_MIC,
            "mic": cls.MIC_TO_RADIO,
            "tx": cls.MIC_TO_RADIO,
            "mic_to_radio": cls.MIC_TO_RADIO,
            "unknown": cls.UNKNOWN,
        }
        try:
            return aliases[value.lower()]
        except KeyError as exc:
            raise ValueError(f"unknown direction: {value!r}") from exc


class MessageKind(str, Enum):
    HEARTBEAT = "heartbeat"
    KEY_STATE = "key_state"
    PTT_STATE = "ptt_state"
    AUDIO_STATE = "audio_state"
    AUDIO_STATUS = "audio_status"
    POWER_STATE = "power_state"
    MIC_GAIN = "mic_gain"
    BACKLIGHT_STATE = "backlight_state"
    DISPLAY_SYNC = "display_sync"
    DISPLAY_UPDATE = "display_update"
    DISPLAY_ACK = "display_ack"
    UNKNOWN = "unknown"
    UNFRAMED = "unframed"


@dataclass(frozen=True, slots=True)
class Message:
    """One conservatively delimited application message.

    Fields whose meaning has not been demonstrated remain explicitly unknown.
    ``checksum_valid`` is therefore ``None`` until a checksum algorithm is proven.
    """

    raw: bytes
    direction: Direction = Direction.UNKNOWN
    kind: MessageKind = MessageKind.UNKNOWN
    framing_valid: bool = True
    checksum_valid: bool | None = None
    evidence: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def length(self) -> int:
        return len(self.raw)

    @property
    def body(self) -> bytes:
        payload_hex = self.metadata.get("payload_hex")
        if isinstance(payload_hex, str):
            return bytes.fromhex(payload_hex)
        if self.framing_valid and len(self.raw) >= 3:
            return self.raw[2:-1]
        return self.raw

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "kind": self.kind.value,
            "length": self.length,
            "raw_hex": self.raw.hex(),
            "body_hex": self.body.hex(),
            "framing_valid": self.framing_valid,
            "checksum_valid": self.checksum_valid,
            "evidence": self.evidence,
            **self.metadata,
        }
