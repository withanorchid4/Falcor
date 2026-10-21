"""Scale distance resolution, ray density and angular kernel together; keep runtime weighting fixed."""
from pathlib import Path
import sys, time, traceback, struct
from falcor import float2
sys.path.insert(0,'F:/scripts')
from probe_snapshot import replay, capture, write_json, json_value, digest, save_snapshot

out=Path('F:/build/wicked-angular-precision');out.mkdir(parents=True,exist_ok=True)
case=Path('F:/build/probe-issues/20260924-104702-ae8fb0')
base=Path('F:/build/wicked-static-validation/visibility.wdist')
stages=[('r32',32,10704,334.),('r64',64,42800,1337.),('r128-wide',128,171200,64.),('r128',128,171200,5350.)]

def prepare(tag):
    directory=out/tag;directory.mkdir(exist_ok=True)
    for f in directory.glob('frame.*'):f.unlink()
    return directory

def image_error(a,b):
    aa=Path(a).read_bytes();bb=Path(b).read_bytes();assert len(aa)==len(bb)
    return max(abs(x[0]-y[0]) for x,y in zip(struct.iter_unpack('<f',aa),struct.iter_unpack('<f',bb)))

try:
    sha=digest(case/'probes.shprobe');base_sha=digest(base)
    replay(m,renderFrame,case,prepare('baseline'),{'antiLeakMode':'wickedStatic','wickedCacheFile':str(base),
        'wickedResolution':14,'wickedExponent':64.,'wickedRaysPerProbe':2048,'wickedNormalBias':.001,
        'wickedSmoothBackface':.01,'wickedVisibilityMode':'moments','samplingMode':'full'})
    p=m.activeGraph.getPass('Probes');report={'variants':{},'checks':{}}
    for tag,resolution,rays,exponent in stages:
        directory=prepare(tag);cache=directory/'visibility.wdist'
        p.configureAntiLeak({'wickedResolution':resolution,'wickedRaysPerProbe':rays,'wickedExponent':exponent,
            'wickedCacheFile':str(cache)})
        renderFrame();started=time.perf_counter();p.bake()
        last=started
        for _ in range(40000):
            renderFrame()
            if p.ready or not p.baking:break
            if time.perf_counter()-last>15:
                print(tag,'samples',p.completedDistanceSamples,'/',rays,flush=True);last=time.perf_counter()
        assert p.ready,p.status
        elapsed=time.perf_counter()-started
        capture(m,renderFrame,m.activeGraph,p,directory)
        pts=[]
        for x,y in ((432,220),(433,360),(434,520),(435,620),(520,417),(521,417),(1057,192),(1058,192)):
            p.pickSurface(float2((x+.5)/1280,(y+.5)/720));renderFrame()
            info=json_value(p.debugInfo)
            assert info['valid'] and info['distanceResolution']==resolution and info['distanceExponent']==exponent
            pts.append({'pixel':[x,y],'data':info})
        report['variants'][tag]={'resolution':resolution,'rays':rays,'exponent':exponent,'bake_seconds':elapsed,
            'points':pts,'settings':json_value(p.settings),'cache_sha256':digest(cache)}
        write_json(out/'progress.json',report)
        print('Captured',tag,'seconds',elapsed,flush=True)
    p.loadCache();renderFrame();assert p.ready,p.status
    capture(m,renderFrame,m.activeGraph,p,prepare('reloaded'))
    assert image_error(out/'r128/hdr.f32',out/'reloaded/hdr.f32')==0
    saved=save_snapshot(m,renderFrame,out/'snapshots')
    replay(m,renderFrame,saved,prepare('snapshot'))
    assert image_error(out/'r128/hdr.f32',out/'snapshot/hdr.f32')==0
    p=m.activeGraph.getPass('Probes')
    p.configureAntiLeak({'wickedExponent':64.});p.loadCache();renderFrame()
    assert not p.ready and 'mismatch' in p.status,p.status
    p.configureAntiLeak({'wickedExponent':5350.});p.loadCache();renderFrame();assert p.ready,p.status
    p.configureAntiLeak({'wickedVisibilityMode':'rayTraced'});renderFrame()
    capture(m,renderFrame,m.activeGraph,p,prepare('ray'))
    p.configureAntiLeak({'antiLeakMode':'current'});renderFrame();assert p.ready
    capture(m,renderFrame,m.activeGraph,p,prepare('current-restored'))
    assert image_error(out/'current-restored/hdr.f32',Path('F:/build/wicked-resolution-sweep/current-restored/hdr.f32'))==0
    assert digest(case/'probes.shprobe')==sha and digest(base)==base_sha
    report['checks']={'cache_roundtrip_exact':True,'snapshot_roundtrip_exact':True,'wrong_exponent_rejected':True,
        'current_path_exact':True,'original_caches_unchanged':True}
    write_json(out/'result.json',report);(out/'failure.txt').unlink(missing_ok=True)
    print('Angular precision experiment passed.',flush=True)
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    print(traceback.format_exc(),flush=True)
    exit(1)
