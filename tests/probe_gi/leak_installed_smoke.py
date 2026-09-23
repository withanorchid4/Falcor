"""Verify the installed plugin, preview defaults and automatically named Room cache."""
from falcor import *
from pathlib import Path
import json, sys, traceback
sys.path.insert(0, 'F:/scripts')
from probe_snapshot import verify, restore, write_json, json_value, capture

out = Path('F:/build/probe-leak-installed')
out.mkdir(exist_ok=False)
try:
    data = verify(Path('F:/build/probe-issues/20260924-021543-642825'))
    exec(compile(Path('F:/scripts/TraditionalProbeGI.py').read_text(), 'TraditionalProbeGI.py', 'exec'))
    g = TraditionalProbeGI
    m.setActiveGraph(g)
    m.loadScene(data['scene'])
    m.resizeFrameBuffer(*data['resolution'])
    m.clock.time = data['time']
    m.clock.pause()
    m.scene.animated = data['animated']
    restore(m.scene.camera, data['camera'])
    settings = m.scene.renderSettings
    restore(settings, data['renderSettings'])
    m.scene.renderSettings = settings
    env = data['environment']
    if env:
        m.scene.setEnvMap(env['path'])
        restore(m.scene.envMap, env['properties'])
    else:
        m.scene.envMap = None
    for kind in ('materials', 'lights'):
        for obj, record in zip(getattr(m.scene, kind), data[kind]):
            assert obj.name == record['name']
            restore(obj, record['properties'])
    renderFrame()
    renderFrame()
    p = g.getPass('Probes')
    assert p.settings['cacheFile'] == ''
    assert p.settings['distanceResolution'] == 128
    assert p.settings['distanceSamplesPerTexel'] == 32
    p.loadCache()
    renderFrame()
    assert p.ready and not p.baking, p.status
    assert Path(p.cacheFile).name.endswith('-texel-local-r128-s32.shprobe')
    capture(m, renderFrame, g, p, out)
    write_json(out/'result.json', {'ready': p.ready, 'cache': str(p.cacheFile), 'settings': json_value(p.settings)})
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
    exit(1)
