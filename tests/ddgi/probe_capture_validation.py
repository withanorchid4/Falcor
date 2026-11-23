from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/probe-capture-validation';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
results={'validation':[],'normalTimings':[]}
def save(stage):(O/'progress.json').write_text(json.dumps({'stage':stage,**results},indent=2))
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi');p=g.getPass('DDGI')
 runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 p.set_properties({'batchProbeUpdates':False,'tetrahedralInterpolation':False,'useRTXDI':False})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
 save('warm full ray field')
 for _ in range(4096):renderFrame()
 p.set_properties({'captureOnly':True});p.set_properties({'rasterProbeUpdate':True,'batchProbeUpdates':True,'wrapProbeBatches':True,'probesPerFrame':32,'probeCubemapSize':32})
 for offset in range(0,10648,32):
  p.set_properties({'probeCaptureTestOffset':offset,'probesPerFrame':min(32,10648-offset),'validateCapture':True,'optimizedProbeCapture':False})
  for _ in range(2):renderFrame()
  p.set_properties({'optimizedProbeCapture':True})
  for _ in range(2):renderFrame()
  s=dict(p.capture_stats)
  results['validation'].append({'offset':offset,'stats':{k:v for k,v in s.items() if k.startswith('capture') or k in ['referencePixels','missingCapturePixels','extraCapturePixels','visibleMeshViews','candidateMeshViews']}})
  if offset%1024==0:save('validate '+str(offset))
 p.set_properties({'validateCapture':False,'probesPerFrame':32,'probeCaptureTestOffset':0})
 p.set_properties({'captureOnly':False})
 for repeat,optimized in enumerate([False,True,True,False]):
  save('normal timing '+str(repeat));p.set_properties({'optimizedProbeCapture':optimized,'probeCaptureTestOffset':0})
  for _ in range(64):renderFrame()
  m.profiler.enabled=True;m.profiler.start_capture()
  for _ in range(1024):renderFrame()
  timing=m.profiler.end_capture();m.profiler.enabled=False
  name='normal-timing-'+str(repeat)+'.json';(O/name).write_text(json.dumps(timing))
  results['normalTimings'].append({'optimized':optimized,'repeat':repeat,'file':name,'stats':dict(p.stats)})
 (O/'complete.json').write_text(json.dumps(results,indent=2));save('complete')
except:(O/'failure.txt').write_text(traceback.format_exc());save('failed')
exit()
