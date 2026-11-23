from falcor import *
from pathlib import Path
import runpy,json,traceback,os
R=Path(__file__).resolve().parents[2];O=R/os.environ.get('MULTIVIEW_TEST_OUTPUT','build/probe-multiview-benchmark');O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True);results={'validation':[],'timings':[]}
def save(stage):(O/'progress.json').write_text(json.dumps({'stage':stage,**results},indent=2))
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi');p=g.getPass('DDGI')
 runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 p.set_properties({'multiviewAcrossProbes':os.environ.get('MULTIVIEW_ACROSS_PROBES')=='1','batchProbeUpdates':False,'tetrahedralInterpolation':False,'useRTXDI':False})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
 save('warm ray field')
 for _ in range(512):renderFrame()
 p.set_properties({'captureOnly':True});p.set_properties({'rasterProbeUpdate':True,'batchProbeUpdates':True,'wrapProbeBatches':True,'probesPerFrame':32,'probeCubemapSize':32})
 for offset in [0,1024,5000,10000]:
  save('validate '+str(offset));p.set_properties({'probeCaptureTestOffset':offset,'validateCapture':True,'optimizedProbeCapture':False,'multiviewProbeCapture':False})
  for _ in range(2):renderFrame()
  p.set_properties({'optimizedProbeCapture':True,'multiviewProbeCapture':True})
  for _ in range(2):renderFrame()
  s=dict(p.capture_stats);results['validation'].append({'offset':offset,'stats':s});save('validated '+str(offset))
  assert s['viewInstancingTier']==3 and s['multiviewProbeCapture'],s
  assert s['missingCapturePixels']==0 and s['extraCapturePixels']==0,s
 for budget in [32,1024]:
  p.set_properties({'captureOnly':True});p.set_properties({'validateCapture':False,'probesPerFrame':budget});p.set_properties({'captureOnly':False})
  for repeat,mv in enumerate([False,True,True,False]):
   save('timing '+str((budget,repeat)));p.set_properties({'optimizedProbeCapture':True,'multiviewProbeCapture':mv,'probeCaptureTestOffset':0})
   for _ in range(32):renderFrame()
   m.profiler.enabled=True;m.profiler.start_capture()
   for _ in range(128):renderFrame()
   timing=m.profiler.end_capture();m.profiler.enabled=False
   name='timing-%s-%s.json'%(budget,repeat);(O/name).write_text(json.dumps(timing))
   results['timings'].append({'budget':budget,'multiview':mv,'file':name,'stats':dict(p.stats)})
 (O/'complete.json').write_text(json.dumps(results,indent=2));save('complete')
except:(O/'failure.txt').write_text(traceback.format_exc());save('failed')
exit()
