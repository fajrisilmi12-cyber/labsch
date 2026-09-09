import importlib.util
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).parents[1] / "agent" / "device_blocker.py"
spec = importlib.util.spec_from_file_location("device_blocker_under_test", MODULE)
device_blocker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device_blocker)


class Result:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_disable_audio_disables_existing_pnp_audio_devices():
    calls = []

    def fake_run(cmd, timeout=10):
        calls.append(cmd)
        return Result(0)

    with patch.object(device_blocker, "_run", side_effect=fake_run):
        assert device_blocker.disable_audio() is True

    ps = [c for c in calls if c and c[0].lower() == "powershell"]
    assert ps, "disable_audio must invoke PowerShell"
    script = " ".join(ps[-1])
    assert "Get-PnpDevice" in script
    assert "Disable-PnpDevice" in script
    assert "MEDIA" in script
    assert "AudioEndpoint" in script


def test_disable_camera_disables_existing_camera_devices():
    calls = []
    def fake_run(cmd, timeout=10):
        calls.append(cmd)
        return Result(0)
    with patch.object(device_blocker, "_run", side_effect=fake_run):
        assert device_blocker.disable_camera() is True
    scripts = [" ".join(c) for c in calls if c and c[0].lower() == "powershell"]
    assert any("Disable-PnpDevice" in s and "Camera" in s and "Image" in s for s in scripts)


def test_pnp_failure_reports_device_and_windows_error():
    with patch.object(device_blocker, "_run", return_value=Result(1, stderr=b"Access denied: USB Audio")):
        result = device_blocker._set_existing_devices(True, ("MEDIA", "AudioEndpoint"))
    assert result.ok is False
    assert "USB Audio" in result.detail
    assert "Access denied" in result.detail


def test_disable_audio_fails_when_existing_device_disable_fails():
    def fake_run(cmd, timeout=10):
        if cmd and cmd[0].lower() == "powershell" and "Disable-PnpDevice" in " ".join(cmd):
            return Result(1, stderr=b"Access denied")
        return Result(0)

    with patch.object(device_blocker, "_run", side_effect=fake_run):
        assert device_blocker.disable_audio() is False


def test_apply_device_flags_retries_audio_after_failure():
    with patch.object(device_blocker, "disable_audio", return_value=False) as disable:
        state = device_blocker.apply_device_flags(False, True, {})
        assert state["disable_audio"] is False
        state = device_blocker.apply_device_flags(False, True, state)
        assert disable.call_count == 2
        assert state["disable_audio"] is False


def test_apply_device_flags_reports_result_to_console():
    messages = []
    with patch.object(device_blocker, "disable_audio", return_value=True):
        state = device_blocker.apply_device_flags(False, True, {}, log_fn=messages.append)
    assert state["disable_audio"] is True
    assert any("audio" in m.lower() and "disabled" in m.lower() for m in messages)
