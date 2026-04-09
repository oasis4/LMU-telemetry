<p align="center">
  <img src="https://img.shields.io/badge/license-NonCommercial-orange?style=flat-square" alt="License" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <a href="https://github.com/alelosbrigia/LMU-telemetry/releases"><img src="https://img.shields.io/github/v/release/alelosbrigia/LMU-telemetry?style=flat-square&color=c8ff00" alt="Release" /></a>
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?style=flat-square&logo=windows&logoColor=white" alt="Platform" />
</p>

<h1 align="center">🏎️ LMU Telemetry → MoTeC Converter</h1>

<p align="center">
  <strong>Convert Le Mans Ultimate telemetry to MoTeC i2 &mdash; one click, zero hassle.</strong>
</p>

<p align="center">
  <a href="https://ko-fi.com/alessandromanfredi"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi" /></a>
</p>

---

## ✨ Features

| Category | Details |
|---|---|
| **Import** | Direct import from LMU `.duckdb` telemetry files |
| **Output** | Single unified MoTeC log (`*_CUSTOM.ld`) + CSV export |
| **Channel Groups** | Driver / Inputs · Powertrain · Vehicle Dynamics · Aero & Suspension · Tyres · Track & Environment · States & Flags |
| **Sampling** | Configurable frequency per group |
| **Timeline** | Correct master timeline — no broken graphs |
| **Naming** | Wheels: `FL / FR / RL / RR` · Sides: `_L / _R` · Tyre layers: `_I / _M / _O` |
| **Units** | °C · bar · mm · km/h · rpm — consistent across all channels |
| **GUI** | Simple one-click interface |

---

## 🖥️ Requirements

- **Windows**
- **Python 3.10+** (with Tkinter — included in the official installer)

### Quick install (recommended)

```
1.  Install Python 3.10+ and make sure it's in your PATH
2.  Double-click  install_dependencies.bat   → creates venv & installs packages
3.  Launch the GUI with  Start.bat
```

### Manual install

```bash
pip install -r requirements.txt
```

> Tkinter ships with the official Windows Python distribution — no extra install needed.

---

## 🚀 Quick Start

1. Clone or download this repository
2. Make sure Python is available in your `PATH`
3. Launch the GUI:
   ```
   Start.bat
   ```
4. Select an LMU `.duckdb` telemetry file
5. Choose channel groups and sampling frequencies
6. Click **RUN**

### 📂 Output

```
Telemetry/
  ├── <SessionName>_CUSTOM.ld        ← open in MoTeC i2
  ├── <SessionName>_CUSTOM.csv
  └── <SessionName>_CUSTOM.meta.csv
```

---

## 📊 MoTeC Output

- Single, coherent telemetry log
- Channels already renamed and grouped
- Beacon and LapTime generated automatically
- Ready for overlays, histograms, and math channels

---

## ⚠️ Disclaimer

This project is **not affiliated** with Studio 397, Motorsport Games, or MoTeC Pty Ltd.  
It is a community-driven, unofficial tool.

---

## 📄 License

Released under a **Non-Commercial License**.

| | |
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
- **ChatGPT** for the assist

---

<p align="center">
  <strong>💙 Support the Project</strong><br/>
  This is a community-driven, non-commercial project.<br/>
  If you find it useful, you can buy me a coffee ☕<br/><br/>
  <a href="https://ko-fi.com/alessandromanfredi"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi" /></a>
</p>


