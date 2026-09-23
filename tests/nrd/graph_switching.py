"""Exercise the unified launcher graphs in one D3D12 Mogwai process."""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import traceback
import uuid

out = Path('F:/build/gi-switch-validation') / uuid.uuid4().hex[:8]
out.mkdir(parents=True)
os.environ['FALCOR_START_RENDERER'] = 'PathTracer'
os.environ['PROBE_GI_MODE'] = 'manual'
os.environ['PROBE_GI_CACHE'] = str(out / 'test.shprobe')

def frames(n=1):
    for _ in range(n):
        renderFrame()

def capture(tag):
    m.frameCapture.outputDir = str(out)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()

def camera_position():
    p = m.scene.camera.position
    return (p.x, p.y, p.z)

try:
    graphs = runpy.run_path('F:/scripts/GIPreview.py', init_globals={'m': m})['graphs']
    assert m.activeGraph.name == 'PathTracer'
    assert graphs['PathTracerNRD'].getPass('DLSS').properties['enabled']
    m.loadScene('F:/media/test_scenes/cornell_box.pyscene')
    frames(16)
    capture('cornell-pathtracer')
    scene = m.scene
    position = camera_position()
    probe_graph = graphs['TraditionalProbeGI']
    p = probe_graph.getPass('Probes')
    m.setActiveGraph(probe_graph)
    frames(2)
    assert not p.ready and not p.baking
    p.configureBake({'gridCounts': uint3(3), 'samplesPerProbe': 64, 'samplesPerFrame': 4})
    p.bake()
    frames(2)
    progress = p.completedSamples
    assert p.baking and 0 < progress < 64
    m.setActiveGraph(graphs['PathTracerNRD'])
    frames(32)
    capture('cornell-nrd')
    assert p.completedSamples == progress
    assert camera_position() == position
    assert m.scene == scene
    m.setActiveGraph(probe_graph)
    frames(20)
    assert p.ready and p.completedSamples == 64
    capture('cornell-probe')
    cache = Path(p.cacheFile).read_bytes()
    m.setActiveGraph(graphs['PathTracer'])
    frames(8)
    m.scene.camera.position += float3(.02, 0, 0)
    frames(8)
    m.setActiveGraph(graphs['PathTracerNRD'])
    frames(16)
    m.setActiveGraph(probe_graph)
    frames(2)
    assert p.ready and p.completedSamples == 64
    assert Path(p.cacheFile).read_bytes() == cache
    capture('probe-after-switch')
    m.loadScene('F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene')
    for name, graph in graphs.items():
        m.setActiveGraph(graph)
        frames(16)
        capture('room-' + name)
    assert not p.ready and not p.baking and p.completedSamples == 0
    assert Path(p.cacheFile).read_bytes() == cache
    (out / 'result.json').write_text(json.dumps({
        'checks': ['three graphs render in D3D12', 'shared scene and camera',
                   'inactive probe bake paused', 'bake resumes and cache preserved',
                   'switch after camera motion', 'scene change resets probes'],
        'graphs': list(graphs), 'cache': p.cacheFile,
    }, indent=2))
    print('Unified graph checks passed: ' + str(out))
except Exception:
    (out / 'failure.txt').write_text(traceback.format_exc())
    raise
exit()
