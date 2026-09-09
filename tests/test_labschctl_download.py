"""Tests for labschctl download subcommands (pure logic, no network).

Import labschctl as a module (its __main__ guard prevents CLI execution on
import) and drive the new download command handlers with a stubbed `call`.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill"))

import importlib.machinery
import importlib.util

_spec = importlib.util.spec_from_loader(
    "labschctl",
    importlib.machinery.SourceFileLoader("labschctl", str(Path(__file__).resolve().parent.parent / "skill" / "labschctl")),
)
labschctl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(labschctl)


class FakeCall:
    """Record API calls and return canned responses."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        key = (method, path)
        if key in self.responses:
            return self.responses[key]
        if path == "/api/clients":
            return [
                {"client_id": "desktop-3d1knvb-ec8871bc", "display_name": "TesPC",
                 "hostname": "DESKTOP-3D1KNVB", "status": "online"},
                {"client_id": "desktop-other-0000000000", "display_name": "PC-LAB-01",
                 "hostname": "PC-LAB-01", "status": "online"},
            ]
        return {"task_id": "11111111-2222-3333-4444-555555555555", "missing_clients": []}


def test_download_requires_explicit_targets(capsys):
    fake = FakeCall()
    labschctl.call = fake
    args = SimpleNamespace(
        url="https://example.com/a.pdf", name=None, dest="desktop", autorun=True,
        sha256="a" * 64, clients=None, group=None, ttl_seconds=None,
        max_size_mb=None, run_as="user",
    )
    import pytest
    with pytest.raises(SystemExit):
        labschctl.cmd_download(args)
    err = capsys.readouterr().err
    assert "target" in err.lower()
    assert fake.calls == []  # nothing sent without explicit targeting


def test_download_sends_validated_task_for_named_clients():
    fake = FakeCall()
    labschctl.call = fake
    args = SimpleNamespace(
        url="https://example.com/a.pdf", name="Lembar.pdf", dest="desktop",
        autorun=False, sha256=None, clients=["TesPC", "desktop-other-0000000000"],
        group=None, ttl_seconds=None, max_size_mb=None, run_as="user",
    )
    labschctl.cmd_download(args)
    method, path, body = fake.calls[-1]
    assert method == "POST" and path == "/api/admin/downloads"
    # display names resolved to canonical client ids
    assert body["clients"] == ["desktop-3d1knvb-ec8871bc", "desktop-other-0000000000"]
    assert body["autorun"] is False
    assert body["sha256"] is None
    assert body["url"] == "https://example.com/a.pdf"
    assert body["filename"] == "Lembar.pdf"


def test_download_autorun_requires_sha256(capsys):
    fake = FakeCall()
    labschctl.call = fake
    args = SimpleNamespace(
        url="https://example.com/a.pdf", name=None, dest="desktop", autorun=True,
        sha256=None, clients=["TesPC"], group=None, ttl_seconds=None,
        max_size_mb=None, run_as="user",
    )
    import pytest
    with pytest.raises(SystemExit):
        labschctl.cmd_download(args)
    assert "sha256" in capsys.readouterr().err.lower()
    assert fake.calls == []


def test_downloads_lists_tasks_with_rollup(capsys):
    fake = FakeCall({
        ("GET", "/api/admin/downloads"): {
            "tasks": [{
                "task_id": "11111111-2222-3333-4444-555555555555",
                "filename": "Lembar.pdf",
                "url": "https://example.com/a.pdf",
                "autorun": True,
                "status": "active",
                "created_at": 1757000000,
                "rollup": {"done": 1, "failed": 0, "pending": 1, "downloading": 0, "skipped": 0},
            }],
        },
    })
    labschctl.call = fake
    labschctl.cmd_downloads(SimpleNamespace())
    out = capsys.readouterr().out
    assert "11111111" in out
    assert "Lembar.pdf" in out


def test_download_cancel_calls_cancel_endpoint(capsys):
    fake = FakeCall({("POST", "/api/admin/downloads/11111111-2222-3333-4444-555555555555/cancel"): {"ok": True}})
    labschctl.call = fake
    labschctl.cmd_download_cancel(SimpleNamespace(task_id="11111111-2222-3333-4444-555555555555"))
    assert fake.calls[0][0] == "POST"
    assert "cancel" in fake.calls[0][1]
    out = capsys.readouterr().out
    assert "cancel" in out.lower()
