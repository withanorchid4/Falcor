from falcor import *
from pathlib import Path
import runpy
import json

out = Path("F:/build/svgf-long-run")
out.mkdir(parents=True, exist_ok=True)
g = runpy.run_path("F:/scripts/PathTracerSVGF.py")["PathTracerSVGF"]
m.addGraph(g)
g.markOutput("SVGF.Filtered image")
g.markOutput("PathTracer.color")
g.markOutput("GBuffer.mask")
m.loadScene("F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene")
m.clock.pause()
renderFrame()
m.scene.camera.animated = False
m.scene.camera.position = float3(0.132343, 1.312430, -2.434279)
m.scene.camera.target = float3(1.103621, 1.334360, -2.197343)
g.getPass("SVGF").resetHistory()
for i in range(6000):
    renderFrame()
    if i + 1 in (64, 512, 2048, 6000):
        m.frameCapture.outputDir = str(out)
        m.frameCapture.baseFilename = "frame" + str(i + 1)
        m.frameCapture.capture()
        (out / "progress.json").write_text(json.dumps({"frame": i + 1, "history": g.getPass("SVGF").historyFrames}))
assert g.getPass("SVGF").historyFrames >= 5990
exit()
