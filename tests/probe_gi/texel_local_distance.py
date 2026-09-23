"""Run headless/deferred. Uses isolated caches; set PROBE_TEXEL_LOAD=1 for fresh-process load."""
from falcor import *
from pathlib import Path
import json, math, os, traceback

out = Path('F:/build/probe-texel-local-validation')
out.mkdir(parents=True, exist_ok=True)
(out/'failure.txt').unlink(missing_ok=True)
cache = out / 'wall.shprobe'

def frames(n=1):
    for _ in range(n): renderFrame()

def bake():
    p.bake()
    for _ in range(400):
        frames()
        if p.ready: return
    raise AssertionError(p.status)

def read_moments():
    lines=cache.read_text().splitlines()
    assert lines[0]=='FALCOR_PROBE_SH 3'
    assert lines[6].split()[0]=='texel_local_uv_point'
    return [tuple(map(float,line.split())) for line in lines[lines.index('DISTANCE_MOMENTS')+1:]]

try:
    g=RenderGraph('TexelLocalValidation')
    g.addPass(createPass('VBufferRT',{'samplePattern':'Center'}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI',{'mode':'manual','cacheFile':str(cache),
        'gridCounts':uint3(2),'gridMin':float3(-.5,.3,-.5),'gridMax':float3(.5,1.5,.5),
        'samplesPerProbe':2,'samplesPerFrame':2,'maxBounces':1,'normalBias':0,
        'distanceResolution':128,'distanceSamplesPerTexel':4,'distanceBilinear':False}),'Probes')
    g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer'); g.addEdge('Visibility.viewW','Probes.viewW')
    g.addEdge('Probes.color','Display.src'); g.markOutput('Display.dst')
    m.addGraph(g); m.clock.pause(); m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene')
    frames(2); p=g.getPass('Probes')
    if os.environ.get('PROBE_TEXEL_LOAD'):
        p.configureBake({'samplesPerProbe':3,'samplesPerFrame':1}); frames()
        p.loadCache(); frames()
        assert p.ready and p.completedDistanceSamples==4 and 'loaded' in p.status,p.status
        p.inspectSurfacePoint(float3(-.1,.7,-.3),float3(0,1,0)); frames()
        expected=json.loads((out/'inspection.json').read_text())
        actual=p.debugInfo
        assert max(abs(actual['meanDistance'+str(i)]-expected['meanDistance'+str(i)]) for i in range(8))<1e-7
        (out/'load.json').write_text(json.dumps({'fresh_process_load':True}))
        exit()
    else:
        bake(); baseline=read_moments()
        assert p.completedSamples==2 and p.completedDistanceSamples==4
        assert all(math.isfinite(a) and math.isfinite(b) and 0<=a<=1 and a*a-2e-5<=b<=a+2e-5 for a,b in baseline)
    
        # Probe 0, texel (126,64): its entire angular footprint sees the wall x=-0.02.
        # Thus every independent sample MUST be near 0.48; no distant neighboring directions can enter.
        p.inspectSurfacePoint(float3(-.1,.7,-.3),float3(0,1,0)); frames(); info=p.debugInfo
        D=info['distanceMax']; stride=130; width=390
        mean=baseline[(64+1)*width+(126+1)][0]*D
        assert .48 <= mean <= .482,mean
    
        # The production P/Q path must fetch the exact cached texel, not bilinear moments.
        max_error=0
        for x in (-.1131,-.113099):
            p.inspectSurfacePoint(float3(x,.7317,-.3173),float3(0,1,0)); frames(); current=p.debugInfo
            for i in range(8):
                s=str(i); idx=current['probe'+s]; uv=current['queryTexel'+s]
                u,v=(uv.x,uv.y) if hasattr(uv,'x') else uv
                cached=baseline[((idx//3)*stride+1+v)*width+(idx%3)*stride+1+u][0]*D
                max_error=max(max_error,abs(current['meanDistance'+s]-cached))
                assert abs(current['meanDistance'+s]-cached)<2e-6
            if x==-.1131: first=current
            else:
                for i in range(8):
                    s=str(i)
                    assert list(first['queryTexel'+s])==list(current['queryTexel'+s])
                    assert first['meanDistance'+s]==current['meanDistance'+s]
    
        # Changing SH sample count and scheduling must not change distance samples.
        p.configureBake({'samplesPerProbe':3,'samplesPerFrame':1}); frames(); assert not p.ready
        bake(); repeated=read_moments()
        difference=max(abs(a-b) for x,y in zip(baseline,repeated) for a,b in zip(x,y))
        assert difference<2e-6,difference
        # Changing frame budget during a partial sweep preserves its sample range.
        p.configureBake({'samplesPerFrame':2}); p.bake(); frames(3)
        assert p.baking and p.completedDistanceSamples==0
        p.configureBake({'samplesPerFrame':64})
        for _ in range(100):
            frames()
            if p.ready: break
        assert p.ready,p.status
        live_batch_error=max(abs(a-b) for x,y in zip(baseline,read_moments()) for a,b in zip(x,y))
        assert live_batch_error<2e-6,live_batch_error
        saved=cache.read_bytes()
        # An interrupted distance sweep must not publish a cache.
        p.bake(); frames(4); assert p.baking and not p.ready
        p.cancelBake(); frames(); assert not p.baking and p.completedDistanceSamples==0
        assert cache.read_bytes()==saved
        cache.write_bytes(saved.replace(b'FALCOR_PROBE_SH 3',b'FALCOR_PROBE_SH 2',1))
        p.loadCache(); frames(); assert not p.ready and 'rebake required' in p.status,p.status
        cache.write_bytes(saved); p.loadCache(); frames(); assert p.ready
        p.inspectSurfacePoint(float3(-.1,.7,-.3),float3(0,1,0)); frames()
        (out/'inspection.json').write_text(json.dumps(p.debugInfo,indent=2))
        (out/'results.json').write_text(json.dumps({'resolution':128,'distance_samples_per_texel':4,
            'plane_texel_mean':mean,'plane_distance':.48,'point_fetch_max_error':max_error,
            'different_SH_and_batch_max_error':difference,'live_batch_change_max_error':live_batch_error,
            'checks':['finite moments','analytic wall footprint',
            'integer texel lookup','constant values within texel','SH-independent distance rays',
            'batch-independent samples','live batch changes','cancel preserves cache','reject old filtered cache','reload v3']},indent=2))
        print('Texel-local distance validation passed:',out)
        exit()

except Exception:
    (out/'failure.txt').write_text(traceback.format_exc())
    exit(1)
