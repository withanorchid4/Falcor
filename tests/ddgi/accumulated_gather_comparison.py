"""Converged DDGI / half FG / full FG with NRD entirely removed."""
from falcor import *
from pathlib import Path
import os,json,runpy,traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/accumulated-gather-comparison';OUT.mkdir(exist_ok=True)
for stale in ['complete.json','failure.txt']:(OUT/stale).unlink(missing_ok=True)
record={'resolution':[480,270],'probe_warmup':2560,'accumulation_frames':65536,
    'checkpoints':[1024,4096,8192,16384,32768,65536],'stable_capture_frames':64,
    'probe_updates':True,'nrd':False,'accumulation_precision':'Single'}
def save():(OUT/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
    for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
    os.environ['CORNELL_RTXGI_CONFIG']=str(ROOT/'build/three-way-half-gather/scene.json')
    factory=runpy.run_path(str(ROOT/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
    for mode in ['ddgi','half','full']:
        g=factory(mode);dd=g.getPass('DDGI');acc=g.getPass('Accumulate')
        dd.set_properties({'gridCounts':uint3(9,9,9),'raysPerProbe':256,'autoBounds':False,
            'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
            'normalBias':.02/.3,'viewBias':.1/.3,'hysteresis':.97,'useWRC':False})
        acc.set_properties({'autoReset':False})
        g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
        m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(ROOT/'scripts/scenes/CornellLambert.pyscene'))
        m.clock.pause();m.scene.camera.animated=False
        m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
        record['stage']=mode+' probe warmup';save();frames(2560);acc.reset()
        for i in range(1,65537):
            renderFrame()
            if i in record['checkpoints']:capture(mode+'-'+str(i))
            if i%4096==0:record['stage']=mode+' accumulated '+str(i);save()
        for i in range(64):frames(1);capture(mode+'-stable-'+str(i))
        frames(128);m.profiler.enabled=True;frames(32);m.profiler.start_capture();frames(256)
        (OUT/(mode+'-timing.json')).write_text(json.dumps(m.profiler.end_capture(),indent=2));m.profiler.enabled=False
        record[mode+'_stats']=dict(dd.stats);save()
    record['stage']='complete';save();(OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
