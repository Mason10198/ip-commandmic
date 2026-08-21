from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from .models import Message, MessageKind

DISPLAY_BUFFER_SIZE = 68
PRIMARY_TEXT_SIZE = 8
AUXILIARY_REGION_OFFSET = 8
AUXILIARY_REGION_SIZE = 20
CHARACTER_ATTRIBUTE_OFFSET = 28
CHARACTER_ATTRIBUTE_SIZE = 8
INDICATOR_STATE_OFFSET = 56
SECONDARY_INDICATOR_STATE_OFFSET = 57
KEY_AND_POINT_STATE_OFFSET = 58
SECONDARY_POINT_STATE_OFFSET = 59
PRIMARY_BLINK_MASK_OFFSET = 60
SECONDARY_BLINK_MASK_OFFSET = 61
KEY_AND_POINT_BLINK_MASK_OFFSET = 62
SECONDARY_POINT_BLINK_MASK_OFFSET = 63
DISPLAY_CONTROL_64_OFFSET = 64
DISPLAY_CONTROL_65_OFFSET = 65
DISPLAY_CONTROL_66_OFFSET = 66
DISPLAY_CONTROL_67_OFFSET = 67

# Physical left-to-right decimal-point paths in the supplied CommandMic LCD
# vector. The SVG's source path IDs are not sequential in physical order.
VERIFIED_DISPLAY_SVG_DECIMAL_POINT_PATHS = (382, 384, 383, 386, 385, 387, 388, 389)

# Capture-derived tail used by the verified software-radio display composer.
# Offset 56 is fully mapped by one-bit and RSSI-ladder trials.
VERIFIED_BASELINE_DISPLAY_TAIL = bytes(48) + b"\x88" + bytes(11)

# Exact whole-byte observations retained as regression anchors; all eight bits
# are also independently composable.
VERIFIED_OFFSET56_INDICATORS: dict[int, tuple[str, ...]] = {
    0x00: (),
    0x01: ("message",),
    0x04: ("shift",),
    0x05: ("shift", "message"),
    0x08: ("low_power",),
    0x80: ("rssi",),
    0x88: ("low_power", "rssi"),
    0x8A: ("low_power", "audible", "rssi"),
    0x90: ("rssi",),
    0xA0: ("rssi",),
    0xB0: ("rssi",),
    0xC0: ("rssi",),
    0xD0: ("rssi",),
    0xE0: ("rssi",),
    0xF0: ("rssi",),
    0xFA: ("low_power", "audible", "rssi"),
}

VERIFIED_OFFSET57_INDICATORS: dict[int, str] = {
    0x80: "bell",
    0x40: "scan",
    0x20: "scan_target",
    0x10: "encryption",
    0x08: "gps",
    0x04: "talk_around",
    0x02: "lone_worker",
    0x01: "bluetooth",
}

VERIFIED_OFFSET58_KEY_ICONS: dict[int, str] = {
    0x80: "dealer_p1",
    0x40: "dealer_p2",
    0x20: "dealer_p3",
    0x10: "dealer_p4",
}

VERIFIED_OFFSET58_DECIMAL_POINTS: dict[int, int] = {
    0x08: 1,
    0x04: 2,
    0x02: 3,
    0x01: 4,
}

VERIFIED_OFFSET59_DECIMAL_POINTS: dict[int, int] = {
    0x80: 5,
    0x40: 6,
    0x20: 7,
    0x10: 8,
}

VERIFIED_OFFSET60_BLINK_INDICATORS: dict[int, str] = {
    0x80: "rssi",
    0x08: "low_power",
    0x04: "shift",
    0x02: "audible",
    0x01: "message",
}

# Descriptive visual states only. The endpoint's internal purpose for these
# whole-LCD modes is not yet established.
VERIFIED_OFFSET64_VISUAL_STATES: dict[int, str] = {
    0x00: "normal_composed_display",
    0x01: "full_segment_pattern",
    0x02: "lower_segment_pattern",
    0x04: "u_segment_pattern",
    0x08: "blank_display",
    0x10: "blank_display",
    0x20: "blank_display",
    0x40: "blank_display",
    0x80: "blank_display",
}

# Exact segment/icon composition observed in the two photographed offset-64
# whole-LCD patterns. Segment names use the canonical 14-segment geometry used
# by the reference display vector. Position numbering is left-to-right, 1..8.
VERIFIED_OFFSET64_PATTERNS: dict[int, dict[str, object]] = {
    0x02: {
        "segments_by_position": tuple(("e", "m", "d") for _ in range(8)),
        "indicators": ("rssi", "dealer_p2", "dealer_p3"),
        "decimal_points": tuple(range(1, 9)),
    },
    0x04: {
        "segments_by_position": (
            ("b", "e", "m", "c", "d"),
            *(("e", "m", "c", "d"),) * 7,
        ),
        "indicators": ("scan", "encryption", "rssi_bar_3"),
        "decimal_points": (),
    },
}

VERIFIED_OFFSET65_VISUAL_STATES: dict[int, str] = {
    value: "no_visible_change_all_visible"
    for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
}
VERIFIED_OFFSET66_VISUAL_STATES: dict[int, str] = {
    value: "no_visible_change_all_visible"
    for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
}
VERIFIED_OFFSET67_VISUAL_STATES: dict[int, str] = {
    value: "no_visible_change_all_visible"
    for value in (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
}

VERIFIED_CHARACTER_BLINK_ATTRIBUTE_OFFSETS: dict[int, int] = {
    offset: offset - CHARACTER_ATTRIBUTE_OFFSET + 1
    for offset in range(
        CHARACTER_ATTRIBUTE_OFFSET,
        CHARACTER_ATTRIBUTE_OFFSET + CHARACTER_ATTRIBUTE_SIZE,
    )
}


def verified_display_bit_controls() -> tuple[dict[str, int | str], ...]:
    """Return canonical static LCD bit controls for UI/tool generation."""

    controls: list[dict[str, int | str]] = [
        {"name": "Message", "key": "message", "offset": 56, "mask": 0x01},
        {"name": "Speaker", "key": "audible", "offset": 56, "mask": 0x02},
        {"name": "Shift", "key": "shift", "offset": 56, "mask": 0x04},
        {"name": "LOW", "key": "low_power", "offset": 56, "mask": 0x08},
        {"name": "RSSI bar 3", "key": "rssi_bar_3", "offset": 56, "mask": 0x10},
        {"name": "RSSI bar 2", "key": "rssi_bar_2", "offset": 56, "mask": 0x20},
        {"name": "RSSI bar 1", "key": "rssi_bar_1", "offset": 56, "mask": 0x40},
        {"name": "RSSI base", "key": "rssi", "offset": 56, "mask": 0x80},
    ]
    controls.extend(
        {"name": name.replace("_", " ").title(), "key": name, "offset": 57, "mask": mask}
        for mask, name in sorted(VERIFIED_OFFSET57_INDICATORS.items())
    )
    controls.extend(
        {"name": name.replace("dealer_", "").upper(), "key": name, "offset": 58, "mask": mask}
        for mask, name in sorted(VERIFIED_OFFSET58_KEY_ICONS.items())
    )
    controls.extend(
        {"name": f"Dot {position}", "key": f"decimal_{position}", "offset": 58, "mask": mask}
        for mask, position in sorted(
            VERIFIED_OFFSET58_DECIMAL_POINTS.items(), key=lambda item: item[1]
        )
    )
    controls.extend(
        {"name": f"Dot {position}", "key": f"decimal_{position}", "offset": 59, "mask": mask}
        for mask, position in sorted(
            VERIFIED_OFFSET59_DECIMAL_POINTS.items(), key=lambda item: item[1]
        )
    )
    return tuple(controls)


def verified_display_blink_bit_controls() -> tuple[dict[str, int | str], ...]:
    """Return canonical LCD blink-mask controls for UI/tool generation.

    Offsets 60 through 63 mirror the verified steady-state planes at offsets
    56 through 59.  Keeping this mapping in the protocol package prevents
    applications from embedding wire offsets or inventing display semantics.
    """

    controls: list[dict[str, int | str]] = [
        {"name": "Message", "key": "message", "offset": 60, "mask": 0x01},
        {"name": "Speaker", "key": "audible", "offset": 60, "mask": 0x02},
        {"name": "Shift", "key": "shift", "offset": 60, "mask": 0x04},
        {"name": "LOW", "key": "low_power", "offset": 60, "mask": 0x08},
        {"name": "RSSI bar 3", "key": "rssi_bar_3", "offset": 60, "mask": 0x10},
        {"name": "RSSI bar 2", "key": "rssi_bar_2", "offset": 60, "mask": 0x20},
        {"name": "RSSI bar 1", "key": "rssi_bar_1", "offset": 60, "mask": 0x40},
        {"name": "RSSI base", "key": "rssi", "offset": 60, "mask": 0x80},
    ]
    controls.extend(
        {"name": name.replace("_", " ").title(), "key": name, "offset": 61, "mask": mask}
        for mask, name in sorted(VERIFIED_OFFSET57_INDICATORS.items())
    )
    controls.extend(
        {"name": name.replace("dealer_", "").upper(), "key": name, "offset": 62, "mask": mask}
        for mask, name in sorted(VERIFIED_OFFSET58_KEY_ICONS.items())
    )
    controls.extend(
        {"name": f"Dot {position}", "key": f"decimal_{position}", "offset": 62, "mask": mask}
        for mask, position in sorted(
            VERIFIED_OFFSET58_DECIMAL_POINTS.items(), key=lambda item: item[1]
        )
    )
    controls.extend(
        {"name": f"Dot {position}", "key": f"decimal_{position}", "offset": 63, "mask": mask}
        for mask, position in sorted(
            VERIFIED_OFFSET59_DECIMAL_POINTS.items(), key=lambda item: item[1]
        )
    )
    return tuple(controls)


def verified_character_blink_controls() -> tuple[dict[str, int], ...]:
    """Return the eight verified primary-character blink attributes."""

    return tuple(
        {"position": position, "offset": offset, "mask": 0x80}
        for offset, position in VERIFIED_CHARACTER_BLINK_ATTRIBUTE_OFFSETS.items()
    )


def verified_display_visual_modes() -> tuple[dict[str, int | str], ...]:
    """Return the synchronized, visually verified offset-64 LCD modes."""

    labels = {
        0x00: "Normal composed display",
        0x01: "All segments",
        0x02: "Lower-segment pattern",
        0x04: "Upper-segment pattern",
        0x08: "Blank display",
    }
    return tuple(
        {"name": labels[value], "key": VERIFIED_OFFSET64_VISUAL_STATES[value], "value": value}
        for value in labels
    )


def verified_display_svg_decimal_point_paths() -> tuple[int, ...]:
    """Return supplied-LCD-vector point paths in physical positions 1..8."""

    return VERIFIED_DISPLAY_SVG_DECIMAL_POINT_PATHS


class DisplayPhase(str, Enum):
    IDLE = "idle"
    BEFORE_BUFFER = "before_buffer"
    BUFFER_RECEIVED = "buffer_received"
    AFTER_BUFFER = "after_buffer"
    ACKNOWLEDGED = "acknowledged"


class DisplayEventKind(str, Enum):
    SYNC_BEFORE = "sync_before"
    BUFFER_UPDATED = "buffer_updated"
    SYNC_AFTER = "sync_after"
    ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True, slots=True)
class DisplayBuffer:
    """Lossless representation of one verified 68-byte display payload.

    Offsets 0 through 7 contain primary text. Exact observed indicator sets are
    also exposed for four verified offset-56 values. All bytes remain preserved
    exactly, and unverified values retain no inferred semantics.
    """

    raw: bytes

    def __post_init__(self) -> None:
        if len(self.raw) != DISPLAY_BUFFER_SIZE:
            raise ValueError(
                f"display payload must be exactly {DISPLAY_BUFFER_SIZE} bytes"
            )

    @classmethod
    def from_primary_text(
        cls,
        text: str,
        *,
        tail: bytes = VERIFIED_BASELINE_DISPLAY_TAIL,
    ) -> "DisplayBuffer":
        encoded = text.encode("ascii", "strict")
        if len(encoded) > PRIMARY_TEXT_SIZE:
            raise ValueError("verified primary display text is limited to 8 ASCII bytes")
        if len(tail) != DISPLAY_BUFFER_SIZE - PRIMARY_TEXT_SIZE:
            raise ValueError("display tail must be exactly 60 bytes")
        return cls(encoded.ljust(PRIMARY_TEXT_SIZE, b"\x00") + tail)

    @property
    def primary_raw(self) -> bytes:
        return self.raw[:PRIMARY_TEXT_SIZE]

    @property
    def primary_text(self) -> str:
        return self.primary_raw.rstrip(b"\x00").decode("ascii", "replace")

    @property
    def auxiliary_region_raw(self) -> bytes:
        return self.raw[
            AUXILIARY_REGION_OFFSET : AUXILIARY_REGION_OFFSET + AUXILIARY_REGION_SIZE
        ]

    @property
    def character_attribute_raw(self) -> bytes:
        return self.raw[
            CHARACTER_ATTRIBUTE_OFFSET :
            CHARACTER_ATTRIBUTE_OFFSET + CHARACTER_ATTRIBUTE_SIZE
        ]

    @property
    def verified_blinking_character_positions(self) -> tuple[int, ...]:
        return tuple(
            position
            for offset, position in VERIFIED_CHARACTER_BLINK_ATTRIBUTE_OFFSETS.items()
            if self.raw[offset] & 0x80
        )

    @property
    def unknown_tail(self) -> bytes:
        return self.raw[PRIMARY_TEXT_SIZE:]

    @property
    def indicator_state_byte(self) -> int:
        return self.raw[INDICATOR_STATE_OFFSET]

    @property
    def secondary_indicator_state_byte(self) -> int:
        return self.raw[SECONDARY_INDICATOR_STATE_OFFSET]

    @property
    def key_and_point_state_byte(self) -> int:
        return self.raw[KEY_AND_POINT_STATE_OFFSET]

    @property
    def secondary_point_state_byte(self) -> int:
        return self.raw[SECONDARY_POINT_STATE_OFFSET]

    @property
    def primary_blink_mask_byte(self) -> int:
        return self.raw[PRIMARY_BLINK_MASK_OFFSET]

    @property
    def secondary_blink_mask_byte(self) -> int:
        return self.raw[SECONDARY_BLINK_MASK_OFFSET]

    @property
    def key_and_point_blink_mask_byte(self) -> int:
        return self.raw[KEY_AND_POINT_BLINK_MASK_OFFSET]

    @property
    def secondary_point_blink_mask_byte(self) -> int:
        return self.raw[SECONDARY_POINT_BLINK_MASK_OFFSET]

    @property
    def display_control_64_byte(self) -> int:
        return self.raw[DISPLAY_CONTROL_64_OFFSET]

    @property
    def verified_offset64_visual_state(self) -> str | None:
        return VERIFIED_OFFSET64_VISUAL_STATES.get(self.display_control_64_byte)

    @property
    def verified_offset64_pattern(self) -> dict[str, object] | None:
        """Return the exact photographed segment composition, when defined."""

        return VERIFIED_OFFSET64_PATTERNS.get(self.display_control_64_byte)

    @property
    def display_control_65_byte(self) -> int:
        return self.raw[DISPLAY_CONTROL_65_OFFSET]

    @property
    def verified_offset65_visual_state(self) -> str | None:
        return VERIFIED_OFFSET65_VISUAL_STATES.get(self.display_control_65_byte)

    @property
    def display_control_66_byte(self) -> int:
        return self.raw[DISPLAY_CONTROL_66_OFFSET]

    @property
    def verified_offset66_visual_state(self) -> str | None:
        return VERIFIED_OFFSET66_VISUAL_STATES.get(self.display_control_66_byte)

    @property
    def display_control_67_byte(self) -> int:
        return self.raw[DISPLAY_CONTROL_67_OFFSET]

    @property
    def verified_offset67_visual_state(self) -> str | None:
        return VERIFIED_OFFSET67_VISUAL_STATES.get(self.display_control_67_byte)

    @property
    def verified_dealer_key_icons(self) -> tuple[str, ...]:
        return tuple(
            name
            for bit, name in VERIFIED_OFFSET58_KEY_ICONS.items()
            if self.key_and_point_state_byte & bit
        )

    @property
    def verified_decimal_points(self) -> tuple[int, ...]:
        first = tuple(
            position
            for bit, position in VERIFIED_OFFSET58_DECIMAL_POINTS.items()
            if self.key_and_point_state_byte & bit
        )
        second = tuple(
            position
            for bit, position in VERIFIED_OFFSET59_DECIMAL_POINTS.items()
            if self.secondary_point_state_byte & bit
        )
        return first + second

    @property
    def unresolved_offset59_low_nibble(self) -> int:
        return self.secondary_point_state_byte & 0x0F

    @property
    def verified_blinking_indicators(self) -> tuple[str, ...]:
        return tuple(
            name
            for bit, name in VERIFIED_OFFSET60_BLINK_INDICATORS.items()
            if self.primary_blink_mask_byte & bit
        )

    @property
    def verified_blinking_rssi_bars(self) -> tuple[int, ...]:
        bars: list[int] = []
        if self.primary_blink_mask_byte & 0x40:
            bars.append(1)
        if self.primary_blink_mask_byte & 0x20:
            bars.append(2)
        if self.primary_blink_mask_byte & 0x10:
            bars.append(3)
        return tuple(bars)

    @property
    def verified_secondary_blinking_indicators(self) -> tuple[str, ...]:
        return tuple(
            name
            for bit, name in VERIFIED_OFFSET57_INDICATORS.items()
            if self.secondary_blink_mask_byte & bit
        )

    @property
    def verified_blinking_dealer_key_icons(self) -> tuple[str, ...]:
        return tuple(
            name
            for bit, name in VERIFIED_OFFSET58_KEY_ICONS.items()
            if self.key_and_point_blink_mask_byte & bit
        )

    @property
    def verified_blinking_decimal_points(self) -> tuple[int, ...]:
        first = tuple(
            position
            for bit, position in VERIFIED_OFFSET58_DECIMAL_POINTS.items()
            if self.key_and_point_blink_mask_byte & bit
        )
        second = tuple(
            position
            for bit, position in VERIFIED_OFFSET59_DECIMAL_POINTS.items()
            if self.secondary_point_blink_mask_byte & bit
        )
        return first + second

    @property
    def unresolved_offset63_low_nibble(self) -> int:
        return self.secondary_point_blink_mask_byte & 0x0F

    @property
    def verified_secondary_indicators(self) -> tuple[str, ...]:
        return tuple(
            name
            for bit, name in VERIFIED_OFFSET57_INDICATORS.items()
            if self.secondary_indicator_state_byte & bit
        )

    @property
    def verified_indicators(self) -> tuple[str, ...] | None:
        """Return verified/composable offset-56 icons, or None if unmapped.

        Every bit in offset 56 is mapped. Bar bits without the RSSI base bit
        have not been displayed and therefore remain outside verified decode.
        """

        exact = VERIFIED_OFFSET56_INDICATORS.get(self.indicator_state_byte)
        if exact is not None:
            return (
                exact
                + self.verified_secondary_indicators
                + self.verified_dealer_key_icons
            )
        value = self.indicator_state_byte
        if value & 0x70 and not value & 0x80:
            return None
        indicators: list[str] = []
        if value & 0x08:
            indicators.append("low_power")
        if value & 0x04:
            indicators.append("shift")
        if value & 0x02:
            indicators.append("audible")
        if value & 0x01:
            indicators.append("message")
        if value & 0x80:
            indicators.append("rssi")
        return (
            tuple(indicators)
            + self.verified_secondary_indicators
            + self.verified_dealer_key_icons
        )

    @property
    def verified_rssi_bars(self) -> tuple[int, ...] | None:
        """Return lit RSSI bar positions 1..3, or None when RSSI is absent/unmapped."""

        indicators = self.verified_indicators
        if indicators is None or "rssi" not in indicators:
            return None
        bars: list[int] = []
        if self.indicator_state_byte & 0x40:
            bars.append(1)
        if self.indicator_state_byte & 0x20:
            bars.append(2)
        if self.indicator_state_byte & 0x10:
            bars.append(3)
        return tuple(bars)

    @property
    def ascii_projection(self) -> str:
        return "".join(
            chr(value) if 0x20 <= value <= 0x7E else "." for value in self.raw
        )

    @property
    def unknown_nonzero_offsets(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (offset, value)
            for offset, value in enumerate(self.raw[PRIMARY_TEXT_SIZE:], PRIMARY_TEXT_SIZE)
            if value
        )

    def with_primary_text(self, text: str) -> "DisplayBuffer":
        return self.from_primary_text(text, tail=self.unknown_tail)

    def to_dict(self) -> dict[str, object]:
        return {
            "raw_hex": self.raw.hex(),
            "primary_text": self.primary_text,
            "primary_raw_hex": self.primary_raw.hex(),
            "auxiliary_region_offset": AUXILIARY_REGION_OFFSET,
            "auxiliary_region_raw_hex": self.auxiliary_region_raw.hex(),
            "character_attribute_offset": CHARACTER_ATTRIBUTE_OFFSET,
            "character_attribute_raw_hex": self.character_attribute_raw.hex(),
            "verified_blinking_character_positions": list(
                self.verified_blinking_character_positions
            ),
            "unknown_tail_hex": self.unknown_tail.hex(),
            "indicator_state_offset": INDICATOR_STATE_OFFSET,
            "indicator_state_byte": self.indicator_state_byte,
            "secondary_indicator_state_offset": SECONDARY_INDICATOR_STATE_OFFSET,
            "secondary_indicator_state_byte": self.secondary_indicator_state_byte,
            "key_and_point_state_offset": KEY_AND_POINT_STATE_OFFSET,
            "key_and_point_state_byte": self.key_and_point_state_byte,
            "verified_dealer_key_icons": list(self.verified_dealer_key_icons),
            "verified_decimal_points": list(self.verified_decimal_points),
            "secondary_point_state_offset": SECONDARY_POINT_STATE_OFFSET,
            "secondary_point_state_byte": self.secondary_point_state_byte,
            "unresolved_offset59_low_nibble": self.unresolved_offset59_low_nibble,
            "primary_blink_mask_offset": PRIMARY_BLINK_MASK_OFFSET,
            "primary_blink_mask_byte": self.primary_blink_mask_byte,
            "verified_blinking_indicators": list(self.verified_blinking_indicators),
            "verified_blinking_rssi_bars": list(self.verified_blinking_rssi_bars),
            "secondary_blink_mask_offset": SECONDARY_BLINK_MASK_OFFSET,
            "secondary_blink_mask_byte": self.secondary_blink_mask_byte,
            "verified_secondary_blinking_indicators": list(
                self.verified_secondary_blinking_indicators
            ),
            "key_and_point_blink_mask_offset": KEY_AND_POINT_BLINK_MASK_OFFSET,
            "key_and_point_blink_mask_byte": self.key_and_point_blink_mask_byte,
            "verified_blinking_dealer_key_icons": list(
                self.verified_blinking_dealer_key_icons
            ),
            "verified_blinking_decimal_points": list(
                self.verified_blinking_decimal_points
            ),
            "secondary_point_blink_mask_offset": SECONDARY_POINT_BLINK_MASK_OFFSET,
            "secondary_point_blink_mask_byte": self.secondary_point_blink_mask_byte,
            "unresolved_offset63_low_nibble": self.unresolved_offset63_low_nibble,
            "display_control_64_offset": DISPLAY_CONTROL_64_OFFSET,
            "display_control_64_byte": self.display_control_64_byte,
            "verified_offset64_visual_state": self.verified_offset64_visual_state,
            "verified_offset64_pattern": self.verified_offset64_pattern,
            "display_control_65_offset": DISPLAY_CONTROL_65_OFFSET,
            "display_control_65_byte": self.display_control_65_byte,
            "verified_offset65_visual_state": self.verified_offset65_visual_state,
            "display_control_66_offset": DISPLAY_CONTROL_66_OFFSET,
            "display_control_66_byte": self.display_control_66_byte,
            "verified_offset66_visual_state": self.verified_offset66_visual_state,
            "display_control_67_offset": DISPLAY_CONTROL_67_OFFSET,
            "display_control_67_byte": self.display_control_67_byte,
            "verified_offset67_visual_state": self.verified_offset67_visual_state,
            "verified_indicators": (
                list(self.verified_indicators)
                if self.verified_indicators is not None
                else None
            ),
            "verified_rssi_bars": (
                list(self.verified_rssi_bars)
                if self.verified_rssi_bars is not None
                else None
            ),
            "unknown_nonzero_offsets": [
                {"offset": offset, "value": value}
                for offset, value in self.unknown_nonzero_offsets
            ],
            "ascii_projection": self.ascii_projection,
        }

    def to_metadata(self) -> dict[str, object]:
        return {
            "display_text": self.primary_text,
            "display_primary_raw_hex": self.primary_raw.hex(),
            "display_auxiliary_region_raw_hex": self.auxiliary_region_raw.hex(),
            "display_character_attribute_raw_hex": self.character_attribute_raw.hex(),
            "display_verified_blinking_character_positions": list(
                self.verified_blinking_character_positions
            ),
            "display_unknown_hex": self.unknown_tail.hex(),
            "display_indicator_state_byte": self.indicator_state_byte,
            "display_secondary_indicator_state_byte": self.secondary_indicator_state_byte,
            "display_key_and_point_state_byte": self.key_and_point_state_byte,
            "display_verified_dealer_key_icons": list(self.verified_dealer_key_icons),
            "display_verified_decimal_points": list(self.verified_decimal_points),
            "display_secondary_point_state_byte": self.secondary_point_state_byte,
            "display_unresolved_offset59_low_nibble": self.unresolved_offset59_low_nibble,
            "display_primary_blink_mask_byte": self.primary_blink_mask_byte,
            "display_verified_blinking_indicators": list(self.verified_blinking_indicators),
            "display_verified_blinking_rssi_bars": list(self.verified_blinking_rssi_bars),
            "display_secondary_blink_mask_byte": self.secondary_blink_mask_byte,
            "display_verified_secondary_blinking_indicators": list(
                self.verified_secondary_blinking_indicators
            ),
            "display_key_and_point_blink_mask_byte": self.key_and_point_blink_mask_byte,
            "display_verified_blinking_dealer_key_icons": list(
                self.verified_blinking_dealer_key_icons
            ),
            "display_verified_blinking_decimal_points": list(
                self.verified_blinking_decimal_points
            ),
            "display_secondary_point_blink_mask_byte": self.secondary_point_blink_mask_byte,
            "display_unresolved_offset63_low_nibble": self.unresolved_offset63_low_nibble,
            "display_control_64_byte": self.display_control_64_byte,
            "display_verified_offset64_visual_state": self.verified_offset64_visual_state,
            "display_verified_offset64_pattern": self.verified_offset64_pattern,
            "display_control_65_byte": self.display_control_65_byte,
            "display_verified_offset65_visual_state": self.verified_offset65_visual_state,
            "display_control_66_byte": self.display_control_66_byte,
            "display_verified_offset66_visual_state": self.verified_offset66_visual_state,
            "display_control_67_byte": self.display_control_67_byte,
            "display_verified_offset67_visual_state": self.verified_offset67_visual_state,
            "display_verified_indicators": (
                list(self.verified_indicators)
                if self.verified_indicators is not None
                else None
            ),
            "display_verified_rssi_bars": (
                list(self.verified_rssi_bars)
                if self.verified_rssi_bars is not None
                else None
            ),
            "display_unknown_nonzero_offsets": [
                {"offset": offset, "value": value}
                for offset, value in self.unknown_nonzero_offsets
            ],
            "display_ascii_projection": self.ascii_projection,
        }


@dataclass(frozen=True, slots=True)
class DisplayEvent:
    kind: DisplayEventKind
    phase: DisplayPhase
    revision: int
    buffer: DisplayBuffer | None = None
    warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "kind": self.kind.value,
            "phase": self.phase.value,
            "revision": self.revision,
        }
        if self.buffer is not None:
            result["display"] = self.buffer.to_dict()
        if self.warning is not None:
            result["warning"] = self.warning
        return result


@dataclass(slots=True)
class DisplayStateModel:
    """Role-neutral tracker for the verified display transaction sequence."""

    current: DisplayBuffer | None = None
    phase: DisplayPhase = DisplayPhase.IDLE
    revision: int = 0
    last_warning: str | None = None

    def consume(self, message: Message) -> DisplayEvent | None:
        event_kind: DisplayEventKind
        warning: str | None = None

        if message.kind is MessageKind.DISPLAY_SYNC:
            sync_phase = message.metadata.get("display_sync_phase")
            if sync_phase == "before_buffer":
                if self.phase in (DisplayPhase.BEFORE_BUFFER, DisplayPhase.BUFFER_RECEIVED):
                    warning = f"display transaction restarted during {self.phase.value}"
                self.phase = DisplayPhase.BEFORE_BUFFER
                event_kind = DisplayEventKind.SYNC_BEFORE
            elif sync_phase == "after_buffer":
                if self.phase is not DisplayPhase.BUFFER_RECEIVED:
                    warning = f"display after marker received during {self.phase.value}"
                self.phase = DisplayPhase.AFTER_BUFFER
                event_kind = DisplayEventKind.SYNC_AFTER
            else:
                return None
        elif message.kind is MessageKind.DISPLAY_UPDATE:
            payload_hex = message.metadata.get("payload_hex")
            if not isinstance(payload_hex, str):
                return None
            if self.phase is not DisplayPhase.BEFORE_BUFFER:
                warning = f"display buffer received during {self.phase.value}"
            self.current = DisplayBuffer(bytes.fromhex(payload_hex))
            self.revision += 1
            self.phase = DisplayPhase.BUFFER_RECEIVED
            event_kind = DisplayEventKind.BUFFER_UPDATED
        elif message.kind is MessageKind.DISPLAY_ACK:
            if self.phase is not DisplayPhase.AFTER_BUFFER:
                warning = f"display acknowledgement received during {self.phase.value}"
            self.phase = DisplayPhase.ACKNOWLEDGED
            event_kind = DisplayEventKind.ACKNOWLEDGED
        else:
            return None

        self.last_warning = warning
        return DisplayEvent(
            kind=event_kind,
            phase=self.phase,
            revision=self.revision,
            buffer=self.current if event_kind is DisplayEventKind.BUFFER_UPDATED else None,
            warning=warning,
        )

    def snapshot(self) -> dict[str, object]:
        result: dict[str, object] = {
            "phase": self.phase.value,
            "revision": self.revision,
        }
        if self.current is not None:
            result["display"] = self.current.to_dict()
        if self.last_warning is not None:
            result["last_warning"] = self.last_warning
        return result


def summarize_display_buffers(
    observations: Iterable[tuple[str, DisplayBuffer]],
) -> dict[str, object]:
    """Summarize known text and byte-level variation without assigning semantics."""

    items = list(observations)
    primary_texts = Counter(display.primary_text for _, display in items)
    tail_variants: dict[bytes, dict[str, object]] = {}
    offset_values: dict[int, Counter[int]] = defaultdict(Counter)
    captures = {capture for capture, _ in items}

    for capture, display in items:
        variant = tail_variants.setdefault(
            display.unknown_tail,
            {"count": 0, "captures": set(), "primary_texts": Counter()},
        )
        variant["count"] = int(variant["count"]) + 1
        variant["captures"].add(capture)  # type: ignore[union-attr]
        variant["primary_texts"][display.primary_text] += 1  # type: ignore[index]
        for offset, value in enumerate(display.raw[PRIMARY_TEXT_SIZE:], PRIMARY_TEXT_SIZE):
            offset_values[offset][value] += 1

    def value_summary(values: Counter[int]) -> list[dict[str, int]]:
        return [
            {"value": value, "count": count}
            for value, count in sorted(values.items())
        ]

    variable_offsets = {
        str(offset): value_summary(values)
        for offset, values in sorted(offset_values.items())
        if len(values) > 1
    }
    nonzero_offsets = {
        str(offset): value_summary(Counter({value: count for value, count in values.items() if value}))
        for offset, values in sorted(offset_values.items())
        if any(values.keys())
    }
    variants = []
    for tail, fields in sorted(
        tail_variants.items(), key=lambda item: (-int(item[1]["count"]), item[0])
    ):
        variants.append(
            {
                "count": fields["count"],
                "tail_hex": tail.hex(),
                "captures": sorted(fields["captures"]),
                "primary_texts": dict(sorted(fields["primary_texts"].items())),
            }
        )

    return {
        "display_count": len(items),
        "captures_with_displays": len(captures),
        "distinct_primary_texts": dict(sorted(primary_texts.items())),
        "distinct_unknown_tail_count": len(tail_variants),
        "variable_unknown_offsets": variable_offsets,
        "observed_nonzero_unknown_offsets": nonzero_offsets,
        "unknown_tail_variants": variants,
    }
