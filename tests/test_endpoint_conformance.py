from __future__ import annotations

import json

import pytest

from ip_commandmic import run_loopback_conformance
from ip_commandmic import conformance


def test_public_endpoint_loopback_conformance(tmp_path):
    report = run_loopback_conformance(tmp_path / "conformance")

    assert report.passed, json.dumps(report.to_dict(), indent=2)
    statuses = {check.name: check.status for check in report.checks}
    assert statuses == {
        "stable_startup": "passed",
        "display_round_trip": "passed",
        "status_led_round_trip": "passed",
        "key_press_release": "passed",
        "power_press_release": "passed",
        "backlight_round_trip": "passed",
        "microphone_gain_round_trip": "passed",
        "tcp_fragmentation_coalescing": "passed",
        "radio_to_commandmic_audio": "passed",
        "radio_rtp_impairment_recovery": "passed",
        "fail_closed_disconnect": "passed",
        "endpoint_reconnect": "passed",
        "commandmic_to_radio_live_audio": "passed",
        "mic_rtp_impairment_recovery": "passed",
        "sustained_bidirectional_audio": "passed",
        "midstream_cancellation_recovery": "passed",
        "network_interruption_recovery": "passed",
        "cold_object_restart_matrix": "passed",
        "subprocess_replacement_recovery": "passed",
    }
    assert report.commandmic_audit.stat().st_size > 0
    assert report.radio_audit.stat().st_size > 0
    json.dumps(report.to_dict())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sustained_audio_seconds": 0.5}, "sustained_audio_seconds"),
        ({"cold_restart_cycles": 0}, "cold_restart_cycles"),
    ],
)
def test_loopback_conformance_rejects_unsafe_stress_bounds(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        run_loopback_conformance(tmp_path / "invalid", **kwargs)


def test_conformance_cli_retains_json_report(tmp_path, monkeypatch, capsys):
    report = conformance.ConformanceReport(
        checks=(conformance.ConformanceCheck("example", "passed", "ok"),),
        elapsed_seconds=1.25,
        commandmic_audit=tmp_path / "mic.jsonl",
        radio_audit=tmp_path / "radio.jsonl",
    )
    monkeypatch.setattr(conformance, "run_loopback_conformance", lambda *args, **kwargs: report)

    assert conformance.main(["--artifact-directory", str(tmp_path)]) == 0
    retained = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    printed = json.loads(capsys.readouterr().out)
    assert retained == printed == report.to_dict()


def test_callback_latency_matching_preserves_rtp_sequence_wraparound() -> None:
    arrivals = [
        (0xFFFE, 10.000),
        (0xFFFF, 10.020),
        (0x0000, 10.040),
        (0x0001, 10.060),
        (0xFFFE, 1320.720),
    ]
    callbacks = [
        (sequence, arrived_at + 0.001)
        for sequence, arrived_at in arrivals
    ]

    assert conformance._rtp_callback_latencies_ms(arrivals, callbacks) == pytest.approx(
        [1.0] * len(arrivals)
    )


def _sustained_summary(
    packet_count: int, *, concealed_sequences: list[int] | None = None
) -> dict[str, object]:
    concealed_sequences = concealed_sequences or []
    concealed = len(concealed_sequences)
    return {
        "session": 1,
        "source_packets": packet_count,
        "received": packet_count - concealed,
        "played": packet_count,
        "concealed": concealed,
        "duplicates": 0,
        "late": concealed,
        "discontinuities": 0,
        "sequences": list(range(packet_count)),
        "concealed_sequences": concealed_sequences,
        "concealment_is_silence": True,
        "callback_times": [
            (index & 0xFFFF, float(index)) for index in range(packet_count)
        ],
    }


def test_sustained_playout_accepts_isolated_100_ppm_scheduler_outliers() -> None:
    summary = _sustained_summary(
        90_000, concealed_sequences=[10_000, 40_000, 70_000]
    )

    assert conformance._validate_sustained_radio_playout(
        summary, expected_packets=90_000
    ) == (3, 9)


def test_sustained_playout_rejects_outliers_over_budget() -> None:
    summary = _sustained_summary(
        90_000, concealed_sequences=list(range(0, 90_000, 9_000))
    )

    with pytest.raises(AssertionError, match="scheduling-outlier budget"):
        conformance._validate_sustained_radio_playout(
            summary, expected_packets=90_000
        )


def test_sustained_playout_rejects_consecutive_concealments() -> None:
    summary = _sustained_summary(90_000, concealed_sequences=[10_000, 10_001])

    with pytest.raises(AssertionError, match="consecutive concealments"):
        conformance._validate_sustained_radio_playout(
            summary, expected_packets=90_000
        )


def test_continuous_rtp_timeline_accepts_wrap_and_rejects_loss() -> None:
    conformance._assert_continuous_rtp_timeline(
        [(0xFFFE, 1.0), (0xFFFF, 1.02), (0, 1.04), (1, 1.06)],
        label="test",
    )

    with pytest.raises(AssertionError, match="expected=2, actual=3"):
        conformance._assert_continuous_rtp_timeline(
            [(1, 1.0), (3, 1.02)], label="test"
        )
