-- Evidence-driven Wireshark dissector for the Icom F5330D/F6330D CommandMic.
-- Install via Analyze > Lua Plugins or load with:
--   tshark -X lua_script:wireshark/ip_commandmic.lua ...

local ipcommandmic = Proto("ipcommandmic", "Icom CommandMic")

local f_type = ProtoField.string("ipcommandmic.type", "Message type")
local f_format = ProtoField.string("ipcommandmic.format", "Frame format")
local f_direction = ProtoField.string("ipcommandmic.direction", "Observed direction")
local f_length = ProtoField.uint16("ipcommandmic.length", "Wire length", base.DEC)
local f_decoded_length = ProtoField.uint16("ipcommandmic.decoded_length", "Decoded length", base.DEC)
local f_start = ProtoField.uint8("ipcommandmic.start", "Start byte", base.HEX)
local f_class = ProtoField.uint8("ipcommandmic.class", "Message class", base.HEX)
local f_command = ProtoField.uint8("ipcommandmic.command", "Command", base.HEX)
local f_payload_length = ProtoField.uint16("ipcommandmic.payload_length", "Declared payload length", base.DEC)
local f_payload_hex = ProtoField.string("ipcommandmic.payload_hex", "Decoded payload")
local f_key_wire_value = ProtoField.uint8("ipcommandmic.key_wire_value", "Key wire value", base.HEX)
local f_key_button = ProtoField.string("ipcommandmic.key_button", "Verified key button")
local f_key_action = ProtoField.string("ipcommandmic.key_action", "Verified key action")
local f_display_ascii = ProtoField.string("ipcommandmic.display_ascii", "Display ASCII projection")
local f_display_text = ProtoField.string("ipcommandmic.display_text", "Verified primary display text")
local f_display_sync_phase = ProtoField.string("ipcommandmic.display_sync_phase", "Display sync phase")
local f_display_indicators_56 = ProtoField.uint8("ipcommandmic.display.indicators_56", "Verified indicators (offset 56)", base.HEX)
local f_display_indicators_57 = ProtoField.uint8("ipcommandmic.display.indicators_57", "Verified indicators (offset 57)", base.HEX)
local f_display_keys_points_58 = ProtoField.uint8("ipcommandmic.display.keys_points_58", "P1-P4 and points 1-4 (offset 58)", base.HEX)
local f_display_points_59 = ProtoField.uint8("ipcommandmic.display.points_59", "Points 5-8 (offset 59)", base.HEX)
local f_display_blink_60 = ProtoField.uint8("ipcommandmic.display.blink_60", "Indicator blink mask (offset 60)", base.HEX)
local f_display_blink_61 = ProtoField.uint8("ipcommandmic.display.blink_61", "Secondary indicator blink mask (offset 61)", base.HEX)
local f_display_blink_62 = ProtoField.uint8("ipcommandmic.display.blink_62", "P1-P4/points blink mask (offset 62)", base.HEX)
local f_display_blink_63 = ProtoField.uint8("ipcommandmic.display.blink_63", "Points 5-8 blink mask (offset 63)", base.HEX)
local f_display_control_64 = ProtoField.uint8("ipcommandmic.display.control_64", "Display control byte 64", base.HEX)
local f_display_control_65 = ProtoField.uint8("ipcommandmic.display.control_65", "Display control byte 65", base.HEX)
local f_display_control_66 = ProtoField.uint8("ipcommandmic.display.control_66", "Display control byte 66", base.HEX)
local f_display_control_67 = ProtoField.uint8("ipcommandmic.display.control_67", "Display control byte 67", base.HEX)
local f_volume_level = ProtoField.uint8("ipcommandmic.volume_level", "Verified volume level", base.DEC)
local f_ptt_active = ProtoField.bool("ipcommandmic.ptt_active", "PTT active")
local f_ptt_action = ProtoField.string("ipcommandmic.ptt_action", "PTT action")
local f_audio_state = ProtoField.string("ipcommandmic.audio_state", "Verified audio-path state")
local f_audio_path_open = ProtoField.bool("ipcommandmic.audio_path_open", "Audio path open")
local f_power_active = ProtoField.bool("ipcommandmic.power_active", "Power button active")
local f_power_action = ProtoField.string("ipcommandmic.power_action", "Power action")
local f_mic_gain_value = ProtoField.uint8("ipcommandmic.mic_gain.value", "Mic gain value", base.DEC)
local f_backlight_value = ProtoField.uint8("ipcommandmic.backlight.value", "Backlight value", base.HEX)
local f_backlight_state = ProtoField.string("ipcommandmic.backlight.state", "Verified backlight state")
local f_status_led_red = ProtoField.bool("ipcommandmic.status_led.red", "Status LED red emitter")
local f_status_led_green = ProtoField.bool("ipcommandmic.status_led.green", "Status LED green emitter")
local f_status_led_color = ProtoField.string("ipcommandmic.status_led.color", "Verified status LED color")
local f_sequence = ProtoField.uint32("ipcommandmic.sequence", "Sequence (unverified)", base.DEC)
local f_state = ProtoField.uint32("ipcommandmic.state", "State (unverified)", base.HEX)
local f_checksum = ProtoField.uint16("ipcommandmic.checksum", "CRC-16/Modbus (big-endian)", base.HEX)
local f_checksum_ok = ProtoField.bool("ipcommandmic.checksum_ok", "Checksum valid")
local f_stuffed = ProtoField.bool("ipcommandmic.stuffed", "Wire byte-stuffing present")
local f_magic = ProtoField.bytes("ipcommandmic.magic", "Magic")
local f_unknown = ProtoField.bytes("ipcommandmic.unknown", "Unknown bytes")
local f_terminator = ProtoField.uint8("ipcommandmic.terminator", "Terminator", base.HEX)

ipcommandmic.fields = {
    f_type,
    f_format,
    f_direction,
    f_length,
    f_decoded_length,
    f_start,
    f_class,
    f_command,
    f_payload_length,
    f_payload_hex,
    f_key_wire_value,
    f_key_button,
    f_key_action,
    f_display_ascii,
    f_display_text,
    f_display_sync_phase,
    f_display_indicators_56,
    f_display_indicators_57,
    f_display_keys_points_58,
    f_display_points_59,
    f_display_blink_60,
    f_display_blink_61,
    f_display_blink_62,
    f_display_blink_63,
    f_display_control_64,
    f_display_control_65,
    f_display_control_66,
    f_display_control_67,
    f_volume_level,
    f_ptt_active,
    f_ptt_action,
    f_audio_state,
    f_audio_path_open,
    f_power_active,
    f_power_action,
    f_mic_gain_value,
    f_backlight_value,
    f_backlight_state,
    f_status_led_red,
    f_status_led_green,
    f_status_led_color,
    f_sequence,
    f_state,
    f_checksum,
    f_checksum_ok,
    f_stuffed,
    f_magic,
    f_unknown,
    f_terminator,
}

local expert_invalid = ProtoExpert.new(
    "ipcommandmic.expert.invalid_framing",
    "Bytes outside the currently evidenced framing",
    expert.group.MALFORMED,
    expert.severity.WARN
)
local expert_bad_checksum = ProtoExpert.new(
    "ipcommandmic.expert.bad_checksum",
    "CommandMic CRC mismatch",
    expert.group.CHECKSUM,
    expert.severity.ERROR
)
ipcommandmic.experts = { expert_invalid, expert_bad_checksum }

local radio_heartbeat = "f34171050000024d003570fd"
local mic_heartbeat = "f34171050000026d0135a8fd"

local function hex_of(range)
    return string.lower(range:bytes():tohex())
end

local function is_magic(buffer, offset)
    if buffer:len() - offset < 3 then
        return false
    end
    local start = buffer(offset, 1):uint()
    return (start == 0xf3 or start == 0xf5)
        and buffer(offset + 1, 1):uint() == 0x41
        and buffer(offset + 2, 1):uint() == 0x71
end

local function xor16(left, right)
    local result = 0
    local place = 1
    for _ = 1, 16 do
        if (left % 2) ~= (right % 2) then
            result = result + place
        end
        left = math.floor(left / 2)
        right = math.floor(right / 2)
        place = place * 2
    end
    return result
end

local function commandmic_crc(decoded)
    local crc = 0xffff
    -- Exclude literal start byte, two-byte CRC, and terminator.
    for index = 2, #decoded - 3 do
        crc = xor16(crc, decoded[index])
        for _ = 1, 8 do
            if crc % 2 == 1 then
                crc = xor16(math.floor(crc / 2), 0xa001)
            else
                crc = math.floor(crc / 2)
            end
        end
    end
    return crc
end

local function decode_wire_frame(range)
    local wire = range:bytes()
    local decoded = {}
    local stuffed = false
    local index = 0
    while index < wire:len() do
        local value = wire:get_index(index)
        if index > 0 and index < wire:len() - 1 and value == 0xff
            and index + 1 < wire:len() - 1 and wire:get_index(index + 1) <= 0x0f then
            table.insert(decoded, 0xf0 + wire:get_index(index + 1))
            stuffed = true
            index = index + 2
        else
            table.insert(decoded, value)
            index = index + 1
        end
    end
    return decoded, stuffed
end

local function bytes_to_hex(values, first, last)
    local parts = {}
    for index = first, last do
        table.insert(parts, string.format("%02x", values[index]))
    end
    return table.concat(parts)
end

local function direction_for(pinfo, hex)
    if tostring(pinfo.src) == "192.168.0.1" or hex == radio_heartbeat then
        return "radio_to_mic"
    elseif tostring(pinfo.src) == "192.168.0.2" or hex == mic_heartbeat then
        return "mic_to_radio"
    end
    return "unknown"
end

local function message_type(hex)
    if hex == radio_heartbeat or hex == mic_heartbeat then
        return "heartbeat"
    end
    return "unknown"
end

local verified_key_states = {
    [0x40] = { "emergency", "press" },
    [0xc0] = { "emergency", "release" },
    [0x00] = { "f1", "press" },
    [0x80] = { "f1", "release" },
    [0x34] = { "keypad_0", "press" },
    [0xb4] = { "keypad_0", "release" },
    [0x03] = { "keypad_1", "press" },
    [0x83] = { "keypad_1", "release" },
    [0x04] = { "keypad_2", "press" },
    [0x84] = { "keypad_2", "release" },
    [0x05] = { "keypad_3", "press" },
    [0x85] = { "keypad_3", "release" },
    [0x13] = { "keypad_4", "press" },
    [0x93] = { "keypad_4", "release" },
    [0x14] = { "keypad_5", "press" },
    [0x94] = { "keypad_5", "release" },
    [0x15] = { "keypad_6", "press" },
    [0x95] = { "keypad_6", "release" },
    [0x23] = { "keypad_7", "press" },
    [0xa3] = { "keypad_7", "release" },
    [0x24] = { "keypad_8", "press" },
    [0xa4] = { "keypad_8", "release" },
    [0x25] = { "keypad_9", "press" },
    [0xa5] = { "keypad_9", "release" },
    [0x33] = { "keypad_star", "press" },
    [0xb3] = { "keypad_star", "release" },
    [0x35] = { "keypad_hash", "press" },
    [0xb5] = { "keypad_hash", "release" },
    [0x02] = { "p1", "press" },
    [0x82] = { "p1", "release" },
    [0x12] = { "p2", "press" },
    [0x92] = { "p2", "release" },
    [0x22] = { "p3", "press" },
    [0xa2] = { "p3", "release" },
    [0x32] = { "p4", "press" },
    [0xb2] = { "p4", "release" },
    [0x20] = { "up", "press" },
    [0xa0] = { "up", "release" },
    [0x21] = { "down", "press" },
    [0xa1] = { "down", "release" },
    [0x31] = { "left", "press" },
    [0xb1] = { "left", "release" },
    [0x30] = { "right", "press" },
    [0xb0] = { "right", "release" },
    [0x01] = { "volume_down", "press" },
    [0x81] = { "volume_down", "release" },
    [0x10] = { "volume_up", "press" },
    [0x90] = { "volume_up", "release" },
    [0x7f] = { "", "neutral" },
}

local function ascii_projection(values, first, last)
    local chars = {}
    for index = first, last do
        local value = values[index]
        table.insert(chars, value >= 0x20 and value <= 0x7e and string.char(value) or ".")
    end
    return table.concat(chars)
end

local function find_terminator(buffer, start_offset)
    for offset = start_offset, buffer:len() - 1 do
        if buffer(offset, 1):uint() == 0xfd then
            return offset
        end
    end
    return nil
end

local function find_magic(buffer, start_offset, stop_offset)
    local final_offset = math.min(stop_offset or (buffer:len() - 2), buffer:len() - 2)
    for offset = start_offset, final_offset do
        if is_magic(buffer, offset) then
            return offset
        end
    end
    return nil
end

function ipcommandmic.dissector(buffer, pinfo, tree)
    if buffer:len() < 3 then
        pinfo.desegment_offset = 0
        pinfo.desegment_len = DESEGMENT_ONE_MORE_SEGMENT
        return buffer:len()
    end

    if not is_magic(buffer, 0) then
        return 0
    end

    pinfo.cols.protocol = "ICOMCM"
    local root = tree:add(ipcommandmic, buffer(), "Icom CommandMic stream")
    local offset = 0
    while offset < buffer:len() do
        if buffer:len() - offset < 3 then
            pinfo.desegment_offset = offset
            pinfo.desegment_len = DESEGMENT_ONE_MORE_SEGMENT
            return buffer:len()
        end

        if not is_magic(buffer, offset) then
            local malformed = root:add(f_unknown, buffer(offset, 1))
            malformed:add_proto_expert_info(expert_invalid)
            offset = offset + 1
        else
            local finish = find_terminator(buffer, offset + 3)
            local nested_magic = find_magic(buffer, offset + 3, finish)
            if nested_magic ~= nil then
                local malformed = root:add(f_unknown, buffer(offset, nested_magic - offset))
                malformed:add_proto_expert_info(expert_invalid)
                offset = nested_magic
            elseif finish == nil then
                pinfo.desegment_offset = offset
                pinfo.desegment_len = DESEGMENT_ONE_MORE_SEGMENT
                return buffer:len()
            else
            local length = finish - offset + 1
            local range = buffer(offset, length)
            local hex = hex_of(range)
            local decoded, stuffed = decode_wire_frame(range)
            local declared_length = nil
            local ordinary = false
            if #decoded >= 10 then
                declared_length = decoded[6] * 256 + decoded[7]
                ordinary = #decoded == declared_length + 10
            end
            local direction = direction_for(pinfo, hex)
            local kind = message_type(hex)
            if ordinary and direction == "mic_to_radio" and decoded[4] == 0x01
                and decoded[5] == 0x01 and declared_length == 1 then
                kind = "key_state"
            elseif ordinary and direction == "mic_to_radio" and decoded[4] == 0x01
                and decoded[5] == 0x00 and declared_length == 1
                and (decoded[8] == 0x00 or decoded[8] == 0x01) then
                kind = "ptt_state"
            elseif ordinary and direction == "radio_to_mic" and decoded[4] == 0x01
                and decoded[5] == 0x04 and declared_length == 4
                and ((decoded[8] == 0x00 and decoded[9] == 0x00
                        and decoded[10] == 0x00 and decoded[11] == 0x00)
                    or (decoded[8] == 0x01 and decoded[9] == 0x00
                        and decoded[10] == 0x00 and decoded[11] == 0x00)
                    or (decoded[8] == 0x08 and decoded[9] == 0x00
                        and decoded[10] == 0x00 and decoded[11] == 0x00)) then
                kind = "audio_state"
            elseif ordinary and direction == "mic_to_radio" and decoded[4] == 0x01
                and decoded[5] == 0x09 and declared_length == 1
                and (decoded[8] == 0x00 or decoded[8] == 0x01) then
                kind = "power_state"
            elseif ordinary and direction == "radio_to_mic" and decoded[4] == 0x02
                and decoded[5] == 0x0b and declared_length == 1
                and (decoded[8] == 0x00 or decoded[8] == 0x01
                    or decoded[8] == 0x02) then
                kind = "backlight_state"
            elseif ordinary and direction == "radio_to_mic" and decoded[4] == 0x02
                and decoded[5] == 0x0e and declared_length == 1
                and decoded[8] >= 0x01 and decoded[8] <= 0x06 then
                kind = "mic_gain"
            elseif ordinary and direction == "radio_to_mic" and decoded[4] == 0x02
                and decoded[5] == 0x02 and declared_length == 1
                and (decoded[8] == 0x00 or decoded[8] == 0x02
                    or decoded[8] == 0x04 or decoded[8] == 0x06) then
                kind = "audio_status"
            elseif ordinary and direction == "radio_to_mic" and decoded[4] == 0x02
                and decoded[5] == 0x07 and declared_length == 1
                and decoded[8] == 0x02 then
                kind = "display_sync"
            elseif ordinary and direction == "radio_to_mic" and decoded[4] == 0x02
                and decoded[5] == 0x0a and declared_length == 68 then
                kind = "display_update"
            elseif ordinary and direction == "radio_to_mic" and decoded[4] == 0x02
                and decoded[5] == 0x08 and declared_length == 2
                and decoded[8] == 0x00 and decoded[9] == 0x44 then
                kind = "display_sync"
            elseif ordinary and direction == "mic_to_radio" and decoded[4] == 0x02
                and decoded[5] == 0x09 and declared_length == 1
                and decoded[8] == 0x01 then
                kind = "display_ack"
            end
            local format = ordinary and "ordinary" or "special_or_unknown"
            local observed_checksum = decoded[#decoded - 2] * 256 + decoded[#decoded - 1]
            local checksum_ok = commandmic_crc(decoded) == observed_checksum
            local subtree = root:add(ipcommandmic, range, "CommandMic " .. kind)
            subtree:add(f_type, kind)
            subtree:add(f_format, format)
            subtree:add(f_direction, direction)
            subtree:add(f_length, length)
            subtree:add(f_decoded_length, #decoded)
            subtree:add(f_start, decoded[1])
            subtree:add(f_magic, buffer(offset, 3))
            subtree:add(f_stuffed, stuffed)
            subtree:add(f_checksum, observed_checksum)
            local checksum_item = subtree:add(f_checksum_ok, checksum_ok)
            if not checksum_ok then
                checksum_item:add_proto_expert_info(expert_bad_checksum)
            end
            if ordinary then
                subtree:add(f_class, decoded[4])
                subtree:add(f_command, decoded[5])
                subtree:add(f_payload_length, declared_length)
                subtree:add(f_payload_hex, bytes_to_hex(decoded, 8, 7 + declared_length))
                if kind == "key_state" then
                    local key_value = decoded[8]
                    local key_state = verified_key_states[key_value]
                    subtree:add(f_key_wire_value, key_value)
                    if key_state ~= nil then
                        if key_state[1] ~= "" then
                            subtree:add(f_key_button, key_state[1])
                        end
                        subtree:add(f_key_action, key_state[2])
                    else
                        subtree:add(f_key_action, "unknown")
                    end
                elseif kind == "ptt_state" then
                    subtree:add(f_ptt_active, decoded[8] == 0x01)
                    subtree:add(f_ptt_action, decoded[8] == 0x01 and "press" or "release")
                elseif kind == "audio_state" then
                    local audio_state = "closed"
                    if decoded[8] == 0x01 then
                        audio_state = "receive_open"
                    elseif decoded[8] == 0x08 then
                        audio_state = "transmit_active"
                    end
                    subtree:add(f_audio_state, audio_state)
                    subtree:add(f_audio_path_open, decoded[8] ~= 0x00)
                elseif kind == "power_state" then
                    subtree:add(f_power_active, decoded[8] == 0x01)
                    subtree:add(
                        f_power_action,
                        decoded[8] == 0x01 and "press" or "release"
                    )
                elseif kind == "mic_gain" then
                    subtree:add(f_mic_gain_value, decoded[8])
                elseif kind == "backlight_state" then
                    subtree:add(f_backlight_value, decoded[8])
                    local backlight_state = "on"
                    if decoded[8] == 0x00 then
                        backlight_state = "off"
                    elseif decoded[8] == 0x01 then
                        backlight_state = "dim"
                    end
                    subtree:add(f_backlight_state, backlight_state)
                elseif kind == "audio_status" then
                    local red = decoded[8] == 0x02 or decoded[8] == 0x06
                    local green = decoded[8] == 0x04 or decoded[8] == 0x06
                    local color = "off"
                    if red and green then
                        color = "orange"
                    elseif red then
                        color = "red"
                    elseif green then
                        color = "green"
                    end
                    subtree:add(f_status_led_red, red)
                    subtree:add(f_status_led_green, green)
                    subtree:add(f_status_led_color, color)
                elseif kind == "display_update" then
                    subtree:add(f_display_ascii, ascii_projection(decoded, 8, 75))
                    subtree:add(f_display_text, ascii_projection(decoded, 8, 15))
                    subtree:add(f_display_indicators_56, decoded[64])
                    subtree:add(f_display_indicators_57, decoded[65])
                    subtree:add(f_display_keys_points_58, decoded[66])
                    subtree:add(f_display_points_59, decoded[67])
                    subtree:add(f_display_blink_60, decoded[68])
                    subtree:add(f_display_blink_61, decoded[69])
                    subtree:add(f_display_blink_62, decoded[70])
                    subtree:add(f_display_blink_63, decoded[71])
                    subtree:add(f_display_control_64, decoded[72])
                    subtree:add(f_display_control_65, decoded[73])
                    subtree:add(f_display_control_66, decoded[74])
                    subtree:add(f_display_control_67, decoded[75])
                    if decoded[8] == 0x20 and decoded[9] == 0x56
                        and decoded[10] == 0x4f and decoded[11] == 0x4c
                        and decoded[12] == 0x20 and decoded[13] == 0x20
                        and decoded[14] >= 0x30 and decoded[14] <= 0x39
                        and decoded[15] == 0x00 then
                        subtree:add(f_volume_level, decoded[14] - 0x30)
                    end
                elseif kind == "display_sync" then
                    subtree:add(
                        f_display_sync_phase,
                        decoded[5] == 0x07 and "before_buffer" or "after_buffer"
                    )
                end
            end
            if length > 3 then
                subtree:add(f_unknown, buffer(offset + 3, length - 4))
            end
            subtree:add(f_terminator, buffer(finish, 1))
            -- Sequence, state, and audio fields remain unset until captures prove them.
            offset = finish + 1
            end
        end
    end
    return buffer:len()
end

ipcommandmic:register_heuristic("tcp", function(buffer, pinfo, tree)
    if buffer:len() < 3 or not is_magic(buffer, 0) then
        return false
    end
    ipcommandmic.dissector(buffer, pinfo, tree)
    return true
end)

DissectorTable.get("tcp.port"):add(52001, ipcommandmic)

local ipcommandmic_rtp = Proto("ipcommandmicrtp", "Icom CommandMic RTP audio")
local f_audio = ProtoField.bool("ipcommandmic.audio", "Audio message")
local f_rtp_version = ProtoField.uint8("ipcommandmic.rtp.version", "RTP version", base.DEC)
local f_rtp_marker = ProtoField.bool("ipcommandmic.rtp.marker", "RTP marker")
local f_rtp_payload_type = ProtoField.uint8("ipcommandmic.rtp.payload_type", "RTP payload type", base.DEC)
local f_rtp_sequence = ProtoField.uint16("ipcommandmic.rtp.sequence", "RTP sequence", base.DEC)
local f_rtp_timestamp = ProtoField.uint32("ipcommandmic.rtp.timestamp", "RTP timestamp", base.DEC)
local f_rtp_ssrc = ProtoField.uint32("ipcommandmic.rtp.ssrc", "RTP SSRC", base.HEX)
local f_rtp_payload = ProtoField.bytes("ipcommandmic.rtp.payload", "Signed 16-bit big-endian PCM candidate")
ipcommandmic_rtp.fields = {
    f_audio,
    f_rtp_version,
    f_rtp_marker,
    f_rtp_payload_type,
    f_rtp_sequence,
    f_rtp_timestamp,
    f_rtp_ssrc,
    f_rtp_payload,
}

function ipcommandmic_rtp.dissector(buffer, pinfo, tree)
    if buffer:len() < 12 or math.floor(buffer(0, 1):uint() / 64) ~= 2 then
        return 0
    end
    local csrc_count = buffer(0, 1):uint() % 16
    local extension = math.floor(buffer(0, 1):uint() / 16) % 2 == 1
    local header_length = 12 + csrc_count * 4
    if buffer:len() < header_length then
        return 0
    end
    if extension then
        if buffer:len() < header_length + 4 then
            return 0
        end
        header_length = header_length + 4 + buffer(header_length + 2, 2):uint() * 4
        if buffer:len() < header_length then
            return 0
        end
    end
    pinfo.cols.protocol = "ICOMCM-RTP"
    local root = tree:add(ipcommandmic_rtp, buffer(), "Icom CommandMic RTP audio")
    root:add(f_audio, true)
    root:add(f_rtp_version, 2)
    root:add(f_rtp_marker, buffer(1, 1):uint() >= 0x80)
    root:add(f_rtp_payload_type, buffer(1, 1):uint() % 0x80)
    root:add(f_rtp_sequence, buffer(2, 2))
    root:add(f_rtp_timestamp, buffer(4, 4))
    root:add(f_rtp_ssrc, buffer(8, 4))
    if buffer:len() > header_length then
        root:add(f_rtp_payload, buffer(header_length))
    end
    return buffer:len()
end

DissectorTable.get("udp.port"):add(50000, ipcommandmic_rtp)
