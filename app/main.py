"""ResponsePrint command-line interface.

Run from the project root:
    python -m app.main demo                         # offline synthetic demo (no hardware)
    python -m app.main status                       # check the ESP32-CAM
    python -m app.main record --name blade0_t1 --condition A
    python -m app.main analyze --input data/hardware/blade0_t1
    python -m app.main analyze --video phone_clip.mp4 --fps 240
    python -m app.main compare --a data/hardware/A_* --b data/hardware/B_*
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

from . import camera_client, comparison, pipeline, synthetic_data, visualization

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _out(cfg: dict, name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    d = ROOT / cfg.get("outputs", {}).get("dir", "outputs") / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_synthetic(cfg: dict, progress=None) -> dict:
    """Generate N synthetic trials per condition and run the full pipeline on the images."""
    s = cfg["synthetic"]
    n = int(s.get("trials_per_condition", 5))
    seed = int(s.get("seed", 42))
    out = {"A": [], "B": [], "recordings": {}}
    for ci, key in enumerate(("A", "B")):
        p = synthetic_data.params_from_config(cfg, key)
        for i in range(n):
            rec = synthetic_data.generate_recording(p, seed=seed + 1000 * ci + i)
            rec["condition"] = p.name
            rec["name"] = f"{p.name} - trial {i + 1}"
            if i == 0:
                out["recordings"][key] = rec
                if s.get("save_frames", True):
                    synthetic_data.save_recording(rec, ROOT / s["output_dir"] / f"condition_{key}")
            out[key].append(pipeline.analyze_recording(rec, cfg))
            if progress:
                progress(key, i + 1, n)
    out["comparison"] = comparison.compare(out["A"], out["B"])
    out["labels"] = (synthetic_data.params_from_config(cfg, "A").name,
                     synthetic_data.params_from_config(cfg, "B").name)
    return out


def write_report(path: Path, title: str, results: list[dict], comp: dict | None,
                 synthetic: bool):
    lines = [f"# {title}", "", f"Generated {datetime.now():%Y-%m-%d %H:%M}", ""]
    if synthetic:
        lines += ["> **SYNTHETIC DATA.** Every number below comes from simulated images of a "
                  "simulated oscillator. It demonstrates the workflow only and is **not** a "
                  "hardware measurement.", ""]
    lines += ["| recording | f (Hz) | method | zeta | fit R² | fps | warnings |",
              "|---|---|---|---|---|---|---|"]
    for r in results:
        an = r["analysis"]
        z = f"{an['zeta_fit']:.4f}" if an["zeta_valid"] else "not valid"
        f = f"{r['f_best_hz']:.3f}" if np.isfinite(r["f_best_hz"]) else "invalid"
        lines.append(f"| {r['name']} | {f} | {r['f_best_method']} | {z} | "
                     f"{an['fit'].get('r2', float('nan')):.3f} | "
                     f"{an['timing']['fps_effective']:.1f} | {len(an['warnings'])} |")
    if synthetic and "truth" in results[0]:
        r0 = results[0]
        lines += ["", "Ground truth is known only because the data is synthetic: "
                  f"tracking RMSE on trial 1 = {r0['truth']['tracking_rmse_px']:.3f} px."]
    if comp:
        lines += ["", "## Comparison", "", f"**Verdict:** {comp['verdict']}", "",
                  comp["explanation"], "", f"_Caveat:_ {comp['caveat']}"]
    lines += ["", "## Warnings per recording", ""]
    for r in results:
        for w in r["analysis"]["warnings"]:
            lines.append(f"- {r['name']}: {w}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_demo(cfg, args):
    print("Running SYNTHETIC demo (simulated data, no hardware)...")
    res = run_synthetic(cfg, progress=lambda k, i, n: print(f"  condition {k}: trial {i}/{n}"))
    out = _out(cfg, "synthetic_demo")
    la, lb = res["labels"]
    for key in ("A", "B"):
        rec = res["recordings"][key]
        visualization.frames_montage(rec["frames"], rec["t"], "SYNTHETIC (simulated)",
                                     path=out / f"frames_{key}.png")
        visualization.recording_figure(res[key][0], path=out / f"recording_{key}.png")
        for i, r in enumerate(res[key]):
            pipeline.export_timeseries_csv(r, out / "timeseries" / f"{key}_trial{i + 1}.csv")
    visualization.comparison_figure(res["A"], res["B"], la, lb, path=out / "comparison.png")
    all_r = res["A"] + res["B"]
    pipeline.export_summary_csv(all_r, out / "summary.csv")
    pipeline.save_json(res["comparison"], out / "comparison.json")
    write_report(out / "report.md", "ResponsePrint - synthetic demonstration", all_r,
                 res["comparison"], synthetic=True)
    _print_summary(all_r, res["comparison"])
    print(f"\nOutputs written to {out}")


def _print_summary(results, comp=None):
    print("\n{:<40} {:>9} {:>9} {:>8} {:>7}".format("recording", "f (Hz)", "true fn", "zeta",
                                                    "warn"))
    for r in results:
        an = r["analysis"]
        tf = r.get("truth", {}).get("freq_hz", float("nan"))
        z = an["zeta_fit"]
        print("{:<40} {:>9.3f} {:>9.3f} {:>8} {:>7}".format(
            r["name"][:40], r["f_best_hz"], tf, f"{z:.4f}" if np.isfinite(z) else "n/a",
            len(an["warnings"])))
    if comp:
        print(f"\nVERDICT: {comp['verdict']}\n  {comp['explanation']}\n  Caveat: {comp['caveat']}")


def cmd_status(cfg, args):
    cam = camera_client.Esp32CamClient.from_config(cfg)
    try:
        print(cam.status())
    except camera_client.CameraError as e:
        print(f"NOT CONNECTED: {e}")
        sys.exit(1)


def cmd_record(cfg, args):
    cam = camera_client.Esp32CamClient.from_config(cfg)
    rc = cfg["recording"]
    dur = args.duration or float(rc["duration_s"])
    print(f"Recording {dur:.1f} s from {cam.capture_url} - release the blade now...")
    rec = cam.record(dur, int(rc.get("max_frames", 400)),
                     progress=lambda n, t: print(f"\r  {n} frames, {t:.1f} s", end=""))
    print()
    folder = ROOT / rc["output_dir"] / args.name
    camera_client.save_hardware_recording(rec, folder, args.name, args.condition)
    print(f"Saved {len(rec['frames'])} frames to {folder} "
          f"(capture errors: {rec['capture_errors']})")
    if not args.no_analyze:
        args.input, args.video = str(folder), None
        cmd_analyze(cfg, args)


def _load(args_input=None, video=None, fps=None):
    if video:
        return camera_client.load_video(Path(video), fps_override=fps)
    return camera_client.load_folder(Path(args_input), default_fps=fps)


def cmd_analyze(cfg, args):
    rec = _load(args.input, args.video, getattr(args, "fps", None))
    res = pipeline.analyze_recording(rec, cfg)
    out = _out(cfg, f"analysis_{res['name']}")
    visualization.recording_figure(res, path=out / "recording.png")
    pipeline.export_timeseries_csv(res, out / "timeseries.csv")
    pipeline.export_summary_csv([res], out / "summary.csv")
    write_report(out / "report.md", f"ResponsePrint - {res['source_label']} - {res['name']}",
                 [res], None, synthetic=res["source"] == "synthetic")
    _print_summary([res])
    for w in res["analysis"]["warnings"]:
        print("  WARNING:", w)
    print(f"Alias candidates (if the true vibration were faster): "
          f"{res['analysis']['alias_candidates_hz']} Hz")
    print(f"Outputs written to {out}")


def cmd_compare(cfg, args):
    ra = [pipeline.analyze_recording(_load(p, fps=args.fps), cfg) for p in args.a]
    rb = [pipeline.analyze_recording(_load(p, fps=args.fps), cfg) for p in args.b]
    comp = comparison.compare(ra, rb)
    out = _out(cfg, "comparison")
    visualization.comparison_figure(ra, rb, args.label_a, args.label_b,
                                    path=out / "comparison.png")
    pipeline.export_summary_csv(ra + rb, out / "summary.csv")
    pipeline.save_json(comp, out / "comparison.json")
    write_report(out / "report.md", "ResponsePrint - comparison", ra + rb, comp,
                 synthetic=any(r["source"] == "synthetic" for r in ra + rb))
    _print_summary(ra + rb, comp)
    print(f"Outputs written to {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="responseprint")
    ap.add_argument("--config", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="offline synthetic demonstration")
    sub.add_parser("status", help="query the ESP32-CAM /status endpoint")
    p = sub.add_parser("record", help="record from the ESP32-CAM")
    p.add_argument("--name", required=True)
    p.add_argument("--condition", default="A")
    p.add_argument("--duration", type=float)
    p.add_argument("--no-analyze", action="store_true")
    p = sub.add_parser("analyze", help="analyze a recording folder or a video")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--input")
    g.add_argument("--video")
    p.add_argument("--fps", type=float, help="assume this fps (folders without timestamps, "
                   "or slow-motion videos stored at playback fps)")
    p = sub.add_parser("compare", help="compare recording folders of two conditions")
    p.add_argument("--a", nargs="+", required=True)
    p.add_argument("--b", nargs="+", required=True)
    p.add_argument("--label-a", default="Condition A")
    p.add_argument("--label-b", default="Condition B")
    p.add_argument("--fps", type=float)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    {"demo": cmd_demo, "status": cmd_status, "record": cmd_record, "analyze": cmd_analyze,
     "compare": cmd_compare}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
