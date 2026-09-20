"""LabSCH Launcher — kiosk-style app launcher for lab PCs (Steam Big Picture style).

Runs in the *student's* console session (launched by the LabSCH agent via
windows_launch.py). Fullscreen tile grid of approved apps only:

    Microsoft Word / Excel / PowerPoint, Chrome, Cisco Packet Tracer, VirtualBox

Features:
- Fullscreen, always-on-top kiosk window; no taskbar/desktop access.
- Exit ONLY via admin password (hashed; sha256('admin123') shipped default).
- Anti-kill: agent re-spawns this launcher on every heartbeat when launcher
  mode is enabled server-side, so taskkill bounces back within ~30s.
- Apps detected via registry (InstallLocation / App Paths) with sane fallbacks.

Control (server side):
    labschctl command <pc> launcher-start     # agent receives pending_command
    labschctl command <pc> launcher-stop      # graceful close requires password;
                                              # force-kill path handled server side

This file is intentionally dependency-free (tkinter + stdlib only) so it runs
on stock Python installs in lab images.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

PROGRAMDATA = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
CONFIG_DIR = PROGRAMDATA / "LabSCHLauncher"
STATE_FILE = CONFIG_DIR / "launcher.json"
TOKEN_FILE = CONFIG_DIR / "exit.hash"

DEFAULT_PASSWORD = "admin123"

# Registry-driven app definitions. Each entry: (label, exe, probe keys, fallback paths)
APPS = [
    {
        "label": "Microsoft Word",
        "exe": "WINWORD.EXE",
        "keys": [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE"],
        "fallbacks": [
            r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
        ],
    },
    {
        "label": "Microsoft Excel",
        "exe": "EXCEL.EXE",
        "keys": [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\EXCEL.EXE"],
        "fallbacks": [
            r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE",
        ],
    },
    {
        "label": "Microsoft PowerPoint",
        "exe": "POWERPNT.EXE",
        "keys": [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE"],
        "fallbacks": [
            r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE",
        ],
    },
    {
        "label": "Google Chrome",
        "exe": "chrome.exe",
        "keys": [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"],
        "fallbacks": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
    },
    {
        "label": "Cisco Packet Tracer",
        "exe": "PacketTracer.exe",
        "keys": [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PacketTracer.exe"],
        "fallbacks": [
            r"C:\Program Files\Cisco Packet Tracer 8.2.2\bin\PacketTracer.exe",
            r"C:\Program Files\Cisco Packet Tracer 8.2.1\bin\PacketTracer.exe",
            r"C:\Program Files\Cisco Packet Tracer 8.2.0\bin\PacketTracer.exe",
            r"C:\Program Files\Cisco Packet Tracer 8.1.1\bin\PacketTracer.exe",
            r"C:\Program Files\Cisco Packet Tracer 8.0.1\bin\PacketTracer.exe",
            r"C:\Program Files\Cisco Packet Tracer 7.3.2\bin\PacketTracer.exe",
        ],
    },
    {
        "label": "Oracle VirtualBox",
        "exe": "VirtualBox.exe",
        "keys": [r"SOFTWARE\Oracle\VirtualBox\InstallDir"],
        "fallbacks": [
            r"C:\Program Files\Oracle\VirtualBox\VirtualBox.exe",
            r"C:\Program Files\Oracle\VirtualBox\VirtualBoxVM.exe",
        ],
    },
]


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def exit_hash() -> str:
    """Return stored exit-password hash, seeding default on first run."""
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        h = sha256_hex(DEFAULT_PASSWORD)
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(h, encoding="utf-8")
        except OSError:
            pass
        return h


def set_password(plain: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(sha256_hex(plain), encoding="utf-8")


def resolve_app(app: dict):
    """Return executable path for an app def, or None."""
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    for key in app["keys"]:
        for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                           (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val and Path(val).is_file():
                        return val
            except OSError:
                continue
    for p in app["fallbacks"]:
        if Path(p).is_file():
            return p
    return None


def detected_apps():
    found = []
    for app in APPS:
        path = resolve_app(app)
        if path:
            found.append((app["label"], path))
    return found


class Kiosk(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LabSCH Launcher")
        self.configure(bg="#0f1420")
        self._to_fullscreen()
        self._setup_fonts()
        self._build_header()
        self._build_grid()
        self._build_footer()
        self.bind("<Escape>", lambda e: None)          # no ESC exit
        self.bind("<Alt-F4>", self._guard_exit)        # guarded
        self.protocol("WM_DELETE_WINDOW", self._guard_exit)
        self.attributes("-topmost", True)
        # Re-assert fullscreen periodically (defeats Win+D show-desktop briefly)
        self.after(5000, self._reassert_fullscreen)

    def _to_fullscreen(self):
        try:
            self.state("zoomed")
        except tk.TclError:
            w, h = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"{w}x{h}+0+0")
            self.overrideredirect(True)

    def _reassert_fullscreen(self):
        try:
            if not self.state() == "zoomed":
                self.state("zoomed")
        except tk.TclError:
            pass
        self.after(5000, self._reassert_fullscreen)

    def _setup_fonts(self):
        self.f_title = tkfont.Font(family="Segoe UI", size=28, weight="bold")
        self.f_tile = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.f_sub = tkfont.Font(family="Segoe UI", size=10)
        self.f_footer = tkfont.Font(family="Segoe UI", size=9)

    def _build_header(self):
        bar = tk.Frame(self, bg="#0f1420")
        bar.pack(fill="x", padx=40, pady=(28, 8))
        tk.Label(bar, text="LABSCH LAUNCHER", font=self.f_title,
                 bg="#0f1420", fg="#ffffff").pack(side="left")
        tk.Label(bar, text="  Komputer Lab — aplikasi terkelola",
                 font=self.f_sub, bg="#0f1420", fg="#8ea0c0").pack(side="left", pady=(12, 0))

    def _build_grid(self):
        self.apps = detected_apps()
        grid = tk.Frame(self, bg="#0f1420")
        grid.pack(expand=True)
        cols = 3
        for i, (label, path) in enumerate(self.apps):
            r, c = divmod(i, cols)
            self._tile(grid, label, path, r, c)
        if not self.apps:
            tk.Label(grid, text="Tidak ada aplikasi terdeteksi.\nHubungi administrator.",
                     font=self.f_tile, bg="#0f1420", fg="#e8b04a").grid(row=0, column=0, padx=40, pady=40)

    def _tile(self, parent, label, path, r, c):
        box = tk.Frame(parent, bg="#1a2333", highlightthickness=1,
                       highlightbackground="#2b3a55", cursor="hand2")
        box.grid(row=r, column=c, padx=18, pady=18, sticky="nsew")
        initial = label[0].upper()
        tk.Label(box, text=initial, font=tkfont.Font(family="Segoe UI", size=34, weight="bold"),
                 bg="#1a2333", fg="#5aa2ff").pack(pady=(26, 4))
        tk.Label(box, text=label, font=self.f_tile, bg="#1a2333", fg="#ffffff").pack(pady=(0, 6))
        tk.Label(box, text="Klik untuk membuka", font=self.f_sub,
                 bg="#1a2333", fg="#8ea0c0").pack(pady=(0, 24))
        for w in (box, *box.winfo_children()):
            w.bind("<Button-1>", lambda e, p=path: self._open(p))
            w.bind("<Enter>", lambda e, b=box: b.configure(bg="#243350"))
            w.bind("<Leave>", lambda e, b=box: b.configure(bg="#1a2333"))
        parent.grid_columnconfigure(c, weight=1)

    def _build_footer(self):
        foot = tk.Frame(self, bg="#0f1420")
        foot.pack(fill="x", side="bottom", pady=(0, 18))
        tk.Label(foot, text="Dikelola LabSCH • Untuk keluar, hubungi administrator (password admin)",
                 font=self.f_footer, bg="#0f1420", fg="#5a6c8c").pack()
        btn = tk.Button(foot, text="Keluar (admin)", font=self.f_footer,
                        bg="#1a2333", fg="#8ea0c0", activebackground="#243350",
                        activeforeground="#ffffff", relief="flat", padx=14, pady=4,
                        command=self._guard_exit)
        btn.pack(pady=(6, 0))

    def _open(self, path):
        try:
            # DETACHED_PROCESS so closing the launcher doesn't kill the app,
            # and the app's windows appear on the user's desktop.
            subprocess.Popen([path], closefd=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            self._flash(f"{Path(path).stem} dibuka")
        except Exception as exc:
            self._flash(f"Gagal membuka: {exc}")

    def _flash(self, text):
        try:
            self._toast.destroy()
        except Exception:
            pass
        self._toast = tk.Label(self, text=text, font=self.f_sub, bg="#243350", fg="#ffffff", padx=18, pady=8)
        self._toast.place(relx=0.5, rely=0.92, anchor="center")
        self.after(2600, self._toast.destroy)

    # ---- exit guard -------------------------------------------------
    def _guard_exit(self, event=None):
        self._ask_password()

    def _ask_password(self):
        if getattr(self, "_pw", None) is not None and self._pw.winfo_exists():
            self._pw.lift()
            self._pw.focus_set()
            return
        pw = tk.Toplevel(self, bg="#0f1420")
        pw.title("Autentikasi Admin")
        pw.geometry("380x190")
        pw.resizable(False, False)
        pw.attributes("-topmost", True)
        pw.grab_set()
        x = self.winfo_screenwidth() // 2 - 190
        y = self.winfo_screenheight() // 2 - 95
        pw.geometry(f"+{x}+{y}")
        tk.Label(pw, text="Password Admin", font=self.f_tile, bg="#0f1420", fg="#ffffff").pack(pady=(20, 4))
        tk.Label(pw, text="Masukkan password untuk menutup launcher", font=self.f_sub,
                 bg="#0f1420", fg="#8ea0c0").pack()
        entry = tk.Entry(pw, show="•", font=tkfont.Font(family="Segoe UI", size=13),
                         bg="#1a2333", fg="#ffffff", insertbackground="#ffffff",
                         relief="flat", justify="center")
        entry.pack(pady=14, ipadx=30, ipady=6)
        status = tk.Label(pw, text="", font=self.f_sub, bg="#0f1420", fg="#ff6b6b")
        status.pack()

        def check(ev=None):
            if sha256_hex(entry.get()) == exit_hash():
                pw.grab_release()
                pw.destroy()
                self._close_kiosk()
            else:
                status.config(text="Password salah")
                entry.delete(0, "end")

        def on_exit():
            try:
                if pw.grab_current():
                    pw.grab_release()
            except Exception:
                pass
            pw.destroy()

        btns = tk.Frame(pw, bg="#0f1420")
        btns.pack(pady=(2, 12))
        tk.Button(btns, text="Buka Launcher", font=self.f_sub, bg="#243350", fg="#ffffff",
                  relief="flat", padx=16, command=check).pack(side="left", padx=6)
        tk.Button(btns, text="Batal", font=self.f_sub, bg="#1a2333", fg="#8ea0c0",
                  relief="flat", padx=16, command=on_exit).pack(side="left", padx=6)
        pw.protocol("WM_DELETE_WINDOW", on_exit)
        entry.bind("<Return>", check)
        entry.focus_set()
        self._pw = pw

    def _close_kiosk(self):
        # Mark graceful admin exit so the agent doesn't immediately re-spawn us.
        try:
            state = load_state()
            state["admin_exit_at"] = int(__import__("time").time())
            save_state(state)
        except Exception:
            pass
        self.destroy()


def main() -> int:
    if os.name != "nt":
        print("LabSCH Launcher hanya untuk Windows.", file=sys.stderr)
        return 1
    app = Kiosk()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
