import subprocess
import sys


def test_plain_package_import_does_not_eagerly_load_endpoint_or_audio_stacks() -> None:
    script = (
        "import sys, ip_commandmic; "
        "blocked=('ip_commandmic.audio','ip_commandmic.emulator',"
        "'ip_commandmic.gui_server','ip_commandmic.test_app'); "
        "raise SystemExit(any(name in sys.modules for name in blocked))"
    )
    completed = subprocess.run([sys.executable, "-c", script], check=False)
    assert completed.returncode == 0


def test_lazy_public_symbol_resolves_and_is_cached() -> None:
    import ip_commandmic

    first = ip_commandmic.DisplayBuffer
    assert first is ip_commandmic.DisplayBuffer
