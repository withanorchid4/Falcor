"""Mogwai entry for normal-consistency A/B quality and GPU timings."""
from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/material-normal-fix';O.mkdir(parents=True,exist_ok=True)
cfg=json.loads((O/'case.json').read_text());tag=cfg['tag'];result=[]
def progress(stage):(O/'progress.json').write_text(json.dumps({'tag':tag,'stage':stage,'runs':result},indent=2))
try:
 for mode in cfg.get('modes',['worldcache','sharc','ddgi']):
  progress(mode+' setup')
  if mode=='pt':g=runpy.run_path(str(R/'scripts/PTReference.py'))['render_graph_PTReference']();p=g.getPass('PT')
  else:
   g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('half',world_cache=mode!='ddgi')
   p=g.getPass('DDGI' if mode=='ddgi' else 'WorldCache');p.set_properties({'sharc':mode=='sharc','sharcSceneScale':20.,'gatherSpecular':False,'primaryShadingNormalCorrection':True,'jitterHalfGather':False})
   if mode=='ddgi':runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  g.updatePass('Visibility',{'adjustShadingNormals':True});g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  progress(mode+' warmup')
  for _ in range(cfg.get('warmup',2048)):renderFrame()
  progress(mode+' timing');m.profiler.enabled=True;m.profiler.start_capture()
  for _ in range(cfg.get('timingFrames',512)):renderFrame()
  (O/(tag+'-'+mode+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  if cfg.get('quality'):
   progress(mode+' image accumulation');g.getPass('Accumulate').reset()
   g.markOutput('Accumulate.output');g.markOutput('Visibility.normW');g.markOutput('Visibility.posW')
   m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
   for i in range(1,cfg.get('imageFrames',8192)+1):
    renderFrame()
    if i in [4096,8192]:
     m.frameCapture.baseFilename=tag+'-'+mode+'-'+str(i);m.frameCapture.capture()
  row={'mode':mode,'properties':dict(p.properties)}
  if mode!='pt':row['stats']=dict(p.stats);assert row['stats']['finite'],row
  result.append(row);m.removeGraph(g)
 (O/(tag+'-complete.json')).write_text(json.dumps(result,indent=2));progress('complete')
except:
 (O/(tag+'-failure.txt')).write_text(traceback.format_exc());progress('failed')
exit()
