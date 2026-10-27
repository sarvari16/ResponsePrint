"""Mock ESP32-CAM for testing the live-hardware code path WITHOUT hardware.

Serves /capture (JPEG) and /status (JSON) like the firmware, but the frames are SYNTHETIC
renders of a damped oscillation (each frame says "SYNTHETIC"). Anything recorded from this
server is test data - never present it as a hardware measurement.

    python tools/mock_camera_server.py --port 8080 --freq 3.0
    # then set camera.base_url: "http://127.0.0.1:8080" in config.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.synthetic_data import _background, damped_oscillation, render_frame  # noqa: E402

ARGS = None
T0 = time.perf_counter()
BG, GEOM = _background(320, 240)
RNG = np.random.default_rng(0)
COUNT = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        global COUNT
        if self.path.startswith("/capture"):
            t = (time.perf_counter() - T0) % ARGS.period
            x = damped_oscillation(t, 40.0, ARGS.zeta, ARGS.freq, 0.0)
            img = render_frame(BG, GEOM, float(x), RNG, 2.0, t)
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
            time.sleep(ARGS.latency_ms / 1000.0)
            COUNT += 1
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg.tobytes())
        elif self.path.startswith("/status"):
            body = json.dumps({"board": "MOCK (synthetic test server, not hardware)",
                               "camera_ready": True, "captures": COUNT,
                               "frame_size": "QVGA 320x240"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--freq", type=float, default=3.0)
    ap.add_argument("--zeta", type=float, default=0.03)
    ap.add_argument("--period", type=float, default=8.0, help="restart the decay every N s")
    ap.add_argument("--latency-ms", type=float, default=30.0, help="simulated link delay")
    ARGS = ap.parse_args()
    print(f"MOCK camera on http://127.0.0.1:{ARGS.port} (synthetic frames)")
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler).serve_forever()
