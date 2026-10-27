"""Mogwai worker for grouped versus mixed WRC compute dispatches.

Run through run_wrc_dispatch_benchmark.py; one graph per process avoids repeated
scene/compiler construction. GPU timing windows contain no diagnostic readbacks.
"""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["WRC_DISPATCH_OUTPUT"])
ORDER = os.environ.get("WRC_DISPATCH_ORDER", "1001")
records = {"order": ORDER, "windows": [], "checks": []}


def frames(count):
    for _ in range(count):
        renderFrame()


def stats(p, grouped):
    s = dict(p.stats)
    assert s["finite"] and s["wrcNonFiniteResults"] == 0, s
    assert all(v == 0 for k, v in s.items() if k.startswith("rejected")), s
    assert s["wrcGroupByMaterial"] == grouped, s
    assert s["wrcMaterialTypes"] == 11, s
    assert s["wrcDispatches"] == (11 if grouped else 1), s
    occupied = s["wrcOccupiedEntries"]
    assert occupied > 0 and occupied == s["wrcActiveEntries"], s
    assert s["wrcShadedEntries"] + s["wrcTemporalReusedEntries"] == occupied, s
    assert s["wrcServedRays"] + s["wrcFallbackRays"] == s["wrcValidRays"], s
    assert s["wrcServedRays"] >= occupied, s
    groups, threads = s["wrcShaderGroups"], s["wrcScheduledThreads"]
    assert 0 < groups <= (11 if grouped else 1), s
    assert occupied <= threads < occupied + 64 * groups and threads % 64 == 0, s
    return s


def capture(tag):
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.baseFilename = tag
    m.frameCapture.captureAllOutputs = False
    m.frameCapture.capture()


try:
    factory = runpy.run_path(str(ROOT / "scripts/RTXGIDDGI.py"))["render_graph_RTXGIDDGI"]
    factory.__globals__.pop("RTXGIDDGI", None)
    graph = factory()
    graph.markOutput("DDGI.indirect")
    p = graph.getPass("DDGI")
    p.set_properties({"useWRC": True, "wrcGroupByMaterial": ORDER[0] == "1",
                      "wrcMaxAge": 0, "wrcShadeSamples": 1, "showWrcCells": False})
    m.addGraph(graph)
    m.setActiveGraph(graph)
    m.loadScene(str(ROOT / "media/test_scenes/materials/materials.pyscene"))
    m.clock.pause()
    m.scene.camera.animated = False
    records["properties"] = dict(p.properties)
    # Properties containing vector bindings need plain JSON values.
    for key in ("gridCounts", "gridMin", "gridMax"):
        value = records["properties"][key]
        records["properties"][key] = [value.x, value.y, value.z] if hasattr(value, "x") else list(value)
    frames(128)
    for index, bit in enumerate(ORDER):
        grouped = bit == "1"
        before = dict(p.stats)
        p.set_properties({"wrcGroupByMaterial": grouped})
        frames(1)
        first = stats(p, grouped)
        assert first["updatedFrames"] == before["updatedFrames"] + 1, (before, first)
        if before["wrcGroupByMaterial"] != grouped:
            assert first["wrcInvalidations"] == before["wrcInvalidations"] + 1, (before, first)
        frames(32)
        m.profiler.enabled = True
        frames(8)
        m.profiler.start_capture()
        frames(192)
        timing = m.profiler.end_capture()
        m.profiler.enabled = False
        tag = f"{index}-{'grouped' if grouped else 'mixed'}"
        (OUT / (tag + "-timing.json")).write_text(json.dumps(timing, indent=2), encoding="utf-8")
        snapshots = []
        for _ in range(4):
            snapshots.append(stats(p, grouped))
            frames(1)
        capture(tag)
        records["windows"].append({"tag": tag, "grouped": grouped, "timed_frames": 192,
                                    "first": first, "stats": snapshots})
        print("Completed " + tag, flush=True)

    # Exercise toggling a frozen field and the cell overlay's mixed-list indexing.
    before = dict(p.stats)
    p.set_properties({"updateEnabled": False, "wrcGroupByMaterial": not before["wrcGroupByMaterial"],
                      "showWrcCells": True})
    frames(2)
    frozen = dict(p.stats)
    assert frozen["updatedFrames"] == before["updatedFrames"] and frozen["wrcActiveEntries"] == 0, frozen
    p.set_properties({"updateEnabled": True})
    frames(1)
    resumed = stats(p, not before["wrcGroupByMaterial"])
    assert resumed["updatedFrames"] == before["updatedFrames"] + 1, resumed
    for grouped in (False, True):
        p.set_properties({"wrcGroupByMaterial": grouped})
        frames(2)
        stats(p, grouped)
        capture("overlay-" + ("grouped" if grouped else "mixed"))
    records["checks"].append("toggle preserves DDGI history; frozen toggle and both overlay list layouts")

    # Changing scheduling also invalidates temporal WRC values without resetting probes.
    p.set_properties({"showWrcCells": False, "wrcMaxAge": 2})
    frames(64)
    for grouped in (False, True):
        before = dict(p.stats)
        p.set_properties({"wrcGroupByMaterial": grouped})
        frames(1)
        first = stats(p, grouped)
        assert first["updatedFrames"] == before["updatedFrames"] + 1, first
        assert first["wrcTemporalReusedEntries"] == 0, first
        frames(8)
        assert stats(p, grouped)["wrcTemporalReusedEntries"] > 0
    records["checks"].append("both modes invalidate and resume temporal reuse")
    (OUT / "complete.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
except Exception:
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    exit(1)
exit()
