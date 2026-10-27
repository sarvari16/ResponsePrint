"""One pipeline for every data source: synthetic, ESP32-CAM, imported folder or phone video."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from . import signal_analysis, tracking

SOURCE_LABELS = {
    "synthetic": "SYNTHETIC (simulated)",
    "hardware": "HARDWARE (ESP32-CAM)",
    "phone_video": "PHONE VIDEO (reference)",
    "imported": "IMPORTED FRAMES",
    "mock": "MOCK SERVER (synthetic frames, test only)",
}


def analyze_recording(rec: dict, cfg: dict) -> dict:
    tc = cfg.get("tracking", {})
    tr = tracking.track_sequence(
        rec["frames"], rec["t"], template_box=tc.get("template_box"),
        search_margin_y=int(tc.get("search_margin_y_px", 20)),
        min_confidence=float(tc.get("min_confidence", 0.6)),
        mm_per_px=tc.get("mm_per_px"))
    an = signal_analysis.analyze(tr, cfg.get("analysis", {}))
    res = {"name": rec["name"], "source": rec["source"],
           "source_label": SOURCE_LABELS.get(rec["source"], rec["source"]),
           "condition": rec.get("condition", rec["name"]), "track": tr, "analysis": an,
           "meta": rec.get("meta", {})}

    # Best available frequency for this trial (fit if accepted, else spectral peak if valid)
    if an["fit_valid"]:
        res["f_best_hz"], res["f_best_method"] = an["fn_fit_hz"], "damped fit (fn)"
    elif an["freq_valid"]:
        res["f_best_hz"], res["f_best_method"] = an["f_fft_hz"], "spectral peak (fd)"
    else:
        res["f_best_hz"], res["f_best_method"] = np.nan, "none (invalid)"

    if rec["source"] == "synthetic" and "truth" in rec:
        truth = rec["truth"]
        ok = tr["ok"]
        # tracking error: tracked centre vs rendered marker centre (both about their medians)
        true_c = truth["x_rendered_px"] + truth["rest_x_px"]
        err = (tr["cx_px"][ok] - np.median(tr["cx_px"][ok])) - (true_c[ok] - np.median(true_c[ok]))
        res["truth"] = {"freq_hz": truth["freq_hz"], "damped_freq_hz": truth["damped_freq_hz"],
                        "zeta": truth["zeta"],
                        "tracking_rmse_px": float(np.sqrt(np.mean(err ** 2)))}
    return res


def summary_row(res: dict) -> dict:
    an, tr, tm = res["analysis"], res["track"], res["analysis"]["timing"]
    row = {
        "source": res["source_label"], "condition": res["condition"], "name": res["name"],
        "frames": tr["n_frames"], "tracking_failures": tr["n_failed"],
        "mean_confidence": round(tr["mean_confidence"], 3),
        "duration_s": round(tm["duration_s"], 3),
        "fps_effective": round(tm["fps_effective"], 2), "dt_cv": round(tm["dt_cv"], 3),
        "timing_gaps": tm["n_gaps"], "est_missing_frames": tm["est_missing_frames"],
        "nyquist_hz": round(an["f_nyquist_hz"], 2),
        "f_spectral_hz": round(an["f_fft_hz"], 3), "freq_valid": an["freq_valid"],
        "fn_fit_hz": _r(an["fn_fit_hz"], 3), "fn_fit_err_hz": _r(an["fn_fit_err_hz"], 3),
        "zeta_fit": _r(an["zeta_fit"], 4), "zeta_logdec": _r(an["envelope"]["zeta_ld"], 4)
        if an["envelope"]["valid"] else None,
        "fit_r2": _r(an["fit"].get("r2", np.nan), 4),
        "peak_disp_px": round(an["peak_disp_px"], 2),
        "spectrum_method": an["spectrum"]["method"],
        "n_warnings": len(an["warnings"]),
    }
    if "truth" in res:
        row.update({"TRUE_fn_hz (synthetic)": res["truth"]["freq_hz"],
                    "TRUE_zeta (synthetic)": res["truth"]["zeta"],
                    "tracking_rmse_px (synthetic)": round(res["truth"]["tracking_rmse_px"], 3)})
    return row


def _r(v, n):
    return None if v is None or not np.isfinite(v) else round(float(v), n)


def export_timeseries_csv(res: dict, path: Path) -> Path:
    tr = res["track"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(f"# source: {res['source_label']}\n# name: {res['name']}\n")
        w = csv.writer(fh)
        w.writerow(["t_s", "x_disp_px", "x_disp_mm", "cy_px", "confidence", "tracking_ok"])
        for i in range(tr["n_frames"]):
            xmm = "" if tr["x_mm"] is None else f"{tr['x_mm'][i]:.5f}"
            w.writerow([f"{tr['t'][i]:.6f}", f"{tr['x_px'][i]:.4f}", xmm,
                        f"{tr['cy_px'][i]:.3f}", f"{tr['confidence'][i]:.4f}",
                        int(tr["ok"][i])])
    return path


def export_summary_csv(results: list[dict], path: Path) -> Path:
    rows = [summary_row(r) for r in results]
    keys = list(dict.fromkeys(k for r in rows for k in r))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    return path


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items() if not isinstance(v, np.ndarray)
                or v.size < 50}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer, np.bool_)):
        return obj.item()
    return obj


def save_json(data, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(data), indent=2, default=str), encoding="utf-8")
    return path
