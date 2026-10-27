"""Baseline vs altered comparison.

The output is a statement about the DATA ("the difference is / is not supported"), never a
fault diagnosis. A frequency shift says the dynamic behaviour changed (stiffness, mass,
boundary/clamp condition, temperature, ...). It does not by itself identify a crack.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

CAVEAT = ("A frequency/damping difference indicates different dynamic behaviour (stiffness, "
          "mass, clamp/boundary condition, temperature, ...). It does not prove a crack or "
          "any specific fault. Decision rules here are screening rules, not validated "
          "detection thresholds.")


def _vals(results, key_fn):
    v = np.array([key_fn(r) for r in results], dtype=float)
    return v[np.isfinite(v)]


def _stat(v):
    if v.size == 0:
        return {"n": 0, "mean": np.nan, "std": np.nan}
    return {"n": int(v.size), "mean": float(v.mean()),
            "std": float(v.std(ddof=1)) if v.size > 1 else np.nan}


def condition_metrics(results: list[dict]) -> dict:
    return {
        "frequency_hz": _stat(_vals(results, lambda r: r["f_best_hz"])),
        "damping_zeta": _stat(_vals(results, lambda r: r["analysis"]["zeta_fit"])),
        "peak_disp_px": _stat(_vals(results, lambda r: r["analysis"]["peak_disp_px"])),
        "duration_s": _stat(_vals(results, lambda r: r["analysis"]["timing"]["duration_s"])),
        "mean_confidence": _stat(_vals(results, lambda r: r["track"]["mean_confidence"])),
        "frame_loss_pct": _stat(_vals(results, lambda r: 100.0 * (
            r["track"]["n_failed"] + r["analysis"]["timing"]["est_missing_frames"])
            / max(r["track"]["n_frames"] + r["analysis"]["timing"]["est_missing_frames"], 1))),
        "timing_cv": _stat(_vals(results, lambda r: r["analysis"]["timing"]["dt_cv"])),
        "n_trials": len(results),
        "n_valid_freq": int(np.isfinite([r["f_best_hz"] for r in results]).sum()),
        "sources": sorted({r["source_label"] for r in results}),
    }


def compare(results_a: list[dict], results_b: list[dict], alpha: float = 0.01) -> dict:
    ma, mb = condition_metrics(results_a), condition_metrics(results_b)
    fa = _vals(results_a, lambda r: r["f_best_hz"])
    fb = _vals(results_b, lambda r: r["f_best_hz"])
    out = {"A": ma, "B": mb, "caveat": CAVEAT, "test": None}

    if set(ma["sources"]) != set(mb["sources"]):
        out["verdict"] = "NOT COMPARABLE"
        out["explanation"] = "The two sets come from different sources (e.g. synthetic vs hardware)."
        return out
    if fa.size == 0 or fb.size == 0:
        out["verdict"] = "INSUFFICIENT DATA"
        out["explanation"] = ("At least one condition has no valid frequency estimate "
                              "(see per-recording warnings: sampling rate, duration, tracking).")
        return out

    diff = float(fb.mean() - fa.mean())
    out["delta_f_hz"] = diff
    out["delta_f_pct"] = 100.0 * diff / fa.mean()
    if fa.size >= 3 and fb.size >= 3:
        t, p = stats.ttest_ind(fa, fb, equal_var=False)
        sd = np.sqrt((fa.var(ddof=1) + fb.var(ddof=1)) / 2)
        d = diff / sd if sd > 0 else np.inf
        out["test"] = {"name": "Welch t-test on per-trial frequency", "t": float(t),
                       "p": float(p), "cohens_d": float(d), "alpha": alpha}
        if p < alpha and abs(d) >= 2:
            out["verdict"] = "DIFFERENCE SUPPORTED BY THIS DATA"
            out["explanation"] = (f"Mean frequency changed by {diff:+.3f} Hz "
                                  f"({out['delta_f_pct']:+.1f}%), p={p:.2g}, |d|={abs(d):.1f} "
                                  f"over {fa.size} vs {fb.size} trials.")
        else:
            out["verdict"] = "NO SUPPORTED DIFFERENCE"
            out["explanation"] = (f"delta f = {diff:+.3f} Hz is not large relative to trial-to-trial "
                                  f"scatter (p={p:.2g}, |d|={abs(d):.1f}).")
    else:
        # single-recording mode: compare with resolution / fit uncertainty
        def unc(rs):
            u = [2 * r["analysis"]["fn_fit_err_hz"] if r["analysis"]["fit_valid"]
                 else r["analysis"]["spectrum"]["resolution_hz"] / 2 for r in rs
                 if np.isfinite(r["f_best_hz"])]
            return float(np.max(u)) if u else np.inf
        u = np.hypot(unc(results_a), unc(results_b))
        out["single_trial_uncertainty_hz"] = u
        out["verdict"] = ("SUGGESTIVE DIFFERENCE (repeat trials needed)" if abs(diff) > u
                          else "NO SUPPORTED DIFFERENCE")
        out["explanation"] = (f"delta f = {diff:+.3f} Hz vs combined single-recording uncertainty "
                              f"+/-{u:.3f} Hz. Record at least 3 trials per condition for a test.")
    return out
