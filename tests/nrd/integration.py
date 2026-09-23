"""Run with Mogwai --device-type d3d12 --headless --deferred --script."""
from falcor import *
from pathlib import Path
import runpy
import json
import traceback

out = Path('F:/build/nrd-dlss-validation')
out.mkdir(parents=True, exist_ok=True)

def frames(count):
    for _ in range(count): renderFrame()

def capture(tag):
    m.frameCapture.outputDir = str(out)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()

try:
    g = runpy.run_path('F:/scripts/PathTracerNRDPreview.py')['PathTracerNRD']
    m.addGraph(g)
    for name in ('DLSS.output', 'PathTracer.color', 'AccumulatePass.output'):
        g.markOutput(name)
    assert g.getPass('DLSS').properties['enabled'] is True
    m.loadScene('F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene')
    m.clock.pause()
    frames(1)
    m.scene.camera.animated = False
    m.scene.camera.position = float3(.132343, 1.312430, -2.434279)
    m.scene.camera.target = float3(1.024723, 1.129566, -2.021704)
    m.scene.camera.up = float3(.001223, .999999, .000565)
    frames(64)
    capture('room64')
    frames(192)
    capture('room256')
    for index in range(8):
        frames(1)
        capture('noise' + str(index))
    m.scene.camera.target = float3(1.103621, 1.334360, -2.197343)
    frames(1)
    capture('move1')
    frames(32)
    capture('move33')
    m.loadScene('F:/media/test_scenes/cornell_box.pyscene')
    frames(64)
    capture('cornell64')
    resizeFrameBuffer(400, 300)
    frames(32)
    capture('resize')
    (out/'integration.json').write_text(json.dumps({
        'backend': 'd3d12', 'dlss': True,
        'checks': ['room256', 'camera-motion', 'cornell', 'resize'],
        'path_tracer': g.getPass('PathTracer').properties,
    }, indent=2))
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc())
    raise
exit()
