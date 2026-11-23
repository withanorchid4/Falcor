from falcor import *
from pathlib import Path
import runpy,json,traceback,time
R=Path(__file__).resolve().parents[2];O=R/'build/probe-capture-optimization';O.mkdir(exist_ok=True)
results={'validation':[],'timings':[]}
def save(stage): (O/'progress.json').write_text(json.dumps({'stage':stage,**results},indent=2))
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi');p=g.getPass('DDGI')
 runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 p.set_properties({'batchProbeUpdates':False,'tetrahedralInterpolation':False,'useRTXDI':False})
 g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
 save('warm full ray field')
 for _ in range(4096):renderFrame()
 p.set_properties({'captureOnly':True})
 p.set_properties({'rasterProbeUpdate':True,'batchProbeUpdates':True,'wrapProbeBatches':True,'probesPerFrame':32,'probeCubemapSize':32})
 for size in [16,32,64]:
  for offset in [0,1024,5000,10000]:
   save('validate '+str((size,offset)))
   p.set_properties({'probeCubemapSize':size,'probeCaptureTestOffset':offset,'validateCapture':True,'optimizedProbeCapture':False})
   for _ in range(4):renderFrame()
   p.set_properties({'optimizedProbeCapture':True})
   for _ in range(4):renderFrame()
   results['validation'].append({'size':size,'offset':offset,'stats':dict(p.stats)})
 p.set_properties({'validateCapture':False})
 for size in [16,32,64]:
  for offset in [0,5000,10000]:
   for repeat,optimized in enumerate([False,True,True,False]):
    save('timing '+str((size,offset,repeat)))
    p.set_properties({'probeCubemapSize':size,'probeCaptureTestOffset':offset,'optimizedProbeCapture':optimized})
    for _ in range(64):renderFrame()
    m.profiler.enabled=True;m.profiler.start_capture()
    for _ in range(256):renderFrame()
    timing=m.profiler.end_capture();m.profiler.enabled=False
    name='timing-%s-%s-%s.json'%(size,offset,repeat);(O/name).write_text(json.dumps(timing))
    results['timings'].append({'size':size,'offset':offset,'optimized':optimized,'repeat':repeat,'file':name,'stats':dict(p.stats)})
 p.set_properties({'captureOnly':False,'optimizedProbeCapture':True,'probeCubemapSize':32})
 for _ in range(128):renderFrame()
 results['normalUpdateStats']=dict(p.stats)
 (O/'complete.json').write_text(json.dumps(results,indent=2));save('complete')
except:(O/'failure.txt').write_text(traceback.format_exc());save('failed')
exit()
