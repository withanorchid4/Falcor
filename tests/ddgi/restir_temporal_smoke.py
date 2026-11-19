"""Runtime regressions for the optional temporal FG reservoir (481x271)."""
from falcor import *
from pathlib import Path
import os, runpy, json, traceback
R = Path(__file__).resolve().parents[2]
O = R / 'build/restir-temporal-smoke'
O.mkdir(exist_ok=True)
(O / 'failure.txt').unlink(missing_ok=True)
record = {}
def frames(n):
    for _ in range(n): renderFrame()
def capture(tag):
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()
try:
    os.environ['CORNELL_RTXGI_CONFIG'] = str(R / 'build/highres-1080p-split-rerun/scene.json')
    setup = runpy.run_path(str(R / 'scripts/scenes/cornell_rtxgi.py'))
    factory = runpy.run_path(str(R / 'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
    for name, enabled, length in [('off', False, 8), ('one', True, 1), ('temporal', True, 8)]:
        g = factory('half'); g.name = 'Reservoir_' + name
        setup['configure_graph'](g)
        dd = g.getPass('DDGI'); acc = g.getPass('Accumulate')
        dd.set_properties({'restirGather': enabled, 'restirHistoryLength': length, 'jitterHalfGather': True})
        acc.enabled = False
        for output in ['DDGI.gatherDiffuse', 'Reconstruct.color', 'Accumulate.output']: g.markOutput(output)
        m.addGraph(g); m.setActiveGraph(g)
        m.loadScene(str(R / 'scripts/scenes/CornellLambert.pyscene'))
        m.clock.pause(); m.scene.camera.animated = False
        m.frameCapture.outputDir = str(O); m.frameCapture.captureAllOutputs = False
        frames(128)
        for i in range(8): renderFrame(); capture(name + '-' + str(i))
        record[name] = dict(dd.stats)
        if enabled and length > 1:
            before = dd.stats['restirResetCount']; frames(8)
            assert dd.stats['restirResetCount'] == before, 'Static history resets every frame'
            m.scene.camera.position += float3(0.05, 0, 0)
            renderFrame()
            assert dd.stats['restirResetCount'] > before, 'Camera motion did not clear reservoir'
            acc.enabled = True; frames(8)
            for tag, props in [('off', {'restirGather': False}), ('on', {'restirGather': True}),
                               ('full', {'halfResolutionGather': False}), ('half', {'halfResolutionGather': True}),
                               ('fixed', {'jitterHalfGather': False}), ('no-fg', {'finalGather': False})]:
                dd.set_properties(props); renderFrame(); capture(tag + '-reset'); frames(3)
            record['switches'] = dict(dd.stats)
        m.removeGraph(g)
    (O / 'result.json').write_text(json.dumps(record, indent=2))
except Exception:
    (O / 'failure.txt').write_text(traceback.format_exc())
finally: exit()
