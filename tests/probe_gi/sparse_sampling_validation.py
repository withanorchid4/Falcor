"""Isolated GPU quality, state and timestamp validation for sparse probe sampling."""
from falcor import *
from pathlib import Path
import json, os, sys, traceback
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from probe_snapshot import replay, digest, write_json, json_value, restore, verify

out = Path(os.environ['PROBE_SPARSE_OUTPUT'])
checks = {}

def frame(): renderFrame()

def sampling(p, stride):
    p.configureSampling({'samplingMode': 'screenSparse' if stride else 'full', 'sparseStride': stride or 2})

def capture(name, g, p):
    dest = out/name
    dest.mkdir()
    p.configureDebug({'enabled': False})
    for output in ('Probes.color', 'Display.dst', 'Probes.samplingInfo'): g.markOutput(output)
    frame(); frame()
    m.frameCapture.outputDir = str(dest)
    m.frameCapture.baseFilename = 'frame'
    m.frameCapture.captureAllOutputs = False
    m.frameCapture.capture()
    write_json(dest/'settings.json', p.settings)
    g.unmarkOutput('Probes.samplingInfo')

def quality(view, g, p):
    for backend in ('moments', 'rayTraced'):
        p.configureVisibility({'visibilityMode': backend})
        for stride in (0,2,4,8):
            sampling(p,stride)
            capture(f'{view}-{backend}-{stride}',g,p)

def benchmark(view, g, p):
    # All timed modes have the same graph outputs, no diagnostic UAV or readback.
    g.unmarkOutput('Probes.samplingInfo')
    m.profiler.enabled = True
    modes = [(b,s) for b in ('moments','rayTraced') for s in (0,2,4,8)]
    for turn in range(3):
        order = modes[turn*3:] + modes[:turn*3]
        if turn == 1: order.reverse()
        for backend,stride in order:
            p.configureVisibility({'visibilityMode':backend}); sampling(p,stride)
            for i in range(45): frame()
            m.profiler.start_capture()
            for i in range(151): frame()
            result = m.profiler.end_capture()
            write_json(out/f'timing-{view}-{backend}-{stride}-{turn}.json', result)
    m.profiler.enabled = False

def graph(name, props):
    g=RenderGraph(name)
    g.addPass(createPass('VBufferRT',{'samplePattern':'Center','useAlphaTest':True}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI',props),'Probes')
    g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer');g.addEdge('Visibility.viewW','Probes.viewW')
    g.addEdge('Probes.color','Display.src');g.markOutput('Display.dst')
    m.addGraph(g);m.setActiveGraph(g)
    return g,g.getPass('Probes')

try:
    case=Path('F:/build/probe-leak-fix/local128-case')
    replay(m,frame,case,out/'baseline',{'viewBias':.05,'varianceBase':1e-6})
    g=m.activeGraph;p=g.getPass('Probes');cache_hash=digest(p.cacheFile)
    quality('wall',g,p)
    benchmark('wall',g,p)
    # Original exact evaluator is unchanged and switching back restores it.
    p.configureVisibility({'visibilityMode':'moments'});sampling(p,0);capture('restored',g,p)
    m.scene.camera.position=float3(4.3,1.3,-2.5);m.scene.camera.target=float3(4.8,1,-.02);m.scene.camera.up=float3(0,1,0)
    quality('corner',g,p)
    # Full room with textured furniture and glass, using the scene's original camera.
    data=verify(case)
    m.loadScene(data['scene']);frame();frame();p.loadCache();frame();assert p.ready,p.status
    # Scene file defines environment/materials; use that state consistently for this view.
    quality('room',g,p)
    benchmark('room',g,p)
    for stride in (2,4,8):
        sampling(p,stride)
        m.resizeFrameBuffer(1279,719)
        m.scene.camera.position += float3(.01,0,0)
        capture(f'odd-{stride}',g,p)
        assert p.ready and not p.baking
    m.resizeFrameBuffer(1280,720)
    assert digest(p.cacheFile)==cache_hash
    # Invalid API changes are rejected atomically; controls are serialized independently.
    old=p.settings
    for props in ({'sparseStride':3},{'samplingMode':'bad'},{'visibilityMode':'moments'}):
        failed=False
        try: p.configureSampling(props)
        except Exception: failed=True
        assert failed and p.settings==old
    checks['parameter_validation']=True
    checks['cache_unchanged']=True
    props=json.loads(Path('F:/build/probe-leak-validation/fixture-new/settings.json').read_text())
    g,p=graph('SparseWallFixture',props)
    m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene');frame();frame();p.loadCache();frame();assert p.ready,p.status
    quality('fixture',g,p)
    props=json.loads(Path('F:/build/probe-leak-validation/open-new/settings.json').read_text())
    g,p=graph('SparseOpenFixture',props)
    m.loadScene('F:/tests/probe_gi/visibility_open.pyscene')
    m.scene.setEnvMap('F:/media/test_scenes/grey_and_white_room/envmap.exr');m.scene.envMap.intensity=1
    p.configureBake({'gridMin':float3(-1,.3,-1),'gridMax':float3(1,1.5,1)})
    frame();frame();p.loadCache();frame();assert p.ready,p.status
    quality('open',g,p)
    # Non-lighting debug views keep exact semantics even in sparse mode.
    sampling(p,4);p.configureDebug({'enabled':True,'view':3});frame()
    p.configureDebug({'enabled':False})
    # No cache load on the new graph: must show only the existing unbaked preview.
    props['mode']='manual';props['samplingMode']='screenSparse';props['sparseStride']=4
    g,p=graph('SparseUnbaked',props);frame();frame();assert not p.ready
    capture('unbaked',g,p)
    checks['odd_size_camera_unbaked']=True
    write_json(out/'validation.json',checks)
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    exit(1)
