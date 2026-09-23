"""GPU reference rays: analytic wall distances, hard occlusion, mode/cache stability, MISS and endpoints."""
from falcor import *
from pathlib import Path
import json, math, traceback, uuid

out = Path('F:/build/probe-ray-validation') / uuid.uuid4().hex[:8]
out.mkdir(parents=True)

def frames(n=1):
    for _ in range(n): renderFrame()

def xyz(v): return (v.x,v.y,v.z) if hasattr(v,'x') else tuple(v)

def capture(tag):
    m.frameCapture.outputDir = str(out)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()

def slab(origin, direction, center, size):
    lo, hi = -float('inf'), float('inf')
    for o,d,c,s in zip(origin,direction,center,size):
        a,b = c-s*.5,c+s*.5
        if abs(d)<1e-10:
            if not a<=o<=b: return float('inf')
        else:
            t0,t1 = sorted(((a-o)/d,(b-o)/d))
            lo,hi = max(lo,t0),min(hi,t1)
    if hi<max(0,lo): return float('inf')
    return lo if lo>=0 else hi

boxes = [((0,-.02,0),(2.08,.04,2.08)), ((0,2.02,0),(2.08,.04,2.08)),
         ((-1.02,1,0),(.04,2,2.08)), ((1.02,1,0),(.04,2,2.08)),
         ((0,1,-1.02),(2.08,2,.04)), ((0,1,1.02),(2.08,2,.04)), ((0,1,0),(.04,2,2.08))]

def expected_hit(origin, point):
    delta = [b-a for a,b in zip(origin,point)]
    length = math.sqrt(sum(v*v for v in delta))
    direction = [v/length for v in delta]
    hit = min(slab(origin,direction,c,s) for c,s in boxes)
    if direction[1] > 1e-10:
        t = (1.995-origin[1])/direction[1]
        x,z = origin[0]+t*direction[0],origin[2]+t*direction[2]
        if t>=0 and abs(z)<=.9 and (abs(x+.5)<=.45 or abs(x-.5)<=.45): hit=min(hit,t)
    return hit

try:
    g = RenderGraph('ProbeRayValidation')
    g.addPass(createPass('VBufferRT', {'samplePattern':'Center'}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI', {'mode':'manual','cacheFile':str(out/'test.shprobe'),
        'gridCounts':uint3(2),'gridMin':float3(-.5,.3,-.5),'gridMax':float3(.5,1.5,.5),
        'samplesPerProbe':256,'samplesPerFrame':64,'maxBounces':1,'normalBias':.02}),'Probes')
    g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer'); g.addEdge('Visibility.viewW','Probes.viewW')
    g.addEdge('Probes.color','Display.src')
    g.markOutput('Display.dst'); g.markOutput('Probes.probeLighting')
    m.addGraph(g); m.clock.pause()
    m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene')
    frames(2); p=g.getPass('Probes'); p.bake(); frames(5); assert p.ready,p.status
    saved=Path(p.cacheFile).read_bytes()
    capture('wall-moments')
    cases=[]; blocked_count=0; visible_count=0; max_error=0
    for uv in ((.35,.65),(.5,.65),(.65,.65),(.4,.8),(.6,.8),(.5,.4)):
        p.configureVisibility({'visibilityMode':'moments'})
        p.pickSurface(float2(*uv)); frames(); a=p.debugInfo
        assert a['valid']
        p.configureVisibility({'visibilityMode':'rayTraced'}); frames(); b=p.debugInfo
        for i in range(8):
            s=str(i); origin=xyz(b['position'+s])
            for target,field in (('samplePosition','queryHitDistance'),('position','surfaceHitDistance')):
                expected=expected_hit(origin,xyz(b[target]))
                actual=b[field+s]
                error=abs(actual-expected)
                assert error < 5e-4,(uv,i,field,actual,expected)
                max_error=max(max_error,error)
            assert a['meanDistance'+s] == b['meanDistance'+s]
            assert a['visibility'+s] == b['visibility'+s]
            assert b['appliedVisibility'+s] == b['rayVisibility'+s]
            if not b['visible'+s]:
                assert b['weight'+s]==0,(uv,i,b)
                blocked_count+=1
            elif b['trilinearWeight'+s]>0:
                assert b['weight'+s]>0
                visible_count+=1
        cases.append({'uv':uv,'blocked_weight_moments':sum(a['weight'+str(i)] for i in range(8) if not b['visible'+str(i)]),
                      'blocked_weight_rays':sum(b['weight'+str(i)] for i in range(8) if not b['visible'+str(i)])})
    assert blocked_count>0 and visible_count>0
    original = p.debugInfo
    p.inspectSurfacePoint(float3(*xyz(original['position'])),float3(*xyz(original['normal'])))
    frames(); restored = p.debugInfo
    assert max(abs(restored['weight'+str(i)]-original['weight'+str(i)]) for i in range(8))<1e-6
    assert max(abs(restored['queryHitDistance'+str(i)]-original['queryHitDistance'+str(i)]) for i in range(8))<1e-6
    p.configureDebug({'enabled':False}); frames(); capture('wall-rays')
    p.configureVisibility({'useVisibility':False}); frames(); capture('wall-off')
    p.configureVisibility({'useVisibility':True,'visibilityMode':'moments'}); frames(); capture('wall-moments-again')
    assert p.ready and p.completedSamples==256 and Path(p.cacheFile).read_bytes()==saved
    try: p.configureVisibility({'visibilityMode':'typo','useVisibility':False})
    except Exception: pass
    else: raise AssertionError('Invalid mode accepted')
    assert p.properties['visibilityMode']=='moments' and p.properties['useVisibility']

    m.loadScene('F:/tests/probe_gi/visibility_open.pyscene'); frames()
    p.configureBake({'gridMin':float3(-.5,.05,-.5),'gridMax':float3(.5,.55,.5)})
    p.configureDebug({'normalBias':1.0}); frames(); p.bake(); frames(5); assert p.ready
    p.configureVisibility({'visibilityMode':'rayTraced'})
    p.pickSurface(float2(.5,.5)); frames(); b=p.debugInfo
    assert b['valid'] and xyz(b['normal'])[1]>.9,b
    misses=0
    for i in range(8):
        s=str(i)
        assert abs(b['surfaceHitDistance'+s]-b['surfaceDistance'+s])<5e-4
        if b['queryHitDistance'+s]<0:
            misses+=1
            assert b['rayVisibility'+s]==1
    assert misses>=4,b
    p.configureDebug({'normalBias':0}); frames(); b=p.debugInfo
    assert all(b['rayVisibility'+str(i)]==1 for i in range(8)), b
    assert all(abs(b['queryHitDistance'+str(i)]-b['queryDistance'+str(i)])<5e-4 for i in range(8))
    (out/'results.json').write_text(json.dumps({'analytic_hit_max_error':max_error,'blocked_corners':blocked_count,
        'visible_contributing_corners':visible_count,'misses':misses,'cases':cases,
        'checks':['nearest hit vs analytic boxes','blocked weights zero','visible weights retained',
                  'cached means unchanged by mode','mode preserves Ready/samples/cache','invalid mode atomic',
                  'restore identical world pick','MISS explicit','surface endpoints excluded']},indent=2))
    print('Probe ray checks passed: '+str(out))
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc())
    raise
