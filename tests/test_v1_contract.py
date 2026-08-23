from __future__ import annotations

from pathlib import Path
from importlib.resources import files

import ip_commandmic as icom


def test_v1_export_classes_are_complete_and_disjoint() -> None:
    advanced = set(icom.V1_ADVANCED_EXPORTS)
    stable = set(icom.V1_STABLE_EXPORTS)
    public_symbols = set(icom.__all__) - {"V1_STABLE_EXPORTS", "V1_ADVANCED_EXPORTS"}

    assert advanced == {
        "AuditLog",
        "CommandMicEmulator",
        "EmulatorConfig",
        "VerifiedMicUdpProtocol",
        "VerifiedRadioUdpProtocol",
    }
    assert stable.isdisjoint(advanced)
    assert stable | advanced == public_symbols
    assert {
        "SoftwareCommandMicEndpoint",
        "SoftwareRadioEndpoint",
        "SoftwareRadioConfig",
        "EndpointState",
        "DisplayBuffer",
        "parse_stream",
        "encode_mic_gain_transaction",
        "run_loopback_conformance",
    } <= stable


def test_v1_endpoint_method_contract_is_present() -> None:
    assert {
        "start",
        "stop",
        "tap",
        "key",
        "ptt",
        "set_tx_armed",
    } <= set(dir(icom.SoftwareCommandMicEndpoint))
    assert {
        "start",
        "stop",
        "send_display",
        "send_led",
        "send_backlight",
        "set_mic_gain",
        "set_speaker_volume",
        "send_tone",
        "send_wav",
        "send_audio_file",
        "stop_audio_playback",
        "start_recording",
        "stop_recording",
    } <= set(dir(icom.SoftwareRadioEndpoint))


def test_v1_scope_records_required_boundaries() -> None:
    scope = (Path(__file__).parents[1] / "docs" / "V1_SCOPE.md").read_text(
        encoding="utf-8"
    )
    for heading in (
        "## Stable version 1 surface",
        "## Advanced and experimental surface",
        "## Release gates",
        "## Explicit post-v1 research",
        "## Evidence and safety boundary",
    ):
        assert heading in scope
    assert "30-minute hardware-free bidirectional soak" in scope
    assert "bounded five-minute physical idle/active soak" in scope
    assert "synchronized acoustic/RF mouth-to-speaker" in scope
    assert "true subprocess and network-interruption" in scope
    assert "Emergency-mode behavior" in scope


def test_distribution_declares_inline_type_information() -> None:
    assert files("ip_commandmic").joinpath("py.typed").is_file()


def test_scheduled_conformance_stays_on_bounded_windows_contract() -> None:
    workflow_path = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "extended-conformance.yml"
    )
    # Distribution verification copies the public test suite but intentionally
    # excludes repository automation metadata.
    if not workflow_path.exists():
        return
    workflow = workflow_path.read_text(encoding="utf-8")
    assert "runs-on: windows-latest" in workflow
    assert "--sustained-audio-seconds 150" in workflow
    assert "--cold-restart-cycles 10" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "--sustained-audio-seconds 1800" not in workflow


def test_normative_docs_and_dissector_cover_every_typed_composer() -> None:
    root = Path(__file__).parents[1]
    protocol = (root / "docs" / "PROTOCOL.md").read_text(encoding="utf-8")
    dissector = (root / "wireshark" / "ip_commandmic.lua").read_text(
        encoding="utf-8"
    )
    expected = {
        "encode_key_state": ("`01/01`", 'kind = "key_state"'),
        "encode_key_tap": ("`01/01`", 'kind = "key_state"'),
        "encode_display_transaction": (
            "`02/07` → `02/0a` → `02/08`",
            'kind = "display_update"',
        ),
        "encode_status_led": ("`02/02`", 'kind = "audio_status"'),
        "encode_backlight_state": ("`02/0b`", 'kind = "backlight_state"'),
        "encode_mic_gain_transaction": ("`02/0e` × 2", 'kind = "mic_gain"'),
        "encode_ptt_state": ("`01/00`", 'kind = "ptt_state"'),
        "encode_power_state": ("`01/09`", 'kind = "power_state"'),
        "encode_audio_path": ("`01/04`", 'kind = "audio_state"'),
    }
    for composer, (wire_family, lua_kind) in expected.items():
        assert composer in protocol
        assert wire_family in protocol
        assert lua_kind in dissector
    for field in (
        "ipcommandmic.audio_state",
        "ipcommandmic.audio_path_open",
        "ipcommandmic.mic_gain.value",
        "ipcommandmic.backlight.state",
        "ipcommandmic.status_led.color",
    ):
        assert field in dissector
