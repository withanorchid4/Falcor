"""Extend corrected temporal+spatial ReSTIR until two successive tail doublings stabilize."""
from falcor import *
from pathlib import Path
import os,runpy,time,json,traceback,sys,subprocess
R=Path(__file__).resolve().parents[2];O=R/'build/restir-pt-long-tail';O.mkdir(exist_ok=True);D=R/'build/restir-pt-convergence'
record={'started':time.time(),'checkpoints':{},'max_frames':2097152,'stability_requirement':'two successive MSE changes <2%, each image delta MSE / PT MSE <1%','seed_offset':0,'accumulation_precision':'SingleCompensated','runs':{}}
def frames(n):
 for _ in range(n):renderFrame()
def progress(s):
 record['stage']=s;record['elapsed']=time.time()-record['started'];(O/'progress.json').write_text(json.dumps(record,indent=2))
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(D/'scene.json')
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated'];setup=runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))
 for name in ['fg','spatial','restir']:
  run={'checkpoints':{}};record['runs'][name]=run
  g=factory('half');g.name='LongTail_'+name;setup['configure_graph'](g);dd=g.getPass('DDGI');g.updatePass('Accumulate',{'enabled':True,'autoReset':True,'precisionMode':'SingleCompensated'});acc=g.getPass('Accumulate')
  dd.set_properties({'finalGather':False,'restirGather':False,'restirFullResolution':False,'jitterHalfGather':True,'gatherSpecular':False,'restirTemporal':name=='restir','restirSpatial':True,'restirBiasCorrection':True,'restirSpatialPasses':2,'restirSpatialSamples':4,'restirSpatialRadius':8.,'restirHistoryLength':20})
  acc.enabled=False;g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output');m.addGraph(g);m.setActiveGraph(g)
  m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False;m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  progress('probe warmup');frames(8192)
  dd.set_properties({'updateEnabled':False,'finalGather':True,'restirGather':name!='fg'});acc.enabled=True;acc.reset()
  streak=0;last=0
  for stop in ([32768,65536,131072,262144,524288,1048576,2097152] if name=='restir' else [32768,65536,131072]):
   for i in range(last,stop,8192):frames(min(8192,stop-i));progress(name+' '+str(min(i+8192,stop)))
   capture(name+'-'+str(stop))
   proc=subprocess.run(['python',str(R/'tests/ddgi/restir_pt_tail_metric.py'),name,str(stop),str(last)],capture_output=True,text=True,creationflags=0x08000000,check=True)
   v=json.loads(proc.stdout)
   if last:
    stable=abs(v['relative_mse_change'])<.02 and v['tail_over_error']<.01
    streak=streak+1 if stable else 0
   run['checkpoints'][str(stop)]=v;run['stable_streak']=streak;progress('checkpoint '+str(stop))
   last=stop
   if stop>=262144 and streak>=2:break
  run['frames']=last;run['practically_stable']=streak>=2
  g.markOutput('Reconstruct.color')
  for w in range(2):
   if w:frames(4096)
   for i in range(64):frames(1);capture(name+'-window'+str(w)+'-'+str(i))
  run['stats']=dict(dd.stats);assert run['stats']['updatedFrames']==8192
  m.removeGraph(g)
 progress('complete');(O/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
