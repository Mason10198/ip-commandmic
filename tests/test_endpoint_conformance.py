from __future__ import annotations

import json

import pytest

from ip_commandmic import run_loopback_conformance


def test_public_endpoint_loopback_conformance(tmp_path):
    report = run_loopback_conformance(tmp_path / "conformance")

    assert report.passed, json.dumps(report.to_dict(), indent=2)
    statuses = {check.name: check.status for check in report.checks}
    assert statuses == {
        "stable_startup": "passed",
        "display_round_trip": "passed",
        "status_led_round_trip": "passed",
        "key_press_release": "passed",
        "tcp_fragmentation_coalescing": "passed",
        "radio_to_commandmic_audio": "passed",
        "radio_rtp_impairment_recovery": "passed",
        "fail_closed_disconnect": "passed",
        "endpoint_reconnect": "passed",
        "commandmic_to_radio_live_audio": "passed",
        "mic_rtp_impairment_recovery": "passed",
        "sustained_bidirectional_audio": "passed",
        "midstream_cancellation_recovery": "passed",
        "cold_object_restart_matrix": "passed",
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
