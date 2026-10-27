"""Matplotlib figures. Every figure carries its data-source label in the title, and synthetic
figures also carry a 'SYNTHETIC DATA' watermark."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .signal_analysis import fit_curve  # noqa: E402

COL_A = "#2a78d6"     # Condition A / single series
COL_B = "#e8890c"     # Condition B
INK = "#2b2b29"
MUTED = "#6b6b66"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
    "axes.spines.right": False, "font.size": 9.5, "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "legend.frameon": False, "lines.linewidth": 1.6,
})


def _tag(fig, sources: set[str]):
    if any("SYNTHETIC" in s for s in sources):
        fig.text(0.5, 0.5, "SYNTHETIC DATA", ha="center", va="center", fontsize=42,
                 color="#000000", alpha=0.05, rotation=20, weight="bold")
    fig.text(0.995, 0.005, " | ".join(sorted(sources)), ha="right", va="bottom",
             fontsize=7.5, color=MUTED)


def recording_figure(res: dict, path: Path | None = None):
    """Displacement + fit + envelope (top), spectrum (bottom) for one recording."""
    tr, an = res["track"], res["analysis"]
    ok = tr["ok"]
    t, x = tr["t"], tr["x_px"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6.2), constrained_layout=True)
    fig.suptitle(f"[{res['source_label']}]  {res['name']}", color=INK, fontweight="bold")

    ax1.plot(t[ok], x[ok], "-o", color=COL_A, ms=3, lw=1.2, label="tracked tip displacement")
    if (~ok).any():
        ax1.plot(t[~ok], np.zeros((~ok).sum()), "x", color="#d03b3b", ms=6,
                 label="tracking failure (excluded)")
    if an["fit_valid"]:
        tt = np.linspace(t[ok][0], t[ok][-1], 1500)
        ax1.plot(tt, fit_curve(tt - t[ok][0], an["fit"]) - 0, color=INK, lw=1, alpha=0.75,
                 label=f"damped fit  fn={an['fn_fit_hz']:.3f} Hz")
    env = an["envelope"]
    if env["n_peaks"]:
        ax1.plot(env["t_peaks"], env["x_peaks"], "s", color=COL_B, ms=5, mfc="none",
                 label="envelope peaks")
    ax1.set_xlabel("time (s)")
    ax1.set_ylabel("displacement (px)")
    ax1.set_title("Displacement vs time")
    ax1.legend(loc="upper right", fontsize=8)

    sp = an["spectrum"]
    ax2.plot(sp["f"], sp["amp"], color=COL_A, lw=1.4)
    ax2.axvline(an["f_nyquist_hz"], color=MUTED, ls="--", lw=1)
    ax2.text(an["f_nyquist_hz"], ax2.get_ylim()[1] * 0.9, " Nyquist", color=MUTED, fontsize=8)
    if np.isfinite(an["f_fft_hz"]):
        ax2.axvline(an["f_fft_hz"], color=COL_B, lw=1)
        ax2.text(an["f_fft_hz"], ax2.get_ylim()[1] * 0.75,
                 f" peak {an['f_fft_hz']:.3f} Hz" + ("" if an["freq_valid"] else " (UNRELIABLE)"),
                 color=INK, fontsize=8)
    ax2.set_xlim(0, an["f_nyquist_hz"] * 1.05)
    ax2.set_xlabel("frequency (Hz)")
    ax2.set_ylabel("amplitude (px)")
    ax2.set_title(f"Spectrum - {sp['method']}")
    _tag(fig, {res["source_label"]})
    if path:
        fig.savefig(path, dpi=140)
    return fig


def comparison_figure(res_a: list[dict], res_b: list[dict], label_a: str, label_b: str,
                      path: Path | None = None):
    """Overlay first trial of each condition, spectra, and per-trial frequency spread."""
    fig = plt.figure(figsize=(10, 7.4), constrained_layout=True)
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1])
    ax1 = fig.add_subplot(gs[0, :])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])
    sources = {r["source_label"] for r in res_a + res_b}
    fig.suptitle(f"[{' / '.join(sorted(sources))}]  Baseline vs altered", color=INK,
                 fontweight="bold")

    for rs, col, lab in ((res_a, COL_A, label_a), (res_b, COL_B, label_b)):
        r = rs[0]
        ok = r["track"]["ok"]
        ax1.plot(r["track"]["t"][ok], r["track"]["x_px"][ok], "-", color=col, lw=1.4,
                 label=f"{lab} (trial 1)")
        sp = r["analysis"]["spectrum"]
        ax2.plot(sp["f"], sp["amp"], color=col, lw=1.4, label=lab)
    ax1.set_xlabel("time (s)")
    ax1.set_ylabel("displacement (px)")
    ax1.set_title("Displacement vs time")
    ax1.legend(loc="upper right", fontsize=8)
    nyq = min(r["analysis"]["f_nyquist_hz"] for r in res_a + res_b)
    ax2.set_xlim(0, nyq * 1.05)
    ax2.axvline(nyq, color=MUTED, ls="--", lw=1)
    ax2.set_xlabel("frequency (Hz)")
    ax2.set_ylabel("amplitude (px)")
    ax2.set_title("Spectra (trial 1)")
    ax2.legend(fontsize=8)

    rng = np.random.default_rng(0)
    for i, (rs, col, lab) in enumerate(((res_a, COL_A, label_a), (res_b, COL_B, label_b))):
        f = np.array([r["f_best_hz"] for r in rs], dtype=float)
        f = f[np.isfinite(f)]
        if f.size:
            ax3.plot(np.full(f.size, i) + rng.uniform(-0.08, 0.08, f.size), f, "o", color=col,
                     ms=8, mec=SURFACE, mew=2)
            ax3.errorbar(i + 0.25, f.mean(), yerr=f.std(ddof=1) if f.size > 1 else 0,
                         fmt="_", color=INK, ms=14, capsize=4, lw=1)
            ax3.text(i + 0.33, f.mean(), f"{f.mean():.3f} Hz\nn={f.size}", va="center",
                     fontsize=8, color=INK)
    ax3.set_xticks([0, 1], [label_a, label_b], fontsize=8)
    ax3.set_xlim(-0.5, 1.9)
    ax3.set_ylabel("frequency per trial (Hz)")
    ax3.set_title("Per-trial frequency (mean ± 1 sd)")
    _tag(fig, sources)
    if path:
        fig.savefig(path, dpi=140)
    return fig


def frames_montage(frames: list[np.ndarray], t: np.ndarray, source_label: str, n: int = 6,
                   path: Path | None = None):
    idx = np.linspace(0, len(frames) - 1, n).astype(int)
    fig, axes = plt.subplots(1, n, figsize=(2.0 * n, 2.2), constrained_layout=True)
    for ax, i in zip(axes, idx):
        ax.imshow(frames[i], cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"t={t[i]:.2f}s", fontsize=8, fontweight="normal")
        ax.axis("off")
    fig.suptitle(f"[{source_label}] sample frames", fontsize=10, color=INK)
    if path:
        fig.savefig(path, dpi=130)
    return fig
