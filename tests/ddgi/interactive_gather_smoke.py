"""Exercise live DDGI mode/resolution switches and accumulation reset/bypass."""
from pathlib import Path
import os, runpy, json, traceback
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/interactive-gather-smoke'
OUT.mkdir(exist_ok=True)
try:
    os.environ['FALCOR_START_SCENE'] = 'CornellLambert'
    os.environ['FALCOR_START_RENDERER'] = 'DDGI'
    graphs = runpy.run_path(str(ROOT / 'scripts/GIPreview.py'), init_globals={'m': m})['graphs']
    assert set(graphs) == {'PTReference', 'TraditionalProbeGI', 'RTXGIDDGI'}
    g = graphs['RTXGIDDGI']
    assert m.activeGraph.name == g.name
    dd, acc = g.getPass('DDGI'), g.getPass('Accumulate')
    assert not dd.properties['finalGather']
    assert dd.properties['halfResolutionGather'] and acc.enabled
    for output in ['DDGI.color', 'DDGI.diffuseRadianceHitDist', 'Reconstruct.color', 'Accumulate.output']:
        g.markOutput(output)
    m.loadScene(str(ROOT / 'scripts/scenes/CornellLambert.pyscene'))
    m.clock.pause()
    m.scene.camera.animated = False
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.captureAllOutputs = False
    def capture(tag):
        m.frameCapture.baseFilename = tag
        m.frameCapture.capture()
    for _ in range(32): renderFrame()
    capture('default')
    for tag, props in [
        ('half', {'finalGather': True}),
        ('full', {'halfResolutionGather': False}),
        ('off-full', {'finalGather': False}),
        ('off-half', {'halfResolutionGather': True}),
        ('half-again', {'finalGather': True}),
    ]:
        dd.set_properties(props)
        renderFrame()
        capture(tag + '-reset')
        for _ in range(8): renderFrame()
    acc.enabled = False
    for _ in range(4): renderFrame()
    capture('acc-off')
    acc.enabled = True
    renderFrame()
    capture('acc-on-reset')
    (OUT / 'result.json').write_text(json.dumps({'passed': True}))
except Exception:
    (OUT / 'result.json').write_text(json.dumps({'passed': False, 'error': traceback.format_exc()}))
finally:
    exit()
