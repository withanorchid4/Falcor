"""One fresh Mogwai process: original DDGI or WRC with mixed material dispatch."""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["WRC_NATIVE_OUTPUT"])
SCENE = os.environ["WRC_NATIVE_SCENE"]
MODE = os.environ["WRC_NATIVE_MODE"]
CELL_SCALE = float(os.environ.get("WRC_NATIVE_CELL_SCALE", "0.1"))
SCENES = {
    "cornell": "media/test_scenes/cornell_box.pyscene",
    "room": "media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene",
    "materials": "media/test_scenes/materials/materials.pyscene",
}
records = {"scene": SCENE, "mode": MODE, "windows": []}


def frames(count):
    for _ in range(count):
        renderFrame()


def checked_stats(p):
    s = dict(p.stats)
    assert s["finite"] and s["irradianceMax"] > 0 and s["usingRTXDI"], s
    assert all(v == 0 for k, v in s.items() if k.startswith("rejected")), s
    assert s["wrcEnabled"] == (MODE == "mixed"), s
    if MODE == "mixed":
        assert not s["wrcGroupByMaterial"] and s["wrcDispatches"] == 1, s
        assert s["wrcNonFiniteResults"] == s["wrcTemporalReusedEntries"] == 0, s
        n = s["wrcOccupiedEntries"]
        assert n > 0 and n == s["wrcActiveEntries"] == s["wrcShadedEntries"], s
        assert s["wrcServedRays"] + s["wrcFallbackRays"] == s["wrcValidRays"], s
        assert s["wrcServedRays"] >= n, s
        assert s["wrcShaderGroups"] == 1 and n <= s["wrcScheduledThreads"] < n + 64, s
        assert s["wrcProbeLimitFailures"] <= s["wrcFallbackRays"], s
    return s


try:
    assert SCENE in SCENES and MODE in ("native", "mixed")
    factory = runpy.run_path(str(ROOT / "scripts/RTXGIDDGI.py"))["render_graph_RTXGIDDGI"]
    factory.__globals__.pop("RTXGIDDGI", None)
    graph = factory()
    graph.markOutput("DDGI.indirect")
    p = graph.getPass("DDGI")
    p.set_properties({"useWRC": MODE == "mixed", "wrcGroupByMaterial": False,
                      "wrcCellScale": CELL_SCALE, "wrcLodDistance": 8.0, "wrcMaxLod": 16,
                      "wrcProbeLimit": 16, "wrcTableSize": 65536, "wrcMaxAge": 0,
                      "wrcShadeSamples": 1, "wrcBypassSharing": False, "showWrcCells": False})
    m.addGraph(graph)
    m.setActiveGraph(graph)
    m.loadScene(str(ROOT / SCENES[SCENE]))
    m.clock.pause()
    m.scene.camera.animated = False
    records["settings"] = dict(p.properties)
    for key in ("gridCounts", "gridMin", "gridMax"):
        v = records["settings"][key]
        records["settings"][key] = [v.x, v.y, v.z] if hasattr(v, "x") else list(v)
    records["camera"] = {name: [getattr(getattr(m.scene.camera, name), axis) for axis in ("x", "y", "z")]
                         for name in ("position", "target", "up")}
    frames(256)
    assert p.updatedFrames == 256, p.updatedFrames
    records["warmup"] = checked_stats(p)
    for index in range(3):
        frames(32)
        m.profiler.enabled = True
        frames(8)
        before = p.updatedFrames
        m.profiler.start_capture()
        frames(256)
        timing = m.profiler.end_capture()
        m.profiler.enabled = False
        assert p.updatedFrames == before + 256, (before, p.updatedFrames)
        tag = f"window-{index}"
        (OUT / (tag + "-timing.json")).write_text(json.dumps(timing, indent=2), encoding="utf-8")
        snapshots = []
        for _ in range(4):
            snapshots.append(checked_stats(p))
            frames(1)
        m.frameCapture.outputDir = str(OUT)
        m.frameCapture.baseFilename = tag
        m.frameCapture.captureAllOutputs = False
        m.frameCapture.capture()
        records["windows"].append({"tag": tag, "timed_frames": 256, "first_update_before_timing": before,
                                    "capture_update": p.updatedFrames, "stats": snapshots})
        print(f"Completed {SCENE} {MODE} {tag}", flush=True)
    (OUT / "complete.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
except Exception:
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    exit(1)
exit()
