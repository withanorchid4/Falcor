from falcor import *
from pathlib import Path
import runpy,os,json,traceback
R=Path(__file__).resolve().parents[2]; O=R/'build/restir-gather-smoke';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-1080p-split-rerun/scene.json')
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 g=factory('half');runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))['configure_graph'](g)
 dd=g.getPass('DDGI');acc=g.getPass('Accumulate');acc.enabled=False
 dd.set_properties({'restirGather':True,'jitterHalfGather':True,'restirFullResolution':True})
 for c in ['DDGI.restirDebug','DDGI.color','Reconstruct.color','Accumulate.output']:g.markOutput(c)
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'))
 m.clock.pause();m.scene.camera.animated=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 frames(128);capture('static')
 before=dd.stats['restirResetCount']
 for i in range(8):
  m.scene.camera.position+=float3(.002,0,0);renderFrame()
  if i in [0,7]:capture('moving-'+str(i))
 assert dd.stats['restirResetCount']==before,'Camera movement reset instead of reprojecting'
 acc.enabled=True;frames(4)
 for tag,props in [('integration-on',{'restirFullResolution':True}),('integration-off',{'restirFullResolution':False}),('spatial-off',{'restirSpatial':False}),('temporal-off',{'restirTemporal':False}),
                   ('restir-off',{'restirGather':False}),('restir-on',{'restirGather':True}),
                   ('full',{'halfResolutionGather':False}),('half',{'halfResolutionGather':True}),
                   ('fg-off',{'finalGather':False}),('fg-on',{'finalGather':True}),
                   ('all-on',{'restirTemporal':True,'restirSpatial':True})]:
  dd.set_properties(props);renderFrame();capture(tag+'-reset');frames(8)
 capture('final');(O/'result.json').write_text(json.dumps(dict(dd.stats),indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
