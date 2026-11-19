from falcor import *
from pathlib import Path
import runpy,os,json,time,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/restir-weight-audit';O.mkdir(exist_ok=True)
record={'runs':{},'started':time.time(),'probe_warmup':8192,'resolution':[640,360]}
def frames(n):
 for _ in range(n):renderFrame()
def progress(s):
 record['stage']=s;record['elapsed']=time.time()-record['started'];(O/'progress.json').write_text(json.dumps(record,indent=2))
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-1080p-split-rerun/scene.json')
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 setup=runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))
 cases=[('fg',False,False,False,False,131072),('uniform',True,False,False,True,32768)]
 for correction in [False,True]:
  for mode,t,s in [('temporal',True,False),('spatial',False,True),('both',True,True)]:cases.append((('fixed-' if correction else 'legacy-')+mode,True,t,s,correction,32768))
 for name,re,t,s,correction,n in cases:
  progress(name+' setup');g=factory('half');g.name='Audit_'+name;setup['configure_graph'](g)
  dd=g.getPass('DDGI');acc=g.getPass('Accumulate')
  dd.set_properties({'finalGather':False,'restirGather':False,'restirFullResolution':False,'jitterHalfGather':True,'gatherSpecular':False,'restirTemporal':t,'restirSpatial':s,'restirBiasCorrection':correction,'restirSpatialPasses':2,'restirSpatialSamples':4,'restirHistoryLength':20})
  acc.enabled=False;g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  progress(name+' warmup');frames(8192)
  dd.set_properties({'updateEnabled':False,'finalGather':True,'restirGather':re});acc.enabled=True;acc.reset()
  previous=0
  for stop in [16,64,256,1024,4096,16384,32768,65536,131072]:
   if stop>n:break
   progress(name+' '+str(stop));frames(stop-previous);previous=stop
   m.frameCapture.baseFilename=name+'-'+str(stop);m.frameCapture.capture()
  record['runs'][name]=dict(dd.stats);assert record['runs'][name]['updatedFrames']==8192
  m.removeGraph(g)
 progress('complete');(O/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
