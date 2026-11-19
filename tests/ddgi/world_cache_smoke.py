"""WorldCache integration checks, not a converged quality benchmark."""
from falcor import *
from pathlib import Path
import runpy,json,traceback,os
R=Path(__file__).resolve().parents[2];O=R/'build/worldcache-validation';O.mkdir(exist_ok=True)
record={}
for stale in ['failure.txt','complete.json']:
 if (O/stale).exists():(O/stale).unlink()
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):
 m.frameCapture.baseFilename=tag;m.frameCapture.capture()
def stats(wc):
 s=dict(wc.stats)
 assert s['finite'] and s['rejectedRaySamples']==0,s
 assert s['totalProbes']==0 and s['updatedFrames']==0 and not s['restirGather'],s
 return s
try:
 # Reproducible point-lit Cornell configuration; do not modify user scene defaults.
 cfg=json.loads((R/'scripts/scenes/CornellRTXGI.json').read_text())
 cfg['directionalLight']['enabled']=False;cfg['ceilingPointLight']['enabled']=True
 (O/'cornell.json').write_text(json.dumps(cfg));os.environ['CORNELL_RTXGI_CONFIG']=str(O/'cornell.json')
 m.frameCapture.outputDir=str(O)
 for scene in ['CornellLambert','SponzaLambert']:
  os.environ['FALCOR_START_SCENE']=scene
  gs=runpy.run_path(str(R/'scripts/GIPreview.py'))['graphs'];g=gs['LumenWorldCache'];m.addGraph(g);m.setActiveGraph(g)
  m.loadScene(str(R/('scripts/scenes/'+scene+'.pyscene')));m.clock.pause();m.scene.camera.animated=False
  g.markOutput('Accumulate.output')
  wc=g.getPass('WorldCache');acc=g.getPass('Accumulate');acc.enabled=False
  frames(512);s=stats(wc);assert s['cacheOccupied']>0 and s['cacheHits']>0,s
  record[scene]={'warm_stats':s}
  acc.enabled=True;acc.reset();frames(1024)
  capture(scene+'-half')
  m.profiler.enabled=True;frames(8);m.profiler.start_capture();frames(128)
  record[scene]['timing']=m.profiler.end_capture();m.profiler.enabled=False
  wc.set_properties({'halfResolutionGather':False});frames(16);stats(wc)
  wc.set_properties({'halfResolutionGather':True,'jitterHalfGather':True});frames(16);stats(wc)
  wc.set_properties({'updateEnabled':False});frames(1);before=stats(wc)['worldCacheUpdates'];frames(4);assert stats(wc)['worldCacheUpdates']==before
  wc.set_properties({'updateEnabled':True,'jitterHalfGather':False});wc.reset();frames(1);assert stats(wc)['worldCacheUpdates']==1
  if scene=='SponzaLambert':
   m.scene.getLight('Atrium Point').active=False;m.scene.getLight('Atrium Sun').active=True;frames(128);stats(wc)
   m.scene.getLight('Atrium Sun').active=False;acc.enabled=False;frames(128)
   capture('lights-off')
  m.scene.camera.position=m.scene.camera.position+float3(.1,0,0);frames(8);stats(wc)
  resizeFrameBuffer(401,301);frames(8);stats(wc)
  resizeFrameBuffer(960,540);frames(8);stats(wc)
  m.removeGraph(g)
  # Existing baseline still runs independently, with probes and no WorldCache.
  dd=gs['RTXGIDDGI'];m.addGraph(dd);m.setActiveGraph(dd)
  dd.getPass('DDGI').set_properties({'finalGather':True,'halfResolutionGather':True})
  frames(32);record[scene]['ddgi_stats']=dict(dd.getPass('DDGI').stats)
  assert record[scene]['ddgi_stats']['totalProbes']>0 and not record[scene]['ddgi_stats']['worldCache']
  m.removeGraph(dd)
 (O/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
