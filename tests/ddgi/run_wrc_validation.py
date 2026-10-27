"""Run distance-LOD WRC validation and preserve captures, build identity, and reports."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import uuid


def file_identity(path):
    if not path.is_file():
        return {"exists": False}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    status = path.stat()
    return {"sha256": digest.hexdigest(), "bytes": status.st_size, "mtime_ns": status.st_mtime_ns}


def git_output(root, *arguments):
    result = subprocess.run(["git", *arguments], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", check=False)
    return result.stdout.strip() if result.returncode == 0 else result.stderr.strip()


SCENES = ("cornell", "room")
MODES = ("baseline", "bypass", "wrc", "lod1", "probe1", "collision", "lodCoarse", "temporal")


def check_one(root, out):
    assert (out / "integration.json").is_file(), "Missing completion record: " + str(out)
    result = subprocess.run([sys.executable, str(root / "tests/ddgi/check_wrc_results.py"), str(out)], cwd=root)
    manifest = out / "run.json"
    if manifest.is_file():
        run = json.loads(manifest.read_text(encoding="utf-8"))
        run["checker_returncode"] = result.returncode
        run["checked_local"] = datetime.now().astimezone().isoformat()
        manifest.write_text(json.dumps(run, indent=2), encoding="utf-8")
    assert result.returncode == 0, ("Image checker failed", result.returncode, str(out))
    return json.loads((out / "results.json").read_text(encoding="utf-8"))


def run_one(root, out, timeout, scene=None, executable=None, mode=None):
    out.mkdir(parents=True)
    env = os.environ.copy()
    # Do not inherit a caller's filter in the explicit single-process long test.
    env.pop("WRC_DDGI_VALIDATION_SCENE", None)
    env.pop("WRC_DDGI_VALIDATION_MODE", None)
    if scene:
        env["WRC_DDGI_VALIDATION_SCENE"] = scene
    if mode:
        assert scene and mode in MODES
        env["WRC_DDGI_VALIDATION_MODE"] = mode
    env.update({"WRC_DDGI_VALIDATION_OUTPUT": str(out), "FALCOR_MEDIA_FOLDERS": str(root / "media"),
                "FALCOR_SCENE_FOLDER": str(root / "media")})
    executable = executable or root / "build/windows-vs2022/bin/Release/Mogwai.exe"
    command = [str(executable), "--device-type", "d3d12", "--headless", "--deferred",
               "--script", str(root / "tests/ddgi/wrc_integration.py"), "--width", "320", "--height", "240",
               "--logfile", str(out / "mogwai.log")]
    tracked_sources = (
        "Source/Falcor/Core/Program/ProgramManager.cpp",
        "Source/Falcor/Core/Program/ProgramManager.h",
        "Source/Falcor/Core/Program/ProgramVersion.cpp",
        "Source/Falcor/Core/Program/ProgramVersion.h",
        "Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp", "Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h",
        "Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang",
        "Source/RenderPasses/RTXGIDDGI/WorldRadianceCache.slang",
        "Source/RenderPasses/RTXGIDDGI/WorldRadianceCache.rt.slang",
        "Source/RenderPasses/RTXGIDDGI/WorldRadianceCache.cs.slang", "scripts/RTXGIDDGI.py",
        "tests/ddgi/wrc_integration.py", "tests/ddgi/check_wrc_results.py", "tests/ddgi/run_wrc_validation.py",
    )
    run = {"started_local": datetime.now().astimezone().isoformat(), "root": str(root),
           "selected_scenes": [scene] if scene else list(SCENES),
           "selected_modes": [mode] if mode else list(MODES),
           "command": command, "environment": {key: env[key] for key in
               ("WRC_DDGI_VALIDATION_OUTPUT", "WRC_DDGI_VALIDATION_SCENE", "WRC_DDGI_VALIDATION_MODE",
                "FALCOR_MEDIA_FOLDERS", "FALCOR_SCENE_FOLDER")
               if key in env},
           # Avoid Windows WMI queries before launching the renderer.
           "python": sys.version,
           "platform": str(sys.getwindowsversion()) if sys.platform == "win32" else platform.platform(),
           "git_head": git_output(root, "rev-parse", "HEAD"),
           "git_status": git_output(root, "status", "--porcelain", "--", *tracked_sources),
           "files": {relative: file_identity(root / relative) for relative in tracked_sources},
           "binaries": {str(path): file_identity(path) for path in (
               executable, executable.parent / "Falcor.dll", executable.parent / "slang.dll",
               executable.parent / "plugins/RTXGIDDGI.dll")},
           "timeout_seconds": timeout, "render_completed": False}
    manifest = out / "run.json"
    manifest.write_text(json.dumps(run, indent=2), encoding="utf-8")
    print("WRC + DDGI validation output: " + str(out), flush=True)
    started = time.perf_counter()
    completion = out / ("mode-complete.json" if mode else "integration.json")
    try:
        with (out / "console.log").open("w", encoding="utf-8") as stream:
            result = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        run["renderer_returncode"] = result.returncode
    except subprocess.TimeoutExpired:
        run["timed_out"] = True
        raise
    finally:
        run["wall_seconds"] = time.perf_counter() - started
        run["render_completed"] = completion.is_file()
        manifest.write_text(json.dumps(run, indent=2), encoding="utf-8")
    failure = out / "failure.txt"
    if failure.exists():
        print(failure.read_text(encoding="utf-8"), flush=True)
    assert result.returncode == 0 and not failure.exists(), (result.returncode, str(out))
    assert completion.is_file(), "Missing completion record: " + str(out)
    log = (out / "mogwai.log").read_text(encoding="utf-8", errors="replace")
    assert "(Error)" not in log, "GPU/compilation error in " + str(out / "mogwai.log")
    if mode:
        return json.loads(completion.read_text(encoding="utf-8"))
    return check_one(root, out)


def run_isolated_scene(root, out, timeout, scene, executable):
    """Bound compiler/driver state to one fresh graph, preserving test coverage."""
    out.mkdir(parents=True)
    combined = None
    workers = []
    for mode in MODES:
        worker_out = out / "workers" / mode
        record = run_one(root, worker_out, timeout, scene, executable, mode)
        assert set(record["scenes"]) == {scene}, (scene, mode, "Unexpected scene")
        assert set(record["scenes"][scene]["modes"]) == {mode}, (scene, mode, "Unexpected mode")
        if combined is None:
            combined = {key: value for key, value in record.items()
                        if key not in ("scenes", "captures", "checks", "selected_mode")}
            combined.update({"scenes": {scene: {"modes": {}}}, "captures": {}, "checks": [],
                             "execution": "one-process-per-mode"})
        assert combined["wrc_design"] == record["wrc_design"]
        assert not set(combined["captures"]).intersection(record["captures"]), "Duplicate captures"
        combined["scenes"][scene]["modes"].update(record["scenes"][scene]["modes"])
        if mode == "temporal":
            combined["scenes"][scene]["lifecycle"] = record["scenes"][scene]["lifecycle"]
        combined["captures"].update(record["captures"])
        for check in record["checks"]:
            if check not in combined["checks"]:
                combined["checks"].append(check)
        for pattern in ("*.exr", "*.png", "*-timing.json"):
            for path in worker_out.glob(pattern):
                destination = out / path.name
                assert not destination.exists(), "Duplicate output: " + str(destination)
                shutil.copy2(path, destination)
        workers.append(str((worker_out / "run.json").relative_to(out)))
    assert set(combined["scenes"][scene]["modes"]) == set(MODES)
    combined["checks"].append("all eight modes collected for the unchanged cross-mode image checker")
    combined["note"] += " Modes ran in separate renderer processes; this run does not validate repeated graph compilation in one process."
    (out / "integration.json").write_text(json.dumps(combined, indent=2), encoding="utf-8")
    (out / "run.json").write_text(json.dumps({"execution": "one-process-per-mode", "workers": workers,
        "render_completed": True, "selected_scenes": [scene], "selected_modes": list(MODES)}, indent=2), encoding="utf-8")
    return check_one(root, out)


def aggregate(out, reports, errors):
    report = {"format": "per-scene-aggregate", "expected_scenes": list(SCENES),
              "finite_hdr_captures": 0, "passed": True, "scenes": {}}
    lines = ["WRC validation: aggregate scene results; see each run.json for process isolation"]
    for scene in SCENES:
        child = reports.get(scene)
        passed = child is not None and child.get("passed", False) and scene not in errors
        count = child.get("finite_hdr_captures", 0) if child else 0
        report["finite_hdr_captures"] += count
        report["passed"] = report["passed"] and passed
        entry = report["scenes"][scene] = {"passed": passed, "finite_hdr_captures": count,
            "directory": scene, "results": scene + "/results.json" if child else None,
            "summary": scene + "/summary.txt" if (out / scene / "summary.txt").is_file() else None}
        if scene in errors:
            entry["error"] = errors[scene]
        lines.append(f"{scene}: {'PASS' if passed else 'FAIL'}; finite HDR={count}; " + str(out / scene))
    lines.append(f"Total finite HDR: {report['finite_hdr_captures']}; passed={report['passed']}")
    # This is a result index, not a fabricated single-process integration record.
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("F:/"))
    parser.add_argument("--timeout", type=int, default=1800, help="Renderer timeout per process in seconds")
    parser.add_argument("--reuse-renders", type=Path, help="Recheck a scene, a legacy single-process run, or an aggregate directory")
    isolation = parser.add_mutually_exclusive_group()
    isolation.add_argument("--single-process", action="store_true", help="Run the original two-scene, 16-graph long test")
    isolation.add_argument("--per-scene", action="store_true", help="Rebuild eight graphs per process (default: one process per mode)")
    parser.add_argument("--executable", type=Path, help="Use an isolated Mogwai build instead of the default runtime")
    args = parser.parse_args()
    root = args.root.absolute()
    executable = args.executable.absolute() if args.executable else None
    if args.reuse_renders:
        out = args.reuse_renders.absolute()
        if (out / "integration.json").is_file():
            check_one(root, out)
            return
        assert out.is_dir(), "Render directory does not exist: " + str(out)
    else:
        out = root / "build/wrc-ddgi-validation" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        if args.single_process:
            run_one(root, out, args.timeout, executable=executable)
            return
        out.mkdir(parents=True)
    reports, errors = {}, {}
    for scene in SCENES:
        child_out = out / scene
        try:
            if args.reuse_renders:
                reports[scene] = check_one(root, child_out)
            elif args.per_scene:
                reports[scene] = run_one(root, child_out, args.timeout, scene, executable)
            else:
                reports[scene] = run_isolated_scene(root, child_out, args.timeout, scene, executable)
        except Exception as error:
            errors[scene] = str(error)
            print(f"{scene} validation failed: {error}", flush=True)
            # Preserve a checker's real failed report without treating it as passed.
            if (child_out / "results.json").is_file():
                reports[scene] = json.loads((child_out / "results.json").read_text(encoding="utf-8"))
        aggregate(out, reports, errors)
    final = aggregate(out, reports, errors)
    assert final["passed"], ("Per-scene WRC validation failed", str(out), errors)


if __name__ == "__main__":
    main()
