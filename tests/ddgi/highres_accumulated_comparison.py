"""1080p Lambert comparison; independent PT reference and equal DDGI accumulation."""
from falcor import *
from pathlib import Path
import os, json, runpy, traceback, time
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/highres-1080p-split-rerun';OUT.mkdir(exist_ok=True)
(OUT/'failure.txt').unlink(missing_ok=True)
(OUT/'complete.json').unlink(missing_ok=True)
record={'resolution':[1920,1080],'half_resolution':[960,540],'probe_warmup':2560,
        'accumulation_frames':65536,'checkpoints':[8192,16384,32768,65536],
        'stable_capture_frames':8,'nrd':False,'pt_spp_per_frame':8,'pt_total_spp':65536,
        'dispatch_layout':'full primary shading + independent half-resolution gather; original reconstruction',
        'started':time.time()}
def save(stage):
 record['stage']=stage;record['elapsed_seconds']=time.time()-record['started']
 (OUT/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
def activate(g):
 g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output')
 m.addGraph(g);m.setActiveGraph(g)
 m.loadScene(str(ROOT/'scripts/scenes/CornellLambert.pyscene'))
 m.clock.pause();m.scene.camera.animated=False
 m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
try:
 cfg=json.loads((ROOT/'scripts/scenes/CornellRTXGI.json').read_text())
 cfg['directionalLight']['enabled']=False;cfg['ceilingPointLight']['enabled']=True
 cfg['display']['exposureStops']=3.0
 (OUT/'scene.json').write_text(json.dumps(cfg,indent=2))
 os.environ['CORNELL_RTXGI_CONFIG']=str(OUT/'scene.json')
 setup=runpy.run_path(str(ROOT/'scripts/scenes/cornell_rtxgi.py'))
 factory=runpy.run_path(str(ROOT/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for mode in ['ddgi','half','full']:
  g=factory(mode);setup['configure_graph'](g);activate(g)
  acc=g.getPass('Accumulate');acc.set_properties({'autoReset':False})
  save(mode+' warmup');frames(2560);acc.reset()
  for i in range(1,65537):
   renderFrame()
   if i in record['checkpoints']:capture(mode+'-'+str(i))
   if i%2048==0:save(mode+' '+str(i)+'/65536')
  for i in range(8):frames(1);capture(mode+'-stable-'+str(i))
  g.markOutput('Display.dst')
  frames(64);m.profiler.enabled=True;frames(16);m.profiler.start_capture();frames(256)
  (OUT/(mode+'-timing.json')).write_text(json.dumps(m.profiler.end_capture(),indent=2));m.profiler.enabled=False
  record[mode+'_stats']=dict(g.getPass('DDGI').stats);save(mode+' finished')
  m.removeGraph(g)
 g=runpy.run_path(str(ROOT/'scripts/PTReference.py'))['PTReference'];setup['configure_display'](g);activate(g)
 g.markOutput('Visibility.normW');frames(1);capture('mask');g.unmarkOutput('Visibility.normW')
 pt=g.getPass('PT');acc=g.getPass('Accumulate');acc.set_properties({'autoReset':False})
 for seq,offset in [('a',1),('b',100001)]:
  acc.reset()
  for i in range(4096):
   pt.fixedSeed=offset+i;renderFrame()
   if i+1 in [1024,2048,4096]:capture('pt-'+seq+'-'+str((i+1)*8))
   if (i+1)%256==0:save('PT '+seq+' '+str((i+1)*8)+'/32768 spp')
 save('complete');(OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
