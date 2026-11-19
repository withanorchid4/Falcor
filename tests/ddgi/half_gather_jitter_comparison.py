"""Fixed versus eight-frame 2x2 sample-phase jitter; same static scene and seeds."""
from falcor import *
from pathlib import Path
import os,runpy,json,time,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/half-gather-jitter';O.mkdir(exist_ok=True)
record={'resolution':[1920,1080],'warmup':2560,'checkpoints':[1,4,8,32,128,1024,32768,65536],
 'sequence':[[0,0],[0,1],[0,0],[0,1],[1,0],[1,1],[1,0],[1,1]],'started':time.time()}
def progress(stage):record['stage']=stage;record['elapsed']=time.time()-record['started'];(O/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-1080p-split-rerun/scene.json')
 setup=runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,jitter in [('fixed',False),('jitter',True)]:
  g=factory('half');g.name='HalfGather_'+name;setup['configure_graph'](g)
  g.getPass('DDGI').set_properties({'jitterHalfGather':jitter})
  g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output');m.addGraph(g);m.setActiveGraph(g)
  m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  progress(name+' warmup');frames(2560);g.getPass('Accumulate').reset()
  for i in range(1,65537):
   renderFrame()
   if i in record['checkpoints']:capture(name+'-'+str(i))
   if i%4096==0:progress(name+' '+str(i))
  for i in range(8):frames(1);capture(name+'-stable-'+str(i))
  g.markOutput('Display.dst');frames(64);m.profiler.enabled=True;frames(16);m.profiler.start_capture();frames(512)
  (O/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  m.removeGraph(g)
 progress('complete');(O/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
