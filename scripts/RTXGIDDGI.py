"""Dynamic diffuse GI using the NVIDIA RTXGI-DDGI probe pipeline (D3D12)."""
from falcor import *


def render_graph_RTXGIDDGI():
    g = RenderGraph("RTXGIDDGI")
    g.addPass(createPass("VBufferRT", {"samplePattern": "Center", "useAlphaTest": True}), "Visibility")
    g.addPass(createPass("RTXGIDDGI", {
        "gridCounts": uint3(8, 6, 8),
        "raysPerProbe": 256,
        "hysteresis": 0.97,
        "normalBias": 0.05,
        "viewBias": 0.05,
        "enableRelocation": True,
        "enableClassification": True,
        "updateEnabled": True,
        "autoBounds": True,
        "showProbes": False,
        "indirectOnly": False,
        "intensity": 1.0,
    }), "DDGI")
    g.addPass(createPass("ToneMapper", {"autoExposure": False, "exposureCompensation": 0.0}), "Display")
    g.addEdge("Visibility.vbuffer", "DDGI.vbuffer")
    g.addEdge("Visibility.viewW", "DDGI.viewW")
    g.addEdge("DDGI.color", "Display.src")
    g.markOutput("Display.dst")
    return g


RTXGIDDGI = render_graph_RTXGIDDGI()
try:
    m.addGraph(RTXGIDDGI)
except NameError:
    pass
