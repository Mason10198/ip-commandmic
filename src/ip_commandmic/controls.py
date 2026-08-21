from __future__ import annotations


KEY_PRESS_VALUES = {
    "f1": 0x00,
    "volume_down": 0x01,
    "p1": 0x02,
    "keypad_1": 0x03,
    "keypad_2": 0x04,
    "keypad_3": 0x05,
    "volume_up": 0x10,
    "p2": 0x12,
    "keypad_4": 0x13,
    "keypad_5": 0x14,
    "keypad_6": 0x15,
    "up": 0x20,
    "down": 0x21,
    "p3": 0x22,
    "keypad_7": 0x23,
    "keypad_8": 0x24,
    "keypad_9": 0x25,
    "right": 0x30,
    "left": 0x31,
    "p4": 0x32,
    "keypad_star": 0x33,
    "keypad_0": 0x34,
    "keypad_hash": 0x35,
    "emergency": 0x40,
}

CONTROL_LABELS = {
    "f1": "Monitor",
    "volume_up": "Volume Up",
    "volume_down": "Volume Down",
    "p1": "P1",
    "p2": "P2",
    "p3": "P3",
    "p4": "P4",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "emergency": "Emergency",
    **{f"keypad_{number}": f"Keypad {number}" for number in range(10)},
    "keypad_star": "Keypad Star",
    "keypad_hash": "Keypad Hash",
}

CONTROL_ALIASES = {
    "monitor": "f1",
    "monitor_f1": "f1",
    "f2": "volume_up",
    "vol_up": "volume_up",
    "volume+": "volume_up",
    "f3": "volume_down",
    "vol_down": "volume_down",
    "volume-": "volume_down",
    "emer": "emergency",
}

CONTROL_PHYSICAL_ALIASES = {
    "f1": "F1 side key",
    "volume_up": "F2 side key",
    "volume_down": "F3 side key",
    "emergency": "Orange top key",
}

ORDINARY_KEY_BUTTONS = tuple(
    button for button in KEY_PRESS_VALUES if button != "emergency"
)
KEY_NEUTRAL_VALUE = 0x7F


def normalize_button_name(button: str) -> str:
    """Return the documented physical-control name for a public alias."""

    normalized = button.strip().lower().replace(" ", "_").replace("-", "_")
    return CONTROL_ALIASES.get(normalized, normalized)


def control_display_name(button: str) -> str:
    """Return a human-readable name with the physical key alias when useful."""

    canonical = normalize_button_name(button)
    label = CONTROL_LABELS.get(canonical, canonical.replace("_", " ").title())
    alias = CONTROL_PHYSICAL_ALIASES.get(canonical)
    return f"{label} ({alias})" if alias else label


def key_wire_value(
    button: str | None,
    action: str,
    *,
    allow_emergency: bool = False,
) -> int:
    """Return the verified 01/01 payload byte for a physical-key state."""

    if action == "neutral":
        if button is not None:
            raise ValueError("neutral key state must not name a button")
        return KEY_NEUTRAL_VALUE
    if action not in {"press", "release"}:
        raise ValueError("key action must be press, release, or neutral")
    if button is not None:
        button = normalize_button_name(button)
    if button not in KEY_PRESS_VALUES:
        choices = ", ".join(KEY_PRESS_VALUES)
        raise ValueError(f"unknown key button {button!r}; choose one of {choices}")
    if button == "emergency" and not allow_emergency:
        raise ValueError("emergency key emission requires an explicit safety gate")
    value = KEY_PRESS_VALUES[button]
    return value | (0x80 if action == "release" else 0)


def key_tap_values(button: str, *, allow_emergency: bool = False) -> tuple[int, int, int]:
    return (
        key_wire_value(button, "press", allow_emergency=allow_emergency),
        key_wire_value(button, "release", allow_emergency=allow_emergency),
        KEY_NEUTRAL_VALUE,
    )
