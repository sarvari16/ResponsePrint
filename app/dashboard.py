"""ResponsePrint Streamlit dashboard.

Launch from the project root:
    streamlit run app/dashboard.py
Runs fully offline; the camera is only contacted when you press a camera button.
"""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import camera_client, comparison, pipeline, visualization  # noqa: E402
from app.main import load_config, run_synthetic  # noqa: E402

st.set_page_config(page_title="ResponsePrint", layout="wide")
BASE_CFG = load_config()
ss = st.session_state
ss.setdefault("recordings", {})       # name -> analysis result (hardware / imported / phone)
ss.setdefault("synthetic", None)
ss.setdefault("cam_status", None)


def show_fig(fig):
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


def source_banner(source: str):
    if source in ("synthetic", "mock"):
        st.warning("**SYNTHETIC DATA** - simulated oscillator rendered as images. "
                   "Demonstrates the workflow only; not a hardware measurement.")
    elif source == "hardware":
        st.success("**HARDWARE DATA** - frames captured from the ESP32-CAM. Timestamps are "
                   "laptop receive times (include Wi-Fi latency); check timing quality below.")
    elif source == "phone_video":
        st.info("**PHONE VIDEO** - reference recording imported from a video file.")
    else:
        st.info("**IMPORTED FRAMES** - loaded from a folder.")


def csv_bytes(results: list[dict]) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        p = pipeline.export_summary_csv(results, Path(d) / "s.csv")
        return p.read_bytes()


def ts_bytes(res: dict) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        p = pipeline.export_timeseries_csv(res, Path(d) / "t.csv")
        return p.read_bytes()


def show_result(res: dict, key: str):
    source_banner(res["source"])
    an = res["analysis"]
    c = st.columns(5)
    c[0].metric("Frequency", f"{res['f_best_hz']:.3f} Hz" if np.isfinite(res["f_best_hz"])
                else "invalid", res["f_best_method"], delta_color="off")
    c[1].metric("Damping ζ", f"{an['zeta_fit']:.4f}" if an["zeta_valid"] else "not valid")
    c[2].metric("Effective fps", f"{an['timing']['fps_effective']:.1f}",
                f"Nyquist {an['f_nyquist_hz']:.2f} Hz", delta_color="off")
    c[3].metric("Tracking", f"{res['track']['mean_confidence']:.2f}",
                f"{res['track']['n_failed']} failed frames", delta_color="off")
    c[4].metric("Timing gaps", an["timing"]["n_gaps"], f"CV {an['timing']['dt_cv']:.2f}",
                delta_color="off")
    show_fig(visualization.recording_figure(res))
    for w in an["warnings"]:
        st.caption(f"⚠ {w}")
    st.caption(f"If the real vibration were faster than Nyquist it could appear here as this "
               f"peak; alias candidates: {an['alias_candidates_hz']} Hz.")
    st.download_button("Download time series CSV", ts_bytes(res), f"{key}_timeseries.csv",
                       "text/csv", key=f"dl_{key}")


# ----------------------------------------------------------------------------- header
st.title("ResponsePrint")
st.markdown("Low-cost visual vibration fingerprinting with an ESP32-CAM: track a marker on a "
            "vibrating blade, extract frequency and damping, and compare a baseline against "
            "an altered condition. **Not yet validated on physical hardware.**")

with st.sidebar:
    st.header("Hardware connection")
    base_url = st.text_input("ESP32-CAM base URL", BASE_CFG["camera"]["base_url"])
    cam_cfg = copy.deepcopy(BASE_CFG)
    cam_cfg["camera"]["base_url"] = base_url
    if st.button("Check connection"):
        try:
            ss.cam_status = camera_client.Esp32CamClient.from_config(cam_cfg).status()
        except camera_client.CameraError as e:
            ss.cam_status = {"error": str(e)}
    if ss.cam_status is None:
        st.info("Not checked. The dashboard works without a camera.")
    elif "error" in ss.cam_status:
        st.error("Not connected")
        st.caption(ss.cam_status["error"])
    else:
        st.success("Connected")
        st.json(ss.cam_status)
    st.divider()
    st.caption("Sampling rule of thumb: the camera can only represent vibrations below "
               "fps/2 (Nyquist). Faster vibrations alias to a false lower frequency.")

tab_syn, tab_live, tab_imp, tab_cmp, tab_alias = st.tabs(
    ["Synthetic demo", "Live ESP32-CAM", "Import recording", "Compare", "Aliasing explainer"])

# --------------------------------------------------------------------------- synthetic
with tab_syn:
    s = BASE_CFG["synthetic"]
    st.subheader("Offline demonstration (synthetic)")
    g = st.columns(6)
    fps = g[0].number_input("Frame rate (fps)", 5.0, 120.0, float(s["fps"]), 1.0)
    dur = g[1].number_input("Duration (s)", 1.0, 20.0, float(s["duration_s"]), 0.5)
    trials = g[2].number_input("Trials / condition", 1, 20, int(s["trials_per_condition"]))
    seed = g[3].number_input("Random seed", 0, 99999, int(s["seed"]))
    jitter = g[4].number_input("Timing jitter (ms)", 0.0, 30.0, float(s["timing_jitter_ms"]))
    drop = g[5].number_input("Frame drop prob.", 0.0, 0.5, float(s["drop_prob"]), 0.01)
    cols = st.columns(2)
    cond = {}
    for col, k in zip(cols, ("A", "B")):
        c = s["conditions"][k]
        with col:
            st.markdown(f"**{c['name']}**")
            cond[k] = {
                "name": c["name"],
                "freq_hz": st.slider(f"Frequency fn (Hz) - {k}", 0.5, 30.0,
                                     float(c["freq_hz"]), 0.05),
                "zeta": st.slider(f"Damping ratio ζ - {k}", 0.0, 0.2, float(c["zeta"]), 0.001,
                                  format="%.3f"),
                "amplitude_px": st.slider(f"Initial displacement (px) - {k}", 5.0, 80.0,
                                          float(c["amplitude_px"]), 1.0),
                "noise_px": st.slider(f"Measurement noise ε (px) - {k}", 0.0, 5.0,
                                      float(c["noise_px"]), 0.1),
            }
    if st.button("Load / run synthetic demonstration", type="primary"):
        cfg = copy.deepcopy(BASE_CFG)
        cfg["synthetic"].update(fps=fps, duration_s=dur, trials_per_condition=int(trials),
                                seed=int(seed), timing_jitter_ms=jitter, drop_prob=drop,
                                save_frames=False)
        cfg["synthetic"]["conditions"] = cond
        with st.spinner("Rendering synthetic frames and running the pipeline..."):
            ss.synthetic = run_synthetic(cfg)

    res = ss.synthetic
    if res:
        source_banner("synthetic")
        comp = res["comparison"]
        st.markdown(f"### Verdict: {comp['verdict']}")
        st.write(comp["explanation"])
        st.caption(comp["caveat"])
        la, lb = res["labels"]
        show_fig(visualization.comparison_figure(res["A"], res["B"], la, lb))
        rows = [pipeline.summary_row(r) for r in res["A"] + res["B"]]
        st.dataframe(pd.DataFrame(rows))
        st.download_button("Download measurements CSV (synthetic)",
                           csv_bytes(res["A"] + res["B"]), "synthetic_summary.csv", "text/csv")
        with st.expander("Per-recording detail (trial 1 of each condition)"):
            for k in ("A", "B"):
                rec = res["recordings"][k]
                show_fig(visualization.frames_montage(rec["frames"], rec["t"],
                                                      "SYNTHETIC (simulated)"))
                show_result(res[k][0], f"syn_{k}")

# -------------------------------------------------------------------------------- live
with tab_live:
    st.subheader("Live hardware mode")
    st.caption("Requires the ESP32-CAM firmware from firmware/ on the same Wi-Fi network.")
    client = camera_client.Esp32CamClient.from_config(cam_cfg)
    if st.button("Preview one frame"):
        try:
            img, _, _ = client.capture()
            st.image(img, caption=f"HARDWARE preview {img.shape[1]}x{img.shape[0]}", width=480)
        except camera_client.CameraError as e:
            st.error(str(e))
    c = st.columns(3)
    name = c[0].text_input("Recording name", "blade_A_t1")
    condition = c[1].selectbox("Condition", ["A (baseline)", "B (altered)"])
    rdur = c[2].number_input("Duration (s)", 1.0, 30.0,
                             float(BASE_CFG["recording"]["duration_s"]), 0.5)
    if st.button("Record (pluck the blade right after pressing)", type="primary"):
        try:
            with st.spinner("Recording..."):
                rec = client.record(rdur, int(BASE_CFG["recording"]["max_frames"]))
            folder = ROOT / BASE_CFG["recording"]["output_dir"] / name
            camera_client.save_hardware_recording(rec, folder, name, condition)
            loaded = camera_client.load_folder(folder)
            ss.recordings[name] = pipeline.analyze_recording(loaded, BASE_CFG)
            st.success(f"Saved {len(rec['frames'])} frames to {folder}")
        except Exception as e:  # noqa: BLE001 - show any failure to the user
            st.error(f"Recording/analysis failed: {e}")
    hw = [k for k, v in ss.recordings.items() if v["source"] in ("hardware", "mock")]
    if hw:
        pick = st.selectbox("Show hardware recording", hw)
        show_result(ss.recordings[pick], f"hw_{pick}")

# ------------------------------------------------------------------------------ import
with tab_imp:
    st.subheader("Import a recording")
    st.caption("A folder with frames/ + timestamps.csv (e.g. data/hardware/<name>), or a phone "
               "slow-motion video for reference.")
    folder = st.text_input("Recording folder", "")
    ffps = st.number_input("Assume fps if no timestamps.csv (0 = require timestamps)", 0.0,
                           1000.0, 0.0)
    if st.button("Analyze folder") and folder:
        try:
            rec = camera_client.load_folder(Path(folder), default_fps=ffps or None)
            r = pipeline.analyze_recording(rec, BASE_CFG)
            ss.recordings[r["name"]] = r
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    up = st.file_uploader("Phone video (mp4/mov)", type=["mp4", "mov", "avi"])
    vfps = st.number_input("Capture fps override (e.g. 240 if the clip plays back at 30)", 0.0,
                           1000.0, 0.0)
    if st.button("Analyze video") and up:
        suffix = Path(up.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            fh.write(up.getbuffer())
        try:
            rec = camera_client.load_video(Path(fh.name), fps_override=vfps or None)
            rec["name"] = rec["condition"] = Path(up.name).stem
            r = pipeline.analyze_recording(rec, BASE_CFG)
            ss.recordings[r["name"]] = r
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    imp = [k for k, v in ss.recordings.items() if v["source"] not in ("hardware", "mock")]
    if imp:
        pick = st.selectbox("Show imported recording", imp)
        show_result(ss.recordings[pick], f"imp_{pick}")

# ----------------------------------------------------------------------------- compare
with tab_cmp:
    st.subheader("Baseline vs altered (recorded or imported data)")
    names = list(ss.recordings)
    if len(names) < 2:
        st.info("Record or import at least two recordings first. "
                "The synthetic tab has its own comparison.")
    else:
        a = st.multiselect("Baseline set (A)", names)
        b = st.multiselect("Altered set (B)", [n for n in names if n not in a])
        if a and b and st.button("Compare"):
            ra = [ss.recordings[n] for n in a]
            rb = [ss.recordings[n] for n in b]
            comp = comparison.compare(ra, rb)
            st.markdown(f"### Verdict: {comp['verdict']}")
            st.write(comp["explanation"])
            st.caption(comp["caveat"])
            show_fig(visualization.comparison_figure(ra, rb, "A", "B"))
            st.dataframe(pd.DataFrame([pipeline.summary_row(r) for r in ra + rb]))
            st.download_button("Download comparison CSV", csv_bytes(ra + rb),
                               "comparison_summary.csv", "text/csv")

# ------------------------------------------------------------------------------ alias
with tab_alias:
    st.subheader("Why frame rate limits what you can measure")
    st.markdown(
        "A camera samples the tip **fps** times per second. It can only represent "
        "frequencies below **fps / 2** (the Nyquist limit). A faster vibration does not "
        "disappear - it shows up at a false, lower *alias* frequency |f − k·fps| that looks "
        "perfectly real. Software cannot tell the difference, so ResponsePrint warns near the "
        "limit and asks for an independent check (phone slow-motion, beam theory).")
    c = st.columns(2)
    true_f = c[0].slider("True vibration frequency (Hz)", 0.5, 40.0, 14.0, 0.5)
    afps = c[1].slider("Camera fps", 5.0, 60.0, 25.0, 1.0)
    tt = np.linspace(0, 1, 4000)
    ts = np.arange(0, 1, 1 / afps)
    alias = abs(true_f - round(true_f / afps) * afps)
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.plot(tt, np.cos(2 * np.pi * true_f * tt), color="#c3c2b7", lw=1, label=f"true {true_f} Hz")
    ax.plot(ts, np.cos(2 * np.pi * true_f * ts), "o", color="#2a78d6", ms=6,
            label=f"camera samples @ {afps:.0f} fps")
    ax.plot(tt, np.cos(2 * np.pi * alias * tt), "--", color="#e8890c", lw=1.4,
            label=f"what the samples look like: {alias:.2f} Hz")
    ax.set_xlabel("time (s)")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title("Illustration (simulated signal)")
    show_fig(fig)
    if true_f > afps / 2:
        st.error(f"{true_f} Hz is above Nyquist ({afps/2:.1f} Hz): the camera reports "
                 f"{alias:.2f} Hz.")
    else:
        st.success(f"{true_f} Hz is below Nyquist ({afps/2:.1f} Hz).")
