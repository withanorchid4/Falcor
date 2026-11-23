from falcor import *
from pathlib import Path
import runpy,json,traceback,os
R=Path(__file__).resolve().parents[2];O=R/'build/ddgi-tetrahedral';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
info={}
def save(stage): (O/'progress.json').write_text(json.dumps({'stage':stage,'runs':info},indent=2))
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,tetra in [('eight',False),('four',True)]:
  save(name+' setup');g=factory('ddgi');runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  g.getPass('DDGI').set_properties({'tetrahedralInterpolation':tetra,'finalGather':False,'useWRC':False,'restirGather':False,'batchProbeUpdates':False})
  g.updatePass('Visibility',{'adjustShadingNormals':True})
  g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.updatePass('Display',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
  for c in ['Accumulate.output','Visibility.normW','Visibility.posW']:g.markOutput(c)
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  assert list(g.getPass('DDGI').properties['gridCounts'])==[22,22,22]
  for i in range(8192):
   renderFrame()
   if (i+1)%2048==0:save(name+' warmup '+str(i+1))
  acc=g.getPass('Accumulate');acc.enabled=True;acc.reset()
  for i in range(1,8193):
   renderFrame()
   if i in [4096,8192]:m.frameCapture.baseFilename=name+'-'+str(i);m.frameCapture.capture();save(name+' accumulate '+str(i))
  info[name]={'properties':dict(g.getPass('DDGI').properties),'stats':dict(g.getPass('DDGI').stats)}
  for freeze in [False,True]:
   if freeze:g.getPass('DDGI').set_properties({'updateEnabled':False})
   m.profiler.enabled=True
   for _ in range(64):renderFrame()
   m.profiler.start_capture()
   for _ in range(512):renderFrame()
   (O/(name+('-frozen' if freeze else '-live')+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  m.removeGraph(g)
 save('complete');(O/'complete.json').write_text(json.dumps(info,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
