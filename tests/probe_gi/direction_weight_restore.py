"""Run inside Mogwai: compare GPU inspection weights against the restored formula."""
from pathlib import Path
import json, math, sys, traceback
from falcor import createPass, float3
sys.path.insert(0, 'F:/scripts')
from probe_snapshot import replay, capture, write_json, digest

out = Path('F:/build/probe-direction-restore/validation')
out.mkdir(parents=True, exist_ok=False)

def xyz(v):
    return list(v) if isinstance(v, (tuple, list)) else [v.x, v.y, v.z]

try:
    assert not createPass('TraditionalProbeGI', {'normalHemisphere': True}).settings['normalHemisphere']
    case = Path('F:/build/probe-leak-fix/local128-case')
    before = digest(case / 'probes.shprobe')
    replay(m, renderFrame, case, out / 'initial', {'normalHemisphere': True, 'samplingMode': 'full'})
    g = m.activeGraph
    p = g.getPass('Probes')
    p.configureVisibility({'useVisibility': True, 'useNormalWeight': True, 'normalHemisphere': True})
    assert not p.settings['normalHemisphere']
    points = json.loads(Path('F:/build/probe-hard-edge-diagnosis-03/analysis/edge-samples.json').read_text())
    records = []
    max_error = 0.0
    back_count = 0
    for region in ('upper', 'left', 'middle'):
        for side in ('a', 'b'):
            point = points[region][0][side]
            p.inspectSurfacePoint(float3(*point['position']), float3(*point['normal']))
            renderFrame()
            info = p.debugInfo
            assert info['valid']
            pos, normal = xyz(info['position']), xyz(info['normal'])
            for i in range(8):
                key = str(i)
                delta = [a-b for a,b in zip(xyz(info['position'+key]), pos)]
                length = max(math.sqrt(sum(x*x for x in delta)), 1e-8)
                cosine = sum(a*b for a,b in zip(normal, delta)) / length
                expected = max(0, min(1, cosine*.5+.5))**2 + .2
                actual = info['normalWeight'+key]
                max_error = max(max_error, abs(expected-actual))
                assert abs(expected-actual) < 1e-5, (region, side, i, expected, actual)
                if cosine <= 0:
                    back_count += 1
                    assert actual >= .2-1e-6
                records.append({'region':region, 'side':side, 'probe':info['probe'+key],
                                'cosine':cosine, 'directionWeight':actual, 'weight':info['weight'+key]})
    assert back_count > 0
    for backend in ('moments', 'rayTraced'):
        p.configureVisibility({'visibilityMode':backend})
        for mode in ('full', 'screenSparse'):
            p.configureSampling({'samplingMode':mode, 'sparseStride':4})
            capture(m, renderFrame, g, p, out / (backend+'-'+mode))
            assert p.ready and not p.baking
    assert digest(case / 'probes.shprobe') == before
    write_json(out/'result.json', {'max_direction_weight_error':max_error,
        'back_facing_samples':back_count, 'cache_unchanged':True, 'samples':records})
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
    exit(1)
