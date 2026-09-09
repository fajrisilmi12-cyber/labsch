"""Visible, non-elevated console-session handoff; no UAC bypass.

SYSTEM uses WTSQueryUserToken (documented Windows API) and CreateProcessAsUser
with the logged-in user's token. Elevated non-SYSTEM agents fail closed rather
than launch with administrator privileges. A helper exits after ShellExecute
accepts the request; this proves dispatch, not application completion.
"""
import os
import sys
from pathlib import Path


def launch_user_file(path):
    if os.name != 'nt':
        raise OSError('Windows user-session launch is unavailable on this platform')
    import subprocess
    import win32api
    import win32con
    import win32event
    import win32process
    import win32profile
    import win32security
    import win32ts
    import win32com.shell.shell as shell

    session = win32ts.WTSGetActiveConsoleSessionId()
    if session == 0xFFFFFFFF or session == 0:
        raise OSError('No active console user session; autorun not performed')
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        system = win32security.ConvertSidToStringSid(sid) == 'S-1-5-18'
        elevated = bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
    finally:
        token.Close()
    if not system:
        if elevated or win32ts.ProcessIdToSessionId(os.getpid()) != session:
            raise OSError('User launch requires SYSTEM handoff or an unelevated active-console agent')
        shell.ShellExecuteEx(fMask=0x00000100, lpVerb='open', lpFile=str(path), nShow=1)
        return

    user_token = win32ts.WTSQueryUserToken(session)
    process = thread = None
    try:
        # A filtered user token is required, even when a console admin is logged in.
        if win32security.GetTokenInformation(user_token, win32security.TokenElevation):
            raise OSError('Active user token is elevated; refusing privileged user launch')
        startup = win32process.STARTUPINFO()
        startup.lpDesktop = 'winsta0\\default'
        helper = str(Path(__file__).resolve())
        executable = str(Path(sys.executable).with_name('python.exe'))
        command = subprocess.list2cmdline([executable, helper, '--open', str(Path(path).resolve())])
        process, thread, _, _ = win32process.CreateProcessAsUser(
            user_token, executable, command, None, None, False,
            win32con.CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_NO_WINDOW,
            win32profile.CreateEnvironmentBlock(user_token, False), str(Path(helper).parent), startup)
        if win32event.WaitForSingleObject(process, 20000) != win32event.WAIT_OBJECT_0:
            raise OSError('User helper timed out; launch outcome unknown, will not retry')
        code = win32process.GetExitCodeProcess(process)
        if code != 0:
            raise OSError('User helper rejected launch (exit %s)' % code)
    finally:
        if process: process.Close()
        if thread: thread.Close()
        user_token.Close()


def _helper(path):
    # Helper has no credentials, network, task queue, or admin operations.
    import win32com.shell.shell as shell
    candidate = Path(path).resolve(strict=True)
    public = Path(os.environ.get('PUBLIC', 'C:/Users/Public')).resolve()
    if not any(candidate.is_relative_to(public / folder) for folder in ('Desktop', 'Documents')):
        raise OSError('outside approved public destination')
    shell.ShellExecuteEx(fMask=0x00000100, lpVerb='open', lpFile=str(candidate), nShow=1)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3 or sys.argv[1] != '--open':
            raise ValueError('invalid helper arguments')
        _helper(sys.argv[2])
    except Exception:
        sys.exit(1)
