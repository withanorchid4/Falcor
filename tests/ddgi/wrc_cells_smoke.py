"""Mogwai smoke test: occupied-cell overlay is visible and leaves frozen GI intact.

Set WRC_CELLS_OUTPUT and optionally WRC_CELLS_SCENE=room before running headless.
Captures are checked externally so no image library runs inside Mogwai.
"""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["WRC_CELLS_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
SCENE = os.environ.get("WRC_CELLS_SCENE", "cornell")


def frames(count):
    for _ in range(count):
        renderFrame()


def capture(tag):
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.baseFilename = tag
    m.frameCapture.captureAllOutputs = False
    m.frameCapture.capture()


try:
    factory = runpy.run_path(str(ROOT / "scripts/RTXGIDDGI.py"))["render_graph_RTXGIDDGI"]
    graph = factory()
    graph.markOutput("DDGI.color")
    graph.markOutput("DDGI.indirect")
    p = graph.getPass("DDGI")
    p.set_properties({"useWRC": True, "indirectOnly": True})
    m.addGraph(graph)
    m.setActiveGraph(graph)
    scene = "cornell_box.pyscene" if SCENE == "cornell" else "grey_and_white_room/grey_and_white_room.pyscene"
    m.loadScene(str(ROOT / "media/test_scenes" / scene))
    m.clock.pause()
    m.scene.camera.animated = False
    frames(128)
    p.set_properties({"updateEnabled": False})
    frames(1)
    before = dict(p.stats)
    assert before["wrcOccupiedEntries"] > 0
    capture("off")
    p.set_properties({"showWrcCells": True})
    frames(1)
    capture("on")
    p.set_properties({"wrcCellsXRay": True})
    frames(1)
    capture("xray")
    p.set_properties({"wrcCellsXRay": False, "wrcCellsLod": 64})
    frames(1)
    capture("empty-lod")
    p.set_properties({"wrcCellsLod": 0, "wrcCellsOpacity": 0.0})
    frames(1)
    capture("transparent")
    p.set_properties({"showWrcCells": False, "wrcCellsOpacity": 0.65})
    frames(1)
    capture("off-again")
    after = dict(p.stats)
    for key in ("updatedFrames", "wrcInvalidations", "wrcValidRays", "wrcOccupiedEntries", "wrcShadedEntries"):
        assert before[key] == after[key], (key, before[key], after[key])
    p.set_properties({"showWrcCells": True})
    resizeFrameBuffer(401, 301)
    frames(1)
    capture("resize")
    assert p.updatedFrames == before["updatedFrames"]
    resizeFrameBuffer(960, 540)
    p.set_properties({"indirectOnly": False, "updateEnabled": True})
    frames(16)
    capture("preview")
    p.set_properties({"wrcMaxLod": 1})
    frames(16)
    assert p.stats["wrcMaxLod"] == 1
    capture("lod1")
    p.set_properties({"wrcBypassSharing": True})
    frames(8)
    bypass = dict(p.stats)
    assert bypass["wrcOccupiedEntries"] == 0
    assert bypass["wrcValidRays"] == bypass["wrcFallbackRays"] > 0
    capture("bypass")
    p.set_properties({"useWRC": False})
    frames(8)
    capture("original")
    (OUT / "smoke.json").write_text(json.dumps({"scene": SCENE, "passed": True, "before": before,
        "after": after, "bypass": bypass}, indent=2), encoding="utf-8")
except Exception:
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    exit(1)
exit()
