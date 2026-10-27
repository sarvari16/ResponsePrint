# ResponsePrint

Low-cost visual vibration fingerprinting using an ESP32-CAM and temporal image analysis.

A steel ruler or hacksaw blade is clamped at one end, displaced and released. A camera tracks a printed marker on the tip, and the laptop turns the tracked positions into a displacement time series, a frequency estimate, a damping estimate (only when the data supports one) and a baseline-versus-altered comparison.

**Status (27 Oct 2026):** the software pipeline runs and has been tested on synthetic data. The ESP32-CAM firmware is written but has **not** been compiled or run on hardware yet. No physical measurements exist. Novelty of the approach is unproven; see `docs/architecture.md` for related work.

## What runs today

| Mode | Needs | Tested here |
|---|---|---|
| Offline synthetic demo (CLI and dashboard) | Python only | Yes |
| Live ESP32-CAM recording | Firmware flashed, same Wi-Fi | Code path tested against `tools/mock_camera_server.py` only |
| Import a frame folder or phone slow-motion video | Python only | Folder import tested; video import not tested with a real phone clip |
| Firmware | PlatformIO + ESP32-CAM | Not compiled (PlatformIO registry was not reachable from the build sandbox) |

Every figure, CSV and report carries its data source (`SYNTHETIC`, `HARDWARE`, `PHONE VIDEO`, `IMPORTED`, `MOCK`). Synthetic frames have "SYNTHETIC" drawn into the image itself.

## Setup on Windows (VS Code)

Install Python 3.10 or newer from python.org (tick "Add Python to PATH"). Then, in a VS Code terminal opened in the `ResponsePrint` folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks the activate script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt with `.venv\Scripts\activate.bat`.

In VS Code, press `Ctrl+Shift+P` → "Python: Select Interpreter" → pick `.venv`.

On Linux/macOS use `python3 -m venv .venv` and `source .venv/bin/activate`.

## Run the demo

All commands are run from the project root (the folder that holds `config.yaml`).

```powershell
python -m app.main demo
```

This renders 5 synthetic trials for each condition, tracks the marker in every frame, analyses each trial, compares the two conditions and writes everything to `outputs/synthetic_demo/`:

- `comparison.png`: displacement overlay, spectra, per-trial frequencies
- `recording_A.png`, `recording_B.png`: one trial each with fit, envelope peaks and spectrum
- `frames_A.png`, `frames_B.png`: sample frames
- `summary.csv`, `timeseries/*.csv`, `comparison.json`, `report.md`

It takes about 10 seconds. Change frequencies, damping, noise, fps and duration in `config.yaml` under `synthetic:`.

## Run the dashboard

```powershell
streamlit run app/dashboard.py
```

It opens in the browser. Tabs:

- **Synthetic demo**: sliders for both conditions, run, verdict, charts, CSV download.
- **Live ESP32-CAM**: preview one frame, record, analyse.
- **Import recording**: a frame folder or a phone video.
- **Compare**: pick recordings for the baseline set and the altered set.
- **Aliasing explainer**: shows why a 14 Hz vibration filmed at 25 fps looks like 11 Hz.

The dashboard runs with no camera connected. If Streamlit gives trouble, the CLI does everything the dashboard does.

## Hardware mode

1. Flash the firmware (see `docs/hardware_setup.md`).
2. Note the IP printed in the serial monitor and put it in `config.yaml` → `camera.base_url`.
3. Check the link:

```powershell
python -m app.main status
```

4. Record and analyse one release (pluck the blade right after starting):

```powershell
python -m app.main record --name A_t1 --condition A --duration 5
```

5. After several trials of each condition:

```powershell
python -m app.main compare --a data/hardware/A_t1 data/hardware/A_t2 data/hardware/A_t3 --b data/hardware/B_t1 data/hardware/B_t2 data/hardware/B_t3 --label-a "baseline" --label-b "altered"
```

Analyse a phone slow-motion clip as a reference (pass `--fps 240` if the phone saves the clip at a 30 fps playback rate):

```powershell
python -m app.main analyze --video clip.mp4 --fps 240
```

### Test the hardware path without hardware

```powershell
python tools/mock_camera_server.py --port 8080
```

Set `camera.base_url: "http://127.0.0.1:8080"`, then use `status` and `record` as above. The mock serves synthetic frames and identifies itself, so its recordings are labelled `MOCK`, never `HARDWARE`.

## How the analysis decides what to report

- Tracking failures (correlation below `tracking.min_confidence`) are excluded and counted. They are never interpolated.
- Timing gaps or irregular intervals switch the spectrum from FFT to Lomb-Scargle, which handles uneven sampling without filling gaps.
- A frequency is marked invalid if the record has fewer than 3 cycles, fewer than 2.5 samples per cycle, or the peak sits within 80% of the Nyquist limit (fps/2).
- The damped-sine fit is accepted only if R² ≥ 0.9, the frequency uncertainty is under 5% and it agrees with the spectral peak.
- Damping is reported only if the fit is accepted, the amplitude visibly decays over the record and the uncertainty is under 50%.
- Comparison with 3+ trials per condition uses a Welch t-test on per-trial frequency (difference "supported" only when p < 0.01 and |Cohen's d| ≥ 2). With fewer trials it only gives a "suggestive" result. These are screening rules, not validated detection thresholds.
- A frequency change means the dynamic behaviour changed. It does not by itself prove a crack.

**Aliasing:** a camera cannot tell a real 11 Hz vibration from a 14 Hz vibration sampled at 25 fps. The software warns near the Nyquist limit, lists alias candidates and refuses to report an expected frequency above Nyquist (`analysis.expected_freq_hz`), but it cannot rule out aliasing on its own. Use a phone slow-motion reference or a beam-theory estimate.

## Project layout

```
ResponsePrint/
  config.yaml              all settings
  requirements.txt
  app/
    main.py                CLI (demo, status, record, analyze, compare)
    dashboard.py           Streamlit dashboard
    synthetic_data.py      damped-oscillation model and frame renderer
    camera_client.py       ESP32-CAM HTTP client, folder and video loaders
    tracking.py            template matching with sub-pixel peak
    signal_analysis.py     timing quality, FFT / Lomb-Scargle, fit, envelope
    comparison.py          baseline vs altered statistics and verdict
    pipeline.py            one pipeline for every source, CSV export
    visualization.py       figures
  firmware/                PlatformIO project for the ESP32-CAM
  tools/mock_camera_server.py
  data/synthetic/          saved synthetic frames (written by the demo)
  outputs/                 figures, CSVs, reports
  docs/                    architecture, hardware setup, protocol, slides outline
```

## Known limitations

- Synthetic results are close to perfect because the simulation is idealised (rigid marker, no motion blur, no rolling shutter, no lighting change). Real recordings will be worse.
- Live timestamps are laptop receive times over Wi-Fi, so expect jitter. The timing report shows how much.
- Single camera, in-plane motion only, first mode only.
- Sub-pixel parabolic peak fitting has a small bias (the synthetic demo measures tracking RMSE against ground truth: about 0.02 px in the idealised case).
