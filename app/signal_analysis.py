"""Signal analysis of a tracked displacement series.

Sampling and aliasing, in one paragraph:
A camera samples the tip position fps times per second. The highest frequency it can
represent unambiguously is the Nyquist limit fN = fps / 2. A vibration at f > fN does not
disappear; it shows up as an alias at |f - k*fps| for some integer k, which looks exactly
like a real, slower vibration. So a camera alone can never prove that a peak below fN is not
an alias. This module (1) reports fN, (2) warns when a peak sits close to fN or has too few
samples per cycle, (3) lists the alias candidates, and (4) refuses to report a configured
expected frequency above fN as "measured". Cross-check with a faster reference
(phone slow-motion) or beam theory.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks, lombscargle


# ----------------------------------------------------------------------------- timing
def timing_quality(t: np.ndarray, gap_factor: float = 1.5) -> dict:
    t = np.asarray(t, dtype=float)
    dt = np.diff(t)
    med = float(np.median(dt))
    cv = float(np.std(dt) / np.mean(dt)) if dt.size else np.nan
    gaps = dt > gap_factor * med
    missing = int(np.sum(np.round(dt[gaps] / med) - 1)) if gaps.any() else 0
    return {
        "n_samples": int(t.size),
        "duration_s": float(t[-1] - t[0]) if t.size else 0.0,
        "median_dt_s": med,
        "fps_effective": 1.0 / med if med > 0 else np.nan,
        "fps_mean": (t.size - 1) / (t[-1] - t[0]) if t.size > 1 and t[-1] > t[0] else np.nan,
        "dt_cv": cv,
        "n_gaps": int(gaps.sum()),
        "max_gap_s": float(dt.max()) if dt.size else 0.0,
        "est_missing_frames": missing,
        "uniform": bool(cv <= 0.05 and not gaps.any()),
        "irregular": bool(cv > 0.10 or gaps.any()),
    }


# --------------------------------------------------------------------------- spectrum
def spectrum(t: np.ndarray, x: np.ndarray, uniform: bool) -> dict:
    """Amplitude spectrum. FFT for uniform sampling, Lomb-Scargle otherwise (no gap filling)."""
    t = np.asarray(t, float) - t[0]
    x = np.asarray(x, float) - np.mean(x)
    T = t[-1] if t[-1] > 0 else 1.0
    dt = np.median(np.diff(t))
    f_nyq = 0.5 / dt
    if uniform:
        win = np.hanning(x.size)
        nfft = int(2 ** np.ceil(np.log2(x.size)) * 8)
        X = np.fft.rfft(x * win, n=nfft)
        f = np.fft.rfftfreq(nfft, d=dt)
        amp = 2.0 * np.abs(X) / win.sum()
        method = "FFT (Hann window, zero-padded)"
    else:
        f = np.linspace(1.0 / (4 * T), f_nyq, 4000)
        p = lombscargle(t, x, 2 * np.pi * f)
        amp = np.sqrt(4.0 * p / x.size)
        method = "Lomb-Scargle (irregular sampling, no interpolation)"
    return {"f": f, "amp": amp, "method": method, "f_nyquist": f_nyq,
            "resolution_hz": 1.0 / T}


def dominant_peak(spec: dict, f_min: float) -> dict:
    f, a = spec["f"], spec["amp"]
    m = f >= f_min
    if not m.any():
        return {"f_peak": np.nan, "amp_peak": np.nan}
    idx = np.flatnonzero(m)
    k = idx[np.argmax(a[m])]
    fp = f[k]
    if 0 < k < f.size - 1 and a[k - 1] > 0 and a[k + 1] > 0:
        la, lb, lc = np.log(a[k - 1]), np.log(a[k]), np.log(a[k + 1])
        den = la - 2 * lb + lc
        if den < 0:
            fp = f[k] + 0.5 * (la - lc) / den * (f[1] - f[0])
    # simple peak-to-median prominence as a quality indicator
    prominence = float(a[k] / (np.median(a[m]) + 1e-12))
    return {"f_peak": float(fp), "amp_peak": float(a[k]), "prominence": prominence}


# ------------------------------------------------------------------------ damped fit
def _model(t, A, zeta, fn, phi, c):
    wn = 2 * np.pi * fn
    wd = wn * np.sqrt(np.clip(1 - zeta ** 2, 1e-12, None))
    return A * np.exp(-zeta * wn * t) * np.cos(wd * t + phi) + c


def damped_fit(t: np.ndarray, x: np.ndarray, f0: float) -> dict:
    """Least-squares fit of the damped-sine model, started from the spectral peak."""
    t = np.asarray(t, float) - t[0]
    x = np.asarray(x, float)
    A0 = float(np.max(np.abs(x - np.mean(x))))
    best = None
    for phi0 in (0.0, np.pi / 2, np.pi, -np.pi / 2):
        p0 = [A0, 0.02, f0, phi0, float(np.mean(x))]
        lo = [0.0, 0.0, 0.7 * f0, -2 * np.pi, -np.inf]
        hi = [np.inf, 0.5, 1.3 * f0, 2 * np.pi, np.inf]
        try:
            p, cov = curve_fit(_model, t, x, p0=p0, bounds=(lo, hi), maxfev=20000)
        except (RuntimeError, ValueError):
            continue
        resid = x - _model(t, *p)
        r2 = 1 - np.sum(resid ** 2) / np.sum((x - x.mean()) ** 2)
        if best is None or r2 > best["r2"]:
            err = np.sqrt(np.clip(np.diag(cov), 0, None)) if np.all(np.isfinite(cov)) \
                else np.full(5, np.inf)
            best = {"A": p[0], "zeta": p[1], "fn": p[2], "phi": p[3], "c": p[4],
                    "A_err": err[0], "zeta_err": err[1], "fn_err": err[2],
                    "r2": float(r2), "rmse": float(np.sqrt(np.mean(resid ** 2))),
                    "params": p}
    return best or {"r2": -np.inf}


def fit_curve(t, fit: dict) -> np.ndarray:
    return _model(np.asarray(t, float), *fit["params"])


# --------------------------------------------------------------------------- envelope
def envelope_log_decrement(t: np.ndarray, x: np.ndarray, f_est: float, fps: float) -> dict:
    """Positive peaks of the centred signal and a log-decrement damping estimate."""
    x = np.asarray(x, float) - np.mean(x)
    spc = fps / f_est if f_est > 0 else 0
    dist = max(int(0.6 * spc), 1)
    pk, _ = find_peaks(x, distance=dist)
    pk = pk[x[pk] > 0]
    out = {"t_peaks": t[pk], "x_peaks": x[pk], "n_peaks": int(pk.size), "zeta_ld": np.nan,
           "valid": False, "reason": ""}
    if pk.size < 4:
        out["reason"] = "fewer than 4 positive peaks"
        return out
    if spc < 6:
        out["reason"] = f"only {spc:.1f} samples/cycle - sampled peaks underestimate true peaks"
        return out
    cycles = (t[pk] - t[pk[0]]) * f_est
    slope, _ = np.polyfit(cycles, np.log(x[pk]), 1)
    delta = -slope
    if delta <= 0:
        out["reason"] = "envelope is not decaying"
        return out
    out["zeta_ld"] = float(delta / np.sqrt(4 * np.pi ** 2 + delta ** 2))
    out["valid"] = True
    return out


# --------------------------------------------------------------------------- top level
def analyze(track: dict, cfg_analysis: dict) -> dict:
    """Run all analyses on valid samples only. Never interpolates across failed frames."""
    warnings: list[str] = []
    ok = track["ok"]
    t = track["t"][ok]
    x = track["x_px"][ok]
    if track["n_failed"]:
        warnings.append(f"{track['n_failed']} of {track['n_frames']} frames failed tracking "
                        "(low correlation); they are excluded, not interpolated.")

    gap_factor = float(cfg_analysis.get("gap_factor", 1.5))
    timing = timing_quality(t, gap_factor)
    if timing["n_gaps"]:
        warnings.append(f"{timing['n_gaps']} timing gaps (max {timing['max_gap_s']*1000:.0f} ms, "
                        f"~{timing['est_missing_frames']} missing samples). Using Lomb-Scargle "
                        "instead of FFT; gaps are not filled.")
    if timing["dt_cv"] > 0.10:
        warnings.append(f"Irregular frame intervals (CV {timing['dt_cv']:.2f}).")

    fps = timing["fps_effective"]
    f_nyq = fps / 2
    spec = spectrum(t, x, timing["uniform"])
    f_min = max(1.5 / timing["duration_s"], 0.2)
    peak = dominant_peak(spec, f_min)
    f_peak = peak["f_peak"]

    min_cycles = float(cfg_analysis.get("min_cycles", 3))
    min_spc = float(cfg_analysis.get("min_samples_per_cycle", 2.5))
    n_cycles = f_peak * timing["duration_s"]
    spc = fps / f_peak if f_peak > 0 else 0
    freq_valid = True
    if n_cycles < min_cycles:
        freq_valid = False
        warnings.append(f"Only {n_cycles:.1f} cycles recorded (< {min_cycles:g}); "
                        "record longer.")
    if spc < min_spc:
        freq_valid = False
        warnings.append(f"Peak at {f_peak:.2f} Hz has only {spc:.1f} samples/cycle "
                        f"(< {min_spc:g}); estimate unreliable.")
    if f_peak > 0.8 * f_nyq:
        freq_valid = False
        warnings.append(f"Peak {f_peak:.2f} Hz is close to Nyquist ({f_nyq:.2f} Hz): "
                        "likely aliased or distorted.")
    aliases = sorted({round(abs(k * fps + s * f_peak), 2) for k in (1, 2) for s in (-1, 1)})
    exp_f = cfg_analysis.get("expected_freq_hz")
    if exp_f:
        if exp_f > f_nyq:
            freq_valid = False
            warnings.append(f"Expected frequency {exp_f} Hz exceeds Nyquist {f_nyq:.2f} Hz: "
                            "this recording CANNOT measure it. The observed peak is an alias "
                            "at best.")
        elif abs(f_peak - exp_f) / exp_f > 0.25:
            warnings.append(f"Peak {f_peak:.2f} Hz differs >25% from expected {exp_f} Hz.")

    fit = damped_fit(t, x, f_peak) if np.isfinite(f_peak) and f_peak > 0 else {"r2": -np.inf}
    fit_valid = bool(
        fit.get("r2", -np.inf) >= 0.9 and freq_valid
        and fit["fn_err"] / fit["fn"] < 0.05
        and abs(fit["fn"] * np.sqrt(1 - fit["zeta"] ** 2) - f_peak) / f_peak < 0.1)
    if not fit_valid:
        why = ("frequency checks above failed - a good-looking fit to aliased or too-short data "
               "is still wrong" if not freq_valid else "R^2 < 0.9, fn uncertainty > 5%, or fit "
               "disagrees with spectral peak")
        warnings.append(f"Damped-sine fit not accepted (R^2={fit.get('r2', float('nan')):.3f}; "
                        f"{why}).")

    zeta_valid = False
    zeta_reason = ""
    if fit_valid:
        decay = np.exp(-fit["zeta"] * 2 * np.pi * fit["fn"] * timing["duration_s"])
        if fit["zeta"] <= 1e-3:
            zeta_reason = "fitted damping at lower bound"
        elif fit["zeta_err"] > 0.5 * fit["zeta"]:
            zeta_reason = "damping uncertainty > 50%"
        elif decay > 0.8:
            zeta_reason = "amplitude decays < 20% over the record; damping not identifiable"
        else:
            zeta_valid = True
    else:
        zeta_reason = "fit not accepted"
    if not zeta_valid:
        warnings.append(f"Damping not reported: {zeta_reason}.")

    env = envelope_log_decrement(t, x, f_peak if f_peak > 0 else 1.0, fps)

    return {
        "timing": timing,
        "spectrum": spec,
        "peak": peak,
        "f_fft_hz": f_peak,
        "f_nyquist_hz": f_nyq,
        "samples_per_cycle": spc,
        "n_cycles": n_cycles,
        "alias_candidates_hz": aliases,
        "freq_valid": freq_valid,
        "fit": fit,
        "fit_valid": fit_valid,
        "fn_fit_hz": fit.get("fn", np.nan) if fit_valid else np.nan,
        "fn_fit_err_hz": fit.get("fn_err", np.nan) if fit_valid else np.nan,
        "zeta_fit": fit.get("zeta", np.nan) if zeta_valid else np.nan,
        "zeta_fit_err": fit.get("zeta_err", np.nan) if zeta_valid else np.nan,
        "zeta_valid": zeta_valid,
        "envelope": env,
        "peak_disp_px": float(np.max(np.abs(x))),
        "warnings": warnings,
    }
