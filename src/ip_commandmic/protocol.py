from __future__ import annotations

from collections.abc import Iterable

from .checksums import crc16
from .controls import KEY_NEUTRAL_VALUE, KEY_PRESS_VALUES, key_tap_values, key_wire_value
from .display import DisplayBuffer
from .models import Direction, Message, MessageKind

STATUS_LED_COLORS = ("off", "red", "green", "orange")

MAGIC_PREFIXES = (b"\xf3\x41\x71", b"\xf5\x41\x71")
TERMINATOR = 0xFD

RADIO_IDLE_HEARTBEAT = bytes.fromhex("f34171050000024d003570fd")
MIC_IDLE_HEARTBEAT = bytes.fromhex("f34171050000026d0135a8fd")

_KNOWN_MESSAGES = {
    RADIO_IDLE_HEARTBEAT: (
        MessageKind.HEARTBEAT,
        Direction.RADIO_TO_MIC,
        "passively observed idle radio heartbeat",
    ),
    MIC_IDLE_HEARTBEAT: (
        MessageKind.HEARTBEAT,
        Direction.MIC_TO_RADIO,
        "passively observed idle microphone heartbeat response",
    ),
}

_VERIFIED_KEY_STATES = {
    **{
        value: (button, "press")
        for button, value in KEY_PRESS_VALUES.items()
    },
    **{
        value | 0x80: (button, "release")
        for button, value in KEY_PRESS_VALUES.items()
    },
    KEY_NEUTRAL_VALUE: (None, "neutral"),
}


def unstuff_bytes(data: bytes) -> bytes:
    """Decode the evidenced F0-FF byte-stuffing used inside a frame."""

    output = bytearray()
    index = 0
    while index < len(data):
        byte = data[index]
        if byte == 0xFF and index + 1 < len(data) and data[index + 1] <= 0x0F:
            output.append(0xF0 | data[index + 1])
            index += 2
        else:
            output.append(byte)
            index += 1
    return bytes(output)


def stuff_bytes(data: bytes) -> bytes:
    output = bytearray()
    for byte in data:
        if byte >= 0xF0:
            output.extend((0xFF, byte & 0x0F))
        else:
            output.append(byte)
    return bytes(output)


def crc16_commandmic(data: bytes) -> int:
    """Verified link CRC: Modbus polynomial/init, serialized big-endian."""

    return crc16(data, poly=0xA001, init=0xFFFF, refin=True)


def decode_wire_frame(raw: bytes) -> tuple[bytes, bool]:
    if len(raw) < 4:
        return raw, False
    # Start and terminator are literal framing bytes; stuffing applies between them.
    decoded = raw[:1] + unstuff_bytes(raw[1:-1]) + raw[-1:]
    return decoded, len(decoded) != len(raw)


def classify_message(raw: bytes, direction: Direction | str = Direction.UNKNOWN) -> Message:
    supplied_direction = Direction.coerce(direction)
    known = _KNOWN_MESSAGES.get(raw)
    if known:
        kind, observed_direction, evidence = known
        effective_direction = (
            observed_direction if supplied_direction is Direction.UNKNOWN else supplied_direction
        )
        decoded, stuffed = decode_wire_frame(raw)
        return Message(
            raw=raw,
            direction=effective_direction,
            kind=kind,
            checksum_valid=crc16_commandmic(decoded[1:-3]) == int.from_bytes(decoded[-3:-1], "big"),
            evidence=evidence,
            metadata={
                "start_byte": decoded[0],
                "message_class": decoded[3],
                "command": decoded[4],
                "declared_payload_length": int.from_bytes(decoded[5:7], "big"),
                "payload_hex": decoded[7:-3].hex(),
                "wire_stuffed": stuffed,
                "decoded_hex": decoded.hex(),
                "checksum": int.from_bytes(decoded[-3:-1], "big"),
                "frame_format": "ordinary",
            },
        )
    decoded, stuffed = decode_wire_frame(raw)
    metadata: dict[str, object] = {
        "start_byte": decoded[0] if decoded else None,
        "wire_stuffed": stuffed,
        "decoded_hex": decoded.hex(),
    }
    checksum_valid: bool | None = None
    kind = MessageKind.UNKNOWN
    evidence: str | None = None
    framing_valid = (
        len(decoded) >= 6
        and decoded[:3] in MAGIC_PREFIXES
        and decoded[-1] == TERMINATOR
    )
    if framing_valid and len(decoded) >= 6:
        checksum_valid = crc16_commandmic(decoded[1:-3]) == int.from_bytes(decoded[-3:-1], "big")
        metadata["checksum"] = int.from_bytes(decoded[-3:-1], "big")
    if framing_valid and len(decoded) >= 10:
        declared_length = int.from_bytes(decoded[5:7], "big")
        ordinary = len(decoded) == declared_length + 10
        if ordinary:
            message_class = decoded[3]
            command = decoded[4]
            payload = decoded[7:-3]
            metadata.update(
                {
                    "message_class": message_class,
                    "command": command,
                    "declared_payload_length": declared_length,
                    "payload_hex": payload.hex(),
                    "frame_format": "ordinary",
                }
            )
            if (
                supplied_direction is Direction.MIC_TO_RADIO
                and message_class == 0x01
                and command == 0x00
                and payload in (b"\x00", b"\x01")
            ):
                kind = MessageKind.PTT_STATE
                metadata["ptt_action"] = "press" if payload == b"\x01" else "release"
                metadata["ptt_active"] = payload == b"\x01"
                evidence = "PTT down/up mapped during dummy-load transmit trial"
            elif (
                supplied_direction is Direction.RADIO_TO_MIC
                and message_class == 0x01
                and command == 0x04
                and payload in (bytes(4), b"\x01\x00\x00\x00", b"\x08\x00\x00\x00")
            ):
                kind = MessageKind.AUDIO_STATE
                metadata["audio_state"] = {
                    bytes(4): "closed",
                    b"\x01\x00\x00\x00": "receive_open",
                    b"\x08\x00\x00\x00": "transmit_active",
                }[payload]
                evidence = "audio open/TX active/close mapped in F1 and PTT trials"
            elif (
                supplied_direction is Direction.RADIO_TO_MIC
                and message_class == 0x02
                and command == 0x02
                and payload in (b"\x00", b"\x02", b"\x04", b"\x06")
            ):
                kind = MessageKind.AUDIO_STATUS
                metadata["audio_status"] = {
                    b"\x00": "idle",
                    b"\x02": "transmit_active",
                    b"\x04": "receive_active",
                    b"\x06": "combined_active",
                }[payload]
                value = payload[0]
                metadata["status_led_red"] = bool(value & 0x02)
                metadata["status_led_green"] = bool(value & 0x04)
                metadata["status_led_color"] = {
                    0x00: "off",
                    0x02: "red",
                    0x04: "green",
                    0x06: "orange",
                }[value]
                evidence = (
                    "audio/status correlates mapped in F1/PTT trials; LED colors "
                    "verified in isolated observed-value scan"
                )
            elif (
                supplied_direction is Direction.RADIO_TO_MIC
                and message_class == 0x02
                and command == 0x0B
                and payload in (b"\x00", b"\x01", b"\x02")
            ):
                kind = MessageKind.BACKLIGHT_STATE
                metadata["backlight_value"] = payload[0]
                metadata["backlight_state"] = {
                    b"\x00": "off",
                    b"\x01": "dim",
                    b"\x02": "on",
                }[payload]
                metadata["backlight_active"] = payload != b"\x00"
                metadata["backlight_dimmed"] = payload == b"\x01"
                evidence = (
                    "CPS Backlight OFF/Dim/ON comparison plus OFF Auto startup "
                    "and key-triggered five-second transitions"
                )
            elif (
                supplied_direction is Direction.RADIO_TO_MIC
                and message_class == 0x02
                and command == 0x0E
                and len(payload) == 1
                and 0x01 <= payload[0] <= 0x06
            ):
                kind = MessageKind.MIC_GAIN
                metadata["mic_gain_value"] = payload[0]
                evidence = (
                    "Gain 2/3/4 codeplug differential: first startup value equals "
                    "programmed gain and the following value is gain plus one"
                )
            elif (
                supplied_direction is Direction.MIC_TO_RADIO
                and message_class == 0x01
                and command == 0x09
                and payload in (b"\x00", b"\x01")
            ):
                kind = MessageKind.POWER_STATE
                metadata["power_action"] = "press" if payload == b"\x01" else "release"
                metadata["power_active"] = payload == b"\x01"
                evidence = "Power press/release mapped by short-tap and hold trials"
            elif (
                supplied_direction is Direction.MIC_TO_RADIO
                and message_class == 0x01
                and command == 0x01
                and len(payload) == 1
            ):
                kind = MessageKind.KEY_STATE
                button, action = _VERIFIED_KEY_STATES.get(
                    payload[0], (None, "unknown")
                )
                metadata.update(
                    {
                        "key_wire_value": payload[0],
                        "key_button": button,
                        "key_action": action,
                    }
                )
                evidence = "01/01 physical key-state structure reproduced in three-trial mappings"
            elif (
                supplied_direction is Direction.RADIO_TO_MIC
                and message_class == 0x02
                and command == 0x07
                and payload == b"\x02"
            ):
                kind = MessageKind.DISPLAY_SYNC
                metadata["display_sync_phase"] = "before_buffer"
                evidence = "precedes all six verified channel display buffers"
            elif (
                supplied_direction is Direction.RADIO_TO_MIC
                and message_class == 0x02
                and command == 0x0A
                and len(payload) == 68
            ):
                kind = MessageKind.DISPLAY_UPDATE
                display = DisplayBuffer(payload)
                metadata.update(display.to_metadata())
                display_text = display.primary_text
                display_parts = display_text.split()
                if (
                    len(display_parts) == 2
                    and display_parts[0] == "VOL"
                    and display_parts[1].isdigit()
                ):
                    metadata["volume_level"] = int(display_parts[1])
                evidence = "68-byte display buffer; first 8 bytes verified as primary display text"
            elif (
                supplied_direction is Direction.RADIO_TO_MIC
                and message_class == 0x02
                and command == 0x08
                and payload == b"\x00\x44"
            ):
                kind = MessageKind.DISPLAY_SYNC
                metadata["display_sync_phase"] = "after_buffer"
                evidence = "follows all six verified channel display buffers"
            elif (
                supplied_direction is Direction.MIC_TO_RADIO
                and message_class == 0x02
                and command == 0x09
                and payload == b"\x01"
            ):
                kind = MessageKind.DISPLAY_ACK
                evidence = "microphone response after all six verified channel display buffers"
        else:
            metadata["frame_format"] = "special_or_unknown"
    return Message(
        raw=raw,
        direction=supplied_direction,
        kind=kind,
        framing_valid=framing_valid,
        checksum_valid=checksum_valid,
        evidence=evidence,
        metadata=metadata,
    )


def _find_magic(data: bytes, start: int) -> int:
    offsets = [offset for magic in MAGIC_PREFIXES if (offset := data.find(magic, start)) >= 0]
    return min(offsets) if offsets else -1


def _incomplete_magic_suffix_length(data: bytes) -> int:
    for length in (2, 1):
        suffix = data[-length:]
        if any(magic.startswith(suffix) for magic in MAGIC_PREFIXES):
            return length
    return 0


def parse_stream(
    data: bytes,
    direction: Direction | str = Direction.UNKNOWN,
) -> tuple[list[Message], bytes]:
    """Parse all complete messages and return an incomplete trailing fragment.

    Current evidence supports a two-byte magic value and an 0xfd terminator. The
    function deliberately emits non-framed bytes as ``UNFRAMED`` messages so no
    captured application data silently disappears. If later captures demonstrate
    byte escaping or embedded terminators, this delimiter is the single place to
    revise.
    """

    direction = Direction.coerce(direction)
    messages: list[Message] = []
    cursor = 0

    while cursor < len(data):
        start = _find_magic(data, cursor)
        if start < 0:
            preserve = _incomplete_magic_suffix_length(data)
            end = len(data) - preserve
            if end > cursor:
                messages.append(
                    Message(
                        raw=data[cursor:end],
                        direction=direction,
                        kind=MessageKind.UNFRAMED,
                        framing_valid=False,
                        evidence="bytes outside the currently known framing",
                    )
                )
            return messages, data[end:]

        if start > cursor:
            messages.append(
                Message(
                    raw=data[cursor:start],
                    direction=direction,
                    kind=MessageKind.UNFRAMED,
                    framing_valid=False,
                    evidence="bytes preceding the next known magic value",
                )
            )

        end = data.find(bytes((TERMINATOR,)), start + 3)
        next_start = _find_magic(data, start + 3)
        if next_start >= 0 and (end < 0 or next_start < end):
            messages.append(
                Message(
                    raw=data[start:next_start],
                    direction=direction,
                    kind=MessageKind.UNFRAMED,
                    framing_valid=False,
                    evidence="new magic encountered before a terminator; parser resynchronized",
                )
            )
            cursor = next_start
            continue
        if end < 0:
            return messages, data[start:]

        raw = data[start : end + 1]
        messages.append(classify_message(raw, direction))
        cursor = end + 1

    return messages, b""


def encode_message(message: Message | bytes) -> bytes:
    """Encode a message without inventing unknown fields.

    Unknown messages are represented by their original bytes, making replay and
    round-trip fixture tests lossless while the wire schema is still being learned.
    """

    if isinstance(message, bytes):
        return message
    return message.raw


def build_frame(
    message_class: int,
    command: int,
    payload: bytes = b"",
    *,
    start_byte: int = 0xF3,
) -> bytes:
    """Build an ordinary frame using the verified framing, stuffing, and CRC.

    This low-level primitive does not assign semantics to class/command values and
    is not exposed by any hardware-contact CLI command.
    """

    if start_byte not in (0xF3, 0xF5):
        raise ValueError("start_byte must be 0xf3 or 0xf5")
    if not 0 <= message_class <= 0xFF or not 0 <= command <= 0xFF:
        raise ValueError("class and command must be bytes")
    if len(payload) > 0xFFFF:
        raise ValueError("payload is too large")
    logical = (
        bytes((start_byte, 0x41, 0x71, message_class, command))
        + len(payload).to_bytes(2, "big")
        + payload
    )
    checksum = crc16_commandmic(logical[1:]).to_bytes(2, "big")
    return logical[:1] + stuff_bytes(logical[1:] + checksum) + bytes((TERMINATOR,))


def encode_key_state(
    button: str | None,
    action: str,
    *,
    allow_emergency: bool = False,
) -> bytes:
    """Encode one verified physical-key state as mic-to-radio class 01/01."""

    value = key_wire_value(button, action, allow_emergency=allow_emergency)
    return build_frame(0x01, 0x01, bytes((value,)))


def encode_key_tap(
    button: str,
    *,
    allow_emergency: bool = False,
) -> tuple[bytes, bytes, bytes]:
    """Encode the observed press, release, neutral sequence for one key tap."""

    return tuple(
        build_frame(0x01, 0x01, bytes((value,)))
        for value in key_tap_values(button, allow_emergency=allow_emergency)
    )  # type: ignore[return-value]


def encode_display_transaction(display: DisplayBuffer) -> tuple[bytes, bytes, bytes]:
    """Compose the verified radio-to-mic display before/buffer/after sequence."""

    return (
        build_frame(0x02, 0x07, b"\x02"),
        build_frame(0x02, 0x0A, display.raw),
        build_frame(0x02, 0x08, b"\x00\x44"),
    )


def encode_status_led(color: str) -> bytes:
    """Compose the verified two-emitter status LED state."""

    values = {"off": 0x00, "red": 0x02, "green": 0x04, "orange": 0x06}
    try:
        value = values[color]
    except KeyError as exc:
        raise ValueError("status LED must be off, red, green, or orange") from exc
    return build_frame(0x02, 0x02, bytes((value,)))


def encode_backlight_state(state: str) -> bytes:
    """Compose immediate CommandMic backlight state: off, dim, or on."""

    values = {"off": 0x00, "dim": 0x01, "on": 0x02}
    try:
        value = values[state]
    except KeyError as exc:
        raise ValueError("backlight state must be off, dim, or on") from exc
    return build_frame(0x02, 0x0B, bytes((value,)))


def encode_mic_gain_transaction(level: int) -> tuple[bytes, bytes]:
    """Compose the observed two-frame CommandMic microphone-gain transaction."""

    value = int(level)
    if value not in (1, 2, 3, 4, 5):
        raise ValueError("microphone gain must be one of the observed values: 1 through 5")
    return (
        build_frame(0x02, 0x0E, bytes((value,))),
        build_frame(0x02, 0x0E, bytes((value + 1,))),
    )


def encode_ptt_state(action: str) -> bytes:
    """Compose verified mic-to-radio PTT down/up state."""

    if action not in {"press", "release"}:
        raise ValueError("PTT action must be press or release")
    return build_frame(0x01, 0x00, b"\x01" if action == "press" else b"\x00")


def encode_power_state(action: str) -> bytes:
    """Compose verified mic-to-radio Power press/release state."""

    if action not in {"press", "release"}:
        raise ValueError("Power action must be press or release")
    return build_frame(0x01, 0x09, b"\x01" if action == "press" else b"\x00")


def encode_audio_path(state: str) -> bytes:
    """Compose verified radio audio-path open/TX-active/closed state."""

    payloads = {
        "receive_open": b"\x01\x00\x00\x00",
        "transmit_active": b"\x08\x00\x00\x00",
        "closed": bytes(4),
    }
    try:
        payload = payloads[state]
    except KeyError as exc:
        raise ValueError("audio path must be receive_open, transmit_active, or closed") from exc
    return build_frame(0x01, 0x04, payload)


def iter_messages(
    chunks: Iterable[bytes], direction: Direction | str = Direction.UNKNOWN
) -> Iterable[Message]:
    remainder = b""
    for chunk in chunks:
        messages, remainder = parse_stream(remainder + chunk, direction)
        yield from messages
    if remainder:
        yield Message(
            raw=remainder,
            direction=Direction.coerce(direction),
            kind=MessageKind.UNFRAMED,
            framing_valid=False,
            evidence="incomplete trailing stream data",
        )
