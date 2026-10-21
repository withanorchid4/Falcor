"""Script-only original-snapshot bake, isolation and cache/snapshot regression."""
from pathlib import Path
import os, sys, time, traceback, json, struct, math
from falcor import float2
sys.path.insert(0, 'F:/scripts')
from probe_snapshot import replay, capture, save_snapshot, write_json, json_value, digest, read_image

case = Path('F:/build/probe-issues/20260924-104702-ae8fb0')
out = Path('F:/build/wicked-static-validation')
out.mkdir(parents=True, exist_ok=True)
# Remove only prior generated frame captures of this test, so Falcor's frame-numbered files are unambiguous.
for directory in ('current','current-restored','wicked','wrapped-zero-bias','wrapped-same-bias','ray','ray-wrapped-zero-bias','reloaded','sparse','snapshot-replay','legacy-p50'):
    for file in (out/directory).glob('frame.*'): file.unlink()

def diff(a,b):
    aa=Path(a).read_bytes(); bb=Path(b).read_bytes()
    assert len(aa)==len(bb)
    return max(abs(x[0]-y[0]) for x,y in zip(struct.iter_unpack('f',aa),struct.iter_unpack('f',bb)))

def points(p):
    result=[]
    for x,y in ((520,417),(521,417),(1057,192),(1058,192),(1092,325),(1092,326)):
        p.pickSurface(float2((x+.5)/1280,(y+.5)/720)); renderFrame()
        info=json_value(p.debugInfo); assert info['valid']
        weights=[]
        for i in range(8):
            k=str(i); d,mu,var=(info[t+k] for t in ('queryDistance','meanDistance','distanceVariance'))
            v=1 if d<=mu else (var/(var+(d-mu)**2))**3
            assert abs(v-info['visibility'+k])<.003,(i,v,info['visibility'+k])
            if info['visibilityMode']=='rayTraced': v=info['rayVisibility'+k]
            a=max(.01,info['normalWeight'+k]*v)
            if a<.2: a*=a*a/.04
            if info['visibilityMode']=='rayTraced' and v==0: a=0
            weights.append(a*info['trilinearWeight'+k])
        for i,a in enumerate(weights):
            assert abs(a/max(sum(weights),1e-20)-info['weight'+str(i)])<.0001
        result.append({'pixel':[x,y],'data':info})
    return result

def diagnostics(p, tag):
    directory=out/tag/'moments';directory.mkdir(exist_ok=True)
    graph=m.activeGraph;graph.markOutput('Probes.color')
    fc=m.frameCapture;previous=(fc.outputDir,fc.baseFilename,fc.captureAllOutputs)
    try:
        for probe in (375,382):
            for view,label in ((9,'m2'),(10,'mu2'),(11,'variance')):
                name=f'p{probe}-{label}'
                for file in directory.glob(name+'.*'):file.unlink()
                p.configureDebug({'enabled':True,'view':view,'selectedProbe':probe,'showProbes':False,'showBounds':False,'showLinks':False,'preview':False})
                renderFrame();fc.outputDir=str(directory);fc.baseFilename=name;fc.captureAllOutputs=False;fc.capture();renderFrame()
                # Convert EXR after Mogwai exits: FreeImage uses asynchronous writers.
    finally:
        fc.outputDir,fc.baseFilename,fc.captureAllOutputs=previous
        graph.unmarkOutput('Probes.color')
        p.configureDebug({'enabled':False,'view':0})

try:
    original=digest(case/'probes.shprobe')
    legacy=Path('F:/build/probe-filter-strength')
    options=json.loads((legacy/'p50/render.json').read_text())['overrides']
    replay(m,renderFrame,legacy/'p50-case',out/'legacy-p50',options)
    legacy_error=diff(out/'legacy-p50/hdr.f32',Path('F:/build/probe-wicked-alignment/legacy-p50/hdr.f32'))
    replay(m,renderFrame,case,out/'current',{'antiLeakMode':'current','samplingMode':'full'})
    p=m.activeGraph.getPass('Probes'); original_settings=json_value(p.settings)
    cache=out/'visibility.wdist'
    p.configureAntiLeak({'antiLeakMode':'wickedStatic','wickedCacheFile':str(cache)})
    renderFrame()
    start=time.perf_counter()
    if cache.is_file(): p.loadCache()
    else: p.bake()
    for i in range(1000):
        renderFrame()
        if p.ready or not p.baking: break
    assert p.ready,p.status
    timing=time.perf_counter()-start
    report={'bake_or_load_seconds':timing,'settings':json_value(p.settings),'checks':{},'points':{},'legacy_p50_max_error':legacy_error}
    for tag,settings in (
        ('wicked',{'wickedNormalBias':.001,'wickedSmoothBackface':.01,'wickedVisibilityMode':'moments'}),
        ('wrapped-zero-bias',{'wickedNormalBias':0.,'wickedSmoothBackface':1.}),
        ('wrapped-same-bias',{'wickedNormalBias':.025939816,'wickedSmoothBackface':1.}),
        ('ray',{'wickedNormalBias':.001,'wickedSmoothBackface':.01,'wickedVisibilityMode':'rayTraced'}),
        ('ray-wrapped-zero-bias',{'wickedNormalBias':0.,'wickedSmoothBackface':1.,'wickedVisibilityMode':'rayTraced'})):
        p.configureAntiLeak(settings); renderFrame()
        capture(m,renderFrame,m.activeGraph,p,out/tag)
        report['points'][tag]=points(p)
        print('Captured',tag,flush=True)
    p.configureAntiLeak({'antiLeakMode':'current'}); renderFrame()
    capture(m,renderFrame,m.activeGraph,p,out/'current-restored')
    report['checks']['switch_back_max_error']=diff(out/'current/hdr.f32',out/'current-restored/hdr.f32')
    assert report['checks']['switch_back_max_error']==0
    now=json_value(p.settings)
    for key,value in original_settings.items():
        if key!='antiLeakMode' and not key.startswith('wicked'): assert now[key]==value,key
    p.configureAntiLeak({'antiLeakMode':'wickedStatic','wickedNormalBias':.001,'wickedSmoothBackface':.01,'wickedVisibilityMode':'moments'})
    p.loadCache();renderFrame();assert p.ready,p.status
    capture(m,renderFrame,m.activeGraph,p,out/'reloaded')
    report['checks']['cache_roundtrip_max_error']=diff(out/'wicked/hdr.f32',out/'reloaded/hdr.f32')
    assert report['checks']['cache_roundtrip_max_error']==0
    p.configureSampling({'samplingMode':'screenSparse'});renderFrame()
    capture(m,renderFrame,m.activeGraph,p,out/'sparse')
    assert p.ready
    p.configureSampling({'samplingMode':'full'});renderFrame()
    saved=save_snapshot(m,renderFrame,out/'snapshots')
    replay(m,renderFrame,saved,out/'snapshot-replay')
    report['checks']['snapshot_roundtrip_max_error']=diff(out/'wicked/hdr.f32',out/'snapshot-replay/hdr.f32')
    assert report['checks']['snapshot_roundtrip_max_error']==0
    p=m.activeGraph.getPass('Probes')
    bad=out/'corrupt.wdist'; blob=bytearray(cache.read_bytes());blob[-1]^=1;bad.write_bytes(blob)
    p.configureAntiLeak({'wickedCacheFile':str(bad)});p.loadCache();renderFrame()
    assert not p.ready and 'corrupt' in p.status,p.status
    p.configureAntiLeak({'wickedCacheFile':str(cache),'wickedRaysPerProbe':1024});p.loadCache();renderFrame()
    assert not p.ready and 'mismatch' in p.status,p.status
    report['checks']['corrupt_and_mismatched_cache_rejected']=True
    assert digest(case/'probes.shprobe')==original
    report['checks']['original_cache_unchanged']=True
    p.configureAntiLeak({'wickedCacheFile':str(cache),'wickedRaysPerProbe':2048,'wickedNormalBias':.001,'wickedSmoothBackface':.01})
    p.loadCache();renderFrame();assert p.ready,p.status
    diagnostics(p,'wicked')
    p.configureAntiLeak({'wickedNormalBias':0.,'wickedSmoothBackface':1.});renderFrame()
    diagnostics(p,'wrapped-zero-bias')
    write_json(out/'result.json',report)
    (out/'failure.txt').unlink(missing_ok=True)
    print('All Wicked static validation checks passed.',flush=True)
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    print(traceback.format_exc(),flush=True)
    exit(1)
