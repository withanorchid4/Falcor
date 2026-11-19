from falcor import *
from pathlib import Path
import runpy,os,json,traceback,time
R=Path(__file__).resolve().parents[2];O=R/'build/restir-gather-ablation';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-1080p-split-rerun/scene.json')
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 setup=runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))
 for name,en,t,s in [('baseline',False,False,False),('initial',True,False,False),('temporal',True,True,False),('spatial',True,False,True),('all',True,True,True)]:
  g=factory('full');g.name='Ablation_'+name;setup['configure_graph'](g)
  dd=g.getPass('DDGI');acc=g.getPass('Accumulate')
  dd.set_properties({'restirFullResolution':True,'restirGather':en,'restirTemporal':t,'restirSpatial':s,'restirIntegrateSamples':1,'restirIntegrateRadius':0.0,'jitterHalfGather':False})
  g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  (O/'progress.txt').write_text(name+' warmup');frames(2560);acc.reset()
  for i in range(1,16385):
   renderFrame()
   if i in [8192,16384]:capture(name+'-'+str(i));(O/'progress.txt').write_text(name+' '+str(i))
  m.removeGraph(g)
 (O/'complete.json').write_text(json.dumps({'passed':True,'size':[640,360],'frames':16384}))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
