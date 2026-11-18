"""Matched before/after captures and repeated 1080p GPU timings."""
from falcor import *
from pathlib import Path
import os,runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/half-gather-optimization'/os.environ.get('DDGI_OPT_TAG','baseline');O.mkdir(parents=True,exist_ok=True)
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-accumulated-comparison/scene.json')
 setup=runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 graphs={}
 for mode in ['ddgi','half','full']:
  g=factory(mode);setup['configure_graph'](g);g.markOutput('Accumulate.output');m.addGraph(g);graphs[mode]=g
 m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 def frames(n):
  for _ in range(n):renderFrame()
 for mode,g in graphs.items():
  m.setActiveGraph(g);frames(1024);g.getPass('Accumulate').reset();frames(32)
  m.frameCapture.baseFilename=mode;m.frameCapture.capture()
 for round in range(3):
  for mode in (['ddgi','half','full'] if round%2==0 else ['full','half','ddgi']):
   m.setActiveGraph(graphs[mode]);frames(64);m.profiler.enabled=True;frames(16);m.profiler.start_capture();frames(512)
   (O/(mode+'-'+str(round)+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
 (O/'complete.json').write_text(json.dumps({'passed':True}))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
