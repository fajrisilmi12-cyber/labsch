"""Install LabSCHAgent as Windows service.

Run as Administrator:
  python install_service.py install
  python install_service.py start
  python install_service.py stop
  python install_service.py remove
"""
import sys
from pathlib import Path

# Detect pywin32
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except ImportError:
    print("pywin32 not installed. Run: pip install pywin32")
    sys.exit(1)


class LabSCHAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "LabSCHAgent"
    _svc_display_name_ = "LabSCHAgent — School Client Manager"
    _svc_description_ = ("Heartbeat + config sync for labsch-manager server. "
                         "Manages website/app blocklist per server policy.")

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.running = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        self.running = False

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ''),
        )
        self.main()

    def main(self):
        # Import here to avoid path issues when running as service
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from labsch_agent import run_loop, load_agent_config
        cfg = load_agent_config()
        run_loop(cfg)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(LabSCHAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(LabSCHAgentService)
