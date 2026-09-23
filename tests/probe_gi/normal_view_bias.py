"""Existing-cache GPU checks for normal/view query bias; does not touch the user's scene/cache."""
from falcor import *
from pathlib import Path
import json, math, traceback

out = Path('F:/build/probe-bias-validation')
out.mkdir(parents=True, exist_ok=True)
cache = Path('F:/build/probe-texel-local-validation/wall.shprobe')
saved = cache.read_bytes()

def xyz(v): return list(v) if isinstance(v, (list, tuple)) else [v.x, v.y, v.z]
def frames(): renderFrame()

try:
    g = RenderGraph('BiasValidation')
    g.addPass(createPass('VBufferRT', {'samplePattern': 'Center'}), 'Visibility')
    settings = {'mode': 'manual', 'cacheFile': str(cache), 'gridCounts': uint3(2),
        'gridMin': float3(-.5, .3, -.5), 'gridMax': float3(.5, 1.5, .5),
        'samplesPerProbe': 3, 'samplesPerFrame': 1, 'maxBounces': 1,
        'distanceResolution': 128, 'distanceSamplesPerTexel': 4}
    g.addPass(createPass('TraditionalProbeGI', settings), 'Probes')
    g.addEdge('Visibility.vbuffer', 'Probes.vbuffer')
    g.addEdge('Visibility.viewW', 'Probes.viewW')
    g.markOutput('Probes.color'); m.addGraph(g)
    m.clock.pause(); m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene')
    frames(); frames(); p = g.getPass('Probes'); p.loadCache(); frames()
    assert p.ready and p.settings['viewBias'] == 0
    assert abs(p.settings['normalBias'] - .05) < 1e-7
    # Actual divider surface; outward normal points into the camera's room.
    P = [-.02, .8, .1]; N = [-1., 0., 0.]
    p.inspectSurfacePoint(float3(*P), float3(*N)); frames()
    baseline = p.debugInfo
    records = []; maximum_error = 0

    def check(tag, normal, view):
        global maximum_error
        d = p.debugInfo
        camera = xyz(m.scene.camera.position)
        stored_point = xyz(d['position'])
        delta = [c-a for c,a in zip(camera, stored_point)]
        length = math.sqrt(sum(x*x for x in delta))
        direction = [x/length if length > 1e-8 else 0 for x in delta]
        expected = [a+normal*n+view*v for a,n,v in zip(stored_point,N,direction)]  # minSpacing=1
        actual = xyz(d['samplePosition'])
        error = max(abs(a-b) for a,b in zip(actual, expected))
        assert error < 2e-6, (tag, actual, expected)
        maximum_error = max(maximum_error, error)
        assert p.ready and not p.baking and p.completedSamples == 3 and p.completedDistanceSamples == 4
        assert max(abs(a-b) for a,b in zip(xyz(d['position']), P)) < 1e-6
        records.append({'case': tag, 'Q': actual, 'camera': camera, 'error': error})
        return d

    check('old default', .05, 0)
    for normal, view in ((0,0), (.1,0), (0,.24), (.06,.24)):
        p.configureVisibility({'normalBias': normal, 'viewBias': view}); frames()
        check('moments bias', normal, view)
        p.configureVisibility({'visibilityMode': 'rayTraced'}); frames()
        check('ray bias', normal, view)
        p.configureVisibility({'visibilityMode': 'moments'}); frames()

    # No manual refresh: a saved world selection must follow changes to camera position.
    for camera in ((-.8,1.4,-.7), (-.1,.9,.5), tuple(P)):
        m.scene.camera.position = float3(*camera); frames()
        check('camera move / coincident camera', .06, .24)

    # Property round trip; rejection must leave the live values unchanged.
    clone = createPass('TraditionalProbeGI', p.settings)
    assert abs(clone.settings['viewBias']-.24) < 1e-7
    for field in ('normalBias', 'viewBias'):
        for invalid in (-1., 1.1, float('nan'), float('inf')):
            rejected = False
            try: p.configureVisibility({field: invalid})
            except Exception: rejected = True
            assert rejected, (field, invalid)
    assert abs(p.settings['normalBias']-.06) < 1e-7 and abs(p.settings['viewBias']-.24) < 1e-7

    p.configureDebug({'normalBias': .05, 'viewBias': 0}); frames()
    restored = check('restore original', .05, 0)
    for i in range(8):
        for prefix in ('weight', 'meanDistance', 'distanceVariance'):
            key = prefix+str(i)
            assert abs(restored[key]-baseline[key]) < 1e-6, key
    assert cache.read_bytes() == saved
    (out/'results.json').write_text(json.dumps({'max_Q_error': maximum_error, 'cases': records,
        'checks': ['default unchanged', 'normal/view/formula preset', 'moments and ray same Q',
            'automatic camera refresh', 'coincident camera finite', 'property round trip',
            'invalid input rejected atomically', 'old weights restored', 'cache and bake state unchanged']}, indent=2))
    print('Normal/view bias checks passed:', out)
    (out/'failure.txt').unlink(missing_ok=True)
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc())
    exit(1)
