"""Mogwai D3D12 integration: shared graphs, dynamic light, history and probe state.

Run through run_validation.py. Captures are linear HDR, before tone mapping.
"""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["DDGI_VALIDATION_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
os.environ["FALCOR_START_RENDERER"] = "DDGI"
os.environ["PROBE_GI_MODE"] = "manual"
os.environ["PROBE_GI_CACHE"] = str(OUT / "isolated-static-probe.shprobe")
records = {"backend": "d3d12", "scenes": {}, "checks": []}


def frames(count):
    for _ in range(count):
        renderFrame()


def capture(tag):
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()


def camera_position():
    position = m.scene.camera.position
    return (position.x, position.y, position.z)


def stats(p):
    s = dict(p.stats)
    assert s["finite"], s
    assert s["rejectedHistorySamples"] == 0, s
    assert s["rejectedRaySamples"] == 0, s
    assert s["totalProbes"] == 8 * 6 * 8, s
    assert 0 <= s["activeProbes"] <= s["totalProbes"], s
    assert 0 <= s["relocatedProbes"] <= s["totalProbes"], s
    return s


def reference(tag):
    m.setActiveGraph(graphs["PathTracer"])
    # Scene lighting edits auto-reset PathTracer's accumulation.
    frames(64)
    capture(tag)
    m.setActiveGraph(graphs["RTXGIDDGI"])


try:
    graphs = runpy.run_path(str(ROOT / "scripts/GIPreview.py"), init_globals={"m": m})["graphs"]
    assert set(graphs) == {"PathTracer", "PathTracerNRD", "TraditionalProbeGI", "RTXGIDDGI"}
    assert m.activeGraph.name == "RTXGIDDGI"
    graph = graphs["RTXGIDDGI"]
    p = graph.getPass("DDGI")
    for channel in ("DDGI.color", "DDGI.indirect"):
        graph.markOutput(channel)
    graphs["PathTracer"].markOutput("AccumulatePass.output")
    for name, scene_path in (
        ("cornell", "media/test_scenes/cornell_box.pyscene"),
        ("room", "media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene"),
    ):
        started = time.perf_counter()
        m.loadScene(str(ROOT / scene_path))
        m.clock.pause()
        m.scene.camera.animated = False
        m.setActiveGraph(graph)
        frames(1)
        assert p.updatedFrames == 1, (name, p.updatedFrames)
        scene = m.scene
        position = camera_position()
        scene_record = records["scenes"][name] = {"initial": stats(p)}

        # Each graph executes against the same live scene and camera. An inactive
        # DDGI pass must preserve history while only the active graph executes.
        for graph_name in ("PathTracer", "PathTracerNRD", "TraditionalProbeGI"):
            count = p.updatedFrames
            m.setActiveGraph(graphs[graph_name])
            frames(16)
            assert p.updatedFrames == count, (name, graph_name, "inactive DDGI updated")
            assert m.scene == scene and camera_position() == position
            capture(name + "-switch-" + graph_name)
        m.setActiveGraph(graph)
        frames(128)
        capture(name + "-baseline")
        scene_record["baseline"] = stats(p)
        assert scene_record["baseline"]["activeProbes"] > 0
        assert scene_record["baseline"]["irradianceMax"] > 0
        reference(name + "-reference-baseline")

        # Use an actual source edit; scaling the final GI output would not test
        # dynamic propagation through the irradiance and distance histories.
        if name == "cornell":
            light = m.scene.getMaterial("Light")
            original = light.emissiveFactor
            light.emissiveFactor = original * 0.25
            restore = lambda: setattr(light, "emissiveFactor", original)
        else:
            original = m.scene.envMap.intensity
            m.scene.envMap.intensity = original * 0.25
            restore = lambda: setattr(m.scene.envMap, "intensity", original)
        count = p.updatedFrames
        frames(1)
        assert p.updatedFrames == count + 1, "Lighting changes unexpectedly erased DDGI history"
        capture(name + "-dim-first")
        frames(95)
        capture(name + "-dim-settled")
        scene_record["dim"] = stats(p)
        reference(name + "-reference-dim")
        restore()
        frames(96)
        capture(name + "-restored")
        scene_record["restored"] = stats(p)

        # Freeze must retain identical indirect lighting, and resuming must use
        # the existing pass rather than replacing it with a new instance.
        p.set_properties({"updateEnabled": False})
        count = p.updatedFrames
        frames(1)
        capture(name + "-freeze-before")
        frames(8)
        assert p.updatedFrames == count
        capture(name + "-freeze-after")
        p.set_properties({"updateEnabled": True})
        frames(2)
        assert p.updatedFrames == count + 2

        # Record real GPU state with both SDK features disabled, then enabled.
        p.set_properties({"enableRelocation": False, "enableClassification": False})
        p.reset()
        frames(16)
        disabled = scene_record["features_disabled"] = stats(p)
        assert disabled["activeProbes"] == disabled["totalProbes"], disabled
        assert disabled["relocatedProbes"] == 0, disabled
        p.set_properties({"enableRelocation": True, "enableClassification": True})
        p.reset()
        frames(32)
        scene_record["features_enabled"] = stats(p)
        p.set_properties({"showProbes": True})
        frames(1)
        capture(name + "-probes")
        p.set_properties({"showProbes": False, "updateEnabled": False})
        p.reset()
        frames(1)
        assert p.updatedFrames == 0
        cleared = scene_record["reset_while_frozen"] = stats(p)
        assert cleared["irradianceMax"] == 0, cleared
        p.set_properties({"updateEnabled": True})
        frames(2)
        assert p.updatedFrames == 2
        scene_record["elapsed_seconds"] = time.perf_counter() - started
        (OUT / "partial.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    resizeFrameBuffer(400, 300)
    frames(16)
    capture("resize")
    records["checks"] = [
        "four graphs in one process", "shared scene and camera", "inactive history preserved",
        "Cornell and Room scene reload", "dynamic emissive and environment changes",
        "freeze/resume", "reset while frozen", "GPU classification/relocation state", "resize",
    ]
    (OUT / "integration.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("DDGI integration captures: " + str(OUT))
except Exception:
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    exit(1)
exit()
