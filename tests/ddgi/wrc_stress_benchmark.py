"""Mogwai worker: amplify ALU divergence on real WRC entries in materials.pyscene."""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["WRC_STRESS_OUTPUT"])
CONFIG = json.loads(os.environ["WRC_STRESS_CONFIG"])
records = {"config": CONFIG, "windows": []}


def frames(count):
    for _ in range(count):
        renderFrame()


def plain(value):
    if hasattr(value, "x"):
        return [value.x, value.y, value.z]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def checked_stats(p, grouped, mode, iterations):
    s = plain(dict(p.stats))
    assert s["finite"] and s["wrcNonFiniteResults"] == 0, s
    assert all(v == 0 for k, v in s.items() if k.startswith("rejected")), s
    assert s["wrcMaterialTypes"] == 11 and s["wrcDispatches"] == (11 if grouped else 1), s
    assert s["wrcStressMode"] == mode and s["wrcStressIterations"] == iterations, s
    assert s["wrcOccupiedEntries"] == s["wrcActiveEntries"] == s["wrcShadedEntries"] > 0, s
    assert s["wrcTemporalReusedEntries"] == 0, s
    assert s["wrcServedRays"] + s["wrcFallbackRays"] == s["wrcValidRays"], s
    assert s["wrcFallbackRays"] == 0, s  # Keep synthetic work inside the measured shade stage.
    assert s["wrcWaveCount"] > 0, s
    if grouped:
        assert s["wrcWaveTypeSum"] == s["wrcWaveCount"], s
    if mode and iterations:
        assert s["wrcStressEntries"] == s["wrcShadedEntries"], s
        assert s["wrcStressChecksum"] != 0, s
    return s


try:
    factory = runpy.run_path(str(ROOT / "scripts/RTXGIDDGI.py"))["render_graph_RTXGIDDGI"]
    graph = factory()
    graph.markOutput("DDGI.indirect")
    p = graph.getPass("DDGI")
    p.set_properties({"useWRC": True, "wrcMaxAge": 0, "wrcShadeSamples": 1,
                      "gridCounts": uint3(*CONFIG["counts"]), "raysPerProbe": CONFIG["rays"],
                      "wrcCellScale": CONFIG.get("cell_scale", 0.1), "wrcMaxLod": CONFIG.get("max_lod", 16),
                      "wrcTableSize": 262144, "wrcProbeLimit": 64,
                      "showWrcCells": False, "wrcStressMode": 0, "wrcStressIterations": 0,
                      "wrcStressStats": False})
    m.addGraph(graph)
    m.setActiveGraph(graph)
    m.loadScene(str(ROOT / "media/test_scenes/materials/materials.pyscene"))
    m.clock.pause()
    m.scene.camera.animated = False
    frames(128)
    records["properties"] = plain(dict(p.properties))
    for case_index, (mode, iterations) in enumerate(CONFIG["cases"]):
        p.set_properties({"wrcStressMode": mode, "wrcStressIterations": iterations})
        for window_index, grouped in enumerate(CONFIG["order"]):
            p.set_properties({"wrcGroupByMaterial": grouped, "wrcStressStats": False})
            frames(64)
            m.profiler.enabled = True
            frames(8)
            m.profiler.start_capture()
            frames(CONFIG["frames"])
            timing = m.profiler.end_capture()
            m.profiler.enabled = False
            tag = f"{case_index}-{mode}-{iterations}-{window_index}-{'grouped' if grouped else 'mixed'}"
            (OUT / (tag + "-timing.json")).write_text(json.dumps(timing), encoding="utf-8")
            # Wave/type/checksum atomics and CPU readbacks are outside timed windows.
            p.set_properties({"wrcStressStats": True})
            snapshots = []
            for _ in range(4):
                frames(1)
                snapshots.append(checked_stats(p, grouped, mode, iterations))
            records["windows"].append({"tag": tag, "mode": mode, "iterations": iterations,
                                        "grouped": grouped, "stats": snapshots})
            (OUT / "progress.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
            print("Completed " + tag, flush=True)
    p.set_properties({"wrcStressStats": False})
    frames(1)
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.baseFilename = "final"
    m.frameCapture.captureAllOutputs = False
    m.frameCapture.capture()
    # Restore normal shaders and verify turning the experiment off is functional.
    p.set_properties({"wrcStressMode": 0, "wrcStressIterations": 0, "wrcStressStats": True})
    frames(2)
    final = checked_stats(p, CONFIG["order"][-1], 0, 0)
    assert final["wrcStressEntries"] == 0 and final["wrcStressChecksum"] == 0, final
    records["disabled_check"] = final
    (OUT / "complete.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
except Exception:
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    exit(1)
exit()
