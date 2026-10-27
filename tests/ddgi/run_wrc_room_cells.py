"""Sweep Room WRC cell width at a fixed table size; compare sharing, image differences and GPU time."""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import uuid

from check_rtxdi_results import read_exr, timing_summary
from run_wrc_native_benchmark import identity, dump

CONFIGS = [("native", None), ("cell010", 0.1), ("cell005", 0.05), ("cell0025", 0.025), ("cell001", 0.01)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.output or root / "build/wrc-room-cells" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    exe = root / "build/windows-vs2022/bin/Release/Mogwai.exe"
    shader_dir = root / "Source/RenderPasses/RTXGIDDGI"
    sources = list(shader_dir.glob("*.slang")) + [shader_dir / n for n in ("RTXGIDDGI.cpp", "RTXGIDDGI.h")]
    sources += [root / p for p in ("media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene",
                "scripts/RTXGIDDGI.py", "tests/ddgi/wrc_native_benchmark.py", "tests/ddgi/run_wrc_native_benchmark.py",
                "tests/ddgi/run_wrc_room_cells.py", "tests/ddgi/check_rtxdi_results.py", "tests/probe_gi/check_results.py")]
    for path in shader_dir.glob("*.slang"):
        assert identity(path) == identity(exe.parent / "shaders/RenderPasses/RTXGIDDGI" / path.name), ("Rebuild required", path)
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,temperature.gpu,utilization.gpu", "--format=csv,noheader"],
                         capture_output=True, text=True, check=True).stdout.strip()
    manifest = {"started_local": datetime.now().astimezone().isoformat(), "gpu_before": gpu,
                "sources": {str(p.relative_to(root)): identity(p) for p in sources},
                "binaries": {str(p.relative_to(root)): identity(p) for p in
                             (exe, exe.parent / "Falcor.dll", exe.parent / "plugins/RTXGIDDGI.dll", exe.parent / "slang.dll")},
                "workers": [], "passed": False}
    dump(out / "run.json", manifest)
    print("Output: " + str(out), flush=True)
    records = {name: [] for name, _ in CONFIGS}
    for repeat in (0, 1):
        for name, scale in (CONFIGS if repeat == 0 else list(reversed(CONFIGS))):
            child = out / f"repeat-{repeat}" / name
            child.mkdir(parents=True)
            env = os.environ.copy()
            env.update({"WRC_NATIVE_OUTPUT": str(child), "WRC_NATIVE_SCENE": "room",
                        "WRC_NATIVE_MODE": "native" if scale is None else "mixed",
                        "WRC_NATIVE_CELL_SCALE": str(scale if scale is not None else 0.1),
                        "FALCOR_MEDIA_FOLDERS": str(root / "media"), "FALCOR_SCENE_FOLDER": str(root / "media")})
            command = [str(exe), "--device-type", "d3d12", "--headless", "--deferred", "--script",
                       str(root / "tests/ddgi/wrc_native_benchmark.py"), "--width", "320", "--height", "240",
                       "--logfile", str(child / "mogwai.log")]
            print(f"Starting repeat-{repeat} {name}", flush=True)
            with (child / "console.log").open("w", encoding="utf-8") as stream:
                result = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=args.timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            manifest["workers"].append({"directory": str(child.relative_to(out)), "cell_scale": scale,
                                         "command": command, "exit_code": result.returncode})
            dump(out / "run.json", manifest)
            assert result.returncode == 0 and (child / "complete.json").exists() and not (child / "failure.txt").exists(), str(child)
            assert "(Error)" not in (child / "mogwai.log").read_text(encoding="utf-8", errors="replace"), str(child)
            record = json.loads((child / "complete.json").read_text(encoding="utf-8"))
            record.update({"repeat": repeat, "directory": str(child.relative_to(out))})
            if scale is not None:
                assert math.isclose(record["settings"]["wrcCellScale"], scale, rel_tol=1e-6), record["settings"]
                assert record["settings"]["wrcTableSize"] == 65536, record["settings"]
            for window in record["windows"]:
                window["timings"] = timing_summary(child / (window["tag"] + "-timing.json"))
                images = list(child.glob(window["tag"] + ".DDGI.indirect.*.exr"))
                assert len(images) == 1, (child, images)
                width, height, pixels = read_exr(images[0])
                assert (width, height) == (320, 240) and min(pixels) >= -1e-5 and max(pixels) > 0, images[0]
                window["hdr_mean"] = statistics.mean(pixels)
            records[name].append(record)
            dump(out / "partial.json", records)
            lane = "/onFrameRender/RenderGraphExe::execute()/DDGI/ProbeUpdate/gpu_time"
            print(f"Passed repeat-{repeat} {name}: {statistics.median(w['timings'][lane]['median_ms'] for w in record['windows']):.6f} ms", flush=True)

    def pixels(worker, window):
        path = next((out / worker["directory"]).glob(window["tag"] + ".DDGI.indirect.*.exr"))
        return read_exr(path)[2]

    summary = {}
    prefix = "/onFrameRender/RenderGraphExe::execute()/DDGI"
    stages = {"DDGI": prefix, "ProbeUpdate": prefix + "/ProbeUpdate", **{s: prefix + "/ProbeUpdate/" + s for s in
              ("OriginalTrace", "WRCTrace", "WRCBuild", "WRCPrepare", "WRCShade", "WRCGather", "SDKUpdate")}}
    mean_reference = None
    for name, scale in CONFIGS:
        windows = [w for worker in records[name] for w in worker["windows"]]
        required = ("DDGI", "ProbeUpdate", "OriginalTrace", "SDKUpdate") if scale is None else tuple(s for s in stages if s != "OriginalTrace")
        timings = {}
        for stage in required:
            values = [w["timings"][stages[stage] + "/gpu_time"]["median_ms"] for w in windows]
            timings[stage] = {"median_ms": statistics.median(values), "min_window_ms": min(values), "max_window_ms": max(values)}
        keys = ("activeProbes", "relocatedProbes") + (("wrcCellSize", "wrcValidRays", "wrcShadedEntries", "wrcFallbackRays",
                "wrcShadeEvaluations", "wrcProbeLimitFailures", "wrcProbeSteps", "wrcMaxLod", "wrcLodRays") if scale is not None else ())
        counts = {k: statistics.mean(s[k] for w in windows for s in w["stats"]) for k in keys}
        entry = {"cell_scale": scale, "gpu": timings, "counters": counts, "hdr_mean": statistics.mean(w["hdr_mean"] for w in windows)}
        avg = None
        differences = []
        mean_ratios = []
        for worker in records[name]:
            native = next(w for w in records["native"] if w["repeat"] == worker["repeat"])
            assert worker["camera"] == native["camera"], name
            for nw, ww in zip(native["windows"], worker["windows"]):
                assert nw["capture_update"] == ww["capture_update"], name
                for ns, ws in zip(nw["stats"], ww["stats"]):
                    for k in ("updatedFrames", "activeProbes", "relocatedProbes", "gridMin", "gridMax"):
                        assert ns[k] == ws[k], (name, k)
                val = pixels(worker, ww)
                if avg is None:
                    avg = [x / 6 for x in val]
                else:
                    avg = [x + y / 6 for x, y in zip(avg, val)]
                if scale is not None:
                    ref = pixels(native, nw)
                    differences.append(math.sqrt(sum((x-y)**2 for x,y in zip(val,ref)) / sum(y*y for y in ref)))
                    mean_ratios.append(ww["hdr_mean"] / nw["hdr_mean"])
        if scale is None:
            mean_reference = avg
        else:
            entry["probe_update_change_percent"] = (timings["ProbeUpdate"]["median_ms"] / summary["native"]["gpu"]["ProbeUpdate"]["median_ms"] - 1) * 100
            entry["shading_call_reduction_percent"] = (1 - counts["wrcShadeEvaluations"] / counts["wrcValidRays"]) * 100
            entry["indirect_mean_ratio"] = entry["hdr_mean"] / summary["native"]["hdr_mean"]
            entry["mean_single_frame_relative_rmse"] = statistics.mean(differences)
            entry["averaged_hdr_relative_rmse"] = math.sqrt(sum((x-y)**2 for x,y in zip(avg,mean_reference)) / sum(y*y for y in mean_reference))
            entry["per_frame_mean_ratios"] = mean_ratios
            entry["per_frame_relative_rmse"] = differences
        summary[name] = entry
    manifest["passed"] = True
    dump(out / "run.json", manifest)
    report = {"passed": True, "finite_hdr_captures": 30, "configurations": summary, "workers": records,
              "method": "Five configurations, forward then reverse, fresh process per run. Fixed 65536 hash slots; only WRC cell scale changes. Same 256 warmup + three windows of 40 warmup/256 rendered frames as the native benchmark. Six window medians per configuration. Timestamp readback remains enabled; image/statistics readbacks occur outside timing windows.",
              "quality_note": "Paired single-frame differences and six-frame-average HDR differences relative to native DDGI at matched update counts; not a PathTracer accuracy or convergence test."}
    dump(out / "results.json", report)
    print(json.dumps(summary, indent=2), flush=True)
    print("PASS: " + str(out / "results.json"), flush=True)


if __name__ == "__main__":
    main()
