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
- **Reference Lap** — Pick any lap as reference and see the delta everywhere
- **Auto-rotating Track Map** — PCA-based projection that fills available space
- **One-Click Launcher** — `start.py` GUI to pick your telemetry folder and go

## Screenshots

> Add your own screenshots to `docs/screenshots/` and they will appear here.

| Dashboard | Compare View |
|-----------|-------------|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Compare](docs/screenshots/compare.png) |

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Le Mans Ultimate telemetry files (DuckDB format)

### 1. Clone & install

```bash
git clone https://github.com/your-user/LMU-telemetry.git
cd LMU-telemetry

# Backend
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### 2. Run

**Option A — One-click launcher (Windows)**

```bash
python start.py
```

A small GUI opens where you pick your telemetry folder. Backend + frontend start automatically and the browser opens.

**Option B — Manual**

```bash
# Terminal 1 — Backend
set TELEMETRY_DIR=F:\path\to\Telemetry
python -m uvicorn backend.main:app --port 8001

# Terminal 2 — Frontend
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

**Option C — Docker**

```bash
docker compose up --build
```

Frontend at `http://localhost:3000`, API at `http://localhost:8001`.

---

## Architecture

```
LMU-telemetry/
├── backend/          FastAPI + DuckDB (read-only)
│   ├── main.py       API routes
│   ├── duckdb_reader.py  Telemetry data access
│   ├── corner_detector.py  Corner detection (curvature-based)
│   ├── delta_calc.py     Delta time calculation
│   └── lap_processor.py  Lap data processing
├── frontend/         Vue 3 + Vite + Pinia
│   └── src/
│       ├── views/    SessionDashboard, CompareView, CornerDetail, SessionLoader
│       ├── components/  TrackMap, TelemetryChart, DeltaStrip, CoachingTip
│       └── stores/   Pinia telemetry store
├── start.py          One-click launcher GUI
└── docker-compose.yml
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
- [ ] Standalone `.exe` build
- [ ] Support for other DuckDB-based simulators

---

## ❤️ Credits

- The **LMU sim racing community**
- **MoTeC** for the analysis software
- Everyone who tests and provides feedback
- **Claude** for the assist

---


