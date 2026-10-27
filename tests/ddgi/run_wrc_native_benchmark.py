"""Compare original DDGI and mixed-dispatch WRC across three scenes, in ABBA order."""
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import uuid

from check_rtxdi_results import read_exr, timing_summary

SCENES = {
    "cornell": "media/test_scenes/cornell_box.pyscene",
    "room": "media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene",
    "materials": "media/test_scenes/materials/materials.pyscene",
}


def identity(path):
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.output or root / "build/wrc-native-validation" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    exe = root / "build/windows-vs2022/bin/Release/Mogwai.exe"
    source_dir = root / "Source/RenderPasses/RTXGIDDGI"
    sources = list(source_dir.glob("*.slang")) + [source_dir / name for name in ("RTXGIDDGI.cpp", "RTXGIDDGI.h")]
    sources += [root / p for p in (*SCENES.values(), "media/test_scenes/materials/test_materials.py",
                "scripts/RTXGIDDGI.py", "tests/ddgi/wrc_native_benchmark.py", "tests/ddgi/run_wrc_native_benchmark.py")]
    for path in source_dir.glob("*.slang"):
        deployed = exe.parent / "shaders/RenderPasses/RTXGIDDGI" / path.name
        assert identity(path) == identity(deployed), ("Rebuild required for shader", path)
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,temperature.gpu,utilization.gpu", "--format=csv,noheader"],
                         capture_output=True, text=True, check=True).stdout.strip()
    manifest = {"started_local": datetime.now().astimezone().isoformat(), "gpu_before": gpu,
                "sources": {str(p.relative_to(root)): identity(p) for p in sources},
                "binaries": {str(p.relative_to(root)): identity(p) for p in
                             (exe, exe.parent / "Falcor.dll", exe.parent / "plugins/RTXGIDDGI.dll", exe.parent / "slang.dll")},
                "workers": [], "passed": False}
    dump(out / "run.json", manifest)
    print("Output: " + str(out), flush=True)
    reports = {}
    ddgi = "/onFrameRender/RenderGraphExe::execute()/DDGI"
    update = ddgi + "/ProbeUpdate"
    stages = {"DDGI": ddgi, "ProbeUpdate": update, **{s: update + "/" + s for s in
              ("OriginalTrace", "WRCTrace", "WRCBuild", "WRCPrepare", "WRCShade", "WRCGather", "SDKUpdate")}}
    for scene in SCENES:
        workers = []
        # Two cold process repetitions per mode, matched frame indices and seeds.
        for run_index, mode in enumerate(("native", "mixed", "mixed", "native")):
            child = out / scene / f"{run_index}-{mode}"
            child.mkdir(parents=True)
            env = os.environ.copy()
            env.update({"WRC_NATIVE_OUTPUT": str(child), "WRC_NATIVE_SCENE": scene, "WRC_NATIVE_MODE": mode,
                        "WRC_NATIVE_CELL_SCALE": "0.1",
                        "FALCOR_MEDIA_FOLDERS": str(root / "media"), "FALCOR_SCENE_FOLDER": str(root / "media")})
            command = [str(exe), "--device-type", "d3d12", "--headless", "--deferred", "--script",
                       str(root / "tests/ddgi/wrc_native_benchmark.py"), "--width", "320", "--height", "240",
                       "--logfile", str(child / "mogwai.log")]
            print(f"Starting {scene} {run_index}-{mode}", flush=True)
            with (child / "console.log").open("w", encoding="utf-8") as stream:
                result = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=args.timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            manifest["workers"].append({"directory": str(child.relative_to(out)), "command": command, "exit_code": result.returncode})
            dump(out / "run.json", manifest)
            assert result.returncode == 0 and (child / "complete.json").exists() and not (child / "failure.txt").exists(), str(child)
            assert "(Error)" not in (child / "mogwai.log").read_text(encoding="utf-8", errors="replace"), str(child)
            record = json.loads((child / "complete.json").read_text(encoding="utf-8"))
            record["directory"] = str(child.relative_to(out))
            for window in record["windows"]:
                window["timings"] = timing_summary(child / (window["tag"] + "-timing.json"))
                images = list(child.glob(window["tag"] + ".DDGI.indirect.*.exr"))
                assert len(images) == 1, (child, images)
                width, height, pixels = read_exr(images[0])
                assert (width, height) == (320, 240) and min(pixels) >= -1e-5 and max(pixels) > 0, images[0]
                window["hdr_mean"] = statistics.mean(pixels)
            workers.append(record)
            print(f"Passed {scene} {run_index}-{mode}", flush=True)
        entry = {"modes": {}, "workers": workers}
        for mode in ("native", "mixed"):
            windows = [w for worker in workers if worker["mode"] == mode for w in worker["windows"]]
            timing = {}
            required = ("DDGI", "ProbeUpdate", "SDKUpdate", "OriginalTrace") if mode == "native" else tuple(s for s in stages if s != "OriginalTrace")
            for name in required:
                values = [w["timings"][stages[name] + "/gpu_time"]["median_ms"] for w in windows]
                timing[name] = {"median_ms": statistics.median(values), "min_window_ms": min(values), "max_window_ms": max(values), "window_medians_ms": values}
            keys = ("activeProbes", "relocatedProbes") + (("wrcValidRays", "wrcShadedEntries", "wrcFallbackRays", "wrcShadeEvaluations", "wrcAllocatedBytes", "wrcDispatches", "wrcMaterialTypes") if mode == "mixed" else ())
            counts = {k: statistics.mean(s[k] for w in windows for s in w["stats"]) for k in keys}
            entry["modes"][mode] = {"gpu": timing, "counters": counts, "hdr_mean": statistics.mean(w["hdr_mean"] for w in windows)}
        a, b = (entry["modes"][mode] for mode in ("native", "mixed"))
        entry["probe_update_change_percent"] = (b["gpu"]["ProbeUpdate"]["median_ms"] / a["gpu"]["ProbeUpdate"]["median_ms"] - 1) * 100
        entry["ddgi_change_percent"] = (b["gpu"]["DDGI"]["median_ms"] / a["gpu"]["DDGI"]["median_ms"] - 1) * 100
        entry["shading_call_reduction_percent"] = (1 - b["counters"]["wrcShadeEvaluations"] / b["counters"]["wrcValidRays"]) * 100
        entry["indirect_mean_ratio"] = b["hdr_mean"] / a["hdr_mean"]
        # Compare matched updates across the two mode pairs; record quality, not a truth-based pass/fail claim.
        differences = []
        for native_index, mixed_index in ((0, 1), (3, 2)):
            n, w = workers[native_index], workers[mixed_index]
            assert n["camera"] == w["camera"], scene
            for nw, ww in zip(n["windows"], w["windows"]):
                assert nw["capture_update"] == ww["capture_update"], scene
                for ns, ws in zip(nw["stats"], ww["stats"]):
                    for key in ("updatedFrames", "activeProbes", "relocatedProbes", "gridMin", "gridMax"):
                        assert ns[key] == ws[key], (scene, key, ns[key], ws[key])
                np = next((out / n["directory"]).glob(nw["tag"] + ".DDGI.indirect.*.exr"))
                wp = next((out / w["directory"]).glob(ww["tag"] + ".DDGI.indirect.*.exr"))
                ref, val = read_exr(np)[2], read_exr(wp)[2]
                differences.append(math.sqrt(sum((x-y)**2 for x,y in zip(val,ref)) / sum(y*y for y in ref)))
        entry["mean_single_frame_relative_rmse"] = statistics.mean(differences)
        reports[scene] = entry
        dump(out / "partial.json", reports)
        print(f"{scene}: native={a['gpu']['ProbeUpdate']['median_ms']:.6f} ms mixed={b['gpu']['ProbeUpdate']['median_ms']:.6f} ms change={entry['probe_update_change_percent']:+.2f}%", flush=True)
    manifest["passed"] = True
    dump(out / "run.json", manifest)
    report = {"passed": True, "scenes": reports, "finite_hdr_captures": 36,
              "method": "ABBA fresh processes per scene; 256 initial warmup frames, 3 windows per process, 40 warmup frames then 256 captured frames per window, discard first 5 timing records, median of 6 window medians per mode. Identical initial sampling seeds and probe update counts. No readbacks in timed windows.",
              "quality_note": "Single-frame HDR difference relative to native DDGI, not path-traced truth or a convergence test. WRC changes spatial approximation and sample correlation."}
    dump(out / "results.json", report)
    print("PASS: " + str(out / "results.json"), flush=True)


if __name__ == "__main__":
    main()
