"""Shared-scene D3D12 preview: choose an algorithm in Mogwai's Active Graph UI."""
from pathlib import Path
import os
import runpy


def create_preview_graphs():
    directory = Path(__file__).parent
    graphs = {}
    for name in ("PathTracer", "PathTracerNRD", "TraditionalProbeGI", "RTXGIDDGI"):
        graphs[name] = runpy.run_path(str(directory / (name + ".py")))[name]
    return graphs


graphs = create_preview_graphs()
renderer = os.environ.get("FALCOR_START_RENDERER", "PathTracer")
initial_graph = {
    "NRD": "PathTracerNRD",
    "Probe": "TraditionalProbeGI",
    "DDGI": "RTXGIDDGI",
}.get(renderer, "PathTracer")
try:
    for graph in graphs.values():
        m.addGraph(graph)
    m.setActiveGraph(graphs[initial_graph])
    m.clock.pause()
except NameError:
    pass
