import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

import downloader


def make_registry(tmp_path):
    import downloader
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_download_task_registry_is_idempotent_and_at_most_once(tmp_path):
    reg = make_registry(tmp_path)
    claim = downloader.claim_task(reg, "task-1", "sha-abc")
    assert claim is True
    assert downloader.claim_task(reg, "task-1", "sha-abc") is False
    downloader.mark_download_done(reg, "task-1", "sha-abc", 12)
    entry = json.loads((tmp_path / "downloads.json").read_text(encoding="utf-8"))["task-1"]
    assert entry["download_state"] == "done"
    assert entry["sha256"] == "sha-abc"
    assert downloader.claim_task(reg, "task-1", "sha-abc") is False


def test_registry_survives_partial_state_without_double_execution(tmp_path):
    reg = make_registry(tmp_path)
    downloader.claim_task(reg, "task-1", "sha-abc")
    downloader.mark_download_done(reg, "task-1", "sha-abc", 5)
    downloader.mark_execution_state(reg, "task-1", "launched")
    assert downloader.claim_execution(reg, "task-1") is False
    assert downloader.execution_state(reg, "task-1") == "launched"
    downloader.mark_execution_state(reg, "task-2", "unsupported")
    assert downloader.execution_state(reg, "task-2") == "unsupported"


def test_private_and_non_https_urls_are_rejected(tmp_path):
    for bad in [
        "http://example.com/a.pdf",
        "file://server/share/a.pdf",
        "https://192.168.1.20/a.pdf",
        "https://172.16.5.4/a.pdf",
        "https://10.1.2.3/a.pdf",
        "https://127.0.0.1/a.pdf",
        "https://localhost/a.pdf",
        "https://169.254.169.254/a.pdf",
        "https://[::1]/a.pdf",
    ]:
        assert downloader.validate_source_url(bad) is None, bad


def test_redirect_to_private_ip_is_rejected(tmp_path):
    assert downloader.validate_source_url("https://example.com/a.pdf") is not None
    assert downloader.validate_redirect("https://192.168.1.5/x") is None
    assert downloader.validate_redirect("https://example.org/x") is not None


def test_resolve_drive_and_onedrive_single_file_links():
    r = downloader.resolve_url("https://drive.google.com/file/d/FILE123/view?usp=sharing")
    assert r == "https://drive.google.com/uc?export=download&id=FILE123"
    r2 = downloader.resolve_url("https://example.com/uc?export=download&id=FILE123&confirm=t")
    assert r2 == "https://example.com/uc?export=download&id=FILE123&confirm=t"
    r3 = downloader.resolve_url("https://1drv.ms/w/s!ABC123")
    assert r3 == "https://api.onedrive.com/v1.0/shares/u!aHR0cHM6Ly8xZHJ2Lm1zL3cvcyFBQkMxMjM/root/content"
    r4 = downloader.resolve_url("https://my.sharepoint.com/:b:/g/personal/x/y/FILE?e=abc")
    assert r4 == "https://api.onedrive.com/v1.0/shares/u!aHR0cHM6Ly9teS5zaGFyZXBvaW50LmNvbS86YjovZy9wZXJzb25hbC94L3kvRklMRT9lPWFiYw/root/content"
    assert downloader.is_onedrive_share("https://1drv.ms/w/s!ABC123")
    # multi-file / folder Drive links are unsupported in v1
    assert downloader.resolve_url("https://drive.google.com/drive/folders/ABC123") is None


def test_filename_and_destination_validation():
    assert downloader.sanitize_filename("..\\..\\evil.exe") not in ("..\\..\\evil.exe",)
    assert downloader.sanitize_filename("../../evil.exe") == "evil.exe"
    assert downloader.sanitize_filename("a/b/c.pdf") == "c.pdf"
    assert downloader.validate_destination("desktop") == "desktop"
    assert downloader.validate_destination("documents") == "documents"
    with pytest.raises(ValueError):
        downloader.validate_destination("C:\\Temp")
    with pytest.raises(ValueError):
        downloader.validate_destination("custom/path")
    assert downloader.sanitize_filename("x" * 200) != "x" * 200


def test_safe_executor_user_context_refuses_privileged_paths(tmp_path):
    payload = {
        "task_id": "t1",
        "filename": "doc.pdf",
        "destination": "desktop",
        "run_as": "user",
        "extensions": [],
        "sha256": hashlib.sha256(b"pdf-bytes").hexdigest(),
    }
    user_dir = tmp_path / "Users" / "Public" / "Desktop"
    user_dir.mkdir(parents=True)
    final_path = user_dir / "doc.pdf"
    final_path.write_bytes(b"pdf-bytes")
    result = downloader.evaluate_launch(tmp_path, payload, final_path)
    assert result["execution_state"] == "launchable"
    # a path outside the public destination must never be launchable
    outside = tmp_path / "evil" / "doc.pdf"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"pdf-bytes")
    outside_result = downloader.evaluate_launch(tmp_path, payload, outside)
    assert outside_result["execution_state"] in ("unsupported", "failed_launch")
    assert outside_result["reason"]


def test_safe_executor_rejects_shell_and_script_extensions(tmp_path):
    user_dir = tmp_path / "Users" / "Public" / "Desktop"
    user_dir.mkdir(parents=True)
    for name, expected in [
        ("evil.msc", "unsupported"),
        ("setup.msi", "unsupported"),
        ("run.bat", "unsupported"),
        ("run.cmd", "unsupported"),
        ("run.ps1", "unsupported"),
        ("scr.scr", "unsupported"),
        ("doc.pdf", "launchable"),
        ("app.exe", "launchable"),
    ]:
        payload = {
            "task_id": "t-" + name,
            "filename": name,
            "destination": "desktop",
            "run_as": "user",
            "extensions": [],
            "sha256": hashlib.sha256(b"x").hexdigest(),
        }
        final_path = user_dir / name
        final_path.write_bytes(b"x")
        result = downloader.evaluate_launch(tmp_path, payload, final_path)
        assert result["execution_state"] == expected, name


def test_authorization_header_is_not_forwarded_to_hosts():
    opener = downloader.build_download_opener("secret-token")
    assert opener.addheaders == [("User-Agent", "LabSCHDownloader/0.4.0")]


def test_atomic_same_volume_rename(tmp_path):
    src = tmp_path / "labsch-dl-t1.part"
    src.write_bytes(b"data")
    dest_dir = tmp_path / "Users" / "Public" / "Desktop"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "file.pdf"
    downloader.atomic_install(src, dest)
    assert dest.read_bytes() == b"data"
    assert not src.exists()


def test_sha_mismatch_blocks_launch(tmp_path):
    user_dir = tmp_path / "Users" / "Public" / "Desktop"
    user_dir.mkdir(parents=True)
    final_path = user_dir / "doc.pdf"
    final_path.write_bytes(b"pdf-bytes")
    payload = {
        "task_id": "t-sha",
        "filename": "doc.pdf",
        "destination": "desktop",
        "run_as": "user",
        "extensions": [],
        "sha256": "f" * 64,
    }
    result = downloader.evaluate_launch(tmp_path, payload, final_path)
    assert result["execution_state"] == "failed_launch"
    assert "sha256" in result["reason"]


def test_registry_entry_removed_for_new_task_keeps_other_tasks(tmp_path):
    reg = make_registry(tmp_path)
    downloader.claim_task(reg, "task-a", "sha-a")
    downloader.claim_task(reg, "task-b", "sha-b")
    downloader.forget_task(reg, "task-a")
    data = json.loads((tmp_path / "downloads.json").read_text(encoding="utf-8"))
    assert "task-a" not in data
    assert "task-b" in data


def test_build_download_opener_user_agent_only():
    opener = downloader.build_download_opener(None)
    assert opener.addheaders == [("User-Agent", "LabSCHDownloader/0.4.0")]
    opener2 = downloader.build_download_opener("any")
    assert opener2.addheaders == [("User-Agent", "LabSCHDownloader/0.4.0")]


def test_download_stream_aborts_on_oversize(tmp_path):
    class FakeResponse:
        def __init__(self, chunks):
            self._chunks = chunks
            self.headers = {"Content-Length": None}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

    src = tmp_path / "labsch-dl-t9.part"
    dest_dir = tmp_path / "Users" / "Public" / "Desktop"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "big.pdf"
    max_bytes = 10
    with pytest.raises(downloader.DownloadSizeExceeded):
        downloader.stream_to_file(
            FakeResponse([b"x" * 8, b"x" * 8, b"x" * 8]), src, max_bytes, report=lambda *a: None
        )
    assert not dest.exists()
    assert src.exists()
