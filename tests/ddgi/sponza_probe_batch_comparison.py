"""Compare cold-start full vs budgeted DDGI updates; retain instantaneous convergence captures."""
from falcor import *
from pathlib import Path
import runpy,json,traceback,time,hashlib
R=Path(__file__).resolve().parents[2];O=R/'build/sponza-probe-batch-20261120';O.mkdir(exist_ok=True)
N=8192; checkpoints=[1,2,4,8,11,16,32,64,128,256,512,1024,2048,4096,8192]
info={'scene':'SponzaLambert','resolution':[1920,1080],'checkpoints':checkpoints,'cold_frames':N,'final_accumulate_frames':1024,'hysteresis':.97,'runs':{},'started':time.time(),'source_hashes':{}}
for p in (R/'Source/RenderPasses/RTXGIDDGI').glob('*'):
 if p.is_file():info['source_hashes'][p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
def save(stage):
 info['stage']=stage;(O/'progress.json').write_text(json.dumps(info,indent=2))
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,batch in [('full',False),('batch1024',True)]:
  save(name+' setup');g=factory('ddgi');runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.updatePass('Display',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
  g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  m.scene.getLight('Atrium Point').active=True;m.scene.getLight('Atrium Sun').active=False
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  p=g.getPass('DDGI');p.set_properties({'batchProbeUpdates':batch,'probesPerFrame':1024,'useWRC':False,'useRTXDI':False,'finalGather':False,'restirGather':False})
  frames(2);p.reset();g.getPass('Accumulate').reset();info['runs'][name]={'checkpoints':{}}
  for i in range(1,N+1):
   renderFrame()
   if i in checkpoints:
    capture(name+'-'+str(i));info['runs'][name]['checkpoints'][str(i)]=dict(p.stats);save(name+' '+str(i))
   elif i%512==0:save(name+' '+str(i))
  acc=g.getPass('Accumulate');acc.enabled=True;acc.reset()
  frames(512);capture(name+'-stable512');frames(512);capture(name+'-stable1024')
  info['runs'][name]['stats']=dict(p.stats);info['runs'][name]['properties']=dict(p.properties)
  assert p.stats['finite']
  m.profiler.enabled=True;frames(32);m.profiler.start_capture();frames(550)
  (O/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  m.removeGraph(g)
 save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
