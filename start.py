"""LMU Telemetry - one-click launcher for the web interface.

Pick the folder of recordings, start the API and the Vite dev server, and open
the browser on the page the two serve together.

The API is ``python -m lmu_telemetry.api`` on port 8000. That port is not a
preference: ``frontend/vite.config.js`` proxies ``/api`` to 127.0.0.1:8000, so
the browser only ever talks to Vite and Vite is the one that has to find the
API. This launcher used to start ``backend.main`` on 8001 - a module that no
longer exists, on a port nothing reads - which brought up two processes that
never met.
"""

import json
import re
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

#: Where the two servers' output is kept. Under ``.cache`` because that is
#: already ignored by git, and in files rather than pipes: a pipe nobody reads
#: fills and blocks the process writing into it, which on Windows is how a
#: launcher ends up staring at a backend that stopped talking for no visible
#: reason.
LOG_DIR = ROOT / ".cache" / "launcher"

API_PORT = 8000
#: What Vite is asked for. It moves to 5174 and up when the port is taken, so
#: the address actually opened is read back from its output, not assumed.
FRONTEND_PORT = 5173

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_VITE_LOCAL = re.compile(r"Local:\s*(http://\S+)")

# Windows-only flag; keeping the console hidden is the whole point of the GUI.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _python() -> str:
    """The interpreter to start the API with, preferring the project's venv."""
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


def _suggested_dir() -> str:
    """The folder to offer, in the order the rest of the project prefers.

    ``lmu_telemetry.recordings`` already answers this - the curated working set
    where it exists, the launcher's own configured folder otherwise - so asking
    it is what keeps the box agreeing with what the API would pick on its own.
    It imports nothing heavier than ``json``, so it is safe before any check
    that the dependencies are installed.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from lmu_telemetry.recordings import default_recordings_dir

        found = default_recordings_dir()
        if found.is_dir():
            return str(found)
    except Exception:
        pass
    return _load_config().get("telemetry_dir", "")


def _tail(path: Path, lines: int = 8) -> str:
    """The last few lines a server wrote, for a message that says what broke."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return " / ".join(text.strip().splitlines()[-lines:])


class LauncherApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("LMU Telemetry — Launcher")
        self.root.resizable(False, False)
        self.root.configure(bg="#111114")

        self.backend_proc: subprocess.Popen | None = None
        self.frontend_proc: subprocess.Popen | None = None
        self.backend_log = LOG_DIR / "api.log"
        self.frontend_log = LOG_DIR / "frontend.log"
        self.url = f"http://localhost:{FRONTEND_PORT}"

        self.telemetry_dir = tk.StringVar(value=_suggested_dir())

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
        ttk.Label(self.root, text="Pick your recordings folder and launch.",
                  style="Status.TLabel").pack(**pad)

        # --- Folder picker ---
        folder_frame = tk.Frame(self.root, bg="#111114")
        folder_frame.pack(fill="x", **pad)

        ttk.Label(folder_frame, text="Recordings folder:").pack(anchor="w")

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

        self.open_btn = ttk.Button(btn_frame, text="Open in browser",
                                   command=self._open, state="disabled")
        self.open_btn.pack(fill="x", pady=(6, 0))

        self.stop_btn = ttk.Button(btn_frame, text="Stop",
                                   command=self._stop, state="disabled")
        self.stop_btn.pack(fill="x", pady=(6, 0))

        # --- Status ---
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var,
                  style="Status.TLabel", wraplength=430,
                  justify="left").pack(pady=(4, 16), padx=16)

    def _browse(self) -> None:
        d = filedialog.askdirectory(
            title="Select the folder holding your .duckdb recordings",
            initialdir=self.telemetry_dir.get() or str(Path.home()))
        if d:
            self.telemetry_dir.set(d)

    # ---- Launch / Stop ----------------------------------------------------

    def _launch(self) -> None:
        tdir = self.telemetry_dir.get().strip()
        if not tdir or not Path(tdir).is_dir():
            self.status_var.set("⚠  That folder is not there. Pick another.")
            return
        if not any(Path(tdir).glob("*.duckdb")):
            self.status_var.set(
                f"⚠  No .duckdb recordings in {Path(tdir).name}. "
                f"Pick the folder the game writes telemetry into.")
            return

        _save_config({"telemetry_dir": tdir})

        self.launch_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Starting the API…")

        threading.Thread(target=self._start_servers, args=(tdir,),
                         daemon=True).start()

    def _start_servers(self, tdir: str) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # --- API ---
        # The folder is passed explicitly rather than left to the default: the
        # driver just chose it in the box above, and a launcher that then
        # served somewhere else would be ignoring the only question it asked.
        try:
            api_out = self.backend_log.open("w", encoding="utf-8")
            self.backend_proc = subprocess.Popen(
                [_python(), "-m", "lmu_telemetry.api",
                 "--recordings", tdir, "--port", str(API_PORT)],
                cwd=str(ROOT),
                stdout=api_out,
                stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW,
            )
        except Exception as exc:
            self._fail(f"❌  The API would not start: {exc}")
            return

        if not self._wait_for(f"http://localhost:{API_PORT}/api/health",
                              self.backend_proc, self.backend_log, 30):
            return

        # --- Frontend ---
        if not (FRONTEND_DIR / "node_modules").is_dir():
            self._fail("❌  frontend/node_modules is missing. "
                       "Run 'npm install' in the frontend folder first.")
            return

        self._set_status("Starting the browser interface…")
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        try:
            web_out = self.frontend_log.open("w", encoding="utf-8")
            self.frontend_proc = subprocess.Popen(
                [npm, "run", "dev"],
                cwd=str(FRONTEND_DIR),
                stdout=web_out,
                stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW,
            )
        except FileNotFoundError:
            self._fail("❌  npm was not found. Install Node.js 18 or newer.")
            return
        except Exception as exc:
            self._fail(f"❌  The browser interface would not start: {exc}")
            return

        self.url = self._await_vite() or f"http://localhost:{FRONTEND_PORT}"
        if not self._wait_for(self.url, self.frontend_proc,
                              self.frontend_log, 30):
            return

        self._open()
        self.root.after(0, lambda: self.open_btn.configure(state="normal"))
        self._set_status(
            f"✅  Running at {self.url}  (API on :{API_PORT})\n"
            f"The first listing reads every recording and takes a few seconds."
        )

    def _await_vite(self, timeout: float = 20.0) -> "str | None":
        """The address Vite actually bound, read from its own output.

        It is asked for 5173 and takes the next free port when something else
        holds it, so opening 5173 regardless is how the browser lands on a page
        that is not this one - or on nothing at all.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.frontend_proc and self.frontend_proc.poll() is not None:
                return None
            try:
                text = _ANSI.sub("", self.frontend_log.read_text(
                    encoding="utf-8", errors="replace"))
            except OSError:
                text = ""
            found = _VITE_LOCAL.search(text)
            if found:
                return found.group(1).rstrip("/")
            time.sleep(0.25)
        return None

    def _wait_for(self, url: str, proc: subprocess.Popen, log: Path,
                  timeout: int) -> bool:
        """Poll *url* until it answers, giving up if *proc* dies first.

        Health, not the session listing: ``/api/sessions`` opens every
        recording it can find, which measured 17 s over 239 of them on a cold
        cache. Waiting on that would report the API as slow to start when it
        started immediately and is doing exactly what it was asked to.
        """
        self._set_status(f"Waiting for {url} …")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self._fail(f"❌  It stopped on its own: {_tail(log)}")
                return False
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status < 500:
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        self._fail(f"⚠  No answer from {url} after {timeout} s: {_tail(log)}")
        return False

    def _open(self) -> None:
        webbrowser.open(self.url)

    def _stop(self) -> None:
        self._kill(self.frontend_proc)
        self._kill(self.backend_proc)
        self.frontend_proc = None
        self.backend_proc = None
        self._reset_buttons()
        self.status_var.set("Stopped.")

    # ---- Helpers ----------------------------------------------------------

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

    def _fail(self, message: str) -> None:
        """Report why, and leave nothing half-started behind."""
        self._kill(self.frontend_proc)
        self._kill(self.backend_proc)
        self.frontend_proc = None
        self.backend_proc = None
        self._set_status(message)
        self._reset_buttons()

    def _set_status(self, msg: str) -> None:
        self.root.after(0, lambda: self.status_var.set(msg))

    def _reset_buttons(self) -> None:
        def _do():
            self.launch_btn.configure(state="normal")
            self.open_btn.configure(state="disabled")
            self.stop_btn.configure(state="disabled")
        self.root.after(0, _do)

    def _on_close(self) -> None:
        self._stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    LauncherApp().run()
