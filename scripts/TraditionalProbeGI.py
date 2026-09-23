"""Traditional diffuse SH probes. Configure via PROBE_GI_* environment variables."""
from falcor import *
import os


def render_graph_TraditionalProbeGI():
    props = {
        "mode": os.environ.get("PROBE_GI_MODE", "manual"),
        "cacheFile": os.environ.get("PROBE_GI_CACHE", ""),
        "sceneRevision": os.environ.get("PROBE_GI_REVISION", "1"),
        "gridCounts": uint3(8, 6, 8),
        "samplesPerProbe": int(os.environ.get("PROBE_GI_SAMPLES", "2048")),
        "samplesPerFrame": 16,
        "maxBounces": 3,
        "enableProbes": os.environ.get("PROBE_GI_ENABLED", "1") != "0",
    }
    g = RenderGraph("TraditionalProbeGI")
    # No camera jitter or infinite accumulation: show the actual runtime result.
    g.addPass(createPass("VBufferRT", {"samplePattern": "Center", "useAlphaTest": True}), "Visibility")
    g.addPass(createPass("TraditionalProbeGI", props), "Probes")
    g.addPass(createPass("ToneMapper", {"autoExposure": False, "exposureCompensation": 0.0}), "Display")
    g.addEdge("Visibility.vbuffer", "Probes.vbuffer")
    g.addEdge("Visibility.viewW", "Probes.viewW")
    g.addEdge("Probes.color", "Display.src")
    g.markOutput("Display.dst")
    return g


TraditionalProbeGI = render_graph_TraditionalProbeGI()
try:
    m.addGraph(TraditionalProbeGI)
except NameError:
    pass
