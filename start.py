"""LMU Telemetry Analyzer — One-Click Launcher.

Opens a small GUI to pick the telemetry folder, then starts
backend (uvicorn) + frontend (vite) and opens the browser.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / ".telemetry_config.json"
FRONTEND_DIR = ROOT / "frontend"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

BACKEND_PORT = 8001
FRONTEND_PORT = 5173
BROWSER_URL = f"http://localhost:{FRONTEND_PORT}"


def _python() -> str:
    """Return the best available Python executable."""
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def _load_config() -> dict:
    if CONFIG_FILE.is_file():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


class LauncherApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("LMU Telemetry — Launcher")
        self.root.resizable(False, False)
        self.root.configure(bg="#111114")

        self.backend_proc: subprocess.Popen | None = None
        self.frontend_proc: subprocess.Popen | None = None

        cfg = _load_config()
        self.telemetry_dir = tk.StringVar(value=cfg.get("telemetry_dir", ""))

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TLabel", background="#111114", foreground="#e0e0e0",
                        font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 14, "bold"),
                        foreground="#3b82f6")
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Launch.TButton", font=("Segoe UI", 12, "bold"))
        style.configure("Status.TLabel", foreground="#888888",
                        font=("Segoe UI", 9))

        pad = {"padx": 16, "pady": 4}

        ttk.Label(self.root, text="LMU Telemetry Analyzer",
                  style="Title.TLabel").pack(pady=(16, 4), **{"padx": 16})
        ttk.Label(self.root, text="Pick your telemetry folder and launch.",
                  style="Status.TLabel").pack(**pad)

        # --- Folder picker ---
        folder_frame = tk.Frame(self.root, bg="#111114")
        folder_frame.pack(fill="x", **pad)

        ttk.Label(folder_frame, text="Telemetry folder:").pack(anchor="w")

        row = tk.Frame(folder_frame, bg="#111114")
        row.pack(fill="x", pady=4)

        self.dir_entry = ttk.Entry(row, textvariable=self.telemetry_dir,
                                   width=50)
        self.dir_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._browse).pack(
            side="left", padx=(6, 0))

        # --- Buttons ---
        btn_frame = tk.Frame(self.root, bg="#111114")
        btn_frame.pack(fill="x", padx=16, pady=(12, 4))

        self.launch_btn = ttk.Button(btn_frame, text="🚀  Launch",
                                     style="Launch.TButton",
                                     command=self._launch)
        self.launch_btn.pack(fill="x", ipady=6)

        self.stop_btn = ttk.Button(btn_frame, text="Stop",
                                   command=self._stop, state="disabled")
        self.stop_btn.pack(fill="x", pady=(6, 0))

        # --- Status ---
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var,
                  style="Status.TLabel").pack(pady=(4, 16), padx=16)

    def _browse(self) -> None:
        d = filedialog.askdirectory(title="Select Telemetry Folder",
                                    initialdir=self.telemetry_dir.get() or str(Path.home()))
        if d:
            self.telemetry_dir.set(d)

    # ---- Launch / Stop ----------------------------------------------------

    def _launch(self) -> None:
        tdir = self.telemetry_dir.get().strip()
        if not tdir or not Path(tdir).is_dir():
            self.status_var.set("⚠  Please select a valid folder.")
            return

        # Save choice
        _save_config({"telemetry_dir": tdir})

        self.launch_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Starting backend…")

        threading.Thread(target=self._start_servers, args=(tdir,),
                         daemon=True).start()

    def _start_servers(self, tdir: str) -> None:
        env = {**os.environ, "TELEMETRY_DIR": tdir}
        py = _python()

        # --- Backend ---
        try:
            self.backend_proc = subprocess.Popen(
                [py, "-m", "uvicorn", "backend.main:app",
                 "--host", "0.0.0.0", "--port", str(BACKEND_PORT)],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as exc:
            self._set_status(f"❌  Backend failed: {exc}")
            self._reset_buttons()
            return

        self._set_status("Starting frontend…")

        # --- Frontend ---
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        try:
            self.frontend_proc = subprocess.Popen(
                [npm, "run", "dev"],
                cwd=str(FRONTEND_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as exc:
            self._set_status(f"❌  Frontend failed: {exc}")
            self._kill(self.backend_proc)
            self._reset_buttons()
            return

        # Wait for backend to be ready (up to 30 s)
        self._set_status("Waiting for backend…")
        if not self._wait_for_port(f"http://localhost:{BACKEND_PORT}/api/sessions", 30):
            self._set_status("⚠  Backend slow to start — opening browser anyway…")

        # Wait for frontend to be ready (up to 20 s)
        self._set_status("Waiting for frontend…")
        if not self._wait_for_port(f"http://localhost:{FRONTEND_PORT}/", 20):
            self._set_status("⚠  Frontend slow to start — opening browser anyway…")

        webbrowser.open(BROWSER_URL)
        self._set_status(
            f"✅  Running — Backend :{BACKEND_PORT}  |  Frontend :{FRONTEND_PORT}"
        )

    def _stop(self) -> None:
        self._kill(self.frontend_proc)
        self._kill(self.backend_proc)
        self.frontend_proc = None
        self.backend_proc = None
        self._reset_buttons()
        self.status_var.set("Stopped.")

    # ---- Helpers ----------------------------------------------------------

    @staticmethod
    def _wait_for_port(url: str, timeout: int = 30) -> bool:
        """Poll *url* until it responds with HTTP 200 (or *timeout* expires)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status < 500:
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    @staticmethod
    def _kill(proc: subprocess.Popen | None) -> None:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _set_status(self, msg: str) -> None:
        self.root.after(0, lambda: self.status_var.set(msg))

    def _reset_buttons(self) -> None:
        def _do():
            self.launch_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
        self.root.after(0, _do)

    def _on_close(self) -> None:
        self._stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    LauncherApp().run()
