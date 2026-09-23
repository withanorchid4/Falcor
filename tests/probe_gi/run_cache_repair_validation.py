"""Room/Cornell cross-process cache round trips and failed-replacement safety."""
import json
import os
from pathlib import Path
import subprocess
from check_results import read_exr, check_cache

root = Path("F:/")
output = root / "build/probe-cache-repair"
output.mkdir(parents=True, exist_ok=True)
exe = root / "build/windows-vs2022/bin/Release/Mogwai.exe"


def run(tag, scene="room", mode="load", cache=None, expected=0, script=None):
    cache = cache or output / f"{scene}-repaired.shprobe"
    env = os.environ.copy()
    env.update({"FALCOR_MEDIA_FOLDERS": "F:/media", "PROBE_GI_MODE": mode, "PROBE_GI_SAMPLES": "2048",
        "PROBE_GI_REVISION": "1", "PROBE_GI_ENABLED": "1", "PROBE_GI_CACHE": str(cache),
        "PROBE_GI_OUTPUT": str(output), "PROBE_GI_TAG": tag, "PROBE_GI_REFERENCE": "0", "PROBE_GI_MOVE_CAMERA": "0",
        "PROBE_GI_SCENE": "F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene" if scene == "room"
            else "F:/media/test_scenes/cornell_box.pyscene"})
    with (output / f"{tag}-console.log").open("w", encoding="utf-8") as stream:
        proc = subprocess.run([str(exe), "--device-type", "vulkan", "--headless", "--deferred", "--script",
            script or "F:/scripts/TraditionalProbeGIValidation.py", "--width", "640", "--height", "480",
            "--logfile", str(output / f"{tag}.log")], cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT,
            timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    assert proc.returncode == expected, (tag, proc.returncode, (output / f"{tag}-console.log").read_text()[-3000:])
    log = (output / f"{tag}.log").read_text(encoding="utf-8", errors="replace")
    if not expected:
        assert "(Error)" not in log, tag
        if mode == "load" and script is None:
            assert "LOAD ready" in log and "BAKE start" not in log
    else:
        assert "cache rejected" in log and "BAKE start" not in log
    print("PASS", tag, flush=True)


def pixels(tag):
    return read_exr(output / f"{tag}.Probes.color.0.exr")[2]


run("room-bake", mode="bake")
run("room-load")
room_error = max(abs(a-b) for a,b in zip(pixels("room-bake"), pixels("room-load")))
assert room_error == 0, room_error
run("cornell-bake", scene="cornell", mode="bake")
cornell_old = read_exr(root / "build/probe-validation/load.Probes.color.0.exr")[2]
cornell_error = max(abs(a-b) for a,b in zip(pixels("cornell-bake"), cornell_old))
assert cornell_error < 2e-5, cornell_error
valid = (output / "room-repaired.shprobe").read_text(encoding="utf-8")
lines = valid.splitlines()
for tag, text in {"truncated": "\n".join(lines[:-1]),
                  "nonfinite": "\n".join(lines[:6] + ["nan 0 0"] + lines[7:])}.items():
    invalid = output / f"{tag}.shprobe"
    invalid.write_text(text, encoding="utf-8")
    run(tag, cache=invalid, expected=1)
run("atomic", script="F:/tests/probe_gi/cache_safety_script.py")
report = {"room_cache": check_cache(output / "room-repaired.shprobe"),
    "room_cross_process_hdr_error": room_error, "cornell_vs_original_hdr_error": cornell_error,
    "rejected": ["truncated", "nonfinite"], "atomic": json.loads((output / "atomic-results.json").read_text())}
(output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
