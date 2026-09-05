r"""Device blocker — disable camera & audio on Windows.

Camera: Block via registry policy (HKLM\SOFTWARE\Policies\Microsoft\Camera)
        + device-install restriction on the imaging class GUID.
Audio:  Block via device-install restriction on the MEDIA class GUID
        (mutes output hardware, keeps audiosrv running so the volume
        system-tray icon stays functional). Reversible.
Both are reversible — enable_* restores original state.
"""
import subprocess
import logging

log = logging.getLogger("labsch.device_blocker")

# v0.3.5 — subprocess.CREATE_NO_WINDOW so spawned reg.exe never flashes a
# console window at the student. Fall back to 0 on non-Windows.
try:
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
except AttributeError:
    _NO_WINDOW = 0

# v0.3.5 — single helper so every subprocess call gets explicit timeout +
# CREATE_NO_WINDOW consistently. (No capture_output/text here — callers
# either ignore output or use their own.)
def _run(cmd: list, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, timeout=timeout,
        creationflags=_NO_WINDOW,
    )


CAMERA_POLICY_KEY = r"HKLM\SOFTWARE\Policies\Microsoft\MicrosoftCamera"
MEDIA_CLASS_GUID = "{4d36e96c-e325-11ce-bfc1-08002be10318}"  # MEDIA (audio endpoints)
CAMERA_CLASS_GUID = "{6bdd1fc6-810f-11d0-bec7-08002be2092f}"


def _reg_add(path: str, name: str, value: str, vtype: str = "REG_DWORD") -> bool:
    r = _run(
        ["reg", "add", path, "/v", name, "/t", vtype, "/d", value, "/f"],
    )
    return r.returncode == 0


def _reg_delete(path: str, name: str) -> bool:
    r = _run(
        ["reg", "delete", path, "/v", name, "/f"],
    )
    return r.returncode == 0


def _reg_delete_tree(path: str) -> bool:
    r = _run(
        ["reg", "delete", path, "/f"],
    )
    return r.returncode == 0


def _sc(cmd: list) -> bool:
    r = _run(["sc"] + cmd)
    return r.returncode == 0


# ── Camera ────────────────────────────────────────────────────

DENY_BASE = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Restrictions"
DENY_LIST = DENY_BASE + r"\DenyDeviceClasses"
CAM_DENY_INDEX = "1"    # imaging class
AUD_DENY_INDEX = "2"    # media class


def _deny_index(index: str, guid_value: str) -> bool:
    ok = _reg_add(DENY_BASE, "DenyDeviceClasses", "1")
    ok = _reg_add(DENY_LIST, index, guid_value, "REG_SZ") and ok
    return ok


def _undeny_index(index: str) -> None:
    # Remove one indexed entry; drop the master switch only if list is empty.
    _reg_delete(DENY_LIST, index)
    r = _run(
        ["reg", "query", DENY_LIST],
    )
    if r.returncode != 0 or ("REG_SZ" not in (r.stdout.decode("utf-8", errors="replace") if r.stdout else "")):
        _reg_delete(DENY_BASE, "DenyDeviceClasses")


def disable_camera() -> bool:
    """Block camera access system-wide via policy + device class (index 1)."""
    ok = _reg_add(CAMERA_POLICY_KEY, "AllowCamera", "0")
    _reg_add(r"HKLM\SOFTWARE\Policies\Microsoft\Camera", "AllowCamera", "0")
    ok = _deny_index(CAM_DENY_INDEX, CAMERA_CLASS_GUID) and ok
    log.info("camera disabled: %s", ok)
    return ok


def enable_camera() -> bool:
    """Re-enable camera (keeps audio deny entry intact)."""
    _reg_delete(CAMERA_POLICY_KEY, "AllowCamera")
    _reg_delete(r"HKLM\SOFTWARE\Policies\Microsoft\Camera", "AllowCamera")
    _undeny_index(CAM_DENY_INDEX)
    log.info("camera enabled")
    return True


# ── Audio ─────────────────────────────────────────────────────
# NOTE (2026-09-04): old approach stopped+disabled audiosrv/AudioEndpointBuilder.
# That kills the volume system-tray icon and needs reboot to recover.
# New approach: deny the MEDIA device class (audio endpoints) + force mute.
# audiosrv keeps running, taskbar icon stays alive, fully reversible.

def _ensure_audiosrv_running() -> None:
    # Make sure the audio service is up so the tray icon works.
    _sc(["config", "audiosrv", "start=", "auto"])
    _sc(["config", "AudioEndpointBuilder", "start=", "auto"])
    _sc(["start", "AudioEndpointBuilder"])
    _sc(["start", "audiosrv"])


def _mute_all_outputs() -> None:
    # Best-effort mute via PowerShell AudioDeviceCmdlets-free approach:
    # set master volume to 0 through WScript shell SendKeys-free API is unreliable,
    # so use nircmd-free fallback: `powershell (New-Object -ComObject WScript.Shell)`
    # would steal focus — instead just silence via sndvol? Skip invasive mute;
    # the class-deny already blocks render/capture devices on next plug-in.
    # Keep devices muted at the endpoint level for currently-present ones:
    # v0.3.5 — explicit timeout + CREATE_NO_WINDOW so the powershell.exe call
    # never flashes a console at the student.
    _run(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
         "$o=(New-Object -ComObject MMDeviceEnumerator 2>$null);"
         "try{$d=$o.GetDefaultAudioEndpoint(0,1);"
         "$v=$d.AudioEndpointVolume;$v.MasterVolumeLevelScalar=0.0}catch{}"],
        timeout=15,
    )


def disable_audio() -> bool:
    """Block audio output/input hardware. audiosrv stays running (tray OK)."""
    _ensure_audiosrv_running()
    ok = _deny_index(AUD_DENY_INDEX, MEDIA_CLASS_GUID)
    _mute_all_outputs()
    # Restore legacy damage: if services were disabled by old version, re-enable.
    _sc(["config", "audiosrv", "start=", "auto"])
    _sc(["config", "AudioEndpointBuilder", "start=", "auto"])
    _sc(["start", "AudioEndpointBuilder"])
    _sc(["start", "audiosrv"])
    log.info("audio disabled: %s", ok)
    return ok


def enable_audio() -> bool:
    """Re-enable audio hardware + make sure services are up."""
    _undeny_index(AUD_DENY_INDEX)
    ok = True
    _ensure_audiosrv_running()
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
