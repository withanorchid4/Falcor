"""Same Sponza Lambert view, directional intensity 50, four stable captures."""
from falcor import *
from pathlib import Path
import runpy,json,traceback,time,subprocess,hashlib
R=Path(__file__).resolve().parents[2];O=R/'build/sponza-sun50-20261120';O.mkdir(exist_ok=True)
assert not (O/'complete.json').exists()
PY='C:/Users/luozilong01/AppData/Local/Programs/Python/Python312/python.exe'
info={'resolution':[1920,1080],'scene':'SponzaLambert','camera':{'position':[-9,1.6,0],'target':[8,2.5,0],'focalLength':18,'frameHeight':24},'pointActive':False,'sunActive':True,'sunIntensity':[50,50,50],'sunDirectionInput':[.3,-1,.2],'gi_warmup':8192,'runs':{},'started':time.time()}
info['source_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (R/'Source/RenderPasses/RTXGIDDGI').glob('*') if p.is_file()}
if (O/'pt-8192-stability.json').exists():
 info=json.loads((O/'progress.json').read_text())
 checks={str(n):json.loads((O/('pt-'+str(n)+'-stability.json')).read_text()) for n in [512,1024,2048,4096,8192]}
 assert checks['8192']['passed']
 info['runs']['pt']={'checkpoints':checks,'final_frame':8192,'spp':65536,'stable':True}
 info['stability_policy']='One passing doubling comparison; minimum 2048 GI accumulated frames. Reuse saved 65536 spp PT, which passed the same numeric thresholds.'
def save(stage):info['stage']=stage;(O/'progress.json').write_text(json.dumps(info,indent=2))
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,mode,wc in [('pt',None,False),('ddgi','ddgi',False),('half','half',False),('worldcache','half',True)]:
  if name in info['runs'] and info['runs'][name]['stable']:continue
  save(name+' setup')
  g=runpy.run_path(str(R/'scripts/PTReference.py'))['render_graph_PTReference']() if name=='pt' else factory(mode,world_cache=wc)
  if name!='pt' and not wc:runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  g.updatePass('Visibility',{'adjustShadingNormals':True})
  g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  m.scene.getLight('Atrium Point').active=False;sun=m.scene.getLight('Atrium Sun');sun.active=True;sun.intensity=float3(50.0)
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  if name!='pt':
   p=g.getPass('WorldCache' if wc else 'DDGI');p.set_properties({'batchProbeUpdates':False,'primaryShadingNormalCorrection':True,'useWRC':False,'useRTXDI':False,'restirGather':False,'jitterHalfGather':False,'gatherSpecular':False,'worldCacheDensity':20.,'worldCacheDownsample':8,'worldCacheBounces':3,'worldCacheHistory':16,'worldCacheMaxIntensity':0.})
  else:
   p=g.getPass('PT');p.useFixedSeed=True;p.fixedSeed=0
  for _ in range(2):renderFrame()
  if name!='pt':
   p.reset()
   for i in range(8192):
    renderFrame()
    if (i+1)%2048==0:save(name+' warmup '+str(i+1))
  acc=g.getPass('Accumulate');acc.enabled=True;acc.reset();streak=0;run={'checkpoints':{}}
  maximum=32768 if name=='pt' else 262144
  for i in range(1,maximum+1):
   if name=='pt':p.fixedSeed=i
   renderFrame()
   if i>=512 and (i&(i-1))==0:
    capture(name+'-'+str(i));save(name+' check '+str(i))
    result=subprocess.run([PY,str(R/'tests/ddgi/check_sponza_sun_stability.py'),name,str(i)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    check=json.loads((O/(name+'-'+str(i)+'-stability.json')).read_text());run['checkpoints'][str(i)]=check
    streak=streak+1 if check['passed'] else 0
    if i>=(4096 if name=='pt' else 2048) and streak>=1:break
   elif i%(128 if name=='pt' else 2048)==0:save(name+' accumulate '+str(i))
  run.update({'final_frame':i,'spp':i*8 if name=='pt' else i,'stable':streak>=1})
  if name!='pt':run.update({'properties':dict(p.properties),'stats':dict(p.stats)});assert p.stats['finite']
  info['runs'][name]=run;save(name+' finished');m.removeGraph(g)
 save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
