# LMU Telemetry

![Vue 3](https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-FFF000?logo=duckdb&logoColor=black)
![License](https://img.shields.io/badge/License-Non--Commercial-red)

**Real-time telemetry analysis for Le Mans Ultimate.** Compare laps, analyse corners, find time — all in the browser.

---

## Features

- **Session Dashboard** — Speed, throttle & brake traces with interactive track map
- **Lap Comparison** — Side-by-side overlay of any two laps (cross-session, cross-driver)
- **Corner Analysis** — Per-corner breakdown with coaching tips (braking point, apex speed, throttle application)
- **Delta Strip** — Visual time-gain/loss bar across the lap
- **Shared lap folders** — Publish selected laps through Google Drive Desktop, sync friends’ public folders, and compare their laps offline
- **Reference Lap** — Pick any lap as reference and see the delta everywhere
- **Auto-rotating Track Map** — PCA-based projection that fills available space
- **Desktop Launcher** — Pick your telemetry folder, open the analyzer, and start the live coaching overlay

## Screenshots

> Add your own screenshots to `docs/screenshots/` and they will appear here.

| Dashboard | Compare View |
|-----------|-------------|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Compare](docs/screenshots/compare.png) |

---

## Windows portable download

Download `LMU-Telemetry-windows-x64.zip` from [GitHub Releases](https://github.com/marcolinoas/LMU-telemetry/releases). Test builds are also available in the **Windows portable package** workflow's artifacts (a GitHub login is required for artifacts). Extract the entire ZIP and double-click **LMU Telemetry.exe**. Keep its `_internal` folder beside the executable. Windows 10/11 x64 is supported; Python, Node.js, npm, and administrator access are not required. The first release is unsigned.

1. Browse to the folder containing your `.duckdb` recordings.
2. **Start analyzer** opens the analysis interface in your default browser.
3. **Start live overlay** independently starts coaching. Start LMU and load a session; its shared-memory interface must be available. The selected folder must contain a usable reference recording matching the circuit. Reference selection is automatic; the overlay uses the game monitor, top-center placement, and default scale. Use borderless/windowed mode if exclusive fullscreen hides the overlay.
4. Keep the launcher open. Each component has its own stop button; closing the launcher stops both. Closing the browser alone leaves the analyzer running.

Settings, caches, and logs are stored in `%LOCALAPPDATA%\LMU Telemetry`, so the extracted app folder can be read-only. Use **Open logs** for startup or game connection failures. Recordings are read from your selected folder and are not bundled.

## Share laps with friends

1. Create a dedicated local folder synced by **Google Drive Desktop**. In Google Drive, share that folder as **Anyone with the link → Viewer**.
2. Open **Sharing** in LMU Telemetry. Save the local folder's absolute path and, optionally, its public Drive folder URL.
3. Choose a recording and usable lap, then click **Share lap**. You can also share either selected lap from Compare. The app writes a `.lmulap` file; Drive Desktop handles uploading it.
4. Give your folder URL to your friends. They add your name and URL under **Friends’ folders** in their own app. No Google login is required in LMU Telemetry.
5. Sync runs when the analyzer starts and every five minutes while it runs. **Sync now** downloads immediately. Downloaded laps appear in both Compare selectors with friend and driver names and remain available offline.

**Stop sharing** removes the app's published file, which Drive Desktop then removes from Drive. Friends keep copies they already downloaded. Removing a friend stops syncing their folder and also keeps existing copies. A successfully synced folder marks missing files **No longer shared**; a failed sync preserves the previous library and displays an error.

Lap packages include driver/car/circuit metadata, lap and sector times, the full internal comparison trace (speed, pedals, steering and position on the distance grid), and track geometry. They contain neither the whole recording nor raw channels outside the selected lap. Only usable recorded laps can be published; ideal laps are excluded. Publishing is not a confirmation that Drive Desktop has finished uploading.

Friends, sharing settings, downloaded packages and sync history live under `%LOCALAPPDATA%\LMU Telemetry\sharing` on Windows, separate from recordings and trace caches. Public-folder downloads use pinned `gdown`; Google permission, quota, or website changes can cause sync errors. Only `.lmulap` files directly inside a friend's folder are downloaded. Existing files are checked again on each sync to detect replacements; identical content reuses the stored package.

For release validation, test two public folders with actual `.lmulap` files, resource-key URLs where available, stop sharing, offline comparisons after restart, and a private/quota-limited folder. The automated tests use a fake download provider, and the Windows frozen smoke test checks publishing and removal without requiring Drive access.

## Developer setup

Use Python 3.11+ and Node.js 22:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
npm --prefix frontend ci
npm --prefix frontend run build
.venv\Scripts\python.exe start.py
```

For frontend hot reload, run `python -m lmu_telemetry.api --recordings <folder>` and `npm --prefix frontend run dev` in separate terminals. Open [http://localhost:5173](http://localhost:5173). The existing API and overlay CLI commands remain available.

## Build the Windows package

On Windows with **Python 3.13 x64** and **Node.js 22** available, run:

```powershell
./packaging/build-windows.ps1
```

The script selects Python 3.13 through `py -3.13` (falling back to `python` on PATH), creates an isolated build environment, installs the committed Python lock, runs `npm ci`, builds the frontend, freezes the current implementation with PyInstaller, smoke-tests the executable, and creates `dist/LMU-Telemetry-windows-x64.zip`. Build on Windows; macOS builds cannot produce this Windows executable.

If Windows PowerShell blocks script execution, run from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-windows.ps1
```

Python 3.14 can remain installed alongside 3.13; the build selects 3.13 explicitly. Check its availability with `py -3.13 --version`.

The **Windows portable package** GitHub Actions workflow builds on pushes to `main` and `codex/windows-portable-package`, pull requests, manual runs, and `v*` tags. Successful runs upload the ZIP as an artifact. Tag pushes also publish the ZIP to GitHub Releases after the Windows build, frozen-app smoke test, Python tests, and frontend tests pass. Tags containing a hyphen (for example `v1.0.0-rc.1`) produce a prerelease. Rerunning a tag build replaces its ZIP asset.

To test from your fork, push the branch and open **Actions → Windows portable package**. If Actions is disabled on the fork, enable it first. Manual **Run workflow** becomes available once the workflow exists on the default branch; branch pushes can trigger it before that.

To publish a release from a tested commit, choose an unused `v*` tag and push that tag to `origin`. The workflow uses GitHub's automatic `GITHUB_TOKEN`; no personal token or SSH secret is needed. Publication uses the repository receiving the tag, so testing on the fork publishes to the fork.

To update the Python build lock, use `uv pip compile packaging/requirements-windows.in --python-version 3.13 --python-platform x86_64-pc-windows-msvc -o packaging/requirements-windows.lock`, then rebuild and test on Windows.

Before distributing a release, test on Windows without Python/Node installed: analyzer navigation and lap comparisons, actual LMU coaching and unavailable-game errors, independent start/stop and launcher shutdown, an extraction path with spaces/non-ASCII characters, and a read-only app directory. CI covers frozen API processing, paths with spaces/non-ASCII characters, no runtimes on PATH, and occupied port 8000; actual in-game behavior still needs a Windows machine running LMU.

---

## Architecture

```
LMU-telemetry/
├── lmu_telemetry/     Current telemetry implementation
│   ├── api/          FastAPI routes and bundled web interface serving
│   ├── core/         Lap processing, geometry and coaching
│   ├── live/         Windows shared-memory coaching overlay
│   └── data/tracks/  Track definitions bundled in the portable app
├── frontend/         Vue 3 + Vite browser interface
├── start.py          Desktop launcher and packaged worker entrypoint
├── packaging/        Windows build, dependency lock and smoke test
└── backend/          Legacy implementation (excluded from portable app)
```

---

## License

Non-commercial use only. See [LICENSE](LICENSE).

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md).
|---|---|
| ✅ Personal use | ✅ Educational use |
| ✅ Community / sim-racing use | |
| ❌ Commercial use | ❌ SaaS / resale / commercial integration |

See [`LICENSE`](LICENSE) for full details.

---

## 🤝 Contributing

Pull Requests and improvements are welcome — as long as they stay consistent with the non-commercial nature of the project.

Want to use this commercially? Contact the author first.

---

## 🏁 Roadmap

- [ ] GUI profile presets (Qualifying / Race / Endurance)
- [ ] Save/load GUI profiles (JSON)
- [ ] Improved unit detection from metadata
- [x] Portable Windows `.exe` build workflow
- [ ] Support for other DuckDB-based simulators

---

## ❤️ Credits

- The **LMU sim racing community**
- **MoTeC** for the analysis software
- Everyone who tests and provides feedback
- **Claude** for the assist

---


