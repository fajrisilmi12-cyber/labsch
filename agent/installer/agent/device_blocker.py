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
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceResult:
    ok: bool
    detail: str


_last_detail = {"camera": "", "audio": ""}

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
    """Block present and future cameras system-wide."""
    policy_ok = _reg_add(CAMERA_POLICY_KEY, "AllowCamera", "0")
    policy_ok = _reg_add(r"HKLM\SOFTWARE\Policies\Microsoft\Camera", "AllowCamera", "0") and policy_ok
    policy_ok = _deny_index(CAM_DENY_INDEX, CAMERA_CLASS_GUID) and policy_ok
    devices = _set_existing_devices(True, ("Camera", "Image"))
    _last_detail["camera"] = devices.detail
    ok = policy_ok and devices.ok
    log.info("camera disabled: %s; %s", ok, devices.detail)
    return ok


def enable_camera() -> bool:
    """Re-enable present cameras while keeping the audio deny entry intact."""
    policy_ok = _reg_delete(CAMERA_POLICY_KEY, "AllowCamera")
    _reg_delete(r"HKLM\SOFTWARE\Policies\Microsoft\Camera", "AllowCamera")
    _undeny_index(CAM_DENY_INDEX)
    devices = _set_existing_devices(False, ("Camera", "Image"))
    _last_detail["camera"] = devices.detail
    ok = policy_ok and devices.ok
    log.info("camera enabled: %s; %s", ok, devices.detail)
    return ok


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


def _set_existing_devices(disabled: bool, classes: tuple[str, ...]) -> DeviceResult:
    """Toggle present devices one-by-one and retain actionable diagnostics."""
    verb = "Disable-PnpDevice" if disabled else "Enable-PnpDevice"
    class_expr = " -or ".join(f"$_.Class -eq '{name}'" for name in classes)
    script = (
        "$ErrorActionPreference='Continue';$failed=@();$done=@();"
        f"$devices=@(Get-PnpDevice -PresentOnly | Where-Object {{{class_expr}}});"
        f"foreach($d in $devices){{try{{{verb} -InstanceId $d.InstanceId "
        "-Confirm:$false -ErrorAction Stop;$done+=($d.FriendlyName+' ['+$d.Class+']')}"
        "catch{$failed+=($d.FriendlyName+' ['+$d.Class+']: '+$_.Exception.Message)}};"
        "Write-Output ('OK='+($done -join '|'));"
        "if($failed.Count -gt 0){Write-Error ('FAILED='+($failed -join '|'));exit 1}"
    )
    r = _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-Command", script], timeout=60,
    )
    stdout = r.stdout.decode("utf-8", errors="replace").strip() if r.stdout else ""
    stderr = r.stderr.decode("utf-8", errors="replace").strip() if r.stderr else ""
    detail = "; ".join(x for x in (stdout, stderr) if x) or f"exit={r.returncode}"
    return DeviceResult(r.returncode == 0, detail[:2000])


def _set_existing_audio_devices(disabled: bool) -> bool:
    return _set_existing_devices(disabled, ("MEDIA", "AudioEndpoint")).ok


def disable_audio() -> bool:
    """Block currently-present and future audio devices; keep audiosrv healthy."""
    _ensure_audiosrv_running()
    policy_ok = _deny_index(AUD_DENY_INDEX, MEDIA_CLASS_GUID)
    devices = _set_existing_devices(True, ("MEDIA", "AudioEndpoint"))
    _last_detail["audio"] = devices.detail
    # Restore legacy service damage without re-enabling the PnP devices.
    _ensure_audiosrv_running()
    ok = policy_ok and devices.ok
    log.info("audio disabled: %s; %s", ok, devices.detail)
    return ok


def enable_audio() -> bool:
    """Re-enable present audio hardware and allow future installations."""
    _undeny_index(AUD_DENY_INDEX)
    devices = _set_existing_devices(False, ("MEDIA", "AudioEndpoint"))
    _last_detail["audio"] = devices.detail
    _ensure_audiosrv_running()
    log.info("audio enabled: %s; %s", devices.ok, devices.detail)
    return devices.ok


# ── Entry point (called from labsch_agent on config change) ──

def apply_device_flags(cam_off: bool, aud_off: bool, current: dict, log_fn=None) -> dict:
    """Apply changed flags and retain only states proven successful."""
    if log_fn is None:
        log_fn = lambda message: None
    prev_cam = current.get("disable_camera", False)
    prev_aud = current.get("disable_audio", False)
    next_cam = prev_cam
    next_aud = prev_aud

    if cam_off != prev_cam:
        ok = disable_camera() if cam_off else enable_camera()
        if ok:
            next_cam = cam_off
            log_fn(f"[device_blocker] camera {'disabled' if cam_off else 'enabled'}")
        else:
            log_fn(f"[device_blocker] camera {'disable' if cam_off else 'enable'} failed: {_last_detail['camera']}; will retry")

    if aud_off != prev_aud:
        ok = disable_audio() if aud_off else enable_audio()
        if ok:
            next_aud = aud_off
            log_fn(f"[device_blocker] audio {'disabled' if aud_off else 'enabled'}")
        else:
            log_fn(f"[device_blocker] audio {'disable' if aud_off else 'enable'} failed: {_last_detail['audio']}; will retry")

    return {"disable_camera": next_cam, "disable_audio": next_aud}
