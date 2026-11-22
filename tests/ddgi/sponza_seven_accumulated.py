"""Seven accumulated-only cold-start curves, matching nominal probe-ray budgets."""
from falcor import *
from pathlib import Path
import runpy,json,traceback,hashlib,time,subprocess
R=Path(__file__).resolve().parents[2];O=R/'build/sponza-seven-accumulated-20261120';O.mkdir(exist_ok=True)
assert not (O/'complete.json').exists()
PY='C:/Users/luozilong01/AppData/Local/Programs/Python/Python312/python.exe'
cases=[('ddgi_full','ddgi',10648,False),('ddgi_ac','ddgi',800,False),('ddgi_id','ddgi',1274,False),('fg_full','half',10648,False),('fg_ac','half',800,False),('fg_id','half',1274,False),('worldcache','half',10648,True)]
checkpoints=[1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384,32768,65536,131072,262144]
info={'resolution':[1920,1080],'checkpoints':checkpoints,'accumulation_from_empty_cache':True,'probe_rays':256,'runs':{},'started':time.time(),'sources':{}}
for folder in ['Source/RenderPasses/RTXGIDDGI','Source/RenderPasses/DDGIReconstruct']:
 for p in (R/folder).glob('*'):
  if p.is_file():info['sources'][str(p.relative_to(R))]=hashlib.sha256(p.read_bytes()).hexdigest()
def save(stage):info['stage']=stage;(O/'progress.json').write_text(json.dumps(info,indent=2))
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,mode,budget,wc in cases:
  save(name+' setup');g=factory(mode,world_cache=wc)
  if not wc:runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  g.updatePass('Visibility',{'adjustShadingNormals':True})
  g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.updatePass('Display',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
  g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  m.scene.getLight('Atrium Point').active=True;m.scene.getLight('Atrium Sun').active=False
  p=g.getPass('WorldCache' if wc else 'DDGI');p.set_properties({'batchProbeUpdates':budget<10648,'wrapProbeBatches':True,'probesPerFrame':budget,'primaryShadingNormalCorrection':True,'useWRC':False,'useRTXDI':False,'restirGather':False,'jitterHalfGather':False,'gatherSpecular':False,'worldCacheDensity':20.,'worldCacheDownsample':8,'worldCacheBounces':3,'worldCacheHistory':16,'worldCacheMaxIntensity':0.})
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  for _ in range(2):renderFrame()
  p.reset();g.getPass('Accumulate').reset();streak=0;info['runs'][name]={'mode':mode,'budget':budget if not wc else None,'checkpoints':{}}
  for i in range(1,262145):
   renderFrame()
   if i in checkpoints:
    capture(name+'-'+str(i));save(name+' score '+str(i))
    run=subprocess.run([PY,str(R/'tests/ddgi/score_sponza_seven_checkpoint.py'),name,str(i)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=json.loads((O/(name+'-'+str(i)+'-metrics.json')).read_text());info['runs'][name]['checkpoints'][str(i)]=result
    streak=streak+1 if result['passed'] else 0
    if i>=65536 and streak>=2:break
   elif i%2048==0:save(name+' accumulate '+str(i))
  s=dict(p.stats);assert s['finite']
  if not wc:assert s['probeUpdatesTotal']==i*budget
  info['runs'][name].update({'final_frame':i,'stable':streak>=2,'properties':dict(p.properties),'stats':s})
  m.profiler.enabled=True
  for _ in range(32):renderFrame()
  m.profiler.start_capture()
  for _ in range(512):renderFrame()
  (O/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  save(name+' finished');m.removeGraph(g)
 save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
