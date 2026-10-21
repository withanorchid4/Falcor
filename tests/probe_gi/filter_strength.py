"""Fixed-budget GPU angular-kernel sweep for the saved wall artifact."""
from pathlib import Path
import json, math, os, shutil, sys, time, traceback
from falcor import float2

sys.path.insert(0, 'F:/scripts')
from probe_snapshot import replay, write_json, json_value, digest

case = Path('F:/build/probe-issues/20260924-104702-ae8fb0')
out = Path('F:/build/probe-filter-strength')
out.mkdir(parents=True, exist_ok=True)
source = json.loads((case/'snapshot.json').read_text())
records, timing, checks = {}, {}, {}


def cache_sh(path):
    lines = Path(path).read_text().splitlines()
    marker = lines.index('DISTANCE_MOMENTS')
    cfg = lines[6].split()
    assert cfg[0] == 'angular_cosine' and int(cfg[1]) == 14
    assert int(cfg[2]) == 2048 and float(cfg[3]) == 1.5
    assert tuple(map(int, cfg[4:6])) == (320, 320)
    for line in lines[marker+1:]:
        a, b = map(float, line.split())
        assert math.isfinite(a) and math.isfinite(b)
        assert 0 <= a <= 1 and 0 <= b <= a+2e-5 and b+2e-5 >= a*a
    return [float(v) for line in lines[7:marker] for v in line.split()]


try:
    original_hash = digest(case/'probes.shprobe')
    reference = Path('F:/build/probe-ddgi-alignment/verified/angular-range15/rebaked.shprobe')
    original_sh = cache_sh(reference)
    for exponent in (50, 25, 10, 5):
        tag = f'p{exponent}'
        options = {'distanceBakeMode':'angular', 'distanceResolution':14, 'distanceRaysPerProbe':2048,
                   'distanceExponent':float(exponent), 'distanceRangeScale':1.5, 'ddgiWeights':True,
                   'samplingMode':'full', 'distanceBilinear':True, 'distanceSmooth':False,
                   'useVisibility':True, 'visibilityMode':'moments', 'useNormalWeight':True}
        cached = reference if exponent == 50 else out/tag/'rebaked.shprobe'
        active = case
        rebake = not cached.is_file()
        if not rebake:
            active = out/(tag+'-case')
            active.mkdir(exist_ok=True)
            shutil.copyfile(case/'graph.py', active/'graph.py')
            shutil.copyfile(cached, active/'probes.shprobe')
            data = dict(source)
            data['cacheSha256'] = digest(active/'probes.shprobe')
            write_json(active/'snapshot.json', data)
        for f in (out/tag).glob('frame.*'): f.unlink()
        start = time.perf_counter()
        print('Starting angular exponent', exponent, 'rebake', rebake, flush=True)
        replay(m, renderFrame, active, out/tag, options, rebake=rebake)
        timing[tag] = {'replay_bake_capture_seconds':time.perf_counter()-start, 'rebaked':rebake}
        p = m.activeGraph.getPass('Probes')
        settings = p.settings
        assert p.ready, p.status
        for key, val in options.items(): assert settings[key] == val, (key, settings[key], val)
        for key in ('normalBias','viewBias','gridCounts','samplesPerProbe','maxBounces'):
            assert json_value(settings[key]) == source['probeSettings'][key], key
        sh = cache_sh(p.cacheFile)
        assert len(sh) == len(original_sh)
        err = max(abs(a-b) for a,b in zip(sh, original_sh))
        assert err == 0., err
        checks[tag] = {'sh_max_error':err,'settings':json_value(settings),'cache':str(p.cacheFile)}
        points = []
        for x, y in ((520,417),(521,417),(1057,192),(1058,192),(1092,325),(1092,326)):
            p.pickSurface(float2((x+.5)/1280,(y+.5)/720))
            renderFrame()
            info = p.debugInfo
            assert info['valid']
            weights = []
            for i in range(8):
                k = str(i)
                d, mu, var = info['queryDistance'+k],info['meanDistance'+k],info['distanceVariance'+k]
                v = 1. if d <= mu else (var/(var+(d-mu)**2))**3
                assert abs(v-info['visibility'+k]) < .002
                v = max(.05, info['visibility'+k])
                assert abs(v-info['appliedVisibility'+k]) < 1e-6
                support = max(info['normalWeight'+k]*v,1e-6)
                support *= min(support/.2,1.)**2
                weights.append(support*info['trilinearWeight'+k])
            for i, value in enumerate(weights):
                assert abs(value/sum(weights)-info['weight'+str(i)]) < 2e-5
            points.append({'pixel':[x,y],'data':json_value(info)})
        records[tag] = points
        write_json(out/'progress.json',{'points':records,'timing':timing,'checks':checks})
        print('Completed', tag, timing[tag], flush=True)
    assert digest(case/'probes.shprobe') == original_hash
    write_json(out/'result.json',{'points':records,'timing':timing,'checks':checks,'snapshot_cache_unchanged':True})
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    exit(1)
