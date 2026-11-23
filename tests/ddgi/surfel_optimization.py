"""Run unit-environment and matched-camera Cornell/Sponza tests for independent surfel GI."""
from falcor import *
from pathlib import Path
import runpy,traceback,json,os,subprocess,shutil,time
R=Path(__file__).resolve().parents[2]; scene='SponzaLambert'
O=R/('build/surfel-opt-'+os.environ.get('SURFEL_VARIANT','optimized'));O.mkdir(exist_ok=True)
for f in ['failure.txt','complete.json']:(O/f).unlink(missing_ok=True)
info={'scene':scene,'runs':{},'resolution':[1920,1080],'started':time.time()}
def save(stage):info['stage']=stage;(O/'progress.json').write_text(json.dumps(info,indent=2))
try:
 for name in (['surfel'] if (scene=='SponzaLambert' and (R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr').exists()) or (O/'pt-8192.Accumulate.output.0.exr').exists() else ['pt','surfel']):
  save(name+' setup')
  g=runpy.run_path(str(R/'scripts'/('PTReference.py' if name=='pt' else 'SurfelGI.py')))['PTReference' if name=='pt' else 'SurfelGI']
  g.updatePass('Surfel',{'queryCompact':os.environ.get('SURFEL_VARIANT')!='baseline','queryShared':os.environ.get('SURFEL_VARIANT')=='optimized'})
  g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.updatePass('Display',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
  for c in ['Accumulate.output','Visibility.normW','Visibility.posW']:g.markOutput(c)
  if name=='surfel':g.markOutput('Surfel.output')
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes'/(scene+'.pyscene')));m.clock.pause();m.scene.animated=False
  if scene=='SponzaLambert':assert m.scene.getLight('Atrium Sun').active and not m.scene.getLight('Atrium Point').active
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  for _ in range(2):renderFrame()
  if name=='surfel':
   save('surfel warmup')
   for _ in range(2048):renderFrame()
  acc=g.getPass('Accumulate');acc.enabled=True;acc.reset()
  for i in range(1,8193):
   renderFrame()
   if i in [512,1024,2048,4096,8192]:
    m.frameCapture.baseFilename=name+'-'+str(i);m.frameCapture.capture();save(name+' '+str(i))
  info['runs'][name]={'frames':i,'warmup':2048 if name=='surfel' else 2}
  if name=='surfel':info['runs'][name]['stats']=dict(g.getPass('Surfel').stats)
  m.profiler.enabled=True
  for _ in range(16):renderFrame()
  m.profiler.start_capture()
  for _ in range(256):renderFrame()
  (O/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  g.updatePass('Surfel',{'lockSurfel':True})
  atomic=[]
  for mark in [True,False,True,False,True,False]:
   g.updatePass('Surfel',{'queryMark':mark})
   m.profiler.enabled=True
   for _ in range(32):renderFrame()
   m.profiler.start_capture()
   for _ in range(128):renderFrame()
   atomic.append({'mark':mark,'timing':m.profiler.end_capture()})
   m.profiler.enabled=False
  (O/'atomic.json').write_text(json.dumps(atomic))
  m.removeGraph(g)
 save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
