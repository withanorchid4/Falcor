"""GPU cache roundtrip, snapshot serialization, legacy and ray-backend checks."""
from pathlib import Path
import json, sys, traceback
sys.path.insert(0,'F:/scripts')
from probe_snapshot import replay, capture, save_snapshot, write_json, digest

out=Path('F:/build/probe-wicked-alignment')
case=Path('F:/build/probe-issues/20260924-104702-ae8fb0')
try:
    options=json.loads((out/'hitbias/render.json').read_text())['overrides']
    # This isolated case is prepared by the driver; it contains the new v5 cache.
    replay(m,renderFrame,out/'hitbias-case',out/'roundtrip',options)
    p=m.activeGraph.getPass('Probes')
    assert p.ready
    saved=save_snapshot(m,renderFrame,out/'snapshots')
    replay(m,renderFrame,saved,out/'saved-snapshot-replay')
    p=m.activeGraph.getPass('Probes');g=m.activeGraph
    p.configureVisibility({'visibilityMode':'rayTraced','wickedWeights':True})
    capture(m,renderFrame,g,p,out/'ray-wicked-on')
    p.configureVisibility({'wickedWeights':False})
    capture(m,renderFrame,g,p,out/'ray-wicked-off')
    # Matching-cache load must reject changed kernel metadata.
    p.configureBake({'distanceHitBias':0.})
    p.loadCache();renderFrame()
    assert not p.ready and 'kernel mismatch' in p.status, p.status
    # An old v4 cache and old weights must still reproduce exactly.
    old=Path('F:/build/probe-filter-strength/p50-case')
    settings=json.loads(Path('F:/build/probe-filter-strength/p50/render.json').read_text())['overrides']
    replay(m,renderFrame,old,out/'legacy-p50',settings)
    write_json(out/'regression.json',{'v5_loaded':True,'v5_snapshot_roundtrip':True,
        'mismatched_kernel_rejected':True,'legacy_v4_loaded':True,'snapshot':str(saved)})
    exit()
except Exception:
    (out/'regression-failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    exit(1)
