"""Smoke-test the installed sparse plugin and old-snapshot override compatibility."""
from pathlib import Path
import sys, traceback
sys.path.insert(0,'F:/scripts')
from probe_snapshot import replay, capture, write_json
out=Path('F:/build/probe-sparse-installed')
out.mkdir(exist_ok=False)
try:
    case=Path('F:/build/probe-leak-fix/local128-case')
    replay(m,renderFrame,case,out/'wall-moments-4',{'viewBias':.05,'varianceBase':1e-6,
        'samplingMode':'screenSparse','sparseStride':4})
    g=m.activeGraph;p=g.getPass('Probes')
    for backend,stride in [('moments',0),('rayTraced',4),('rayTraced',0)]:
        p.configureVisibility({'visibilityMode':backend})
        p.configureSampling({'samplingMode':'screenSparse' if stride else 'full'})
        capture(m,renderFrame,g,p,out/f'wall-{backend}-{stride}')
        assert p.ready and not p.baking
    write_json(out/'validation.json',{'ready':p.ready,'old_snapshot_overrides':True,'settings':p.settings})
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');exit(1)
