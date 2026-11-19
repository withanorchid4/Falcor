from falcor import *
from pathlib import Path
import os,runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/restir-gather-material-smoke';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
def frames(n):
 for _ in range(n):renderFrame()
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-1080p-split-rerun/scene.json')
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('half')
 runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))['configure_graph'](g)
 dd=g.getPass('DDGI');dd.set_properties({'restirGather':True,'jitterHalfGather':True})
 g.getPass('Accumulate').enabled=False;g.markOutput('Reconstruct.color')
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellRTXGI.pyscene'))
 m.clock.pause();m.scene.camera.animated=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 for tag,on in [('half',False),('full',True)]:
  dd.set_properties({'restirFullResolution':on});frames(64)
  m.frameCapture.baseFilename=tag;m.frameCapture.capture()
 before=dd.stats['restirResetCount']
 light=m.scene.getLight('Ceiling Point');light.active=False;renderFrame()
 assert dd.stats['restirResetCount']>before,'Light edit did not clear cached radiance'
 (O/'result.json').write_text(json.dumps(dict(dd.stats),indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
