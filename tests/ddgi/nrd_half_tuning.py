"""Controlled RELAX ablations; identical 2048+512 warmup and 32-frame windows."""
from falcor import *
from pathlib import Path
import os,json,runpy,traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ.get('NRD_TUNING_OUT',ROOT/'build/nrd-half-tuning'));OUT.mkdir(exist_ok=True)
for stale in ['complete.json','failure.txt']:(OUT/stale).unlink(missing_ok=True)
combo={'diffusePrepassBlurRadius':0.,'atrousIterationNum':3,'diffuseMaxAccumulatedFrameNum':63,
    'diffuseMaxFastAccumulatedFrameNum':8,'historyClampingColorBoxSigmaScale':3.}
variants={'baseline':{},'offset_only':{'inputSampleOffset':float2(-.25,-.25)},
    'pre0':{'diffusePrepassBlurRadius':0.},'pre4':{'diffusePrepassBlurRadius':4.},
    'pre8':{'diffusePrepassBlurRadius':8.},'atrous3':{'atrousIterationNum':3},
    'fast8':{'diffuseMaxFastAccumulatedFrameNum':8},'history63':{'diffuseMaxAccumulatedFrameNum':63},
    'clamp3':{'historyClampingColorBoxSigmaScale':3.},
    'combo0':{**combo,'inputSampleOffset':float2(-.25,-.25)},
    'combo4':{**combo,'diffusePrepassBlurRadius':4.,'inputSampleOffset':float2(-.25,-.25)},
    'combo2':{**combo,'atrousIterationNum':2,'inputSampleOffset':float2(-.25,-.25)}}
if os.environ.get('NRD_TUNING_VARIANTS'):
    variants=json.loads(Path(os.environ['NRD_TUNING_VARIANTS']).read_text())
    for props in variants.values():
        if 'inputSampleOffset' in props:props['inputSampleOffset']=float2(*props['inputSampleOffset'])
record={'variants':{k:{p:([v.x,v.y] if p=='inputSampleOffset' else v) for p,v in d.items()} for k,d in variants.items()},
    'resolution':[480,270],'probe_warmup':2048,'nrd_warmup':512,'capture_frames':32,'resets':{}}
def save():(OUT/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
    for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
    os.environ['CORNELL_RTXGI_CONFIG']=str(ROOT/'build/three-way-half-gather/scene.json')
    factory=runpy.run_path(str(ROOT/'scripts/DDGIHalfGatherNRD.py'))['render_graph_DDGIHalfGatherNRD']
    for name,props in variants.items():
        record['stage']=name;save()
        g=factory(preset='legacy');g.name='Tuning_'+name
        dd=g.getPass('DDGI');dd.set_properties({'gridCounts':uint3(9,9,9),'raysPerProbe':256,'autoBounds':False,
            'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
            'normalBias':.02/.3,'viewBias':.1/.3,'hysteresis':.97,'useWRC':False})
        nrd=g.getPass('Denoiser');nrd.set_properties(props)
        g.markOutput('Reconstruct.color');g.markOutput('Visibility.normW')
        m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(ROOT/'scripts/scenes/CornellLambert.pyscene'))
        m.clock.pause();m.scene.camera.animated=False
        m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
        frames(2048);nrd.set_properties({'resetHistory':True});frames(512)
        before=nrd.resetHistoryCount
        for i in range(32):frames(1);capture(name+'-'+str(i))
        record['resets'][name]=nrd.resetHistoryCount-before
        if name=='baseline':
            # Same-frame NRD-disabled round trip and exact guide/sample alignment audit.
            g.addPass(createPass('DDGIReconstruct',{}),'RawReconstruct')
            for c in ['diffuse','specular']:
                g.addEdge('DDGI.'+c+'RadianceHitDist','RawReconstruct.'+c)
                g.addEdge('DDGI.'+c+'Reflectance','RawReconstruct.'+c+'Reflectance')
            g.addEdge('DDGI.unfilteredColor','RawReconstruct.direct')
            g.addEdge('Visibility.normW','RawReconstruct.normal');g.addEdge('Visibility.linearZ','RawReconstruct.depth')
            for c in ['RawReconstruct.color','DDGI.diffuseRadianceHitDist','DDGI.specularRadianceHitDist',
                'DDGI.diffuseReflectance','DDGI.unfilteredColor','Guides.halfDepth','Guides.halfNormalRoughness',
                'Guides.halfMotion','Visibility.linearZ','Visibility.normWRoughnessMaterialID','Visibility.mvecW']:
                g.markOutput(c)
            nrd.set_properties({'enabled':False});frames(1);capture('audit')
        record[name+'_stats']=dict(dd.stats);save()
    record['stage']='complete';save();(OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
