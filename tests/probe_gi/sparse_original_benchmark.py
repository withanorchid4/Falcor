"""Measure the installed pre-sparse plugin, not just the new full-resolution branch."""
from pathlib import Path
import os, sys, traceback
sys.path.insert(0,'F:/scripts')
from probe_snapshot import replay, write_json, verify

out=Path(os.environ['PROBE_ORIGINAL_OUTPUT']);out.mkdir(exist_ok=False)
try:
    case=Path('F:/build/probe-leak-fix/local128-case')
    replay(m,renderFrame,case,out/'baseline',{'viewBias':.05,'varianceBase':1e-6})
    g=m.activeGraph;p=g.getPass('Probes')
    for view in ('wall','room'):
        if view=='room':
            m.loadScene(verify(case)['scene']);renderFrame();renderFrame();p.loadCache();renderFrame();assert p.ready
        g.markOutput('Probes.color');g.markOutput('Display.dst')
        m.profiler.enabled=True
        for turn in range(3):
            for backend in (('moments','rayTraced') if turn%2==0 else ('rayTraced','moments')):
                p.configureVisibility({'visibilityMode':backend})
                for _ in range(45):renderFrame()
                m.profiler.start_capture()
                for _ in range(151):renderFrame()
                write_json(out/f'timing-{view}-{backend}-0-{turn}.json',m.profiler.end_capture())
        m.profiler.enabled=False
    write_json(out/'validation.json',{'completed':True})
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');exit(1)
