from falcor import *
from pathlib import Path
import json, os, time, traceback

ROOT=Path('F:/')
STATE=json.loads((ROOT/'build/gi-evaluation-current.json').read_text())
WORK=Path(STATE['work']);RESULT=Path(STATE['result'])
MODE=os.environ.get('GI_CASE','ddgi')
OUT=WORK/os.environ.get('GI_OUT',MODE);OUT.mkdir(exist_ok=True)
SMOKE=os.environ.get('GI_SMOKE','0')=='1'
records={'mode':MODE,'captures':[],'measurements':[],'started_at':time.time()}
def serial(x):
    if isinstance(x,dict):return {str(k):serial(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [serial(v) for v in x]
    if isinstance(x,(str,int,float,bool)) or x is None:return x
    if hasattr(x,'x'):return [getattr(x,c) for c in ['x','y','z','w'] if hasattr(x,c)]
    return str(x)
def capture(tag,frame):
    m.frameCapture.baseFilename=tag
    m.frameCapture.capture()
    records['captures'].append({'tag':tag,'frame':frame,'elapsed_seconds':time.perf_counter()-start})
def persist():
    (OUT/'progress.json').write_text(json.dumps(serial(records),indent=2))
try:
    os.environ['CORNELL_RTXGI_CONFIG']=str(RESULT/'reproduction/scene.json')
    g=RenderGraph('GIEvaluation')
    g.addPass(createPass('GBufferRT',{'samplePattern':'Center','useAlphaTest':True,'useDOF':False}),'Visibility')
    g.markOutput('Visibility.normW')
    g.markOutput('Visibility.diffuseOpacity')
    if MODE=='ddgi':
        opts={'gridCounts':uint3(9,9,9),'raysPerProbe':256,'hysteresis':.97,
            'normalBias':.02/.3,'viewBias':.1/.3,'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
            'autoBounds':False,'enableRelocation':True,'enableClassification':True,'useRTXDI':False,'useWRC':False,
            'showProbes':False,'indirectOnly':True,'intensity':1.0}
        g.addPass(createPass('RTXGIDDGI',opts),'DDGI')
        g.addEdge('Visibility.vbuffer','DDGI.vbuffer');g.addEdge('Visibility.viewW','DDGI.viewW')
        g.markOutput('DDGI.indirect')
    else:
        opts={'samplesPerPixel':8,'maxSurfaceBounces':19,'maxDiffuseBounces':19,'maxSpecularBounces':19,'maxTransmissionBounces':0,
            'useRussianRoulette':False,'useNEE':True,'useMIS':True,'useRTXDI':False,'useReSTIRPT':False,
            'useNRDDemodulation':False,'colorFormat':'RGBA32F','tracePassMode':os.environ.get('GI_PT_TRACE','MinimalPayload'),'fixedSeed':1}
        g.addPass(createPass('PathTracer',opts),'PT')
        for c in ['vbuffer','viewW','mvec']:g.addEdge('Visibility.'+c,'PT.'+c)
        g.addPass(createPass('AccumulatePass',{'enabled':True,'autoReset':False,'precisionMode':'Single','maxFrameCount':0}),'Accumulate')
        g.addEdge('PT.nrdDiffuseRadianceHitDist','Accumulate.input')
        g.markOutput('Accumulate.output')
        # Also retain the full indirect result for separating primary specular paths.
        g.addPass(createPass('AccumulatePass',{'enabled':True,'autoReset':False,'precisionMode':'Single','maxFrameCount':0}),'AccumulateAll')
        g.addEdge('PT.color','AccumulateAll.input');g.markOutput('AccumulateAll.output')
    m.addGraph(g);m.setActiveGraph(g)
    m.loadScene(os.environ.get('GI_SCENE',str(ROOT/'scripts/scenes/CornellRTXGI.pyscene')))
    m.clock.pause();m.scene.camera.animated=False
    m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
    records['options']=serial(opts)
    records['camera']={k:serial(getattr(m.scene.camera,k)) for k in ['position','target','up','focalLength','frameHeight','aspectRatio']}
    start=time.perf_counter()
    if MODE=='ddgi':
        ddgi=g.getPass('DDGI')
        end=4 if SMOKE else 16416
        for frame in range(1,end+1):
            renderFrame()
            if frame in [4,256,1024,4096,8192,16384] or frame>=16385:
                capture('frame-'+str(frame),frame)
                if frame<=16384:records['measurements'].append({'frame':frame,'stats':dict(ddgi.stats)})
                persist()
            elif frame%512==0:
                records['current_frame']=frame;persist()
        assert ddgi.updatedFrames==end,(ddgi.updatedFrames,end)
        if not SMOKE:
            m.profiler.enabled=True
            for _ in range(16):renderFrame()
            m.profiler.start_capture()
            for _ in range(512):renderFrame()
            (OUT/'timing.json').write_text(json.dumps(m.profiler.end_capture(),indent=2))
            m.profiler.enabled=False
    else:
        pt=g.getPass('PT')
        offset=104729 if MODE=='pt-b' else 0
        end=2 if SMOKE else int(os.environ.get('GI_PT_FRAMES','4096'))
        for frame in range(1,end+1):
            pt.fixedSeed=offset+frame
            renderFrame()
            if frame in [2,128,512,1024,2048,4096] or frame==end:
                capture('frame-'+str(frame),frame);persist()
            elif frame%128==0:
                records['current_frame']=frame;persist()
        records['spp']=end*8
    records['completed_at']=time.time();persist()
    (OUT/'complete.json').write_text(json.dumps(serial(records),indent=2))
except Exception:
    (OUT/'failure.txt').write_text(traceback.format_exc())
    print(traceback.format_exc(),flush=True)
finally:
    exit()
