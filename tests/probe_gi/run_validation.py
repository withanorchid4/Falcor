"""Run Vulkan probe integration checks using the existing F: build, then check HDRs.

Run from the repository root with its bundled Python. No additional packages required.
"""
import os
from pathlib import Path
import subprocess
import sys
import json

ROOT = Path("F:/")
OUTPUT = ROOT / "build/probe-validation"
CACHE = ROOT / "build/probes/cornell.shprobe"
EXE = ROOT / "build/windows-vs2022/bin/Release/Mogwai.exe"


def run_case(tag, mode="load", expected=0, **settings):
    env = os.environ.copy()
    env.update({"FALCOR_MEDIA_FOLDERS": "F:/media", "PROBE_GI_MODE": mode,
                "PROBE_GI_SAMPLES": "2048", "PROBE_GI_CACHE": str(CACHE),
                "PROBE_GI_OUTPUT": str(OUTPUT), "PROBE_GI_TAG": tag,
                "PROBE_GI_REVISION": "1", "PROBE_GI_ENABLED": "1",
                "PROBE_GI_MOVE_CAMERA": "0", "PROBE_GI_REFERENCE": "0",
                "PROBE_GI_SCENE": "F:/media/test_scenes/cornell_box.pyscene"})
    env.update(settings)
    log = ROOT / f"build/probe-{tag}.log"
    with (ROOT / f"build/probe-{tag}-console.log").open("w", encoding="utf-8") as stream:
        result = subprocess.run([str(EXE), "--device-type", "vulkan", "--headless", "--deferred",
                                 "--script", "F:/scripts/TraditionalProbeGIValidation.py",
                                 "--width", "640", "--height", "480", "--logfile", str(log)],
                                cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == expected, (tag, result.returncode, expected)
    text = log.read_text(encoding="utf-8", errors="replace")
    text += (ROOT / f"build/probe-{tag}-console.log").read_text(encoding="utf-8", errors="replace")
    if expected == 0:
        assert "(Error)" not in text, tag
        if mode == "load" and env["PROBE_GI_REFERENCE"] == "0":
            assert "LOAD ready" in text and "BAKE start" not in text, tag
    else:
        assert "cache rejected" in text and "BAKE start" not in text, tag
    print(f"PASS {tag}: exit {result.returncode}", flush=True)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "integration.json").unlink(missing_ok=True)
    if "--reuse-renders" not in sys.argv:
        run_case("bake", "bake")
        run_case("load", PROBE_GI_MOVE_CAMERA="1")
        run_case("off", PROBE_GI_ENABLED="0")
        run_case("reference", PROBE_GI_REFERENCE="1")
    original = CACHE.read_text(encoding="utf-8")
    variants = {
        "bad-version": original.replace(original.splitlines()[0], "FALCOR_PROBE_SH 999", 1),
        "truncated": "\n".join(original.splitlines()[:8]),
        "trailing": original + "unexpected-data\n",
        "nonfinite": "\n".join(original.splitlines()[:7]) + "\nnan 0 0\n",
    }
    for tag, data in variants.items():
        path = ROOT / f"build/probes/{tag}.shprobe"
        path.write_text(data, encoding="utf-8")
        run_case(tag, expected=1, PROBE_GI_CACHE=str(path))
    missing = ROOT / "build/probes/intentionally-missing.shprobe"
    assert not missing.exists(), "Choose a genuinely missing cache path for this test."
    run_case("missing", expected=1, PROBE_GI_CACHE=str(missing))
    run_case("mismatch", expected=1, PROBE_GI_REVISION="different-scene-revision")
    subprocess.run([sys.executable, "tests/probe_gi/check_results.py"], cwd=ROOT, check=True)
    (OUTPUT / "integration.json").write_text(json.dumps({
        "passed": ["bake", "load", "camera-move", "off", "reference", *variants, "missing", "mismatch"],
        "api": "Vulkan", "resolution": [640, 480], "reference_spp": 2048,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
