"""GPU versus CPU moment interpolation, including folded edges, with an existing v3 bake."""
from falcor import *
from pathlib import Path
import json, math, traceback, hashlib

out=Path('F:/build/probe-bilinear-validation'); out.mkdir(parents=True,exist_ok=True)
source=Path('F:/build/probe-texel-local-validation/wall.shprobe')
cache=out/'test.shprobe'; original=source.read_bytes(); cache.write_bytes(original)

def frames(): renderFrame()
def xyz(v): return list(v) if isinstance(v,(list,tuple)) else [v.x,v.y,v.z]
def decode(u,v):
    x,y=u*2-1,v*2-1; z=1-abs(x)-abs(y)
    if z<0: x,y=(1-abs(y))*(1 if x>=0 else -1),(1-abs(x))*(1 if y>=0 else -1)
    return [x,y,z]
def encode(delta):
    size=sum(abs(x) for x in delta); x,y,z=[x/size for x in delta]
    if z<0: x,y=(1-abs(y))*(1 if x>=0 else -1),(1-abs(x))*(1 if y>=0 else -1)
    return (x*.5+.5,y*.5+.5)
def wrap(x,y,n):
    if x<0: x,y=0,n-1-y
    elif x>=n: x,y=n-1,n-1-y
    if y<0: x,y=n-1-x,0
    elif y>=n: x,y=n-1-x,n-1
    return x,y

try:
    g=RenderGraph('BilinearValidation')
    g.addPass(createPass('VBufferRT',{'samplePattern':'Center'}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI',{'mode':'manual','cacheFile':str(cache),
        'gridCounts':uint3(2),'gridMin':float3(-.5,.3,-.5),'gridMax':float3(.5,1.5,.5),
        'samplesPerProbe':3,'samplesPerFrame':1,'maxBounces':1,'normalBias':0,
        'distanceResolution':128,'distanceSamplesPerTexel':4}),'Probes')
    g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer'); g.addEdge('Visibility.viewW','Probes.viewW')
    g.addEdge('Probes.color','Display.src'); g.markOutput('Display.dst'); m.addGraph(g)
    m.clock.pause(); m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene'); frames(); frames()
    p=g.getPass('Probes'); p.loadCache(); frames()
    assert p.ready and p.settings['distanceBilinear'] and p.completedDistanceSamples==4
    assert cache.read_bytes()==original

    # Synthetic discontinuities expose wrong tile/padding accesses; header/SH stay from a real v3 bake.
    lines=cache.read_text().splitlines(); marker=lines.index('DISTANCE_MOMENTS')
    n=128; tile=130; width=390; height=390
    texels=[(1.,1.) for _ in range(width*height)]
    for idx in range(8):
        for y in range(n):
            for x in range(n):
                mean=.03*(idx+1)+.1*x/n+.2*y/n
                texels[((idx//3)*tile+y+1)*width+(idx%3)*tile+x+1]=(mean,mean*mean+.001)
    cache.write_text('\n'.join(lines[:marker+1])+ '\n' + '\n'.join(f'{a:.9g} {b:.9g}' for a,b in texels)+'\n')
    saved=cache.read_bytes(); p.loadCache(); frames(); assert p.ready
    def fetch(idx,x,y):
        x,y=wrap(x,y,n)
        return texels[((idx//3)*tile+y+1)*width+(idx%3)*tile+x+1]
    def reference(idx,u,v,bilinear):
        if not bilinear: return fetch(idx,min(n-1,int(u*n)),min(n-1,int(v*n)))
        px,py=u*n-.5,v*n-.5; bx,by=math.floor(px),math.floor(py); tx,ty=px-bx,py-by
        values=[fetch(idx,bx,by),fetch(idx,bx+1,by),fetch(idx,bx,by+1),fetch(idx,bx+1,by+1)]
        weights=[(1-tx)*(1-ty),tx*(1-ty),(1-tx)*ty,tx*ty]
        return [sum(val[k]*w for val,w in zip(values,weights)) for k in range(2)]
    maximum_mean_error=maximum_variance_error=0.; cases=0; observed_difference=0.
    # Interior, all edges and all corners. Probe 0 remains in the interpolation cell.
    for uv in ((.373,.617),(0,.27),(1,.27),(.31,0),(.31,1),(0,0),(0,1),(1,0),(1,1),(.001,.999)):
        direction=decode(*uv); origin=[-.5,.3,-.5]
        position=[a+.01*b for a,b in zip(origin,direction)]
        p.inspectSurfacePoint(float3(*position),float3(0,1,0)); frames()
        modes=[]
        for bilinear in (False,True,False):
            p.configureVisibility({'distanceBilinear':bilinear}); frames(); d=p.debugInfo; modes.append(d)
            assert p.ready and not p.baking and p.completedSamples==3 and p.completedDistanceSamples==4
            assert d['distanceBilinear']==bilinear
            for i in range(8):
                suffix=str(i); idx=d['probe'+suffix]
                delta=[a-b for a,b in zip(xyz(d['samplePosition']),xyz(d['position'+suffix]))]
                u,v=encode(delta); mean,second=reference(idx,u,v,bilinear); D=d['distanceMax']
                me=abs(d['meanDistance'+suffix]-mean*D)
                ve=abs(d['distanceVariance'+suffix]-max(0,second-mean*mean)*D*D)
                maximum_mean_error=max(maximum_mean_error,me); maximum_variance_error=max(maximum_variance_error,ve)
                assert me<1e-5 and ve<1e-5,(uv,i,bilinear,me,ve)
                cases+=1
        for i in range(8):
            key='meanDistance'+str(i)
            assert modes[0][key]==modes[2][key]
            observed_difference=max(observed_difference,abs(modes[0][key]-modes[1][key]))
    assert observed_difference>1e-4
    assert cache.read_bytes()==saved and source.read_bytes()==original
    (out/'results.json').write_text(json.dumps({'comparisons':cases,'mean_max_error':maximum_mean_error,
        'variance_max_error':maximum_variance_error,'point_bilinear_max_difference':observed_difference,
        'checks':['existing v3 load without bake','default bilinear','interior/edges/corners CPU comparison',
        'interpolate both moments before variance','Point/Bilinear/Point identical return',
        'ready/sample counts/cache unchanged']},indent=2))
    print('Bilinear distance checks passed:',out); exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc()); exit(1)
