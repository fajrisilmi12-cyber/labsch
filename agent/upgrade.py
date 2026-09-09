"""Manual-admin, existing-config-only upgrade. No credential prompts or elevation."""
import json
import os
import sys
import shutil
import subprocess
from pathlib import Path

MODULES = ['labsch_agent.py','config_sync.py','app_blocker.py','website_blocker.py',
           'browser_policy.py','ifeo_blocker.py','self_protect.py','device_id.py',
           'device_blocker.py','command_executor.py','downloader.py','windows_launch.py']


def validate_existing_config(path):
    if not path.is_file():
        raise ValueError('Existing ProgramData/LabSCHAgent/config.ini required; this is an upgrade, not enrollment')
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    if not cfg.get('api_token') or not str(cfg.get('server_url','')).startswith('https://'):
        raise ValueError('Existing config must contain HTTPS server_url and api_token')
    return cfg


def run(args, required=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if required and result.returncode:
        raise OSError('Command failed: ' + args[0] + ' (exit %s)' % result.returncode)
    return result


def main():
    import ctypes
    if os.name != 'nt' or not ctypes.windll.shell32.IsUserAnAdmin():
        raise OSError('Right-click upgrade.bat: Run as administrator. No automatic elevation.')
    source = Path(__file__).resolve().parent
    state = Path(os.environ['PROGRAMDATA'])/'LabSCHAgent'
    validate_existing_config(state/'config.ini')
    # Explicitly refuse service-managed older installations: do not install a
    # second service or race a service manager's recovery policy.
    import psutil
    for service in psutil.win_service_iter():
        data = service.as_dict()
        if 'labsch' in (data['name']+' '+data.get('display_name','')).lower():
            raise OSError('Existing LabSCH Windows service detected. Stop/remove that service manually before this scheduled-task upgrade.')
    target = Path(os.environ['ProgramFiles'])/'LabSCHAgent'
    target.mkdir(parents=True, exist_ok=True)
    # Protect code/runtime and state. Students get code READ only, no config.
    run(['icacls',str(target),'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F','*S-1-5-32-545:(OI)(CI)RX'])
    run(['icacls',str(state),'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'])
    # Stop named legacy autostarts before copying. Never kill arbitrary Python.
    for task in ['LabSCHAgentWatchdog','LabSCHAgentOnBoot','LabSCHAgent']:
        run(['schtasks','/End','/TN',task],False)
        run(['schtasks','/Delete','/TN',task,'/F'],False)
    run(['reg','delete',r'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run','/v','LabSCHAgent','/f'],False)
    victims=[]
    for proc in psutil.process_iter(['pid','name','cmdline']):
        if proc.pid == os.getpid(): continue
        args=proc.info['cmdline'] or []
        name=(proc.info['name'] or '').lower()
        if name in ('labschagent.exe','madaniagent.exe') or (name in ('python.exe','pythonw.exe') and any(Path(a).name.lower()=='labsch_agent.py' for a in args)):
            proc.terminate(); victims.append(proc)
    _,alive=psutil.wait_procs(victims,timeout=10)
    if alive: raise OSError('Old agent did not stop; no new agent started. Resolve manually and rerun upgrade.')
    for module in MODULES:
        shutil.copy2(source/module,target/module)
    shutil.copytree(source/'runtime',target/'runtime',dirs_exist_ok=True)
    python = target/'runtime/python.exe'
    # Import every shipped dependency before registering a persistent task.
    run([str(python),'-c','import psutil, win32api, win32ts, win32process, win32profile, win32security, win32com.shell.shell'])
    command = subprocess.list2cmdline([str(python),str(target/'labsch_agent.py')])
    # One SYSTEM task, policy IgnoreNew, 30-second restart on failure.
    from xml.sax.saxutils import escape
    xml = '''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
<Principals><Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure></Settings>
<Actions Context="System"><Exec><Command>PYTHON</Command><Arguments>ARGS</Arguments><WorkingDirectory>CWD</WorkingDirectory></Exec></Actions></Task>'''.replace('PYTHON',escape(str(python))).replace('ARGS',escape(subprocess.list2cmdline([str(target/'labsch_agent.py')]))).replace('CWD',escape(str(target)))
    taskfile=target/'agent-task.xml'; taskfile.write_text(xml,encoding='utf-16')
    run(['schtasks','/Create','/TN','LabSCHAgent','/XML',str(taskfile),'/F'])
    run(['schtasks','/Run','/TN','LabSCHAgent'])
    print('Upgrade installed to',target)
    print('Existing config and identity preserved. One SYSTEM task started.')
    print('Physical Windows acceptance still required: logged-in console document visibility, heartbeat, one agent PID.')


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('UPGRADE FAILED:',exc)
        sys.exit(1)
