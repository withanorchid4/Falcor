"""Shared-scene D3D12 preview: choose an algorithm in Mogwai's Active Graph UI."""
from pathlib import Path
import os
import runpy


def create_preview_graphs():
    directory = Path(__file__).parent
    graphs = {}
    for name in ("PTReference", "TraditionalProbeGI", "RTXGIDDGI"):
        graphs[name] = runpy.run_path(str(directory / (name + ".py")))[name]
    return graphs


graphs = create_preview_graphs()
if os.environ.get("FALCOR_START_SCENE") in ("Cornell", "CornellLambert"):
    cornell_setup = runpy.run_path(str(Path(__file__).parent / "scenes/cornell_rtxgi.py"))
    cornell_setup["configure_graph"](graphs["RTXGIDDGI"])
    for graph in graphs.values():
        cornell_setup["configure_display"](graph)
renderer = os.environ.get("FALCOR_START_RENDERER", "PathTracer")
if os.environ.get("FALCOR_START_SCENE") in ("Sponza", "SponzaLambert"):
    from falcor import uint3
    graphs["RTXGIDDGI"].getPass("DDGI").set_properties({
        "autoBounds": True, "gridCounts": uint3(24, 12, 16),
    })
    for graph in graphs.values():
        graph.updatePass("Display", {"autoExposure": False, "useSceneMetadata": False,
            "operator": "Aces", "filmSpeed": 100.0, "fNumber": 1.0, "shutter": 1.0})
initial_graph = {
    "Probe": "TraditionalProbeGI",
    "DDGI": "RTXGIDDGI",
}.get(renderer, "PTReference")
try:
    for graph in graphs.values():
        m.addGraph(graph)
    m.setActiveGraph(graphs[initial_graph])
    m.clock.pause()
except NameError:
    pass
