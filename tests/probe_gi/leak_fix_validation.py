"""GPU validation of the leak-resistant preset, alternate views, coverage and cache migration."""
from falcor import *
from pathlib import Path
import json, os, sys, shutil, traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from probe_snapshot import replay, capture as snapshot_capture, digest, write_json, json_value, restore

out=Path(os.environ['PROBE_LEAK_OUTPUT']); out.mkdir(exist_ok=True,parents=True)
source=Path('F:/build/probe-issues/20260924-021543-642825')
derived=Path('F:/build/probe-leak-fix/local128-case')
checks={}
def frame(): renderFrame()
def capture(name,g,p):
    dest=out/name; dest.mkdir(exist_ok=True); p.configureDebug({'enabled':False})
    g.markOutput('Probes.color'); g.markOutput('Display.dst'); frame()
    m.frameCapture.outputDir=str(dest); m.frameCapture.baseFilename='frame'; m.frameCapture.captureAllOutputs=False; m.frameCapture.capture()
    write_json(dest/'settings.json',p.settings)
def graph(name,props):
    g=RenderGraph(name); g.addPass(createPass('VBufferRT',{'samplePattern':'Center'}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI',props),'Probes');g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer');g.addEdge('Visibility.viewW','Probes.viewW');g.addEdge('Probes.color','Display.src')
    g.markOutput('Display.dst');m.addGraph(g);m.setActiveGraph(g);return g,g.getPass('Probes')
def bake(p):
    p.bake()
    for i in range(200000):
        frame()
        if p.ready or not p.baking: break
    assert p.ready,p.status
def second_view():
    m.scene.camera.position=float3(4.3,1.3,-2.5);m.scene.camera.target=float3(4.8,1,-.02);m.scene.camera.up=float3(0,1,0)

try:
    replay(m,frame,source,out/'original',{'normalHemisphere':True})
    g=m.activeGraph;p=g.getPass('Probes');second_view();capture('room2-old',g,p)
    replay(m,frame,derived,out/'first-new',{'viewBias':.05,'varianceBase':1e-6})
    g=m.activeGraph;p=g.getPass('Probes');cache_hash=digest(p.cacheFile)
    p.applyLeakResistantPreset();frame();assert p.ready and not p.baking
    expected={'distanceBakeMode':'texelLocal','distanceResolution':128,'distanceSamplesPerTexel':32,
        'normalHemisphere':True,'distanceBilinear':True,'distanceSmooth':False,'visibilityMode':'moments'}
    assert all(p.settings[k]==v for k,v in expected.items())
    checks['preset']=json_value(p.settings)
    records=[]
    for point in json.loads(Path('F:/build/probe-leak-fix/residual-points.json').read_text()):
        p.inspectSurfacePoint(float3(*point['P']),float3(*point['N']));frame();records.append({'region':point['region'],'debug':json_value(p.debugInfo)})
    checks['residualPoints']=records
    p.configureVisibility({'visibilityMode':'rayTraced'});capture('first-ray',g,p)
    p.configureVisibility({'visibilityMode':'moments'});second_view();capture('room2-new',g,p)
    p.configureVisibility({'visibilityMode':'rayTraced'});capture('room2-ray',g,p)
    assert digest(p.cacheFile)==cache_hash
    # Same selected surface, changes in view direction must stay finite and preserve cache/bake state.
    p.configureVisibility({'visibilityMode':'moments'});point=records[0]['debug'];p.inspectSurfacePoint(float3(*point['position']),float3(*point['normal']))
    for position in ((4.0,2.3,-1.5),(4.5,2.3,-1.5),(4.5,1.3,-2.5)):
        m.scene.camera.position=float3(*position);frame();d=p.debugInfo
        assert p.ready and not p.baking and d['valid']
        assert all(0<=d['weight'+str(i)]<=1.00001 for i in range(8))
    checks['camera_sweep_finite']=True
    # Contrast the 32-resolution fixture from the previous fix with the new preset.
    props=json.loads(Path('F:/build/probe-hard-edge-fix-validation-02/fixture-old/settings.json').read_text())
    props['normalHemisphere']=True
    g,p=graph('LeakFixtureOld',props);m.loadScene('F:/tests/probe_gi/visibility_wall.pyscene');frame();frame();p.loadCache();frame();assert p.ready,p.status
    capture('fixture-old',g,p)
    props['cacheFile']=str(out/'fixture-new.shprobe');g,p=graph('LeakFixtureNew',props);p.applyLeakResistantPreset();frame();frame();bake(p)
    capture('fixture-new',g,p);p.configureVisibility({'visibilityMode':'rayTraced'});capture('fixture-ray',g,p)
    old_lines=Path('F:/build/probe-hard-edge-fix-validation-02/fixture.shprobe').read_text().splitlines()
    new_lines=Path(p.cacheFile).read_text().splitlines()
    assert old_lines[7:old_lines.index('DISTANCE_MOMENTS')]==new_lines[7:new_lines.index('DISTANCE_MOMENTS')]
    checks['fixture_SH_unchanged']=True
    # An open lit floor checks that the preset still accepts genuinely visible probes.
    g,p=graph('LeakOpen',dict(props,cacheFile=str(out/'open.shprobe')))
    m.loadScene('F:/tests/probe_gi/visibility_open.pyscene')
    m.scene.setEnvMap('F:/media/test_scenes/grey_and_white_room/envmap.exr');m.scene.envMap.intensity=1
    p.configureBake({'gridMin':float3(-1,.3,-1),'gridMax':float3(1,1.5,1)});p.applyLeakResistantPreset();frame();frame();bake(p)
    capture('open-new',g,p);p.configureVisibility({'visibilityMode':'rayTraced'});capture('open-ray',g,p)
    p.configureVisibility({'visibilityMode':'moments'});minimum=1.;count=0
    for x in (-.75,0.,.75):
        for z in (-.75,0.,.75):
            p.inspectSurfacePoint(float3(x,0,z),float3(0,1,0));frame();d=p.debugInfo
            for i in range(8):
                k=str(i)
                if d['trilinearWeight'+k]>1e-6:
                    assert d['rayVisibility'+k]==1
                    minimum=min(minimum,d['appliedVisibility'+k]);count+=1
    checks['open_visible_samples']=count;checks['open_min_visibility']=minimum;assert minimum>.98
    # Automatic naming fallback is exercised on a newly created scene identity only.
    scene=out/'cache_migration_fixture.pyscene';shutil.copyfile('F:/tests/probe_gi/visibility_open.pyscene',scene)
    g,p=graph('CacheMigration',{'mode':'manual','gridCounts':uint3(2),'samplesPerProbe':1,'samplesPerFrame':1,
        'maxBounces':0,'distanceBakeMode':'texelLocal','distanceResolution':4,'distanceSamplesPerTexel':1})
    m.loadScene(str(scene));p.configureBake({'gridMin':float3(-1,.3,-1),'gridMax':float3(1,1.5,1)});frame();frame()
    new=Path(p.cacheFile);assert new.name.endswith('-texel-local-r4-s1.shprobe') and not new.exists();bake(p)
    legacy=new.with_name(new.name.replace('-r4-s1',''));assert not legacy.exists()
    assert new.resolve().is_relative_to(Path('F:/build/probes').resolve())
    new.rename(legacy);saved=digest(legacy);p.loadCache();frame();assert p.ready and Path(p.cacheFile)==legacy
    bake(p);assert Path(p.cacheFile)==new and new.is_file() and digest(legacy)==saved
    p.configureBake({'distanceResolution':8,'distanceSamplesPerTexel':2});frame();p.loadCache();frame()
    assert not p.ready and 'metadata mismatch' in p.status
    bake(p);assert Path(p.cacheFile).name.endswith('-r8-s2.shprobe') and digest(legacy)==saved
    checks['legacy_fallback_and_new_bake_isolation']=True
    write_json(out/'validation.json',checks);exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8');exit(1)
