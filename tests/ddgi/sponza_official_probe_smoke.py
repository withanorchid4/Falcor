"""Placement A/B preview, not a converged accuracy or timing benchmark."""
from falcor import *
from pathlib import Path
import json, os, runpy, traceback

root = Path(__file__).resolve().parents[2]
output = root / 'build/sponza-official-probe-preview'
output.mkdir(exist_ok=True)
record = {}
try:
    os.environ['FALCOR_START_SCENE'] = 'SponzaLambert'
    g = runpy.run_path(str(root / 'scripts/GIPreview.py'))['graphs']['RTXGIDDGI']
    m.addGraph(g)
    m.setActiveGraph(g)
    m.loadScene(str(root / 'scripts/scenes/SponzaLambert.pyscene'))
    m.clock.pause()
    m.scene.camera.animated = False
    g.markOutput('Accumulate.output')
    m.frameCapture.outputDir = str(output)
    p = g.getPass('DDGI')
    acc = g.getPass('Accumulate')
    official = runpy.run_path(str(root / 'scripts/scenes/sponza_rtxgi.py'))['configure_graph']
    for mode in ['previous', 'official', 'official-half']:
        if mode == 'previous':
            p.set_properties({'autoBounds': True, 'gridCounts': uint3(24,12,16),
                'normalBias': .05, 'viewBias': .05, 'minFrontfaceDistance': .1})
        else:
            official(g)
        p.set_properties({'finalGather': mode == 'official-half', 'halfResolutionGather': True,
            'restirGather': False, 'gatherSpecular': False})
        p.reset()
        acc.enabled = False
        for _ in range(1024): renderFrame()
        acc.enabled = True
        acc.reset()
        for _ in range(1024): renderFrame()
        m.frameCapture.baseFilename = mode
        m.frameCapture.capture()
        s = dict(p.stats)
        assert s['finite'] and s['nonFiniteTexels'] == 0, s
        assert s['totalProbes'] == (4608 if mode == 'previous' else 10648), s
        if mode != 'previous':
            for got, expected in zip(s['gridMin'], [-11.11, .15, -4.975]):
                assert abs(got - expected) < 1e-4, s
        record[mode] = s
    (output / 'complete.json').write_text(json.dumps(record, indent=2))
except Exception:
    (output / 'failure.txt').write_text(traceback.format_exc())
finally:
    exit()
