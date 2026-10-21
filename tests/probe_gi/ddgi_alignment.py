"""Mogwai headless: fixed-camera DDGI ablation and GPU weight validation."""
from pathlib import Path
import json, math, os, sys, traceback
from falcor import createPass, float2

sys.path.insert(0, 'F:/scripts')
from probe_snapshot import replay, capture, write_json, json_value, digest

out = Path(os.environ.get('PROBE_DDGI_OUTPUT', 'F:/build/probe-ddgi-alignment'))
out.mkdir(parents=True, exist_ok=True)
case = Path('F:/build/probe-issues/20260924-104702-ae8fb0')
records = {}


def inspect(p, tag, ddgi=False, ray=False):
    points = []
    for x, y in ((520, 417), (521, 417), (870, 185), (870, 186), (840, 400), (841, 400)):
        p.pickSurface(float2((x+.5)/1280, (y+.5)/720))
        renderFrame()
        info = p.debugInfo
        assert info['valid'], (tag, x, y)
        weights = []
        for i in range(8):
            k = str(i)
            actual = info['appliedVisibility'+k]
            if ray:
                assert actual in (0., 1.), (tag, x, y, k, 'nonbinary', actual)
                # 'visible' is a separate nearest-hit diagnostic; actual segment
                # visibility uses the production shadow any-hit path.
                if actual == 0.:
                    if info['weight'+k] != 0: write_json(out/'ray-failure-data.json',json_value(info))
                    assert info['weight'+k] == 0, (tag,x,y,k,actual,info['weight'+k])
            if ddgi and not ray:
                d, mean, var = info['queryDistance'+k], info['meanDistance'+k], info['distanceVariance'+k]
                v = 1. if d <= mean else (var/(var+(d-mean)**2))**3
                assert abs(v-info['visibility'+k]) < .002, (tag, k, v, info['visibility'+k])
                assert abs(actual-max(.05, info['visibility'+k])) < 1e-6
                support = max(info['normalWeight'+k] * actual, 1e-6)
                support *= min(support/.2, 1.)**2
                weights.append(support * info['trilinearWeight'+k])
        if weights:
            total = sum(weights)
            for i, value in enumerate(weights):
                assert abs(value/total-info['weight'+str(i)]) < 2e-5
        points.append({'pixel':[x,y], 'data':json_value(info)})
    records[tag] = points


def cache_data(path):
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    marker = lines.index('DISTANCE_MOMENTS')
    sh = [float(v) for line in lines[7:marker] for v in line.split()]
    for line in lines[marker+1:]:
        a, b = map(float, line.split())
        assert math.isfinite(a) and math.isfinite(b)
        assert 0 <= a <= 1 and 0 <= b <= a+2e-5 and b+2e-5 >= a*a
    return sh


try:
    source_hash = digest(case/'probes.shprobe')
    source = json.loads((case/'snapshot.json').read_text())
    preset = createPass('TraditionalProbeGI', {'normalBias':.073,'viewBias':.12,'samplingMode':'screenSparse','sparseStride':4})
    preset.applyDDGIPreset()
    props = preset.settings
    assert props['distanceResolution'] == 14 and props['distanceBakeMode'] == 'angular'
    assert props['ddgiWeights'] and props['distanceRangeScale'] == 1.5
    assert abs(props['normalBias']-.073) < 1e-7 and abs(props['viewBias']-.12) < 1e-7
    assert props['samplingMode'] == 'screenSparse' and props['sparseStride'] == 4
    assert createPass('TraditionalProbeGI', props).settings['ddgiWeights']
    original_sh = cache_data(case/'probes.shprobe')
    sh_errors = {}
    variants = [
        ('baseline', {'ddgiWeights':False}, False),
        ('angular-only', {'distanceBakeMode':'angular','distanceRaysPerProbe':2048,'distanceExponent':50.,'ddgiWeights':False}, True),
        ('angular-range15', {'distanceBakeMode':'angular','distanceRaysPerProbe':2048,'distanceExponent':50.,'distanceRangeScale':1.5,'ddgiWeights':False}, True),
    ]
    for tag, options, rebake in variants:
        # Reuse completed isolated bakes when resuming a diagnostic run.
        if rebake and (out/tag/'rebaked.shprobe').is_file():
            import shutil
            resume = out/(tag+'-case')
            resume.mkdir(exist_ok=True)
            shutil.copyfile(case/'graph.py',resume/'graph.py')
            shutil.copyfile(out/tag/'rebaked.shprobe',resume/'probes.shprobe')
            metadata = dict(source)
            metadata['cacheSha256'] = digest(resume/'probes.shprobe')
            write_json(resume/'snapshot.json',metadata)
            active_case = resume
            rebake = False
        else: active_case = case
        # Captures get a fresh filename set on repeated diagnostic runs.
        for f in (out/tag).glob('frame.*'): f.unlink()
        replay(m, renderFrame, active_case, out/tag, options, rebake=rebake)
        p = m.activeGraph.getPass('Probes')
        assert p.settings['distanceResolution'] == 14
        for key in ('normalBias', 'viewBias'):
            assert p.settings[key] == source['probeSettings'][key]
        baked_sh = cache_data(p.cacheFile)
        sh_errors[tag] = max(abs(a-b) for a,b in zip(original_sh, baked_sh))
        assert sh_errors[tag] < 1e-5, sh_errors
        inspect(p, tag)
    g = m.activeGraph
    for tag in ('ddgi-weights','restored','ray-ddgi-on','ray-reference','ddgi-sparse4','ddgi-reloaded'):
        for f in (out/tag).glob('frame.*'): f.unlink()
    p.configureVisibility({'ddgiWeights':True})
    capture(m, renderFrame, g, p, out/'ddgi-weights')
    inspect(p, 'ddgi-weights', ddgi=True)
    p.configureVisibility({'ddgiWeights':False})
    capture(m, renderFrame, g, p, out/'restored')
    p.configureVisibility({'ddgiWeights':True,'visibilityMode':'rayTraced'})
    capture(m, renderFrame, g, p, out/'ray-ddgi-on')
    inspect(p, 'ray-ddgi-on', ddgi=True, ray=True)
    p.configureVisibility({'ddgiWeights':False})
    capture(m, renderFrame, g, p, out/'ray-reference')
    p.configureVisibility({'ddgiWeights':True,'visibilityMode':'moments'})
    p.configureSampling({'samplingMode':'screenSparse','sparseStride':4})
    capture(m, renderFrame, g, p, out/'ddgi-sparse4')
    p.configureSampling({'samplingMode':'full'})
    # Cache roundtrip with DDGI weighting: cached moments are independent of runtime mode.
    p.loadCache(); renderFrame()
    assert p.ready, p.status
    capture(m, renderFrame, g, p, out/'ddgi-reloaded')
    write_json(out/'ddgi-settings.json',json_value(p.settings))
    assert digest(case/'probes.shprobe') == source_hash
    write_json(out/'result.json', {'checks':'preset/serialization/bias/resolution/cache/weights/ray/sparse',
        'sh_max_errors':sh_errors,'snapshot_cache_unchanged':True,'points':records})
    if (out/'failure.txt').exists(): (out/'failure.txt').unlink()
    exit()
except Exception:
    write_json(out/'partial-points.json',records)
    (out/'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
    exit(1)
