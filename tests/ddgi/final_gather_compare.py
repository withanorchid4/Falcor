"""Headless controlled Lambert final-gather experiment, plus native-material smoke."""
from falcor import *
from pathlib import Path
import json, os, runpy, traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ.get('FG_OUTPUT', ROOT/'build/final-gather-comparison'))
OUT.mkdir(parents=True, exist_ok=True)
for stale in ["failure.txt", "complete.json", "complete.txt"]:
    (OUT/stale).unlink(missing_ok=True)
record={"resolution":[480,270], "warmup":2048, "static_gather_spp":[1,16,64,256,1024],
        "pt_spp":32768, "motion_reference_spp":512, "motion_frames":8}
def save(): (OUT/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
    for _ in range(n): renderFrame()
def capture(tag):
    m.frameCapture.baseFilename=tag
    m.frameCapture.capture()
def timing(graph, tag):
    m.setActiveGraph(graph)
    m.profiler.enabled=True
    frames(16)
    m.profiler.start_capture()
    frames(128)
    (OUT/(tag+'-timing.json')).write_text(json.dumps(m.profiler.end_capture(),indent=2))
    m.profiler.enabled=False
try:
    cfg=json.loads((ROOT/'scripts/scenes/CornellRTXGI.json').read_text())
    cfg['directionalLight']['enabled']=False
    cfg['ceilingPointLight']['enabled']=True
    cfg['ceilingPointLight']['intensity']=1.0
    (OUT/'scene.json').write_text(json.dumps(cfg,indent=2))
    os.environ['CORNELL_RTXGI_CONFIG']=str(OUT/'scene.json')
    g=runpy.run_path(str(ROOT/'scripts/RTXGIDDGIFinalGather.py'))['RTXGIDDGIFinalGather']
    g.removeEdge('Compose.output', 'Accumulate.input')
    g.addEdge('DDGI.color', 'Accumulate.input')
    g.getPass('Accumulate').set_properties({'enabled':True})
    dd=g.getPass('DDGI')
    dd.set_properties({'finalGather':False,'gridCounts':uint3(9,9,9),'raysPerProbe':256,
        'autoBounds':False,'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
        'normalBias':.02/.3,'viewBias':.1/.3,'useWRC':False})
    for c in ['DDGI.color','DDGI.indirect','DDGI.gatherDiffuse','DDGI.gatherSpecular',
              'Accumulate.output','Visibility.normW']:g.markOutput(c)
    m.addGraph(g)
    m.loadScene(str(ROOT/'tests/ddgi/final_gather_lambert.pyscene'))
    m.clock.pause();m.scene.camera.animated=False
    m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
    record['stage']='warming probes';save()
    frames(2048)
    record['probe_stats']=dict(dd.stats)
    assert record['probe_stats']['finite']
    dd.set_properties({'updateEnabled':False})
    frames(1);capture('baseline')
    dd.set_properties({'enableGI':False});frames(1);capture('direct')
    dd.set_properties({'enableGI':True,'finalGather':True})
    record['stage']='static gather';save()
    for i in range(1,1025):
        renderFrame()
        if i in record['static_gather_spp']:capture('gather-'+str(i))
    dd.set_properties({'gatherDiffuse':False});frames(1);capture('lambert-specular-only')
    dd.set_properties({'gatherDiffuse':True})
    # Fixed probe field isolates camera motion from probe convergence.
    poses=[(0.1+0.04*i,1.,4.) for i in range(8)]
    record['motion_positions']=poses
    for mode in ['baseline','gather']:
        dd.set_properties({'finalGather':mode=='gather'})
        for i,pos in enumerate(poses):
            m.scene.camera.position=float3(*pos)
            m.scene.camera.target=float3(pos[0],1.,0.)
            frames(1);capture('motion-'+mode+'-'+str(i))
    m.scene.camera.position=float3(.1,1.,4.);m.scene.camera.target=float3(.1,1.,0.)
    for mode in ['baseline','gather']:
        dd.set_properties({'finalGather':mode=='gather','updateEnabled':True})
        timing(g,mode)
    # A conventional PT reference with the full primary contribution intact.
    ptg=RenderGraph('FinalGatherReference')
    ptg.addPass(createPass('GBufferRT',{'samplePattern':'Center','useAlphaTest':True,'useDOF':False}),'Visibility')
    pt=createPass('PathTracer',{'samplesPerPixel':8,'maxSurfaceBounces':19,
        'maxDiffuseBounces':19,'maxSpecularBounces':19,'maxTransmissionBounces':0,
        'useRussianRoulette':False,'useNEE':True,'useMIS':True,'useRTXDI':False,
        'useReSTIRPT':False,'colorFormat':'RGBA32F','fixedSeed':1})
    ptg.addPass(pt,'PT')
    for c in ['vbuffer','viewW','mvec']:ptg.addEdge('Visibility.'+c,'PT.'+c)
    acc=createPass('AccumulatePass',{'enabled':True,'autoReset':False,'precisionMode':'Single'})
    ptg.addPass(acc,'Accumulate');ptg.addEdge('PT.color','Accumulate.input')
    ptg.markOutput('Accumulate.output');ptg.markOutput('Visibility.normW')
    m.addGraph(ptg);m.setActiveGraph(ptg)
    for sequence,offset in [('reference',0),('reference-independent',104729)]:
        acc.reset();record['stage']=sequence;save()
        for i in range(4096):
            pt.fixedSeed=offset+i+1;renderFrame()
            if i==255:capture(sequence+'-2048spp')
        capture(sequence)
    record['stage']='motion references';save()
    for i,pos in enumerate(poses):
        m.scene.camera.position=float3(*pos);m.scene.camera.target=float3(pos[0],1.,0.)
        acc.reset()
        for j in range(64):pt.fixedSeed=200000+i*64+j;renderFrame()
        capture('motion-reference-'+str(i))
    ptg.updatePass('PT',{'samplesPerPixel':1})
    timing(ptg,'pt-1spp')
    # Native BRDF must produce nonzero specular and compile the two-lobe branch.
    m.setActiveGraph(g)
    m.loadScene(str(ROOT/'scripts/scenes/CornellRTXGI.pyscene'))
    dd.set_properties({'finalGather':True,'gatherDiffuse':True,'gatherSpecular':True,'updateEnabled':True})
    frames(256);capture('native-two-lobes')
    record['native_stats']=dict(dd.stats)
    record['stage']='complete';save()
    (OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:
    (OUT/'failure.txt').write_text(traceback.format_exc())
finally:
    exit()
