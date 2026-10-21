"""Only change Wicked distance-map resolution, preserving rays/kernel/SH/camera/runtime weights."""
from pathlib import Path
import sys, time, traceback, struct
from falcor import float2
sys.path.insert(0, 'F:/scripts')
from probe_snapshot import replay, capture, write_json, json_value, digest, save_snapshot

out=Path('F:/build/wicked-resolution-sweep')
out.mkdir(parents=True,exist_ok=True)
case=Path('F:/build/probe-issues/20260924-104702-ae8fb0')
original_cache=Path('F:/build/wicked-static-validation/visibility.wdist')

def prepare(tag):
    directory=out/tag
    directory.mkdir(exist_ok=True)
    for file in directory.glob('frame.*'):file.unlink()
    return directory

def error(a,b):
    aa=Path(a).read_bytes();bb=Path(b).read_bytes();assert len(aa)==len(bb)
    return max(abs(x[0]-y[0]) for x,y in zip(struct.iter_unpack('<f',aa),struct.iter_unpack('<f',bb)))

try:
    sha=digest(case/'probes.shprobe');old_sha=digest(original_cache)
    replay(m,renderFrame,case,prepare('old14'),{'antiLeakMode':'wickedStatic','wickedCacheFile':str(original_cache),
        'wickedResolution':14,'wickedNormalBias':.001,'wickedSmoothBackface':.01,'wickedRaysPerProbe':2048,
        'wickedVisibilityMode':'moments','samplingMode':'full'})
    p=m.activeGraph.getPass('Probes')
    report={'settings_fixed':json_value(p.settings),'variants':{},'checks':{}}
    report['checks']['old14_runtime_max_error']=error(out/'old14/hdr.f32',Path('F:/build/wicked-static-validation/wicked/hdr.f32'))
    for resolution in (14,32,64,128):
        directory=prepare('r'+str(resolution));cache=directory/'visibility.wdist'
        p.configureAntiLeak({'wickedResolution':resolution,'wickedCacheFile':str(cache)})
        renderFrame();started=time.perf_counter();p.bake()
        for _ in range(2000):
            renderFrame()
            if p.ready or not p.baking:break
        assert p.ready,p.status
        elapsed=time.perf_counter()-started
        capture(m,renderFrame,m.activeGraph,p,directory)
        pts=[]
        for x,y in ((432,220),(433,360),(434,520),(435,620)):
            p.pickSurface(float2((x+.5)/1280,(y+.5)/720));renderFrame()
            info=json_value(p.debugInfo);assert info['valid'] and info['distanceResolution']==resolution
            pts.append({'pixel':[x,y],'data':info})
        entry={'resolution':resolution,'bake_seconds':elapsed,'settings':json_value(p.settings),
            'cache_sha256':digest(cache),'distance_texture_mib':(20*(resolution+2))**2*8/(1024**2),'points':pts}
        report['variants'][str(resolution)]=entry
        write_json(out/'progress.json',report)
        print('Captured resolution',resolution,'bake seconds',elapsed,flush=True)
    p.loadCache();renderFrame();assert p.ready,p.status
    capture(m,renderFrame,m.activeGraph,p,prepare('reloaded128'))
    report['checks']['cache128_roundtrip_error']=error(out/'r128/hdr.f32',out/'reloaded128/hdr.f32')
    assert report['checks']['cache128_roundtrip_error']==0
    saved=save_snapshot(m,renderFrame,out/'snapshots')
    replay(m,renderFrame,saved,prepare('snapshot128'))
    report['checks']['snapshot128_roundtrip_error']=error(out/'r128/hdr.f32',out/'snapshot128/hdr.f32')
    assert report['checks']['snapshot128_roundtrip_error']==0
    p=m.activeGraph.getPass('Probes')
    p.configureAntiLeak({'wickedVisibilityMode':'rayTraced'});renderFrame()
    capture(m,renderFrame,m.activeGraph,p,prepare('ray'))
    p.configureAntiLeak({'antiLeakMode':'current'});renderFrame();assert p.ready
    capture(m,renderFrame,m.activeGraph,p,prepare('current-restored'))
    report['checks']['current_switch_back_error']=error(out/'current-restored/hdr.f32',Path('F:/build/wicked-static-validation/current/hdr.f32'))
    assert report['checks']['current_switch_back_error']==0
    p.configureAntiLeak({'antiLeakMode':'wickedStatic','wickedResolution':14,'wickedCacheFile':str(original_cache),'wickedVisibilityMode':'moments'})
    p.loadCache();renderFrame();assert p.ready,p.status
    assert digest(case/'probes.shprobe')==sha and digest(original_cache)==old_sha
    report['checks']['original_sh_and_distance_caches_unchanged']=True
    write_json(out/'result.json',report)
    (out/'failure.txt').unlink(missing_ok=True)
    print('Resolution sweep passed.',flush=True)
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    print(traceback.format_exc(),flush=True)
    exit(1)
