"""Verify tuned defaults at longer warmup and during continuous camera motion."""
from falcor import *
from pathlib import Path
import os,json,runpy,traceback
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'build/nrd-half-validation';OUT.mkdir(exist_ok=True)
for stale in ['complete.json','failure.txt']:(OUT/stale).unlink(missing_ok=True)
record={'warmup_windows':[512,4096],'window_frames':64,'probe_warmup':2048,
    'motion_frame_indices':[0,4,8,12,16,20,24,28],'motion_reference_spp':4096,'motion_resets':{}}
def frames(n):
    for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
def save():(OUT/'progress.json').write_text(json.dumps(record,indent=2))
try:
    os.environ['CORNELL_RTXGI_CONFIG']=str(ROOT/'build/three-way-half-gather/scene.json')
    factory=runpy.run_path(str(ROOT/'scripts/DDGIHalfGatherNRD.py'))['render_graph_DDGIHalfGatherNRD']
    for preset in ['legacy','tuned']:
        record['stage']=preset;save();g=factory(preset);g.name='Validate_'+preset
        dd=g.getPass('DDGI');dd.set_properties({'gridCounts':uint3(9,9,9),'raysPerProbe':256,'autoBounds':False,
            'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
            'normalBias':.02/.3,'viewBias':.1/.3,'hysteresis':.97,'useWRC':False})
        for c in ['Reconstruct.color','Visibility.normW']:g.markOutput(c)
        m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(ROOT/'scripts/scenes/CornellLambert.pyscene'))
        m.clock.pause();m.scene.camera.animated=False
        m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
        frames(2048);nrd=g.getPass('Denoiser');nrd.set_properties({'resetHistory':True});elapsed=0
        for warm in record['warmup_windows']:
            frames(warm-elapsed);elapsed=warm
            for i in range(64):frames(1);elapsed+=1;capture(preset+'-'+str(warm)+'-'+str(i))
        resets=nrd.resetHistoryCount
        for i in range(32):
            x=.1+.01*i;m.scene.camera.position=float3(x,1,4);m.scene.camera.target=float3(x,1,0)
            frames(1)
            if i in record['motion_frame_indices']:capture(preset+'-motion-'+str(i))
        record['motion_resets'][preset]=nrd.resetHistoryCount-resets
        m.scene.camera.position=float3(.1,1,4);m.scene.camera.target=float3(.1,1,0)
        frames(512);m.profiler.enabled=True;frames(32);m.profiler.start_capture();frames(256)
        (OUT/(preset+'-timing.json')).write_text(json.dumps(m.profiler.end_capture(),indent=2));m.profiler.enabled=False
        record[preset+'_stats']=dict(dd.stats);save()
    g=runpy.run_path(str(ROOT/'scripts/PTReference.py'))['PTReference'];g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
    pt=g.getPass('PT');acc=g.getPass('Accumulate');acc.set_properties({'autoReset':False})
    m.addGraph(g);m.setActiveGraph(g)
    for i in record['motion_frame_indices']:
        record['stage']='motion PT '+str(i);save()
        x=.1+.01*i;m.scene.camera.position=float3(x,1,4);m.scene.camera.target=float3(x,1,0)
        acc.reset()
        for j in range(512):pt.fixedSeed=500001+i*512+j;renderFrame()
        capture('motion-reference-'+str(i))
    record['stage']='complete';save();(OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
