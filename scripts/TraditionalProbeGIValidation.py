"""Run with --headless --script ... --deferred. Produces captures then exits."""
from falcor import *
from pathlib import Path
import os
import runpy

import traceback

try:
    root = Path("F:/")
    scene = os.environ.get("PROBE_GI_SCENE", "F:/media/test_scenes/cornell_box.pyscene")
    capture_dir = Path(os.environ.get("PROBE_GI_OUTPUT", "F:/build/probe-validation"))
    capture_dir.mkdir(parents=True, exist_ok=True)
    reference = os.environ.get("PROBE_GI_REFERENCE", "0") == "1"
    if reference:
        g = RenderGraph("ProbeReference")
        g.addPass(createPass("VBufferRT", {"samplePattern": "Center", "useAlphaTest": True}), "Visibility")
        g.addPass(createPass("PathTracer", {"samplesPerPixel": 16, "maxSurfaceBounces": 4,
                                           "tracePassMode": "MinimalPayload"}), "PT")
        g.addPass(createPass("AccumulatePass", {"enabled": True, "precisionMode": "Single"}), "Accum")
        g.addPass(createPass("ToneMapper", {"autoExposure": False, "exposureCompensation": 0.0}), "Display")
        g.addEdge("Visibility.vbuffer", "PT.vbuffer")
        g.addEdge("Visibility.viewW", "PT.viewW")
        g.addEdge("Visibility.mvec", "PT.mvec")
        g.addEdge("PT.color", "Accum.input")
        g.addEdge("Accum.output", "Display.src")
        g.markOutput("Accum.output")
        g.markOutput("Display.dst")
    else:
        scope = runpy.run_path(str(root / "scripts/TraditionalProbeGI.py"))
        g = scope["TraditionalProbeGI"]
        g.markOutput("Probes.color")
        g.markOutput("Probes.probeLighting")
    m.addGraph(g)
    m.loadScene(scene)
    m.clock.pause()
    samples = int(os.environ.get("PROBE_GI_SAMPLES", "2048"))
    mode = os.environ.get("PROBE_GI_MODE", "auto")
    frames = 128 if reference else ((samples + 15) // 16 + 2 if mode != "load" else 3)
    for _ in range(frames):
        renderFrame()
    m.frameCapture.outputDir = str(capture_dir)
    m.frameCapture.baseFilename = os.environ.get("PROBE_GI_TAG", mode)
    m.frameCapture.capture()
    if os.environ.get("PROBE_GI_MOVE_CAMERA", "0") == "1":
        p = m.scene.camera.position
        m.scene.camera.position = float3(p.x + 0.05, p.y, p.z)
        renderFrame()
        m.frameCapture.baseFilename = "camera-moved"
        m.frameCapture.capture()
    exit()

except Exception:
    traceback.print_exc()
    # exit() requests loop termination; prevent another render of the failing graph.
    if "g" in globals():
        m.removeGraph(g)
    exit(1)
