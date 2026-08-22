from __future__ import annotations

import runpy
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_physical_acceptance.py"
MODULE = runpy.run_path(str(SCRIPT))


def test_stable_state_requires_connection_and_controls() -> None:
    is_stable = MODULE["_is_stable"]
    assert is_stable({"connection": "connected", "controls_ready": True})
    assert not is_stable({"connection": "connected", "controls_ready": False})
    assert not is_stable({"connection": "waiting_for_radio", "controls_ready": True})


def test_safety_gate_rejects_both_endpoint_ptt_shapes() -> None:
    safety_error = MODULE["_safety_error"]
    assert safety_error({"ptt": True}) == "PTT became active"
    assert safety_error({"ptt_active": True}) == "PTT became active"
    assert safety_error({"last_error": "boom"}) == "endpoint error: boom"
    assert safety_error({}) is None


def test_physical_soak_is_bounded_to_five_minutes() -> None:
    parse_args = MODULE["_parse_args"]
    accepted = parse_args(["--role", "software-commandmic", "--soak-seconds", "300"])
    assert accepted.soak_seconds == 300
    with pytest.raises(SystemExit):
        parse_args(["--role", "software-commandmic", "--soak-seconds", "301"])
