"""Fresh Sponza Lambert comparison: WorldCache half FG, DDGI, DDGI half FG, PT."""
from falcor import *
from pathlib import Path
import os,json,runpy,traceback,time,hashlib
R=Path(__file__).resolve().parents[2]
O=R/'build/sponza-worldcache-ddgi-1080p-20261119';O.mkdir(exist_ok=True)
assert not (O/'complete.json').exists(),'Do not overwrite completed captures'
N=65536
info={'resolution':[1920,1080],'half_resolution':[960,540],'warmup_frames':8192,
 'accumulation_frames':N,'checkpoints':[1024,2048,4096,8192,16384,32768,65536],
 'cache_updates_frozen':False,'jitter':False,'restir':False,'nrd':False,
 'pt_spp_per_frame':8,'pt_total_spp':32768,'pt_sequence_spp':16384,
 'started':time.time(),'runs':{},'source_hashes':{}}
files=list((R/'Source/RenderPasses/RTXGIDDGI').glob('*'))
files += [R/p for p in ['scripts/DDGIAccumulated.py','scripts/PTReference.py','scripts/scenes/Sponza.pyscene','scripts/scenes/SponzaLambert.pyscene','media/Sponza/Sponza.gltf','tests/ddgi/sponza_worldcache_comparison.py']]
info['source_hashes']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
def save(stage):
 info['stage']=stage;info['elapsed_seconds']=time.time()-info['started'];(O/'progress.json').write_text(json.dumps(info,indent=2))
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):
 m.frameCapture.baseFilename=tag;m.frameCapture.capture()
def activate(g):
 g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
 g.updatePass('Display',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
 g.markOutput('Accumulate.output')
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'))
 m.clock.pause();m.scene.camera.animated=False
 m.scene.getLight('Atrium Point').active=True;m.scene.getLight('Atrium Sun').active=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False

def timing(name):
 save(name+' timing');m.profiler.enabled=True;frames(16);m.profiler.start_capture();frames(512)
 (O/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
try:
 (O/'scene.json').write_text(json.dumps({'scene':'SponzaLambert','camera':{'position':[-9,1.6,0],'target':[8,2.5,0],'frameHeight':24,'focalLength':18},'pointLight':{'position':[0,4,0],'intensity':[600,600,600]},'sunActive':False,'ddgi':{'gridCounts':[24,12,16],'raysPerProbe':256,'autoBounds':True,'hysteresis':.97,'normalBias':.05,'viewBias':.05},'worldCache':{'entries':1048576,'density':20,'minimumCellWidth':.025,'pathDownsample':8,'pathBounces':3,'terminalBootstrap':1,'history':16,'maxUnusedFrames':64,'radianceClamp':0},'accumulate':'SingleCompensated'},indent=2))
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,mode,wc in [('worldcache','half',True),('ddgi','ddgi',False),('half','half',False)]:
  save(name+' setup');g=factory(mode,world_cache=wc);g.name='Sponza_'+name
  p=g.getPass('WorldCache' if wc else 'DDGI')
  p.set_properties({'autoBounds':True,'gridCounts':uint3(24,12,16),'useWRC':False,'useRTXDI':False,
   'restirGather':False,'jitterHalfGather':False,'gatherSpecular':False,'worldCacheDensity':20.,
   'worldCacheDownsample':8,'worldCacheBounces':3,'worldCacheHistory':16,'worldCacheMaxIntensity':0.})
  activate(g);acc=g.getPass('Accumulate');acc.enabled=False
  save(name+' warmup');frames(8192);acc.enabled=True;acc.reset()
  for i in range(1,N+1):
   renderFrame()
   if i in info['checkpoints']:capture(name+'-'+str(i))
   if i%2048==0:save(name+' '+str(i)+'/65536')
  s=dict(p.stats);assert s['finite'] and all(s[k]==0 for k in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']),s
  if wc:assert s['totalProbes']==0 and s['updatedFrames']==0 and s['cacheOccupied']>0,s
  info['runs'][name]={'stats':s,'mode':mode,'worldCache':wc,'properties':dict(p.properties)}
  timing(name);save(name+' finished');m.removeGraph(g)
 g=runpy.run_path(str(R/'scripts/PTReference.py'))['PTReference'];activate(g)
 g.markOutput('Visibility.normW');frames(1);capture('mask');g.unmarkOutput('Visibility.normW');frames(1)
 pt=g.getPass('PT');acc=g.getPass('Accumulate');pt.useFixedSeed=True
 for sequence,offset in [('a',1),('b',100001)]:
  acc.reset()
  for i in range(2048):
   pt.fixedSeed=offset+i;renderFrame()
   if i+1 in [512,1024,2048]:capture('pt-'+sequence+'-'+str((i+1)*8))
   if (i+1)%128==0:save('PT '+sequence+' '+str((i+1)*8)+'/16384 spp')
 timing('pt');save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
