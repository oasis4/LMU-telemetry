"""Desktop launcher and internal workers for the portable Windows bundle."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import filedialog, ttk

ROOT = Path(__file__).resolve().parent


def state_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "LMU Telemetry"


def frontend_dir() -> Path:
    return ROOT / "frontend" / "dist"


def worker_command(mode: str, recordings: Path, readiness: Path | None = None) -> list[str]:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(ROOT / "start.py"))
    command += ["--worker", mode, "--recordings", str(recordings)]
    if readiness is not None:
        command += ["--readiness", str(readiness)]
    return command


def load_folder() -> str:
    try:
        named = json.loads((state_dir() / "settings.json").read_text(encoding="utf-8"))["telemetry_dir"]
        return named if Path(named).is_dir() else ""
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def stop_process(proc) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def run_worker(args) -> int:
    if not args.recordings or not args.recordings.is_dir():
        raise ValueError("Choose an existing recordings folder")
    if args.worker == "overlay":
        from lmu_telemetry.live.__main__ import main
        return main(["--recordings", str(args.recordings)])
    if args.readiness is None:
        raise ValueError("API worker requires a readiness file")
    import socket
    from contextlib import asynccontextmanager
    import uvicorn
    from lmu_telemetry.api.app import create_app
    app = create_app(args.recordings, cache_dir=state_dir() / "cache", frontend_dir=frontend_dir())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, loop="asyncio", http="h11"))
    # Publish only after ASGI startup completes. The socket remains owned by
    # this worker from allocation through serving, avoiding port-selection races.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        lifecycle = app.router.lifespan_context
        @asynccontextmanager
        async def ready(application):
            async with lifecycle(application):
                args.readiness.write_text(json.dumps({"url": f"http://127.0.0.1:{sock.getsockname()[1]}"}), encoding="utf-8")
                yield
        app.router.lifespan_context = ready
        server.run(sockets=[sock])
    return 0


class LauncherApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("LMU Telemetry")
        self.processes = {"api": None, "overlay": None}
        self.started = {}
        self.url = None
        self.readiness = state_dir() / f"ready-{os.getpid()}.json"
        self.folder = tk.StringVar(value=load_folder())
        self.status = {mode: tk.StringVar(value="Stopped") for mode in self.processes}
        self.buttons = {}
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Recordings folder").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.folder, width=65).pack(fill="x", pady=4)
        ttk.Button(frame, text="Browse…", command=self.browse).pack(anchor="w")
        for mode, label in (("api", "analyzer"), ("overlay", "live overlay")):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=8)
            start = ttk.Button(row, text=f"Start {label}", command=lambda m=mode: self.start(m))
            start.pack(side="left")
            stop = ttk.Button(row, text=f"Stop {label}", state="disabled", command=lambda m=mode: self.stop(m))
            stop.pack(side="left", padx=6)
            self.buttons[mode] = (start, stop)
            ttk.Label(frame, textvariable=self.status[mode], wraplength=480).pack(anchor="w")
        self.open_button = ttk.Button(frame, text="Open analyzer in browser", state="disabled", command=self.open_browser)
        self.open_button.pack(pady=8)
        ttk.Button(frame, text="Open logs", command=self.open_logs).pack()
        ttk.Label(frame, text="Keep this launcher open while using the analyzer or overlay.").pack(pady=8)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(250, self.poll)

    def browse(self):
        selected = filedialog.askdirectory(initialdir=self.folder.get() or str(Path.home()))
        if selected:
            self.folder.set(selected)

    def start(self, mode):
        folder = Path(self.folder.get().strip())
        if not self.folder.get().strip() or not folder.is_dir() or not any(folder.glob("*.duckdb")):
            self.status[mode].set("Choose a folder containing .duckdb recordings.")
            return
        try:
            state_dir().mkdir(parents=True, exist_ok=True)
            (state_dir() / "settings.json").write_text(json.dumps({"telemetry_dir": str(folder.resolve())}), encoding="utf-8")
            if mode == "api":
                self.readiness.unlink(missing_ok=True)
                self.url = None
            with (state_dir() / f"{mode}.log").open("w", encoding="utf-8") as log:
                self.processes[mode] = subprocess.Popen(
                    worker_command(mode, folder.resolve(), self.readiness if mode == "api" else None),
                    stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
            self.started[mode] = time.monotonic()
            self.buttons[mode][0].configure(state="disabled")
            self.buttons[mode][1].configure(state="normal")
            self.status[mode].set("Starting…" if mode == "api" else "Running; waiting for game/reference if needed. See logs for details.")
        except Exception as exc:
            self.status[mode].set(f"Could not start: {exc}")

    def poll(self):
        for mode, proc in list(self.processes.items()):
            if proc is None:
                continue
            if proc.poll() is not None:
                try:
                    details = " / ".join((state_dir() / f"{mode}.log").read_text(encoding="utf-8", errors="replace").splitlines()[-4:])
                except OSError:
                    details = "Open logs for details."
                code = proc.returncode
                self.stop(mode)
                self.status[mode].set(f"Exited ({code}): {details}")
            elif mode == "api" and self.url is None:
                try:
                    url = json.loads(self.readiness.read_text(encoding="utf-8"))["url"]
                    with urllib.request.urlopen(url + "/api/health", timeout=0.2) as response:
                        if response.status == 200:
                            self.url = url
                            self.status[mode].set(f"Running at {url}")
                            self.open_button.configure(state="normal")
                            self.open_browser()
                except (OSError, ValueError, KeyError):
                    pass
                if self.url is None and time.monotonic() - self.started[mode] > 60:
                    self.stop(mode)
                    self.status[mode].set("Startup timed out. Open logs for details.")
        self.root.after(250, self.poll)

    def stop(self, mode):
        stop_process(self.processes[mode])
        self.processes[mode] = None
        self.buttons[mode][0].configure(state="normal")
        self.buttons[mode][1].configure(state="disabled")
        self.status[mode].set("Stopped")
        if mode == "api":
            self.url = None
            self.open_button.configure(state="disabled")
            self.readiness.unlink(missing_ok=True)

    def open_browser(self):
        if self.url:
            webbrowser.open(self.url)

    def open_logs(self):
        state_dir().mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(state_dir())
        else:
            webbrowser.open(state_dir().as_uri())

    def close(self):
        for mode in self.processes:
            self.stop(mode)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("api", "overlay"), help=argparse.SUPPRESS)
    parser.add_argument("--recordings", type=Path)
    parser.add_argument("--readiness", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        # Windowed frozen executables have no standard streams. Give libraries
        # and overlay diagnostics real file streams before importing them.
        state_dir().mkdir(parents=True, exist_ok=True)
        with (state_dir() / f"{args.worker}.log").open("a", encoding="utf-8", buffering=1) as log:
            sys.stdout = sys.stderr = log
            try:
                return run_worker(args)
            except Exception:
                import traceback
                traceback.print_exc()
                return 1
    LauncherApp().run()
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
