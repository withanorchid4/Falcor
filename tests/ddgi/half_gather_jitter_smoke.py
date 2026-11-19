from falcor import *
from pathlib import Path
import os,runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/half-gather-jitter-smoke';O.mkdir(exist_ok=True)
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-1080p-split-rerun/scene.json')
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('half')
 runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))['configure_graph'](g)
 dd=g.getPass('DDGI');acc=g.getPass('Accumulate');dd.set_properties({'jitterHalfGather':True});acc.enabled=False
 for c in ['DDGI.gatherDiffuse','Accumulate.output','Reconstruct.color']:g.markOutput(c)
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 for _ in range(64):renderFrame()
 phases=[]
 def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
 for i in range(8):
  renderFrame();frame=dd.updatedFrames-1;phases.append([(frame&7)>>2,frame&1]);capture('phase-'+str(i))
 acc.enabled=True
 for _ in range(8):renderFrame()
 for tag,props in [('fixed',{'jitterHalfGather':False}),('jitter',{'jitterHalfGather':True}),('full',{'halfResolutionGather':False}),('half',{'halfResolutionGather':True}),('off',{'finalGather':False})]:
  dd.set_properties(props);renderFrame();capture(tag+'-reset')
  for _ in range(3):renderFrame()
 (O/'result.json').write_text(json.dumps({'passed':True,'phases':phases}))
except Exception:(O/'result.json').write_text(json.dumps({'passed':False,'error':traceback.format_exc()}))
finally:exit()
