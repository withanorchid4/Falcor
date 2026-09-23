"""Angular bake GPU/CPU analytic geometry checks, batch invariance and cache isolation."""
from falcor import *
from pathlib import Path
import json, math, os, traceback

out=Path('F:/build/probe-angular-validation'); out.mkdir(parents=True,exist_ok=True)
cache=out/'angular.shprobe'
load_only=os.environ.get('PROBE_ANGULAR_TEST')=='load'
props={'mode':'manual','cacheFile':str(cache),'gridCounts':uint3(2),
    'gridMin':float3(-.5,.3,-.5),'gridMax':float3(.5,1.5,.5),
    'samplesPerProbe':3,'samplesPerFrame':16,'maxBounces':1,
    'distanceBakeMode':'angular','distanceRaysPerProbe':64,'distanceExponent':50.,'distanceResolution':32}

def graph(name,settings):
    g=RenderGraph(name); g.addPass(createPass('VBufferRT',{'samplePattern':'Center'}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI',settings),'Probes')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer'); g.addEdge('Visibility.viewW','Probes.viewW')
    g.markOutput('Probes.color'); m.addGraph(g); m.setActiveGraph(g)
    return g,g.getPass('Probes')
def finish(p):
    for _ in range(400):
        renderFrame()
        if p.ready: return
    raise AssertionError(p.status)
def moments():
    lines=cache.read_text().splitlines(); start=lines.index('DISTANCE_MOMENTS')+1
    return [tuple(map(float,l.split())) for l in lines[start:]]
def hash32(x):
    x=((x^(x>>16))*0x7feb352d)&0xffffffff
    x=((x^(x>>15))*0x846ca68b)&0xffffffff
    return x^(x>>16)
def ray(probe,sample):
    seed=hash32(probe^0x9e3779b9)^hash32(sample)
    u=(hash32(seed)>>8)/16777216; v=(hash32(seed^0x68bc21eb)>>8)/16777216
    z=1-2*u; r=math.sqrt(max(0,1-z*z)); phi=2*math.pi*v
    return (r*math.cos(phi),r*math.sin(phi),z)
def oct_direction(x,y,n):
    x=2*(x+.5)/n-1; y=2*(y+.5)/n-1; z=1-abs(x)-abs(y)
    if z<0: x,y=(1-abs(y))*(1 if x>=0 else -1),(1-abs(x))*(1 if y>=0 else -1)
    length=math.sqrt(x*x+y*y+z*z); return (x/length,y/length,z/length)
def hit_distance(origin,direction):
    # All closed wall fixture probes are inside a room. Include the ceiling light plane.
    x,y,z=origin; dx,dy,dz=direction
    lo,hi=(-1,-.02) if x<0 else (.02,1)
    hits=[((hi if dx>0 else lo)-x)/dx if dx else float('inf'),
        ((2 if dy>0 else 0)-y)/dy if dy else float('inf'),
        ((1 if dz>0 else -1)-z)/dz if dz else float('inf')]
    if dy>0:
        t=(1.995-y)/dy; px,pz=x+t*dx,z+t*dz
        if abs(pz)<=.9 and (abs(px+.5)<=.45 or abs(px-.5)<=.45): hits.append(t)
    return min(hits)

try:
    g,p=graph('AngularValidation',props); m.clock.pause()
    m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene'); renderFrame(); renderFrame()
    if load_only:
        saved=cache.read_bytes(); p.loadCache(); renderFrame()
        assert p.ready and p.completedDistanceSamples==64 and cache.read_bytes()==saved
        (out/'load.json').write_text(json.dumps({'ready':True,'samples':p.completedDistanceSamples}))
    else:
        p.bake(); finish(p); baseline=moments(); saved=cache.read_bytes()
        assert saved.startswith(b'FALCOR_PROBE_SH 4')
        D=p.debugInfo['distanceMax']; n=32; tile=34; width=102
        max_error=0; tested=0; shared_contributions=0
        for probe in range(8):
            origin=(-.5+(probe&1),.3+1.2*((probe>>1)&1),-.5+((probe>>2)&1))
            rays=[ray(probe,s) for s in range(64)]
            distances=[min(1,hit_distance(origin,r)/D) for r in rays]
            for x,y in ((0,0),(8,8),(15,15),(23,14),(31,31),(3,27)):
                direction=oct_direction(x,y,n)
                weights=[max(0,sum(a*b for a,b in zip(direction,r)))**50 for r in rays]
                denom=sum(weights)
                expected=[sum(w*d**k for w,d in zip(weights,distances))/denom for k in (1,2)]
                actual=baseline[((probe//3)*tile+y+1)*width+(probe%3)*tile+x+1]
                error=max(abs(a-b) for a,b in zip(actual,expected)); max_error=max(max_error,error)
                assert error<2e-5,(probe,x,y,error,actual,expected)
                shared_contributions+=sum(w>1e-6 for w in weights)>1; tested+=1
        assert shared_contributions>20
        # Partial sweep changes: first distance frame updates only 4096 of 8192 texels.
        p.bake(); renderFrame(); renderFrame(); assert p.baking and p.completedDistanceSamples==0
        p.configureBake({'samplesPerFrame':3}); finish(p)
        second=moments(); batch_error=max(abs(a-b) for av,bv in zip(baseline,second) for a,b in zip(av,bv))
        assert batch_error<2e-6,batch_error
        cache.write_bytes(saved); p.loadCache(); renderFrame(); assert p.ready
        p.configureBake({'distanceExponent':100}); p.loadCache(); renderFrame(); assert not p.ready
        p.configureBake({'distanceBakeMode':'texelLocal'}); p.loadCache(); renderFrame(); assert not p.ready
        assert cache.read_bytes()==saved
        p.configureBake({'distanceBakeMode':'angular','distanceExponent':50}); p.bake(); renderFrame()
        p.cancelBake(); renderFrame(); assert not p.ready and not p.baking and cache.read_bytes()==saved
        p.loadCache(); renderFrame(); assert p.ready
        p.inspectSurfacePoint(float3(-.02,.8,.1),float3(-1,0,0)); renderFrame()
        d=p.debugInfo
        for i in range(8):
            assert math.isfinite(d['weight'+str(i)]) and math.isfinite(d['visibility'+str(i)])
        m.frameCapture.outputDir=str(out); m.frameCapture.baseFilename='angular'; m.frameCapture.capture()
        # Existing local cache still loads when the corresponding mode is explicitly selected.
        local=Path('F:/build/probe-texel-local-validation/wall.shprobe'); local_saved=local.read_bytes()
        g2,p2=graph('LocalCompatibility',dict(props,cacheFile=str(local),distanceBakeMode='texelLocal',
            distanceResolution=128,distanceSamplesPerTexel=4))
        renderFrame(); p2.loadCache(); renderFrame(); assert p2.ready and local.read_bytes()==local_saved
        (out/'results.json').write_text(json.dumps({'cpu_texels':tested,'max_moment_error':max_error,
            'multiple_ray_texels':shared_contributions,'batch_change_max_error':batch_error,
            'checks':['version4 angular bake','CPU weighted first/second moments','shared rays across texels',
            'mid-sweep batch change invariant','wrong mode/exponent rejected','cancel preserves cache',
            'version3 local load','finite inspection']},indent=2))
    print('Angular checks passed', 'load' if load_only else 'bake'); exit()
except Exception:
    (out/('load-failure.txt' if load_only else 'failure.txt')).write_text(traceback.format_exc()); exit(1)
