"""Render the official Cornell geometry with configurable directional/point lights.

Run headless through Mogwai; CORNELL_LIGHT_TEST_OUTPUT selects the artifact directory.
"""
from falcor import *
from pathlib import Path
import hashlib
import json
import os
import runpy
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["CORNELL_LIGHT_TEST_OUTPUT"])

try:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["FALCOR_START_SCENE"] = "Cornell"
    os.environ["FALCOR_START_RENDERER"] = "DDGI"
    setup = runpy.run_path(str(ROOT / "scripts/scenes/cornell_rtxgi.py"))
    default = setup["load_config"]()
    graph = runpy.run_path(str(ROOT / "scripts/GIPreview.py"))["graphs"]["RTXGIDDGI"]
    for channel in ("DDGI.indirect", "DDGI.color", "DirectLighting.diffuseIllumination"):
        graph.markOutput(channel)
    m.setActiveGraph(graph)
    m.clock.pause()
    m.frameCapture.outputDir = str(OUT)
    records = {"modelSHA256": hashlib.sha256(setup["model_path"]().read_bytes()).hexdigest(), "cases": {}}
    for tag, sun_enabled, point_enabled in (("sun", True, False), ("point", False, True), ("off", False, False)):
        config = json.loads(json.dumps(default))
        config["directionalLight"]["enabled"] = sun_enabled
        config["ceilingPointLight"]["enabled"] = point_enabled
        path = OUT / (tag + ".json")
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        os.environ["CORNELL_RTXGI_CONFIG"] = str(path)
        m.loadScene(str(ROOT / "scripts/scenes/CornellRTXGI.pyscene"))
        assert m.scene.getLight("Sun").active == sun_enabled
        assert m.scene.getLight("Ceiling Point").active == point_enabled
        assert abs(m.scene.camera.position.z - 4.0) < 1e-5
        ddgi = graph.getPass("DDGI")
        ddgi.reset()
        for _ in range(256):
            renderFrame()
        stats = dict(ddgi.stats)
        assert stats["finite"] and stats["totalProbes"] == 729, stats
        records["cases"][tag] = stats
        m.frameCapture.baseFilename = tag
        m.frameCapture.capture()
    # Exercise the same property setters used by Scene Settings > Lights, without reloading.
    point = m.scene.getLight("Ceiling Point")
    point.active = True
    point.position = float3(0.5, 1.5, 0.2)
    point.intensity = float3(2.0, 0.0, 0.0)
    for _ in range(256):
        renderFrame()
    m.frameCapture.baseFilename = "live-red-point"
    m.frameCapture.capture()
    records["cases"]["live-red-point"] = dict(ddgi.stats)
    (OUT / "stats.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
except Exception:
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
finally:
    exit()
