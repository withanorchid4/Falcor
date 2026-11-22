"""Matched DDGI half-FG runs, changing only the primary shading-normal policy."""
from falcor import *
from pathlib import Path
import runpy,json,traceback,hashlib,time
R=Path(__file__).resolve().parents[2];O=R/'build/sponza-primary-normal-ab-20261120';O.mkdir(exist_ok=True)
assert not (O/'complete.json').exists()
info={'warmup':8192,'accumulation':32768,'resolution':[1920,1080],'runs':{},'started':time.time()}
info['source_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (R/'Source/RenderPasses/RTXGIDDGI').glob('*') if p.is_file()}
def save(stage):
 info['stage']=stage;(O/'progress.json').write_text(json.dumps(info,indent=2))
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,adjust in [('on',True),('off',False)]:
  g=factory('half');runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  g.updatePass('Visibility',{'adjustShadingNormals':True})
  g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.updatePass('Display',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
  g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  m.scene.getLight('Atrium Point').active=True;m.scene.getLight('Atrium Sun').active=False
  p=g.getPass('DDGI');p.set_properties({'batchProbeUpdates':False,'probesPerFrame':10648,'useWRC':False,'useRTXDI':False,'finalGather':True,'halfResolutionGather':True,'restirGather':False,'jitterHalfGather':False,'gatherSpecular':False})
  p.set_properties({'primaryShadingNormalCorrection':adjust})
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  for _ in range(2):renderFrame()
  p.reset();acc=g.getPass('Accumulate');acc.reset()
  for i in range(8192):
   renderFrame()
   if (i+1)%2048==0:save(name+' warmup '+str(i+1))
  acc.enabled=True;acc.reset()
  for i in range(32768):
   renderFrame()
   if i+1 in [4096,16384,32768]:capture(name+'-'+str(i+1))
   if (i+1)%2048==0:save(name+' accumulate '+str(i+1))
  s=dict(p.stats);assert s['finite']
  info['runs'][name]={'primaryShadingNormalCorrection':adjust,'gbufferAdjustShadingNormals':True,'stats':s,'properties':dict(p.properties)}
  m.removeGraph(g)
 save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
