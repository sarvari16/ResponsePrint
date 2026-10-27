"""Synthetic vibration recordings for the offline demo.

Everything produced here is SIMULATED. Every recording carries source="synthetic"
and every rendered frame has "SYNTHETIC" burned into the image, so it can never be
mistaken for a hardware measurement.

Model (free decay of a single-degree-of-freedom oscillator):
    x(t) = A * exp(-zeta * wn * t) * cos(wd * t + phi) + eps(t)
    wn = 2*pi*fn,  wd = wn * sqrt(1 - zeta^2),  eps ~ N(0, noise_px^2)
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

SYNTHETIC_LABEL = "SYNTHETIC - simulated data, not a hardware measurement"

_SHIFT = 8                      # OpenCV fixed-point bits -> 1/256 px drawing precision
_SCALE = 1 << _SHIFT


@dataclass
class VibrationParams:
    name: str = "Condition A"
    freq_hz: float = 4.0        # natural frequency fn (Hz)
    zeta: float = 0.02          # damping ratio
    amplitude_px: float = 40.0  # initial displacement A (px)
    phase_rad: float = 0.0
    noise_px: float = 0.3       # measurement noise eps (std, px)
    fps: float = 25.0
    duration_s: float = 4.0
    width: int = 320
    height: int = 240
    image_noise: float = 2.0
    timing_jitter_ms: float = 0.0
    drop_prob: float = 0.0


def damped_oscillation(t, amplitude, zeta, fn, phi):
    wn = 2.0 * np.pi * fn
    wd = wn * np.sqrt(max(1.0 - zeta ** 2, 1e-12))
    return amplitude * np.exp(-zeta * wn * t) * np.cos(wd * t + phi)


def _fp(v: float) -> int:
    return int(round(v * _SCALE))


def _background(w: int, h: int) -> tuple[np.ndarray, dict]:
    """Static scene: light gradient, faint grid, clamp block, scale bar."""
    grad = np.linspace(200, 225, w, dtype=np.float32)[None, :].repeat(h, axis=0)
    bg = grad.copy()
    for gx in range(0, w, 20):
        bg[:, gx] -= 12
    for gy in range(0, h, 20):
        bg[gy, :] -= 12
    bg = bg.clip(0, 255).astype(np.uint8)
    cx = w // 2
    clamp = (cx - 30, 0, 60, 26)
    cv2.rectangle(bg, (clamp[0], clamp[1]), (clamp[0] + clamp[2], clamp[1] + clamp[3]), 70, -1)
    cv2.putText(bg, "CLAMP", (cx - 22, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, 230, 1, cv2.LINE_AA)
    cv2.putText(bg, "SYNTHETIC", (6, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 40, 1, cv2.LINE_AA)
    geom = {"cx": cx, "clamp_y": 26, "tip_y": int(h * 0.68), "plate": 15, "r_outer": 9, "r_inner": 4}
    return bg, geom


def render_frame(bg: np.ndarray, geom: dict, x_px: float, rng: np.random.Generator,
                 image_noise: float, t: float) -> np.ndarray:
    img = bg.copy()
    cx, ty = geom["cx"] + x_px, geom["tip_y"]
    p, ro, ri = geom["plate"], geom["r_outer"], geom["r_inner"]
    # blade: thin line from clamp to the top of the marker plate
    cv2.line(img, (_fp(geom["cx"]), _fp(geom["clamp_y"])), (_fp(cx), _fp(ty - p)), 90, 2,
             cv2.LINE_AA, _SHIFT)
    # white plate + black bullseye marker (sub-pixel positioned)
    plate = np.array([[cx - p, ty - p], [cx + p, ty - p], [cx + p, ty + p], [cx - p, ty + p]])
    cv2.fillConvexPoly(img, (plate * _SCALE).round().astype(np.int32), 250, cv2.LINE_AA, _SHIFT)
    cv2.circle(img, (_fp(cx), _fp(ty)), _fp(ro), 15, -1, cv2.LINE_AA, _SHIFT)
    cv2.circle(img, (_fp(cx), _fp(ty)), _fp(ri), 250, -1, cv2.LINE_AA, _SHIFT)
    if image_noise > 0:
        img = (img.astype(np.float32) + rng.normal(0, image_noise, img.shape)).clip(0, 255)
        img = img.astype(np.uint8)
    cv2.putText(img, f"SYNTHETIC t={t:5.2f}s", (6, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, 30, 1,
                cv2.LINE_AA)
    return img


def generate_recording(params: VibrationParams, seed: int) -> dict:
    """Return a labelled synthetic recording: frames, timestamps and ground truth."""
    rng = np.random.default_rng(seed)
    n = int(round(params.duration_s * params.fps))
    t = np.arange(n) / params.fps
    if params.timing_jitter_ms > 0:
        t = t + rng.normal(0, params.timing_jitter_ms / 1000.0, n)
        t[0] = 0.0
        t = np.sort(t)
    keep = np.ones(n, dtype=bool)
    if params.drop_prob > 0:
        keep[1:] = rng.random(n - 1) >= params.drop_prob
    t = t[keep]

    x_clean = damped_oscillation(t, params.amplitude_px, params.zeta, params.freq_hz,
                                 params.phase_rad)
    eps = rng.normal(0, params.noise_px, t.size) if params.noise_px > 0 else np.zeros(t.size)
    x_rendered = x_clean + eps

    bg, geom = _background(params.width, params.height)
    frames = [render_frame(bg, geom, float(x), rng, params.image_noise, float(tt))
              for x, tt in zip(x_rendered, t)]
    return {
        "source": "synthetic",
        "label": SYNTHETIC_LABEL,
        "name": params.name,
        "seed": seed,
        "frames": frames,
        "t": t,
        "truth": {
            "freq_hz": params.freq_hz,
            "damped_freq_hz": params.freq_hz * np.sqrt(1 - params.zeta ** 2),
            "zeta": params.zeta,
            "x_clean_px": x_clean,
            "x_rendered_px": x_rendered,
            "rest_x_px": float(geom["cx"]),
        },
        "params": asdict(params),
    }


def params_from_config(cfg: dict, key: str) -> VibrationParams:
    s = cfg["synthetic"]
    c = s["conditions"][key]
    return VibrationParams(
        name=c.get("name", f"Condition {key}"), freq_hz=float(c["freq_hz"]),
        zeta=float(c["zeta"]), amplitude_px=float(c["amplitude_px"]),
        noise_px=float(c.get("noise_px", 0.3)), fps=float(s["fps"]),
        duration_s=float(s["duration_s"]), width=int(s["width"]), height=int(s["height"]),
        image_noise=float(s.get("image_noise", 2.0)),
        timing_jitter_ms=float(s.get("timing_jitter_ms", 0.0)),
        drop_prob=float(s.get("drop_prob", 0.0)),
    )


def save_recording(rec: dict, folder: Path, write_frames: bool = True) -> Path:
    """Write frames, timestamps and ground truth to disk (clearly labelled)."""
    folder.mkdir(parents=True, exist_ok=True)
    if write_frames:
        fdir = folder / "frames"
        fdir.mkdir(exist_ok=True)
        for i, f in enumerate(rec["frames"]):
            cv2.imwrite(str(fdir / f"frame_{i:04d}.png"), f)
    with open(folder / "timestamps.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "t_s", "true_x_clean_px", "rendered_x_px"])
        for i, (tt, xc, xr) in enumerate(zip(rec["t"], rec["truth"]["x_clean_px"],
                                             rec["truth"]["x_rendered_px"])):
            w.writerow([i, f"{tt:.6f}", f"{xc:.4f}", f"{xr:.4f}"])
    meta = {"source": "synthetic", "label": SYNTHETIC_LABEL, "name": rec["name"],
            "seed": rec["seed"], "params": rec["params"],
            "truth": {k: v for k, v in rec["truth"].items() if not isinstance(v, np.ndarray)}}
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, default=float), encoding="utf-8")
    return folder
