"""Tests for appcheck.py — run on Linux CI with mocked Windows primitives."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

import appcheck


def test_parse_version():
    assert appcheck._parse_version("6.1.50r161033") == (6, 1, 50)
    assert appcheck._parse_version("Python 3.10.11") == (3, 10, 11)
    assert appcheck._parse_version("") is None
    assert appcheck._parse_version(None) is None


def test_compare_versions():
    assert appcheck.compare_versions("6.1.50", "6.1.50") == 0
    assert appcheck.compare_versions("7.0.0", "6.1.50") == 1
    assert appcheck.compare_versions("6.0.0", "6.1.50") == -1
    assert appcheck.compare_versions("9.0", "9.0.0") == 0  # prefix-equal counts


def test_newer_never_downgraded():
    policy = {"version": "6.1.50"}
    res = appcheck._build_result("virtualbox", policy, [{"name": "Oracle VM VirtualBox", "version": "7.0.12", "location": ""}], "C:\\x\\VBoxManage.exe", "7.0.12")
    assert res["status"] == appcheck.STATUS_OK
    assert "tidak di-downgrade" in res["evidence"]


def test_older_is_mismatch():
    policy = {"version": "6.1.50"}
    res = appcheck._build_result("virtualbox", policy, [{"name": "Oracle VM VirtualBox", "version": "6.0.0", "location": ""}], "C:\\x\\VBoxManage.exe", "6.0.0")
    assert res["status"] == appcheck.STATUS_MISMATCH


def test_missing():
    res = appcheck._build_result("python", {"min_version": "3.10.0"}, [], None, None)
    assert res["status"] == appcheck.STATUS_MISSING


def test_failed():
    res = appcheck._build_result("python", {}, [], None, None, error="boom")
    assert res["status"] == appcheck.STATUS_FAILED


def test_check_all_monkeypatched(monkeypatch):
    monkeypatch.setattr(appcheck, "registry_search", lambda frags: [])
    monkeypatch.setattr(appcheck, "find_exe", lambda names, dirs=None: None)
    policy = {
        "python": {"min_version": "3.10.0"},
        "virtualbox": {"version": "6.1.50"},
        "packet_tracer": {"version": "9.0.0"},
    }
    out = appcheck.check_all(policy)
    assert set(out) == {"python", "virtualbox", "packet_tracer"}
    assert all(v["status"] == appcheck.STATUS_MISSING for v in out.values())


def test_check_virtualbox_found(monkeypatch):
    monkeypatch.setattr(appcheck, "registry_search",
                        lambda frags: [{"name": "Oracle VM VirtualBox 6.1.50", "version": "6.1.50", "location": ""}])
    monkeypatch.setattr(appcheck, "find_exe", lambda names, dirs=None: "C:\\Program Files\\Oracle\\VirtualBox\\VBoxManage.exe")
    monkeypatch.setattr(appcheck, "probe_version", lambda exe, args=("--version",): "6.1.50r161033")
    res = appcheck.check_virtualbox({"version": "6.1.50"})
    assert res["status"] == appcheck.STATUS_OK
    assert "VBoxManage" in res["path"]
