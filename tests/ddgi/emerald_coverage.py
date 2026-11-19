"""Render GBuffer coverage and probe overlays for both Emerald volume densities."""
from falcor import *
from pathlib import Path
import runpy, json, traceback

R = Path(__file__).resolve().parents[2]
O = R / 'build/emerald-coverage'
O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
try:
    setup = runpy.run_path(str(R / 'scripts/scenes/emerald_rtxgi.py'))
    factory = runpy.run_path(str(R / 'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
    g = factory('ddgi')
    setup['configure_graph'](g)
    setup['configure_display'](g)
    for output in ('Visibility.posW', 'Visibility.normW'):
        g.markOutput(output)
    m.addGraph(g)
    m.setActiveGraph(g)
    m.loadScene(str(R / 'scripts/scenes/EmeraldSquareLambert.pyscene'))
    m.clock.pause()
    m.scene.animated = False
    m.frameCapture.outputDir = str(O)
    m.frameCapture.captureAllOutputs = False
    def vector(v): return [float(v.x), float(v.y), float(v.z)]
    c = m.scene.camera
    metadata = {'bounds': str(m.scene.bounds), 'camera': {
        'position': vector(c.position), 'target': vector(c.target), 'up': vector(c.up),
        'focalLength': c.focalLength, 'frameHeight': c.frameHeight}, 'lights': []}
    for light in m.scene.lights:
        values = {'name': light.name, 'intensity': vector(light.intensity), 'active': light.active}
        for field in ('position', 'direction'):
            if hasattr(light, field): values[field] = vector(getattr(light, field))
        metadata['lights'].append(values)
    (O/'scene-runtime.json').write_text(json.dumps(metadata, indent=2))
    p = g.getPass('DDGI')
    for name, counts, spacing in [('coarse', uint3(32,16,32), 240/31), ('dense', uint3(32,32,32), 120/31)]:
        p.set_properties({'gridCounts': counts, 'normalBias': .1/spacing, 'viewBias': .3/spacing,
                          'minFrontfaceDistance': .3/spacing, 'showProbes': False})
        for _ in range(512): renderFrame()
        m.frameCapture.baseFilename = 'coverage' if name=='coarse' else 'dense-coverage'
        m.frameCapture.capture()
        (O/(name+'-stats.json')).write_text(json.dumps(dict(p.stats), indent=2))
        p.set_properties({'showProbes': True})
        for _ in range(4): renderFrame()
        m.frameCapture.baseFilename = name+'-probes'
        m.frameCapture.capture()
except Exception:
    (O/'failure.txt').write_text(traceback.format_exc())
finally:
    exit()
