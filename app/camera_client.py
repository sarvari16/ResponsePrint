"""ESP32-CAM HTTP client and recording loaders (live camera, image folder, phone video).

Timestamps for live recordings are taken ON THE LAPTOP when each JPEG finishes arriving
(time.perf_counter). They include Wi-Fi and HTTP latency and jitter, so the recording's
timing-quality report (interval CV, gaps) must be checked before trusting frequencies.
The firmware does not provide validated capture timestamps.
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import cv2
import numpy as np
import requests


class CameraError(RuntimeError):
    pass


class Esp32CamClient:
    def __init__(self, base_url: str, capture_path: str = "/capture",
                 status_path: str = "/status", timeout_s: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.capture_url = self.base_url + capture_path
        self.status_url = self.base_url + status_path
        self.timeout = timeout_s
        self.session = requests.Session()

    @classmethod
    def from_config(cls, cfg: dict) -> "Esp32CamClient":
        c = cfg["camera"]
        return cls(c["base_url"], c.get("capture_path", "/capture"),
                   c.get("status_path", "/status"), float(c.get("timeout_s", 3.0)))

    def status(self) -> dict:
        try:
            r = self.session.get(self.status_url, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            raise CameraError(f"Camera not reachable at {self.status_url}: {e}") from e

    def capture(self) -> tuple[np.ndarray, bytes, float]:
        try:
            r = self.session.get(self.capture_url, timeout=self.timeout)
            t_rx = time.perf_counter()
            r.raise_for_status()
        except requests.RequestException as e:
            raise CameraError(f"Capture failed: {e}") from e
        if "image/jpeg" not in r.headers.get("Content-Type", ""):
            raise CameraError(f"Unexpected content type {r.headers.get('Content-Type')}")
        img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise CameraError("Received data is not a decodable JPEG.")
        return img, r.content, t_rx

    def record(self, duration_s: float, max_frames: int = 400, progress=None) -> dict:
        """Sequential HTTP captures as fast as the link allows."""
        source = "hardware"
        try:  # the mock test server identifies itself; never label its frames as hardware
            if "MOCK" in str(self.status().get("board", "")):
                source = "mock"
        except CameraError:
            pass
        frames, jpgs, ts, errors = [], [], [], 0
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < duration_s and len(frames) < max_frames:
            try:
                img, jpg, t_rx = self.capture()
            except CameraError:
                errors += 1
                if errors > 10:
                    break
                continue
            frames.append(img)
            jpgs.append(jpg)
            ts.append(t_rx - t0)
            if progress:
                progress(len(frames), time.perf_counter() - t0)
        if len(frames) < 2:
            raise CameraError("Recorded fewer than 2 frames.")
        return {"source": source, "frames": frames, "jpgs": jpgs,
                "t": np.asarray(ts) - ts[0], "capture_errors": errors,
                "meta": {"timestamp_origin": "laptop receive time (includes Wi-Fi latency)",
                         "capture_url": self.capture_url}}


def save_hardware_recording(rec: dict, folder: Path, name: str, condition: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    fdir = folder / "frames"
    fdir.mkdir(exist_ok=True)
    for i, jpg in enumerate(rec["jpgs"]):
        (fdir / f"frame_{i:04d}.jpg").write_bytes(jpg)
    with open(folder / "timestamps.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "t_s"])
        for i, t in enumerate(rec["t"]):
            w.writerow([i, f"{t:.6f}"])
    meta = dict(rec.get("meta", {}), source=rec.get("source", "hardware"), name=name, condition=condition,
                n_frames=len(rec["frames"]), capture_errors=rec.get("capture_errors", 0))
    (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return folder


def load_folder(folder: Path, default_fps: float | None = None) -> dict:
    """Load a recording folder (frames/ + timestamps.csv [+ meta.json])."""
    folder = Path(folder)
    fdir = folder / "frames" if (folder / "frames").is_dir() else folder
    files = sorted([p for p in fdir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")])
    if len(files) < 2:
        raise CameraError(f"No image frames found in {fdir}")
    frames = [cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for p in files]
    meta = {}
    if (folder / "meta.json").exists():
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    ts_file = folder / "timestamps.csv"
    if ts_file.exists():
        with open(ts_file, encoding="utf-8") as fh:
            t = np.array([float(r["t_s"]) for r in csv.DictReader(fh)])
    elif default_fps:
        t = np.arange(len(frames)) / default_fps
        meta["timestamp_origin"] = f"assumed uniform {default_fps} fps (no timestamps.csv)"
    else:
        raise CameraError("No timestamps.csv; pass an fps to assume uniform timing.")
    if t.size != len(frames):
        raise CameraError(f"{len(frames)} frames but {t.size} timestamps")
    source = meta.get("source", "imported")
    return {"source": source, "name": meta.get("name", folder.name),
            "condition": meta.get("condition", meta.get("name", folder.name)),
            "frames": frames, "t": t, "meta": meta}


def load_video(path: Path, max_frames: int = 3000, fps_override: float | None = None) -> dict:
    """Load a phone slow-motion video as a reference recording.

    Uses the per-frame position timestamps reported by the container when available,
    otherwise the nominal fps. Some phones store slow-motion clips at a playback fps
    (e.g. 30) rather than the capture fps (e.g. 240): pass fps_override in that case.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise CameraError(f"Cannot open video {path}")
    nominal = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frames, ts = [], []
    while len(frames) < max_frames:
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
        ts.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
    cap.release()
    if len(frames) < 2:
        raise CameraError("Video has fewer than 2 frames.")
    if fps_override:
        t = np.arange(len(frames)) / fps_override
        origin = f"fps_override={fps_override}"
    elif np.all(np.diff(ts) > 0):
        t = np.asarray(ts) - ts[0]
        origin = "container timestamps"
    else:
        t = np.arange(len(frames)) / nominal
        origin = f"nominal fps={nominal}"
    return {"source": "phone_video", "name": Path(path).stem, "condition": Path(path).stem,
            "frames": frames, "t": t,
            "meta": {"timestamp_origin": origin, "nominal_fps": nominal, "file": str(path)}}
