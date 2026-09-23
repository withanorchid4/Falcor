"""Mogwai GPU regressions and captures for smooth moments / hemisphere weighting."""
from falcor import *
from pathlib import Path
import os, sys, math, json, traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from probe_snapshot import replay, digest, write_json, json_value

out=Path(os.environ['PROBE_FIX_OUTPUT']); out.mkdir(parents=True,exist_ok=True)
case=Path('F:/build/probe-issues/20260924-021543-642825')
records=[]; max_moment_error=0.; max_normal_error=0.; max_weight_error=0.
def xyz(v): return list(v) if isinstance(v,(list,tuple)) else [v.x,v.y,v.z]
def frame(): renderFrame()
def capture(name,g,p):
    p.configureDebug({'enabled':False}); g.markOutput('Probes.color'); g.markOutput('Display.dst'); frame()
    dest=out/name; dest.mkdir(exist_ok=True)
    m.frameCapture.outputDir=str(dest); m.frameCapture.baseFilename='frame'; m.frameCapture.captureAllOutputs=False
    m.frameCapture.capture()
    write_json(dest/'settings.json',p.settings)
def reader(cache):
    lines=cache.read_text().splitlines(); fields=lines[6].split(); n=int(fields[1]); width=int(fields[4]); tile=n+2
    atlas=[tuple(map(float,s.split())) for s in lines[lines.index('DISTANCE_MOMENTS')+1:]]
    def sample(id,delta,smooth,bilinear):
        size=sum(abs(x) for x in delta); x,y,z=[x/size for x in delta]
        if z<0: x,y=(1-abs(y))*(1 if x>=0 else -1),(1-abs(x))*(1 if y>=0 else -1)
        u,v=x*.5+.5,y*.5+.5
        def fetch(x,y):
            if x<0: x,y=0,n-1-y
            elif x>=n: x,y=n-1,n-1-y
            if y<0: x,y=n-1-x,0
            elif y>=n: x,y=n-1-x,n-1
            return atlas[((id//(width//tile))*tile+y+1)*width+(id%(width//tile))*tile+x+1]
        if not bilinear: return fetch(min(n-1,int(u*n)),min(n-1,int(v*n)))
        x,y=u*n-.5,v*n-.5; ix,iy=math.floor(x),math.floor(y); tx,ty=x-ix,y-iy
        if smooth: tx,ty=tx*tx*(3-2*tx),ty*ty*(3-2*ty)
        taps=[fetch(ix,iy),fetch(ix+1,iy),fetch(ix,iy+1),fetch(ix+1,iy+1)]
        weights=[(1-tx)*(1-ty),tx*(1-ty),(1-tx)*ty,tx*ty]
        return [sum(t[k]*w for t,w in zip(taps,weights)) for k in (0,1)]
    return sample
def check(p,sample,tag):
    global max_moment_error,max_normal_error,max_weight_error
    info=p.debugInfo; settings=p.settings; P=xyz(info['position']); N=xyz(info['normal']); Q=xyz(info['samplePosition']); D=info['distanceMax']
    raw=[]
    for i in range(8):
        k=str(i); origin=xyz(info['position'+k]); delta=[q-o for q,o in zip(Q,origin)]
        mu,m2=sample(info['probe'+k],delta,settings['distanceSmooth'],settings['distanceBilinear'])
        error=max(abs(info['meanDistance'+k]-mu*D),abs(info['distanceVariance'+k]-max(0,m2-mu*mu)*D*D))
        assert error<3e-5,(tag,i,'moments',error); max_moment_error=max(max_moment_error,error)
        direction=[o-a for o,a in zip(origin,P)]; length=math.sqrt(sum(x*x for x in direction)); cosine=sum(n*x for n,x in zip(N,direction))/max(length,1e-8)
        wrap=max(0,min(1,cosine*.5+.5)); expected=wrap*wrap+.2
        if settings['normalHemisphere']:
            gate=max(0,min(1,cosine/.2)); expected*=gate*gate*(3-2*gate)
        if not settings['useNormalWeight']: expected=1.
        error=abs(info['normalWeight'+k]-expected); assert error<1e-5,(tag,i,'normal',error)
        max_normal_error=max(max_normal_error,error)
        raw.append(info['trilinearWeight'+k]*(expected*info['appliedVisibility'+k] if settings['useVisibility'] else 1))
        if settings['normalHemisphere'] and settings['useNormalWeight'] and settings['useVisibility'] and cosine<=0:
            assert info['weight'+k]==0,(tag,i,'back-facing weight')
    total=max(sum(raw),1e-4)
    for i in range(8):
        error=abs(info['weight'+str(i)]-raw[i]/total); assert error<2e-5,(tag,i,'weight',error)
        max_weight_error=max(max_weight_error,error)
    assert p.ready and not p.baking
    records.append({'tag':tag,'options':{k:settings[k] for k in ('distanceBilinear','distanceSmooth','normalHemisphere','useNormalWeight','useVisibility')},'sumRaw':sum(raw)})

try:
    replay(m,frame,case,out/'baseline')
    g=m.activeGraph; p=g.getPass('Probes'); sample=reader(case/'probes.shprobe'); original_hash=digest(case/'probes.shprobe')
    assert not p.settings['normalHemisphere'] and not p.settings['distanceSmooth']
    for name,options in [('smooth',{'distanceSmooth':True}),('hemisphere',{'distanceSmooth':False,'normalHemisphere':True}),
                         ('smooth_hemisphere',{'distanceSmooth':True,'normalHemisphere':True}),
                         ('restored',{'distanceSmooth':False,'normalHemisphere':False})]:
        p.configureVisibility(options); capture(name,g,p)
    samples=json.loads(Path('F:/build/probe-hard-edge-diagnosis-03/analysis/edge-samples.json').read_text())
    for region in ('upper','left','middle'):
        for side in ('a','b'):
            point=samples[region][0][side]; p.inspectSurfacePoint(float3(*point['position']),float3(*point['normal']))
            for smooth in (False,True):
                for hemisphere in (False,True):
                    p.configureVisibility({'distanceSmooth':smooth,'normalHemisphere':hemisphere}); frame(); check(p,sample,region+side)
    # Different room view, using the exact same loaded volume.
    m.scene.camera.position=float3(4.3,1.3,-2.5); m.scene.camera.target=float3(4.8,1,-.02); m.scene.camera.up=float3(0,1,0)
    for name,options in [('room-view-old',{'normalHemisphere':False,'distanceSmooth':False,'visibilityMode':'moments'}),
        ('room-view-fixed',{'normalHemisphere':True}),('room-view-ray',{'normalHemisphere':False,'visibilityMode':'rayTraced'})]:
        p.configureVisibility(options); capture(name,g,p)
    assert digest(case/'probes.shprobe')==original_hash
    # A fresh independent fixture avoids relying on old scene timestamps in historical test caches.
    cache=out/'fixture.shprobe'
    g=RenderGraph('HemisphereFixture'); g.addPass(createPass('VBufferRT',{'samplePattern':'Center'}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI',{'mode':'manual','cacheFile':str(cache),'gridCounts':uint3(2),
        'gridMin':float3(-.5,.3,-.5),'gridMax':float3(.5,1.5,.5),'samplesPerProbe':256,'samplesPerFrame':16,'maxBounces':3,
        'distanceResolution':32,'distanceSamplesPerTexel':16}),'Probes')
    g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer'); g.addEdge('Visibility.viewW','Probes.viewW'); g.addEdge('Probes.color','Display.src')
    g.markOutput('Display.dst'); m.addGraph(g); m.setActiveGraph(g)
    m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene'); frame(); frame(); p=g.getPass('Probes'); p.bake()
    for i in range(10000):
        frame()
        if p.ready or not p.baking: break
    assert p.ready,p.status
    cache_hash=digest(cache); sample=reader(cache); p.loadCache(); frame(); assert p.ready
    for name,options in [('fixture-old',{'normalHemisphere':False,'distanceSmooth':False}),('fixture-fixed',{'normalHemisphere':True}),
        ('fixture-smooth',{'distanceSmooth':True}),('fixture-ray',{'normalHemisphere':False,'distanceSmooth':False,'visibilityMode':'rayTraced'})]:
        p.configureVisibility(options); capture(name,g,p)
    p.configureVisibility({'visibilityMode':'moments'})
    for N in ((-1,0,0),(0,1,0),(.1,1,.3)):
        p.inspectSurfacePoint(float3(-.02,.8,.1),float3(*N))
        for options in ({'normalHemisphere':True,'distanceSmooth':True,'distanceBilinear':True},
            {'distanceBilinear':False},{'distanceBilinear':True,'useNormalWeight':False},
            {'useNormalWeight':True,'useVisibility':False},{'useVisibility':True}):
            p.configureVisibility(options); frame(); check(p,sample,'fixture')
    clone=createPass('TraditionalProbeGI',p.settings)
    assert clone.settings['normalHemisphere'] and clone.settings['distanceSmooth']
    assert digest(cache)==cache_hash
    write_json(out/'validation.json',{'probe_comparisons':len(records)*8,'max_moment_error':max_moment_error,
        'max_normal_error':max_normal_error,'max_weight_error':max_weight_error,'records':records,'cache_unchanged':True})
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8'); exit(1)
