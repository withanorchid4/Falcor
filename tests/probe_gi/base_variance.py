"""Check additive variance against GPU inspection using isolated constant-moment caches."""
from falcor import *
from pathlib import Path
import json, math, traceback

out = Path('F:/build/probe-base-variance-validation'); out.mkdir(parents=True, exist_ok=True)
source = Path('F:/build/probe-texel-local-validation/wall.shprobe')
original = source.read_bytes(); cache = out/'test.shprobe'
lines = original.decode().splitlines(); marker = lines.index('DISTANCE_MOMENTS')
header = lines[:marker+1]; header[6] = 'texel_local_uv_point 4 4 2 18 18'

def write_moments(mean, variance):
    row = f'{mean:.12g} {mean*mean+variance:.12g}\n'
    cache.write_text('\n'.join(header)+'\n'+row*(18*18))

try:
    write_moments(0,0)
    g = RenderGraph('BaseVarianceValidation')
    g.addPass(createPass('VBufferRT', {'samplePattern':'Center'}), 'Visibility')
    props = {'mode':'manual', 'cacheFile':str(cache), 'gridCounts':uint3(2),
        'gridMin':float3(-.5,.3,-.5), 'gridMax':float3(.5,1.5,.5),
        'samplesPerProbe':3, 'samplesPerFrame':1, 'maxBounces':1,
        'distanceResolution':4, 'distanceSamplesPerTexel':4, 'normalBias':0, 'viewBias':0}
    g.addPass(createPass('TraditionalProbeGI',props),'Probes')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer'); g.addEdge('Visibility.viewW','Probes.viewW')
    g.markOutput('Probes.color'); m.addGraph(g); m.clock.pause()
    m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene'); renderFrame(); renderFrame()
    p=g.getPass('Probes'); assert abs(p.settings['varianceBase']-1e-6)<1e-12
    clone=createPass('TraditionalProbeGI',dict(props,varianceFloor=2e-6))
    assert abs(clone.settings['varianceBase']-2e-6)<1e-12
    clone=createPass('TraditionalProbeGI',dict(props,varianceFloor=2e-6,varianceBase=3e-6))
    assert abs(clone.settings['varianceBase']-3e-6)<1e-12
    p.configureVisibility({'varianceFloor':2e-6,'varianceBase':1e-6})
    cases=[]; max_error=0.; max_old_difference=0.
    for mean,variance,query in ((0,0,0),(0,0,.001),(.125,0,.12),(.125,0,.125),
        (.125,0,.126),(.125,1e-7,.126),(.125,1e-6,.126),(.125,1e-4,.126)):
        write_moments(mean,variance); saved=cache.read_bytes(); p.loadCache(); renderFrame()
        assert p.ready,p.status
        D=p.debugInfo['distanceMax']
        p.inspectSurfacePoint(float3(-.5,.3,-.5+query*D),float3(0,1,0))
        for bilinear in (False,True):
            p.configureVisibility({'distanceBilinear':bilinear}); renderFrame(); d=p.debugInfo
            assert p.ready and not p.baking and p.completedSamples==3 and p.completedDistanceSamples==4
            for i in range(8):
                s=str(i); delta=max(d['queryDistance'+s]/D-d['meanDistance'+s]/D,0)
                raw=d['distanceVariance'+s]/(D*D); base=d['varianceBase']
                expected=((raw+base)/(raw+base+delta*delta))**3
                actual=d['visibility'+s]; error=abs(actual-expected)
                assert math.isfinite(actual) and error<3e-5,(mean,variance,query,i,actual,expected)
                assert math.isfinite(d['weight'+s])
                max_error=max(max_error,error)
                old=max(raw,base); old=(old/(old+delta*delta))**3
                max_old_difference=max(max_old_difference,abs(actual-old))
            cases.append({'mean':mean,'variance':variance,'query':query,'bilinear':bilinear,'probe0_V':d['visibility0']})
            if query<=mean: assert d['visibility0']==1
        assert cache.read_bytes()==saved
    assert max_old_difference>.1  # Detect retaining max(var,base) by mistake.
    assert source.read_bytes()==original
    (out/'results.json').write_text(json.dumps({'max_error':max_error,'max_difference_from_old_floor':max_old_difference,
        'comparisons':len(cases)*8,'cases':cases,'checks':['zero variance and equality finite',
        'below/at/above base variance','Point/Bilinear additive formula','legacy alias/new key precedence',
        'cache and bake state unchanged']},indent=2))
    print('Base variance checks passed:',out); exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc()); exit(1)
