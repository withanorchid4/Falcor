"""Matched-cell SHaRC vs migrated WorldCache, common half FG, sun 50."""
from falcor import *
from pathlib import Path
import runpy,json,traceback,time,subprocess,sys,shutil
R=Path(__file__).resolve().parents[2];O=R/'build/sponza-sharc-official-20261122';O.mkdir(exist_ok=True)
old=R/'build/sponza-sun50-20261120'
shutil.copyfile(old/'display.json',O/'display.json')
shutil.copyfile(old/'pt-512.Visibility.normW.0.exr',O/'pt-512.Visibility.normW.0.exr')
PY=shutil.which('python')
info={'runs':{},'scene':'SponzaLambert','sunIntensity':50,'pointActive':False,'resolution':[1920,1080],
 'warmup':8192,'pt_reference':str(old/'pt-8192.Accumulate.output.0.exr'),'pt_spp':65536,
 'grid':{'density':20,'min_cell':.025,'sharc_scale':20,'sharc_level_bias':2},'started':time.time(),
 'sharc_baseline':{'sample_commit':'04372d7f91bb3a0444f9fd95d3f34381ea4e3b39','entries':4194304,'downsample':5,'max_vertices':8,'history':20,'stale_age':60,'demodulation':True,'native_64bit_atomics':True}}
def save(stage):info['stage']=stage;(O/'progress.json').write_text(json.dumps(info,indent=2))
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name in ['worldcache','sharc']:
  save(name+' setup');g=factory('half',world_cache=True)
  g.updatePass('Visibility',{'adjustShadingNormals':True})
  g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.markOutput('Accumulate.output');g.markOutput('Visibility.normW');g.markOutput('Visibility.posW')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  assert not m.scene.getLight('Atrium Point').active and m.scene.getLight('Atrium Sun').active
  p=g.getPass('WorldCache');p.set_properties({'sharc':name=='sharc','sharcSceneScale':20.,
    'primaryShadingNormalCorrection':True,'jitterHalfGather':False,'restirGather':False,'gatherSpecular':False,'useRTXDI':False})
  if name=='worldcache':p.set_properties({'worldCacheDensity':20.,'worldCacheDownsample':8,'worldCacheBounces':3,'worldCacheHistory':16,'worldCacheMaxIntensity':0.})
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  for _ in range(2):renderFrame()
  p.reset()
  for i in range(8192):
   renderFrame()
   if (i+1)%2048==0:save(name+' warmup '+str(i+1))
  acc=g.getPass('Accumulate');acc.enabled=True;acc.reset();checks={}
  for i in range(1,65537):
   renderFrame()
   if i>=512 and i&(i-1)==0:
    m.frameCapture.baseFilename=name+'-'+str(i);m.frameCapture.capture();save(name+' check '+str(i))
    result=subprocess.run([PY,str(R/'tests/ddgi/check_sponza_sun_stability.py'),name,str(i),str(O)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    checks[str(i)]=json.loads((O/(name+'-'+str(i)+'-stability.json')).read_text())
    if i>=16384 and checks[str(i)]['passed']:break
  stats=dict(p.stats);assert stats['finite'] and stats.get('sharcNonFinite',0)==0
  assert checks[str(i)]['passed'],'stability threshold not met'
  info['runs'][name]={'frames':i,'checks':checks,'stats':stats,'properties':dict(p.properties)}
  save(name+' timing');m.profiler.enabled=True
  for _ in range(32):renderFrame()
  m.profiler.start_capture()
  for _ in range(512):renderFrame()
  (O/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  m.removeGraph(g)
 save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
