from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/ddgi-query-math';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
runs={}
def save(s):(O/'progress.json').write_text(json.dumps({'stage':s,'runs':runs},indent=2))
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,tetra in [('eight',False),('four',True)]:
  g=factory('ddgi');runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  p=g.getPass('DDGI');p.set_properties({'tetrahedralInterpolation':tetra,'hoistNormalOct':False,'skipDirectionNormalize':False})
  g.markOutput('DDGI.indirect');g.markOutput('Visibility.normW');g.markOutput('Accumulate.output')
  g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  save(name+' warmup')
  for _ in range(8192):renderFrame()
  p.set_properties({'updateEnabled':False});runs[name]={'properties':dict(p.properties),'records':[]}
  # Alternate order to reduce thermal/order bias. Same frozen probe textures in all variants.
  variants=[('baseline',False,False),('hoist',True,False),('normalize',False,True),('both',True,True)]
  for rep in range(4):
   for variant,hoist,skip in (variants if rep%2==0 else list(reversed(variants))):
    save(name+' '+str(rep)+' '+variant);p.set_properties({'hoistNormalOct':hoist,'skipDirectionNormalize':skip})
    for _ in range(64):renderFrame()
    if rep==0:
     m.frameCapture.baseFilename=name+'-'+variant;m.frameCapture.capture()
    m.profiler.enabled=True;m.profiler.start_capture()
    for _ in range(512):renderFrame()
    timing=m.profiler.end_capture();m.profiler.enabled=False
    runs[name]['records'].append({'variant':variant,'repeat':rep,'timing':timing})
  m.removeGraph(g)
 (O/'complete.json').write_text(json.dumps(runs));save('complete')
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
