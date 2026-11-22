"""Compare six DDGI update budgets and half-FG DDGI/WorldCache cold starts."""
from falcor import *
from pathlib import Path
import runpy,json,traceback,time,hashlib,os
R=Path(__file__).resolve().parents[2];O=R/'build/sponza-probe-budget-sweep-20261120';O.mkdir(exist_ok=True)
extend_fg=os.environ.get('DDGI_SWEEP_EXTEND_FG')=='1'
assert extend_fg or not (O/'complete.json').exists(), 'Do not overwrite completed captures'
stable_frames=32768 if extend_fg else 4096
N=8192; checkpoints=[1,2,4,8,11,16,32,64,128,256,512,1024,2048,4096,8192]
info={'scene':'SponzaLambert','resolution':[1920,1080],'checkpoints':checkpoints,'cold_frames':N,'final_accumulate_frames':4096,'hysteresis':.97,'runs':{},'started':time.time(),'source_hashes':{}}
if extend_fg:
 info=json.loads((O/'complete.json').read_text());info['fg_extension_started']=time.time()
for p in (R/'Source/RenderPasses/RTXGIDDGI').glob('*'):
 if p.is_file():info['source_hashes'][p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
def save(stage):
 info['stage']=stage;(O/'progress.json').write_text(json.dumps(info,indent=2))
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 cases=[('full',10648,'ddgi',False)]+[('batch'+str(b),b,'ddgi',False) for b in [256,512,1024,2048,4096]]+[('ddgi_half',10648,'half',False),('worldcache',10648,'half',True)]
 for name,budget,mode,wc in (cases[-2:] if extend_fg else cases):
  save(name+' setup');g=factory(mode,world_cache=wc)
  if not wc:runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  source=('Reconstruct.color' if mode=='half' else 'DDGI.color')
  g.addPass(createPass('AccumulatePass',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'}),'ColdAverage')
  g.addEdge(source,'ColdAverage.input');g.markOutput('ColdAverage.output')
  g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.updatePass('Display',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
  g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  m.scene.getLight('Atrium Point').active=True;m.scene.getLight('Atrium Sun').active=False
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  p=g.getPass('WorldCache' if wc else 'DDGI');p.set_properties({'batchProbeUpdates':budget<10648,'probesPerFrame':budget,'useWRC':False,'useRTXDI':False,'finalGather':mode=='half','restirGather':False,'jitterHalfGather':False,'gatherSpecular':False,'worldCacheDensity':20.,'worldCacheDownsample':8,'worldCacheBounces':3,'worldCacheHistory':16,'worldCacheMaxIntensity':0.})
  frames(2);p.reset();g.getPass('Accumulate').reset();g.getPass('ColdAverage').reset();info['runs'][name]={'checkpoints':{}}
  for i in range(1,N+1):
   renderFrame()
   if i in checkpoints:
    capture(name+'-'+str(i));info['runs'][name]['checkpoints'][str(i)]=dict(p.stats);save(name+' '+str(i))
   elif i%512==0:save(name+' '+str(i))
  acc=g.getPass('Accumulate');acc.enabled=True;acc.reset()
  frames(stable_frames//2);capture(name+'-stable'+str(stable_frames//2));frames(stable_frames//2);capture(name+'-stable'+str(stable_frames))
  g.getPass('ColdAverage').enabled=False
  info['runs'][name]['stats']=dict(p.stats);info['runs'][name]['properties']=dict(p.properties)
  info['runs'][name]['stable_frames']=stable_frames
  assert p.stats['finite']
  m.profiler.enabled=True;frames(32);m.profiler.start_capture();frames(840)
  (O/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  m.removeGraph(g)
 save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
