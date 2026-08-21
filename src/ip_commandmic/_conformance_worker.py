"""Private JSON-line worker used by cross-process endpoint conformance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .gui_server import SoftwareCommandMicEndpoint


def _write(response: dict[str, object]) -> None:
    print(json.dumps(response, separators=(",", ":")), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-ip", required=True)
    parser.add_argument("--radio-ip", required=True)
    parser.add_argument("--control-port", type=int, required=True)
    parser.add_argument("--audio-port", type=int, required=True)
    parser.add_argument("--audit-path", type=Path, required=True)
    args = parser.parse_args(argv)

    endpoint = SoftwareCommandMicEndpoint(
        local_ip=args.local_ip,
        radio_ip=args.radio_ip,
        microphone_device=None,
        enable_tx=False,
        play_rx_audio=False,
        audit_path=args.audit_path,
        control_port=args.control_port,
        audio_port=args.audio_port,
    )
    try:
        endpoint.start()
        _write({"ok": True, "event": "started"})
        for line in sys.stdin:
            try:
                request = json.loads(line)
                operation = request.get("op")
                if operation == "snapshot":
                    _write({"ok": True, "state": endpoint.state.snapshot()})
                elif operation == "key":
                    endpoint.key(str(request["button"]), str(request["action"]))
                    _write({"ok": True})
                elif operation == "stop":
                    endpoint.stop()
                    _write({"ok": True, "event": "stopped"})
                    return 0
                else:
                    raise ValueError(f"unknown worker operation: {operation!r}")
            except Exception as exc:
                _write(
                    {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    finally:
        endpoint.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
