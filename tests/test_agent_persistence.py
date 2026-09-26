from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_batch_installer_boot_task_runs_continuous_agent():
    # v0.4.0 unified: ONE task "LabSCHAgent" (SYSTEM, onstart), no --once.
    text = (ROOT / "agent" / "install.bat").read_text(encoding="utf-8")
    create = next(line for line in text.splitlines() if 'schtasks /create /tn "LabSCHAgent"' in line)
    assert "--once" not in create, "task must keep polling after restart"
    assert 'schtasks /create /tn "LabSCHAgentOnBoot"' not in text, "must not create legacy tasks"
    assert 'schtasks /create /tn "LabSCHAgentWatchdog"' not in text, "must not create legacy tasks"


def test_go_installer_boot_task_runs_continuous_agent():
    text = (ROOT / "agent" / "installer" / "setup.go").read_text(encoding="utf-8")
    assert 'trBoot := fmt.Sprintf(`"%s" "%s"`, pythonExe, agentPath)' in text
    assert 'trBoot := fmt.Sprintf(`python "%s" --once`, agentPath)' not in text


def test_installers_do_not_create_competing_periodic_agents():
    bat = (ROOT / "agent" / "install.bat").read_text(encoding="utf-8")
    go = (ROOT / "agent" / "installer" / "setup.go").read_text(encoding="utf-8")
    assert '/sc minute /mo 5' not in bat.lower()
    assert '"/sc", "minute"' not in go


def test_power_commands_use_verified_executor_and_identified_confirmation():
    text = (ROOT / "agent" / "labsch_agent.py").read_text(encoding="utf-8")
    assert 'command_executor.execute(pending)' in text
    assert 'client.confirm_command(pending, "success")' in text
    assert 'client.confirm_command(pending, "failed"' in text


def test_go_installer_uses_absolute_python_for_system_task():
    text = (ROOT / "agent" / "installer" / "setup.go").read_text(encoding="utf-8")
    assert 'exec.LookPath(py)' in text
    assert 'trBoot := fmt.Sprintf(`"%s" "%s"`, pythonExe, agentPath)' in text
    assert 'trBoot := fmt.Sprintf(`python "%s"`, agentPath)' not in text


def test_go_installer_reports_current_bundle_version():
    text = (ROOT / "agent" / "installer" / "setup.go").read_text(encoding="utf-8")
    assert 'const version = `0.4.1`' in text
    assert '"version": "%s"' in text


def test_agent_reports_version_from_installed_config():
    # v0.4.0 unified: single source of truth agent/VERSION via version.py.
    text = (ROOT / "agent" / "labsch_agent.py").read_text(encoding="utf-8")
    assert 'version = AGENT_VERSION' in text
    assert 'from version import AGENT_VERSION' in text
    assert 'cfg.get("version", "0.4.0-test10")' not in text
    assert 'version = "0.4.0-test2"' not in text


def test_go_installer_stops_startup_sources_before_killing_old_agent():
    text = (ROOT / "agent" / "installer" / "setup.go").read_text(encoding="utf-8")
    delete_pos = text.index('"LabSCHAgentOnBoot", "/f"')
    kill_pos = text.index("killOldAgents()")
    assert delete_pos < kill_pos
    assert '"pythonw.exe"' in text


def test_go_installer_verifies_written_version_and_payload():
    text = (ROOT / "agent" / "installer" / "setup.go").read_text(encoding="utf-8")
    assert "verifyInstalledVersion(configPath, version)" in text
    assert "verifyEmbeddedPayloadVersion(agentPath, version)" in text
    assert "CONFIG VERSION VERIFICATION FAILED" in text
    assert "PAYLOAD VERSION VERIFICATION FAILED" in text


def test_go_installer_checks_start_now_result_and_explains_hidden_mode():
    text = (ROOT / "agent" / "installer" / "setup.go").read_text(encoding="utf-8")
    assert 'if runCmd("schtasks", "/run", "/tn", "LabSCHAgentOnBoot")' in text
    assert 'tidak membuka window' in text
    assert 'GAGAL menjalankan task' in text
