"""Run inside Mogwai --headless --deferred --script (Vulkan)."""
from falcor import *
from pathlib import Path
import runpy
import json
import traceback

out = Path("F:/build/svgf-validation")
out.mkdir(parents=True, exist_ok=True)
for name in ("failure.txt", "integration.json", "results.json"):
    (out / name).unlink(missing_ok=True)


def frames(n=1):
    for _ in range(n):
        renderFrame()


def capture(tag):
    m.frameCapture.outputDir = str(out)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()


try:
    scope = runpy.run_path("F:/scripts/PathTracerSVGF.py")
    g = scope["PathTracerSVGF"]
    m.addGraph(g)
    for name in ("PathTracer.color", "SVGF.Filtered image", "Reference.output"):
        g.markOutput(name)
    m.loadScene("F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene")
    m.clock.pause()
    p = g.getPass("SVGF")
    frames(48)
    history = p.historyFrames
    assert history >= 20, ("History resets every frame", history)
    for i in range(8):
        frames()
        capture("room" + str(i))
    p.resetHistory()
    assert p.historyFrames == 0
    frames()
    assert p.historyFrames == 1
    capture("reset")
    frames(8)
    previous = p.historyFrames
    camera = m.scene.camera
    pos = camera.position
    camera.position = float3(pos.x + 0.08, pos.y, pos.z)
    frames()
    assert p.historyFrames > previous, "Camera motion should use reprojection"
    capture("move")
    g.updatePass("PathTracer", {"samplesPerPixel": 4})
    frames()
    assert p.historyFrames == 1, "Sample count change must clear history"
    capture("settings")
    g.updatePass("SVGF", {"Enabled": False, "Demodulate": False})
    p = g.getPass("SVGF")
    frames(2)
    capture("disabled")
    g.updatePass("SVGF", {"Enabled": True, "Demodulate": False})
    p = g.getPass("SVGF")
    frames()
    assert p.historyFrames == 1
    m.loadScene("F:/media/test_scenes/cornell_box.pyscene")
    frames()
    assert p.historyFrames == 1
    frames(24)
    capture("cornell")
    resizeFrameBuffer(400, 300)
    frames()
    assert p.historyFrames == 1
    capture("resized")
    # Revisit Room to ensure no Cornell history survives the scene switch.
    m.loadScene("F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene")
    frames()
    assert p.historyFrames == 1
    frames(24)
    capture("room-return")
    (out / "integration.json").write_text(json.dumps({
        "history_frames_before_capture": history,
        "checks": ["room", "temporal-history", "reset", "camera-motion", "settings",
                   "disabled", "enabled", "scene-switch", "resize", "room-return"],
    }, indent=2))
except Exception:
    (out / "failure.txt").write_text(traceback.format_exc())
    raise
exit()
