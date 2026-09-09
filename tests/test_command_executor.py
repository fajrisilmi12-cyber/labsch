import importlib.util
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).parents[1] / 'agent' / 'command_executor.py'
spec = importlib.util.spec_from_file_location('command_executor_under_test', MODULE)
command_executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(command_executor)


class Result:
    def __init__(self, code=0, stdout=b'', stderr=b''):
        self.returncode=code; self.stdout=stdout; self.stderr=stderr


def test_restart_uses_absolute_shutdown_immediately():
    with patch.object(command_executor.subprocess, 'run', return_value=Result()) as run:
        outcome = command_executor.execute('restart')
    cmd = run.call_args.args[0]
    assert cmd[0].lower().endswith('system32/shutdown.exe') or cmd[0].lower().endswith(r'system32\shutdown.exe')
    assert cmd[1:5] == ['/r', '/t', '0', '/f']
    assert outcome.ok is True


def test_shutdown_failure_includes_windows_error():
    with patch.object(command_executor.subprocess, 'run', return_value=Result(5, stderr=b'Access is denied')):
        outcome = command_executor.execute('shutdown')
    assert outcome.ok is False
    assert 'exit=5' in outcome.reason
    assert 'Access is denied' in outcome.reason


def test_lock_uses_active_console_wts_disconnect_not_rundll32():
    with patch.object(command_executor, '_lock_active_console', return_value=(True, 'session=2')) as lock:
        outcome = command_executor.execute('lock')
    lock.assert_called_once()
    assert outcome.ok is True
    assert 'session=2' in outcome.reason


def test_unknown_command_fails_closed():
    outcome = command_executor.execute('format')
    assert outcome.ok is False
    assert 'unsupported' in outcome.reason
