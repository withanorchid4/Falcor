from falcor import *
from pathlib import Path
import runpy,os,json,traceback
R=Path(__file__).resolve().parents[2]; O=R/'build/restir-temporal-cell-smoke';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-1080p-split-rerun/scene.json')
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 g=factory('half');runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))['configure_graph'](g)
 dd=g.getPass('DDGI');acc=g.getPass('Accumulate');acc.enabled=False
 assert not dd.stats['restirGather'], 'ReSTIR must remain off by default'
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
                   ('all-on',{'restirTemporal':True,'restirSpatial':True}),('feedback-odd',{'restirSpatialFeedback':True,'restirSpatialPasses':1}),('feedback-even',{'restirSpatialPasses':2}),('feedback-three',{'restirSpatialPasses':3}),('legacy-map',{'restirTemporalCellMapping':False}),('cell-map',{'restirTemporalCellMapping':True}),('feedback-off',{'restirSpatialFeedback':False,'restirSpatialPasses':2})]:
  dd.set_properties(props);renderFrame();capture(tag+'-reset');frames(8)
 capture('final');assert dd.stats['rejectedRaySamples']==0
 (O/'result.json').write_text(json.dumps(dict(dd.stats),indent=2))
 # Verify that changes restricted to ReSTIR leave ordinary FG bitwise unchanged.
 m.removeGraph(g);g=factory('half');runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))['configure_graph'](g)
 g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output')
 dd=g.getPass('DDGI');acc=g.getPass('Accumulate');acc.enabled=False
 dd.set_properties({'finalGather':False,'restirGather':False,'jitterHalfGather':True,'gatherSpecular':False})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
 frames(8192);dd.set_properties({'updateEnabled':False,'finalGather':True});acc.enabled=True;acc.reset()
 for i in range(1,257):
  renderFrame()
  if i in [1,16,256]:capture('fg-regression-'+str(i))
 (O/'complete.json').write_text(json.dumps({'fg_frames':256,'stats':dict(dd.stats)}))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
