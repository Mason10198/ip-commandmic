"""Run bounded manual-power-cycle and soak acceptance against physical hardware."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from ip_commandmic import (
    SoftwareCommandMicEndpoint,
    SoftwareRadioConfig,
    SoftwareRadioEndpoint,
)


def _cue(kind: str) -> None:
    try:
        import winsound

        patterns = {
            "unplug": ((1200, 180), (1200, 180), (1200, 180)),
            "restore": ((500, 500),),
            "passed": ((700, 120), (900, 120), (1200, 220)),
            "failed": ((350, 700),),
        }
        for frequency, duration in patterns[kind]:
            winsound.Beep(frequency, duration)
            time.sleep(0.08)
    except (ImportError, RuntimeError):
        print("\a", end="", flush=True)


def _state_key(snapshot: dict[str, Any]) -> tuple[object, ...]:
    return (
        snapshot.get("connection"),
        bool(snapshot.get("controls_ready")),
        bool(snapshot.get("ptt", snapshot.get("ptt_active", False))),
        bool(snapshot.get("rx_audio_open", False)),
        snapshot.get("last_error"),
    )


def _is_stable(snapshot: dict[str, Any]) -> bool:
    return snapshot.get("connection") == "connected" and bool(
        snapshot.get("controls_ready")
    )


def _safety_error(snapshot: dict[str, Any]) -> str | None:
    if snapshot.get("ptt", snapshot.get("ptt_active", False)):
        return "PTT became active"
    error = snapshot.get("last_error")
    if error:
        return f"endpoint error: {error}"
    return None


def _observe_until(
    snapshot: Callable[[], dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float,
    started: float,
    transitions: list[dict[str, object]],
    require_stable: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_key: tuple[object, ...] | None = None
    while time.monotonic() < deadline:
        current = snapshot()
        key = _state_key(current)
        if key != last_key:
            transitions.append(
                {
                    "seconds": round(time.monotonic() - started, 3),
                    "connection": current.get("connection"),
                    "controls_ready": bool(current.get("controls_ready")),
                    "ptt": bool(current.get("ptt", current.get("ptt_active", False))),
                    "rx_audio_open": bool(current.get("rx_audio_open", False)),
                    "last_error": current.get("last_error"),
                }
            )
            last_key = key
        problem = _safety_error(current)
        if problem:
            raise RuntimeError(problem)
        if require_stable and not _is_stable(current):
            raise RuntimeError("session left the stable state")
        if predicate(current):
            return current
        time.sleep(0.1)
    raise TimeoutError(f"condition was not reached within {timeout:.1f} seconds")


def _build_endpoint(args: argparse.Namespace, audit: Path) -> object:
    if args.role == "software-commandmic":
        if not args.dummy_load_confirmed:
            raise RuntimeError(
                "--dummy-load-confirmed is required for the real-radio role"
            )
        return SoftwareCommandMicEndpoint(
            local_ip=args.local_ip or "192.168.0.2",
            radio_ip=args.peer_ip or "192.168.0.1",
            microphone_device=None,
            enable_tx=False,
            play_rx_audio=False,
            audit_path=audit,
        )
    if not args.real_radio_disconnected:
        raise RuntimeError(
            "--real-radio-disconnected is required for the physical-CommandMic role"
        )
    return SoftwareRadioEndpoint(
        SoftwareRadioConfig(
            local_ip=args.local_ip or "192.168.0.1",
            mic_ip=args.peer_ip or "192.168.0.2",
            automatic_key_responses=False,
            automatic_ptt_responses=False,
            speaker_volume=22,
        ),
        audit,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role", choices=("software-commandmic", "software-radio"), required=True
    )
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--soak-seconds", type=float, default=300.0)
    parser.add_argument("--initial-timeout", type=float, default=90.0)
    parser.add_argument("--disconnect-timeout", type=float, default=45.0)
    parser.add_argument("--reconnect-timeout", type=float, default=120.0)
    parser.add_argument("--stable-dwell", type=float, default=5.0)
    parser.add_argument("--local-ip")
    parser.add_argument("--peer-ip")
    parser.add_argument("--dummy-load-confirmed", action="store_true")
    parser.add_argument("--real-radio-disconnected", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/physical-acceptance.json")
    )
    args = parser.parse_args(argv)
    if not 1 <= args.cycles <= 10:
        parser.error("--cycles must be between 1 and 10")
    if not 30 <= args.soak_seconds <= 300:
        parser.error("--soak-seconds must be between 30 and 300")
    if not 5 <= args.stable_dwell <= 15:
        parser.error("--stable-dwell must be between 5 and 15 seconds")
    for name in ("initial_timeout", "disconnect_timeout", "reconnect_timeout"):
        if not 5 <= float(getattr(args, name)) <= 180:
            parser.error(f"--{name.replace('_', '-')} must be between 5 and 180 seconds")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    audit = args.output.with_suffix(".private.jsonl")
    endpoint = _build_endpoint(args, audit)
    started = time.monotonic()
    transitions: list[dict[str, object]] = []
    cycles: list[dict[str, object]] = []
    failure: str | None = None
    print(
        "TX is disabled. The runner will cue each physical power removal with "
        "three high beeps and each restoration with one low beep."
    )
    input("Press Enter when the endpoint and peer are powered and ready: ")
    endpoint.start()  # type: ignore[attr-defined]
    snapshot = endpoint.state.snapshot  # type: ignore[attr-defined]
    try:
        _observe_until(
            snapshot,
            _is_stable,
            timeout=args.initial_timeout,
            started=started,
            transitions=transitions,
        )
        print("Initial stable session accepted.")
        for cycle in range(1, args.cycles + 1):
            _cue("unplug")
            print(f"Cycle {cycle}/{args.cycles}: UNPLUG peer power now.", flush=True)
            cue_at = time.monotonic()
            _observe_until(
                snapshot,
                lambda item: not _is_stable(item),
                timeout=args.disconnect_timeout,
                started=started,
                transitions=transitions,
            )
            disconnected_at = time.monotonic()
            _cue("restore")
            print(f"Cycle {cycle}/{args.cycles}: RESTORE peer power now.", flush=True)
            _observe_until(
                snapshot,
                _is_stable,
                timeout=args.reconnect_timeout,
                started=started,
                transitions=transitions,
            )
            recovered_at = time.monotonic()
            dwell_started = time.monotonic()
            _observe_until(
                snapshot,
                lambda _item: time.monotonic() - dwell_started >= args.stable_dwell,
                timeout=args.stable_dwell + 1.0,
                started=started,
                transitions=transitions,
                require_stable=True,
            )
            cycles.append(
                {
                    "cycle": cycle,
                    "cue_to_disconnect_seconds": round(disconnected_at - cue_at, 3),
                    "disconnect_to_recovery_seconds": round(
                        recovered_at - disconnected_at, 3
                    ),
                }
            )
            print(f"Cycle {cycle}/{args.cycles}: PASS", flush=True)

        print(f"Beginning bounded {args.soak_seconds:.0f}-second stable soak.")
        soak_started = time.monotonic()
        _observe_until(
            snapshot,
            lambda _item: time.monotonic() - soak_started >= args.soak_seconds,
            timeout=args.soak_seconds + 1.0,
            started=started,
            transitions=transitions,
            require_stable=True,
        )
    except (RuntimeError, TimeoutError, KeyboardInterrupt) as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        endpoint.stop()  # type: ignore[attr-defined]

    report = {
        "passed": failure is None and len(cycles) == args.cycles,
        "role": args.role,
        "requested_cycles": args.cycles,
        "completed_cycles": len(cycles),
        "soak_seconds": args.soak_seconds,
        "tx_enabled": False,
        "automatic_ptt_responses": False,
        "duration_seconds": round(time.monotonic() - started, 3),
        "cycles": cycles,
        "transitions": transitions,
        "failure": failure,
        "private_audit": str(audit.resolve()),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    _cue("passed" if report["passed"] else "failed")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
