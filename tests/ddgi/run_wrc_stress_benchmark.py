"""Compare grouped/mixed dispatches with controlled type-specific ALU work."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import uuid

from check_rtxdi_results import read_exr, timing_summary

WORKLOADS = {"small": ([8, 6, 8], 256), "probes8x": ([16, 12, 16], 256),
             "rays16x": ([16, 12, 16], 512)}
CASES = [(0, 0), (2, 64), (2, 512), (2, 2048), (2, 10000), (1, 10000)]


def identity(path):
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workloads", nargs="+", choices=list(WORKLOADS), default=list(WORKLOADS))
    parser.add_argument("--frames", type=int, default=64)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--dense", action="store_true", help="Use cell scale 0.01 and max LOD 1 to reduce spatial sharing.")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.output or root / "build/wrc-stress" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    exe = root / "build/windows-vs2022/bin/Release/Mogwai.exe"
    sources = list((root / "Source/RenderPasses/RTXGIDDGI").glob("*"))
    sources += [Path(__file__), root / "tests/ddgi/wrc_stress_benchmark.py"]
    manifest = {"sources": {str(p): identity(p) for p in sources if p.is_file()},
                "binaries": {str(p): identity(p) for p in (exe, exe.parent / "plugins/RTXGIDDGI.dll", exe.parent / "Falcor.dll", exe.parent / "slang.dll", exe.parent / "dxcompiler.dll")},
                "workers": [], "passed": False}
    (out / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Output: " + str(out), flush=True)
    windows = []
    for workload in args.workloads:
        counts, rays = WORKLOADS[workload]
        for repeat in range(1 if args.smoke else 2):
            child = out / f"{workload}-{repeat}"
            child.mkdir()
            cases = [(0, 0), (2, 64), (1, 64)] if args.smoke else CASES
            if repeat:
                cases = list(reversed(cases))
            order = [False, True] if args.smoke else ([False, True, True, False] if repeat == 0 else [True, False, False, True])
            config = {"counts": counts, "rays": rays, "cases": cases, "order": order, "frames": args.frames}
            if args.dense:
                config.update({"cell_scale": 0.01, "max_lod": 1})
            env = os.environ.copy()
            env.update({"WRC_STRESS_OUTPUT": str(child), "WRC_STRESS_CONFIG": json.dumps(config),
                        "FALCOR_MEDIA_FOLDERS": str(root / "media"), "FALCOR_SCENE_FOLDER": str(root / "media")})
            command = [str(exe), "--device-type", "d3d12", "--headless", "--deferred", "--script",
                       str(root / "tests/ddgi/wrc_stress_benchmark.py"), "--width", "320", "--height", "240",
                       "--logfile", str(child / "mogwai.log")]
            with (child / "console.log").open("w", encoding="utf-8") as stream:
                result = subprocess.run(command, cwd=child, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=args.timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            manifest["workers"].append({"config": config, "command": command, "exit_code": result.returncode})
            (out / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            assert result.returncode == 0 and (child / "complete.json").exists(), str(child)
            assert "(Error)" not in (child / "mogwai.log").read_text(encoding="utf-8", errors="replace"), str(child)
            record = json.loads((child / "complete.json").read_text(encoding="utf-8"))
            images = list(child.glob("*.DDGI.indirect.*.exr"))
            assert len(images) == 1, (child, images)
            width, height, pixels = read_exr(images[0])
            assert (width, height) == (320, 240) and max(pixels) > 0 and min(pixels) >= -1e-5, str(images[0])
            for window in record["windows"]:
                window.update({"workload": workload, "worker": child.name,
                               "timing": timing_summary(child / (window["tag"] + "-timing.json"))})
                windows.append(window)
            print("Passed " + child.name, flush=True)
    prefix = "/onFrameRender/RenderGraphExe::execute()/DDGI/ProbeUpdate"
    stages = {"ProbeUpdate": prefix, **{name: prefix + "/" + name for name in
              ("WRCTrace", "WRCBuild", "WRCPrepare", "WRCShade", "WRCGather", "SDKUpdate")}}
    rows = []
    for workload, mode, iterations, grouped in sorted({(w["workload"], w["mode"], w["iterations"], w["grouped"]) for w in windows}):
        selected = [w for w in windows if (w["workload"], w["mode"], w["iterations"], w["grouped"]) == (workload, mode, iterations, grouped)]
        row = {"workload": workload, "mode": mode, "iterations": iterations, "grouped": grouped, "windows": len(selected)}
        row["gpu_ms"] = {name: statistics.median(w["timing"][lane + "/gpu_time"]["median_ms"] for w in selected)
                         for name, lane in stages.items()}
        row["shade_window_ms"] = [w["timing"][prefix + "/WRCShade/gpu_time"]["median_ms"] for w in selected]
        row["counts"] = {key: statistics.mean(s[key] for w in selected for s in w["stats"])
                         for key in ("wrcShadedEntries", "wrcValidRays", "wrcFallbackRays", "wrcDispatches", "wrcWaveTypeSum", "wrcWaveCount")}
        row["types_per_wave"] = row["counts"]["wrcWaveTypeSum"] / row["counts"]["wrcWaveCount"]
        rows.append(row)
    report = {"dense": args.dense, "rows": rows, "windows": windows, "passed": True,
              "method": "ABBA/BAAB in two fresh processes per workload. Median of window medians; discard first 5 timestamp records. Wave diagnostics/readbacks outside timing. Off recompiles without stress; common/per-type use the same stress-enabled binary. Synthetic dependent uint ALU work; not a production material workload."}
    manifest["passed"] = True
    (out / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2), flush=True)


if __name__ == "__main__":
    main()
