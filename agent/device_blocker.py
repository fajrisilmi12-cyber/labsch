"""Device blocker — disable camera & audio on Windows.

Camera: Block via registry policy (HKLM\SOFTWARE\Policies\Microsoft\Camera)
        + device-install restriction on the imaging class GUID.
Audio:  Stop + disable Windows Audio service (audiosrv) and endpoint builder.
Both are reversible — enable_* restores original state.
"""
import subprocess
import logging

log = logging.getLogger("labsch.device_blocker")

CAMERA_POLICY_KEY = r"HKLM\SOFTWARE\Policies\Microsoft\MicrosoftCamera"
AUDIO_SERVICES = ["audiosrv", "AudioEndpointBuilder"]
CAMERA_CLASS_GUID = "{6bdd1fc6-810f-11d0-bec7-08002be2092f}"


def _reg_add(path: str, name: str, value: str, vtype: str = "REG_DWORD") -> bool:
    r = subprocess.run(
        ["reg", "add", path, "/v", name, "/t", vtype, "/d", value, "/f"],
        capture_output=True,
    )
    return r.returncode == 0


def _reg_delete(path: str, name: str) -> bool:
    r = subprocess.run(
        ["reg", "delete", path, "/v", name, "/f"], capture_output=True
    )
    return r.returncode == 0


def _sc(cmd: list) -> bool:
    r = subprocess.run(["sc"] + cmd, capture_output=True)
    return r.returncode == 0


# ── Camera ────────────────────────────────────────────────────

def disable_camera() -> bool:
    """Block camera access system-wide via policy + device class."""
    ok = _reg_add(CAMERA_POLICY_KEY, "AllowCamera", "0")
    _reg_add(r"HKLM\SOFTWARE\Policies\Microsoft\Camera", "AllowCamera", "0")
    # Deny camera device class via device-install restriction
    _reg_add(
        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Restrictions",
        "DenyDeviceClasses", "1",
    )
    _reg_add(
        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Restrictions\DenyDeviceClasses",
        "1", CAMERA_CLASS_GUID, "REG_SZ",
    )
    log.info("camera disabled: %s", ok)
    return ok


def enable_camera() -> bool:
    """Re-enable camera."""
    _reg_delete(CAMERA_POLICY_KEY, "AllowCamera")
    _reg_delete(r"HKLM\SOFTWARE\Policies\Microsoft\Camera", "AllowCamera")
    _reg_delete(
        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Restrictions",
        "DenyDeviceClasses",
    )
    log.info("camera enabled")
    return True


# ── Audio ─────────────────────────────────────────────────────

def disable_audio() -> bool:
    """Stop + disable Windows Audio services. Requires SYSTEM/admin."""
    ok = True
    for svc in AUDIO_SERVICES:
        _sc(["stop", svc])  # may already be stopped
        if not _sc(["config", svc, "start=", "disabled"]):
            ok = False
    log.info("audio disabled: %s", ok)
    return ok


def enable_audio() -> bool:
    """Re-enable + start Windows Audio services."""
    ok = True
    for svc in AUDIO_SERVICES:
        if not _sc(["config", svc, "start=", "auto"]):
            ok = False
        _sc(["start", svc])
    log.info("audio enabled: %s", ok)
    return ok


# ── Entry point (called from labsch_agent on config change) ──

def apply_device_flags(cam_off: bool, aud_off: bool, current: dict) -> dict:
    """Apply device flags. `current` tracks last applied state to avoid
    redundant registry/service calls.

    Returns new current state dict.
    """
    prev_cam = current.get("disable_camera", False)
    prev_aud = current.get("disable_audio", False)

    if cam_off and not prev_cam:
        disable_camera()
    elif not cam_off and prev_cam:
        enable_camera()

    if aud_off and not prev_aud:
        disable_audio()
    elif not aud_off and prev_aud:
        enable_audio()

    return {"disable_camera": cam_off, "disable_audio": aud_off}
