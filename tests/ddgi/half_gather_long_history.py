"""Extend unchanged half-resolution NRD warmup, sampling 64-frame windows."""
from falcor import *
from pathlib import Path
import os,json,runpy,traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/half-gather-long-history';OUT.mkdir(exist_ok=True)
for stale in ['complete.json','failure.txt']:(OUT/stale).unlink(missing_ok=True)
record={'warmup_windows':[512,1024,2048,4096],'window_frames':64,'probe_warmup':2048}
def frames(n):
    for _ in range(n):renderFrame()
def save():(OUT/'progress.json').write_text(json.dumps(record,indent=2))
try:
    os.environ['CORNELL_RTXGI_CONFIG']=str(ROOT/'build/three-way-half-gather/scene.json')
    g=runpy.run_path(str(ROOT/'scripts/DDGIHalfGatherNRD.py'))['render_graph_DDGIHalfGatherNRD'](preset='legacy')
    dd=g.getPass('DDGI');dd.set_properties({'gridCounts':uint3(9,9,9),'raysPerProbe':256,'autoBounds':False,
        'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
        'normalBias':.02/.3,'viewBias':.1/.3,'hysteresis':.97,'useWRC':False})
    for c in ['Reconstruct.color','Visibility.normW']:g.markOutput(c)
    m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(ROOT/'scripts/scenes/CornellLambert.pyscene'))
    m.clock.pause();m.scene.camera.animated=False
    m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
    record['stage']='probe warmup';save();frames(2048)
    nrd=g.getPass('Denoiser');nrd.set_properties({'resetHistory':True})
    elapsed=0;resets=[]
    for warm in record['warmup_windows']:
        record['stage']='NRD warmup '+str(warm);save()
        frames(warm-elapsed);elapsed=warm
        for i in range(64):
            renderFrame();elapsed+=1
            m.frameCapture.baseFilename='warm-'+str(warm)+'-'+str(i);m.frameCapture.capture()
        resets.append(nrd.resetHistoryCount)
    record['history_reset_counts']=resets;assert len(set(resets))==1,resets
    record['stats']=dict(dd.stats);record['stage']='complete';save()
    (OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
