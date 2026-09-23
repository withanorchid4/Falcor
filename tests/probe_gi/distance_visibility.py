"""GPU bake and occlusion checks. Set PROBE_DISTANCE_TEST=load for a fresh-process cache check."""
from falcor import *
from pathlib import Path
import json, os, traceback

out = Path('F:/build/probe-distance-validation')
out.mkdir(parents=True, exist_ok=True)
cache = out / 'wall.shprobe'
mode = os.environ.get('PROBE_DISTANCE_TEST', 'bake')

def frames(n=1):
    for _ in range(n): renderFrame()

def capture(tag):
    m.frameCapture.outputDir = str(out)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()

def inspect(x, y):
    p.pickSurface(float2(x,y)); frames()
    return p.debugInfo

try:
    g = RenderGraph('ProbeDistanceValidation')
    g.addPass(createPass('VBufferRT', {'samplePattern':'Center'}), 'Visibility')
    g.addPass(createPass('TraditionalProbeGI', {
        'mode':'manual', 'cacheFile':str(cache), 'sceneRevision':'distance-v2',
        'gridCounts':uint3(2), 'gridMin':float3(-.5,.3,-.5), 'gridMax':float3(.5,1.5,.5),
        'samplesPerProbe':2048, 'samplesPerFrame':64, 'maxBounces':3, 'normalBias':.02,
    }), 'Probes')
    g.addPass(createPass('ToneMapper', {'autoExposure':False}), 'Display')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer')
    g.addEdge('Visibility.viewW','Probes.viewW')
    g.addEdge('Probes.color','Display.src')
    for name in ('Display.dst','Probes.probeLighting','Probes.color'): g.markOutput(name)
    m.addGraph(g)
    m.clock.pause()
    m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene')
    frames(2)
    p = g.getPass('Probes')
    if mode == 'load': p.loadCache()
    else: p.bake()
    frames(34 if mode == 'bake' else 2)
    assert p.ready, p.status
    saved = cache.read_bytes()
    capture(mode+'-on')
    if mode == 'load':
        assert p.completedSamples == 2048 and 'loaded' in p.status
        (out/'load.json').write_text(json.dumps({'cache_loaded_without_bake':True}))
        exit()
    p.configureVisibility({'useVisibility':False})
    frames(2); capture('off')
    comparisons = []
    for uv in ((.35,.65),(.5,.65),(.65,.65),(.4,.8),(.6,.8),(.5,.4)):
        p.configureVisibility({'useVisibility':False})
        a = inspect(*uv)
        p.configureVisibility({'useVisibility':True})
        frames(); b = p.debugInfo
        if not a['valid']: continue
        blocked = [i for i in range(8) if not a['visible'+str(i)]]
        off = sum(a['weight'+str(i)] for i in blocked)
        on = sum(b['weight'+str(i)] for i in blocked)
        assert all(0 <= b['visibility'+str(i)] <= 1.00001 for i in range(8))
        assert all(0 <= b['weight'+str(i)] <= 1.00001 for i in range(8))
        comparisons.append({'uv':uv, 'blocked_weight_off':off, 'blocked_weight_on':on})
    useful = [v for v in comparisons if v['blocked_weight_off'] > .1]
    assert useful and all(v['blocked_weight_on'] < v['blocked_weight_off'] * .5 for v in useful), comparisons
    assert p.ready and p.completedSamples == 2048 and cache.read_bytes() == saved
    for view, tag in ((6,'support'),(7,'mean'),(8,'stddev')):
        p.configureDebug({'view':view,'selectedProbe':1, 'showProbes':False,'showBounds':False,'showLinks':False})
        frames(); capture(tag)
    p.configureDebug({'enabled':False,'view':0})
    # Old format, broken numeric moments and incomplete payload must not silently load.
    text = saved.decode('utf-8')
    before, after = text.split('DISTANCE_MOMENTS\n')
    corrupt = {
        'legacy':text.replace(text.splitlines()[0],'FALCOR_PROBE_SH 1',1),
        'truncated':before+'DISTANCE_MOMENTS\n',
        'nonfinite':before+'DISTANCE_MOMENTS\nnan 1\n'+after.split('\n',1)[1],
        'invalidvariance':before+'DISTANCE_MOMENTS\n0.9 0.1\n'+after.split('\n',1)[1],
    }
    for tag, content in corrupt.items():
        cache.write_text(content,encoding='utf-8'); p.loadCache(); frames()
        assert not p.ready and 'Cache not loaded' in p.status, (tag,p.status)
        assert cache.read_text(encoding='utf-8') == content
    cache.write_bytes(saved); p.loadCache(); frames(); assert p.ready
    p.configureBake({'distanceResolution':8}); frames()
    assert not p.ready and not p.baking
    p.loadCache(); frames(); assert not p.ready and 'metadata mismatch' in p.status
    assert cache.read_bytes() == saved
    p.configureBake({'distanceResolution':14}); frames(); p.loadCache(); frames(); assert p.ready
    # A real scene checks general geometry/material paths and debug inspection.
    m.loadScene('F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene')
    frames(); p.configureBake({'samplesPerProbe':512,'gridCounts':uint3(8,6,8)})
    frames(); p.bake(); frames(10); assert p.ready,p.status
    # Keep the synthetic cache for the separate process load check.
    cache.write_bytes(saved)
    p.configureVisibility({'useVisibility':False}); frames(); capture('room-off')
    p.configureVisibility({'useVisibility':True}); frames(); capture('room-on')
    (out/'integration.json').write_text(json.dumps({'comparisons':comparisons,
        'checks':['bake', 'visibility A/B', 'runtime settings preserve cache', 'debug views',
                  'reject legacy/truncated/nonfinite/invalid variance', 'distance resolution mismatch', 'Room bake']},indent=2))
    exit()
except Exception:
    (out/('failure-'+mode+'.txt')).write_text(traceback.format_exc())
    raise
