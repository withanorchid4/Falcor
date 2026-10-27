"""Run ABBA/BAAB WRC dispatch comparisons on the eleven-type materials scene."""
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


def identity(path):
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.output or root / "build/wrc-dispatch-validation" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    exe = root / "build/windows-vs2022/bin/Release/Mogwai.exe"
    sources = [root / "Source/RenderPasses/RTXGIDDGI" / name for name in (
        "RTXGIDDGI.cpp", "RTXGIDDGI.h", "WorldRadianceCache.slang", "WorldRadianceCache.cs.slang")]
    manifest = {"sources": {str(p): identity(p) for p in sources},
                "binaries": {str(p): identity(p) for p in (exe, exe.parent / "plugins/RTXGIDDGI.dll", exe.parent / "slang.dll")},
                "workers": [], "passed": False}
    (out / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Output: " + str(out), flush=True)
    windows = []
    for order in ("1001", "0110"):
        child = out / order
        child.mkdir()
        env = os.environ.copy()
        env.update({"WRC_DISPATCH_OUTPUT": str(child), "WRC_DISPATCH_ORDER": order,
                    "FALCOR_MEDIA_FOLDERS": str(root / "media"), "FALCOR_SCENE_FOLDER": str(root / "media")})
        command = [str(exe), "--device-type", "d3d12", "--headless", "--deferred", "--script",
                   str(root / "tests/ddgi/wrc_dispatch_benchmark.py"), "--width", "320", "--height", "240",
                   "--logfile", str(child / "mogwai.log")]
        with (child / "console.log").open("w", encoding="utf-8") as stream:
            result = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=args.timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        manifest["workers"].append({"order": order, "command": command, "exit_code": result.returncode})
        (out / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        assert result.returncode == 0 and (child / "complete.json").exists(), str(child)
        assert not (child / "failure.txt").exists(), str(child)
        assert "(Error)" not in (child / "mogwai.log").read_text(encoding="utf-8", errors="replace"), str(child)
        record = json.loads((child / "complete.json").read_text(encoding="utf-8"))
        images = list(child.glob("*.DDGI.indirect.*.exr"))
        assert len(images) == 6, (child, images)
        for path in images:
            width, height, pixels = read_exr(path)
            assert (width, height) == (320, 240) and max(pixels) > 0 and min(pixels) >= -1e-5, str(path)
        for window in record["windows"]:
            window["timing"] = timing_summary(child / (window["tag"] + "-timing.json"))
            window["worker"] = order
            windows.append(window)
        print("Passed worker " + order, flush=True)
    prefix = "/onFrameRender/RenderGraphExe::execute()/DDGI/ProbeUpdate"
    stages = {"ProbeUpdate": prefix, **{name: prefix + "/" + name for name in
              ("WRCTrace", "WRCBuild", "WRCPrepare", "WRCShade", "WRCGather", "SDKUpdate")}}
    report = {"windows": windows, "gpu_ms": {}, "counters": {}, "passed": True,
              "note": "Median of four window medians per mode; each window captures 192 frames and discards first 5 records. No readbacks in timing windows. Runtime toggles preserve probe history; ray/owner order can differ."}
    for grouped in (True, False):
        mode = "grouped" if grouped else "mixed"
        selected = [w for w in windows if w["grouped"] == grouped]
        report["gpu_ms"][mode] = {name: statistics.median(w["timing"][lane + "/gpu_time"]["median_ms"] for w in selected)
                                  for name, lane in stages.items()}
        report["counters"][mode] = {key: statistics.mean(s[key] for w in selected for s in w["stats"])
                                    for key in ("wrcShadedEntries", "wrcFallbackRays", "wrcValidRays", "wrcDispatches", "wrcShaderGroups")}
    manifest["passed"] = True
    (out / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("gpu_ms", "counters", "passed")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
