from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))


def test_registry_roots_use_normal_windows_separators():
    import browser_policy
    for root in browser_policy.BROWSER_POLICIES.values():
        assert "\\\\" not in root
        assert root.startswith("HKLM\\SOFTWARE\\")


def test_browser_is_not_reported_successful_when_registry_write_fails(monkeypatch):
    import browser_policy

    monkeypatch.setattr(browser_policy, "_is_windows", lambda: True)
    monkeypatch.setattr(browser_policy, "_reg_delete_key", lambda *args: True)
    monkeypatch.setattr(browser_policy, "_reg_add", lambda *args: False)

    assert browser_policy.apply_browser_policy(["*"], ["google.com"]) == 0


def test_browser_policy_writes_wildcard_once_and_checks_every_write(monkeypatch):
    import browser_policy

    calls = []
    monkeypatch.setattr(browser_policy, "_is_windows", lambda: True)
    monkeypatch.setattr(browser_policy, "_reg_delete_key", lambda *args: True)
    monkeypatch.setattr(browser_policy, "_reg_add", lambda *args: calls.append(args) or True)

    assert browser_policy.apply_browser_policy(["*", "tiktok.com"], ["google.com"]) == 3
    for browser, root in browser_policy.BROWSER_POLICIES.items():
        browser_calls = [c for c in calls if c[0].startswith(root)]
        wildcard = [c for c in browser_calls if len(c) >= 3 and c[2] == "*"]
        assert len(wildcard) == 1
        assert all("\\\\" not in c[0] for c in browser_calls)
