from falcor import *
from pathlib import Path
import os,runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/probe-visualization'/os.environ.get('PROBE_VIS_PHASE','verified');O.mkdir(exist_ok=True)
try:
 os.environ['FALCOR_START_SCENE']='SponzaLambert';os.environ['FALCOR_START_RENDERER']='DDGI'
 gs=runpy.run_path(str(R/'scripts/GIPreview.py'))['graphs'];g=gs['RTXGIDDGI'];m.addGraph(g);m.setActiveGraph(g)
 m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();g.getPass('Accumulate').enabled=False
 dd=g.getPass('DDGI');m.frameCapture.outputDir=str(O)
 for _ in range(128):renderFrame()
 for fg in [False,True]:
  for show in [False,True]:
   key=('half' if fg else 'ddgi')+('-on' if show else '-off')
   dd.set_properties({'finalGather':fg,'halfResolutionGather':True,'showProbes':show,'restirGather':False})
   for _ in range(64):renderFrame()
   m.frameCapture.baseFilename=key;m.frameCapture.capture()
   m.profiler.enabled=True
   for _ in range(4):renderFrame()
   m.profiler.start_capture()
   for _ in range(512):renderFrame()
   (O/(key+'.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
 # Exercise resource resizing, scene/grid changes and all gather dispatch paths.
 for name,props in [('full',{'halfResolutionGather':False}),('restir',{'halfResolutionGather':True,'restirGather':True}),('grid',{'restirGather':False,'gridCounts':uint3(9,9,9)}),('frozen',{'updateEnabled':False})]:
  dd.set_properties(props)
  for _ in range(8):renderFrame()
  assert dd.stats['finite'] and dd.stats['rejectedRaySamples']==0
  m.frameCapture.baseFilename=name;m.frameCapture.capture()
 resizeFrameBuffer(401,301)
 for _ in range(8):renderFrame()
 m.frameCapture.baseFilename='resize';m.frameCapture.capture()
 dd.set_properties({'showProbes':False})
 for _ in range(8):renderFrame()
 dd.set_properties({'showProbes':True})
 m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'))
 for _ in range(8):renderFrame()
 m.frameCapture.baseFilename='scene-switch';m.frameCapture.capture()
 g.removeEdge('Visibility.viewW','DDGI.viewW')
 g.updatePass('Visibility',{'samplePattern':'Halton','useAlphaTest':True,'useDOF':False})
 m.scene.camera.position=float3(0.,1.,4.)
 for _ in range(8):renderFrame()
 m.frameCapture.baseFilename='no-view-jitter';m.frameCapture.capture()
 (O/'complete.json').write_text(json.dumps(dict(dd.stats)))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
