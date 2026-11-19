"""Sponza Lambert: fresh 1080p DDGI / half FG / full FG and independent PT."""
from falcor import *
from pathlib import Path
import os, json, runpy, traceback, time, hashlib

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'build/sponza-lambert-1080p-20261119'
OUT.mkdir(exist_ok=True)
assert not (OUT/'complete.json').exists(), 'Do not overwrite a completed experiment'
N = 65536
record = {'resolution':[1920,1080], 'half_resolution':[960,540],
    'probe_warmup':8192, 'probe_frozen':False, 'jitter':False,
    'accumulation_frames':N, 'checkpoints':[2**i for i in range(17)],
    'stable_capture_frames':32, 'nrd':False, 'pt_spp_per_frame':8,
    'pt_total_spp':131072, 'full_resolution_integration':False,
    'restir':False, 'started':time.time(), 'runs':{}}
sources = ['Source/RenderPasses/RTXGIDDGI/'+f for f in
    ['RTXGIDDGI.cpp','RTXGIDDGI.h','RTXGIDDGI.rt.slang','ReSTIRGather.slang','DDGIReconstruct.cs.slang']]
sources += ['scripts/scenes/Sponza.pyscene','scripts/scenes/SponzaLambert.pyscene','media/Sponza/Sponza.gltf','scripts/DDGIAccumulated.py','scripts/PTReference.py', 'tests/ddgi/sponza_lambert_comparison.py']
record['source_hashes'] = {f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sources}

def save(stage):
    record['stage']=stage; record['elapsed_seconds']=time.time()-record['started']
    (OUT/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
    for _ in range(n): renderFrame()
def capture(tag):
    m.frameCapture.baseFilename=tag; m.frameCapture.capture()
def activate(g):
    g.updatePass('Accumulate', {'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
    g.unmarkOutput('Display.dst'); g.markOutput('Accumulate.output')
    m.addGraph(g); m.setActiveGraph(g)
    m.loadScene(str(ROOT/'scripts/scenes/SponzaLambert.pyscene'))
    m.clock.pause(); m.scene.camera.animated=False
    m.frameCapture.outputDir=str(OUT); m.frameCapture.captureAllOutputs=False

try:
    (OUT/'scene.json').write_text(json.dumps({'scene':'SponzaLambert','pointLight':{'position':[0,4,0],'intensity':[600,600,600]},'probeGrid':[24,12,16],'raysPerProbe':256,'hysteresis':.97,'normalBiasFraction':.05,'viewBiasFraction':.05,'autoBounds':True,'accumulatePrecision':'SingleCompensated'},indent=2))
    def configure_display(g):
        g.updatePass('Display', {'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
    factory=runpy.run_path(str(ROOT/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
    for name,mode,re,temporal in [('ddgi','ddgi',False,False),('half','half',False,False),
            ('full','full',False,False)]:
        save(name+' setup'); g=factory(mode); g.name='Highres_'+name
        configure_display(g); dd=g.getPass('DDGI')
        dd.set_properties({'autoBounds':True,'gridCounts':uint3(24,12,16),'useWRC':False,'useRTXDI':False})
        dd.set_properties({'finalGather':False,'restirGather':False,'restirFullResolution':False,
            'jitterHalfGather':False,'gatherSpecular':False,'restirTemporal':temporal,'restirSpatial':True,
            'restirSpatialFeedback':False,'restirTemporalCellMapping':True,'restirBiasCorrection':True,
            'restirSpatialPasses':2,'restirSpatialSamples':4,'restirSpatialRadius':8.,
            'restirHistoryLength':20,'restirMaxAge':0})
        activate(g); acc=g.getPass('Accumulate'); acc.enabled=False
        save(name+' warmup'); frames(8192)
        dd.set_properties({'finalGather':mode!='ddgi','restirGather':re})
        acc.enabled=True; acc.reset()
        for i in range(1,N+1):
            renderFrame()
            if i in record['checkpoints']: capture(name+'-'+str(i))
            if i%2048==0: save(name+' '+str(i)+'/65536')
        stats=dict(dd.stats)
        assert stats['finite'] and stats['rejectedRaySamples']==0, stats
        record['runs'][name]={'stats':stats,'mode':mode,'restir':re,'temporal':temporal}
        raw='Reconstruct.color' if mode=='half' else 'DDGI.color'
        g.markOutput(raw)
        for i in range(32): frames(1); capture(name+'-stable-'+str(i))
        g.unmarkOutput(raw); g.markOutput('Display.dst'); frames(64)
        m.profiler.enabled=True; frames(16); m.profiler.start_capture(); frames(512)
        (OUT/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()))
        m.profiler.enabled=False; save(name+' finished'); m.removeGraph(g)
    g=runpy.run_path(str(ROOT/'scripts/PTReference.py'))['PTReference']
    configure_display(g); activate(g)
    g.markOutput('Visibility.normW'); frames(1); capture('mask'); g.unmarkOutput('Visibility.normW')
    pt=g.getPass('PT'); acc=g.getPass('Accumulate'); pt.useFixedSeed=True
    for seq,offset in [('a',1),('b',100001)]:
        acc.reset()
        for i in range(8192):
            pt.fixedSeed=offset+i; renderFrame()
            if i+1 in [1024,2048,4096,8192]: capture('pt-'+seq+'-'+str((i+1)*8))
            if (i+1)%256==0: save('PT '+seq+' '+str((i+1)*8)+'/65536 spp')
    save('complete'); (OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:
    (OUT/'failure.txt').write_text(traceback.format_exc())
finally:
    exit()
