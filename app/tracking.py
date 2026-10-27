"""Target tracking: normalized cross-correlation template matching + parabolic sub-pixel peak.

Sub-pixel note: fitting a parabola through the correlation peak and its two neighbours is a
standard refinement. It is not bias-free (errors of roughly 0.1 px are typical on sharp
targets), which is why the synthetic demo reports tracking error against ground truth.
"""
from __future__ import annotations

import cv2
import numpy as np


class TrackingError(RuntimeError):
    pass


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame


def auto_detect_marker(frame: np.ndarray, pad: int = 6) -> list[int]:
    """Find a dark, roughly circular blob (printed dot / bullseye). Returns [x, y, w, h]."""
    g = cv2.GaussianBlur(_to_gray(frame), (5, 5), 0)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        perim = cv2.arcLength(c, True)
        if area < 30 or perim == 0:
            continue
        circularity = 4 * np.pi * area / perim ** 2
        if circularity > 0.7 and area > best_area:
            best, best_area = c, area
    if best is None:
        raise TrackingError("No circular marker found. Set tracking.template_box in config.yaml "
                            "to [x, y, w, h] around the marker in the first frame.")
    x, y, w, h = cv2.boundingRect(best)
    H, W = g.shape
    x0, y0 = max(x - pad, 0), max(y - pad, 0)
    x1, y1 = min(x + w + pad, W), min(y + h + pad, H)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def _parabolic(cm: float, c0: float, cp: float) -> tuple[float, bool]:
    denom = cm - 2 * c0 + cp
    if denom >= 0:              # not a proper maximum
        return 0.0, False
    d = 0.5 * (cm - cp) / denom
    return float(np.clip(d, -0.5, 0.5)), True


def track_sequence(frames: list[np.ndarray], t: np.ndarray, template_box=None,
                   search_margin_y: int = 20, min_confidence: float = 0.6,
                   mm_per_px: float | None = None) -> dict:
    """Track the marker through all frames.

    Horizontal search covers the full frame width (the tip moves horizontally); vertical
    search is limited to +/- search_margin_y around the previous position.
    """
    if len(frames) < 2:
        raise TrackingError("Need at least 2 frames.")
    f0 = _to_gray(frames[0])
    box = list(template_box) if template_box else auto_detect_marker(f0)
    x, y, w, h = box
    tpl = f0[y:y + h, x:x + w].copy()
    if tpl.size == 0 or tpl.std() < 1.0:
        raise TrackingError(f"Template box {box} is empty or has no contrast.")

    H, W = f0.shape
    n = len(frames)
    cx = np.full(n, np.nan)
    cy = np.full(n, np.nan)
    conf = np.zeros(n)
    subpix = np.zeros(n, dtype=bool)
    prev_y = y
    for i, fr in enumerate(frames):
        g = _to_gray(fr)
        sy0 = max(prev_y - search_margin_y, 0)
        sy1 = min(prev_y + h + search_margin_y, H)
        strip = g[sy0:sy1, :]
        if strip.shape[0] < h or strip.shape[1] < w:
            continue
        res = cv2.matchTemplate(strip, tpl, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, (ix, iy) = cv2.minMaxLoc(res)
        dx = dy = 0.0
        okx = oky = False
        if 0 < ix < res.shape[1] - 1:
            dx, okx = _parabolic(res[iy, ix - 1], res[iy, ix], res[iy, ix + 1])
        if 0 < iy < res.shape[0] - 1:
            dy, oky = _parabolic(res[iy - 1, ix], res[iy, ix], res[iy + 1, ix])
        conf[i] = maxv
        subpix[i] = okx
        cx[i] = ix + dx + w / 2.0
        cy[i] = sy0 + iy + dy + h / 2.0
        if maxv >= min_confidence:
            prev_y = sy0 + iy

    ok = (conf >= min_confidence) & np.isfinite(cx)
    if ok.sum() < 2:
        raise TrackingError("Tracking failed on almost every frame (low correlation). "
                            "Check the template box, focus and lighting.")
    rest = float(np.median(cx[ok]))
    disp_px = cx - rest
    return {
        "t": np.asarray(t, dtype=float),
        "cx_px": cx, "cy_px": cy,
        "x_px": disp_px,                         # displacement about the median position
        "x_mm": disp_px * mm_per_px if mm_per_px else None,
        "confidence": conf,
        "ok": ok,
        "subpixel_ok": subpix,
        "template_box": box,
        "rest_px": rest,
        "n_frames": n,
        "n_failed": int((~ok).sum()),
        "mean_confidence": float(conf[ok].mean()),
        "min_confidence_setting": min_confidence,
    }
